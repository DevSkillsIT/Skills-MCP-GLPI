"""Normalize a raw GLPI ticket JSON row into an indexable Document.

Reuses the cleaning logic from scripts/glpi_export_db_tickets/process.py: HTML
stripping (with the double-encoded-entity quirk), code-to-label translation,
and docid extraction. The output is the unit the indexer hashes, embeds and
upserts — structured filter columns plus a single ``body_text`` that carries
the searchable essence (title + description + solutions + follow-ups).
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# GLPI code -> label maps (from process.py).
STATUS = {1: "Novo", 2: "Em atendimento", 3: "Planejado",
          4: "Pendente", 5: "Solucionado", 6: "Fechado"}
TIPO = {1: "Incidente", 2: "Requisicao"}
NIVEL = {1: "Muito baixa", 2: "Baixa", 3: "Media", 4: "Alta", 5: "Muito alta", 6: "Critica"}
SOL_STATUS = {1: "Aguardando aprovacao", 2: "Aceita", 3: "Recusada"}

_DOC_RE = re.compile(r"docid=(\d+)")

# On form-driven GLPI instances a single form title can cover a large share of
# tickets, so titles are boilerplate noise. The real problem statement lives in
# the form's "Descrição :" field. Extract it as the high-signal text; the value
# runs until the next "N)" field marker or end of text. (Used only when
# KB_EMBED_STRATEGY=form_description.)
_DESC_RE = re.compile(
    r"\bDescri[cç][aã]o\s*:\s*?(.*?)(?=\s*\d+\)\s|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def extract_problem(descricao: str) -> str:
    """Pull the form's free-text 'Descrição' value; fall back to the whole text
    for non-form tickets."""
    if not descricao:
        return ""
    m = _DESC_RE.search(descricao)
    problem = (m.group(1) if m else descricao).strip()
    # Guard against a near-empty capture (e.g. form with blank description).
    return problem if len(problem) >= 3 else descricao.strip()


def _label(mapping: dict[int, str], code: Any) -> str:
    """Translate a GLPI numeric code to its label, tolerating None/non-int."""
    if code is None:
        return ""
    try:
        return mapping.get(int(code), str(code))
    except (TypeError, ValueError):
        return str(code)


class _Stripper(HTMLParser):
    """HTML -> text, turning block tags into newlines (from process.py)."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:  # noqa: ARG002 - HTMLParser API
        if tag in ("br", "p", "div", "tr", "li"):
            self.parts.append("\n")
        if tag == "td":
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("p", "div", "tr", "li", "ul", "ol", "table"):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def to_text(htmltxt: str | None) -> str:
    """HTML -> clean text. Some GLPI content is double-encoded (``&#60;p&#62;``
    instead of ``<p>``), so unescape before stripping tags."""
    if not htmltxt:
        return ""
    htmltxt = html.unescape(htmltxt)
    stripper = _Stripper()
    try:
        stripper.feed(htmltxt)
    except (ValueError, AssertionError) as exc:  # malformed HTML: regex fallback
        log.warning("to_text.parse_failed", error=str(exc)[:120])
        return html.unescape(re.sub(r"<[^>]+>", " ", htmltxt)).strip()
    txt = html.unescape("".join(stripper.parts))
    txt = txt.replace("\r\n", "\n").replace("\r", "\n")
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n[ \t]+", "\n", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def _docids(*htmltxts: str | None) -> list[int]:
    out: list[str] = []
    for h in htmltxts:
        if h:
            out += _DOC_RE.findall(html.unescape(h))
    seen: set[str] = set()
    res: list[int] = []
    for d in out:
        if d not in seen:
            seen.add(d)
            res.append(int(d))
    return res


def _parse_dt(value: str | None) -> datetime | None:
    """GLPI MySQL datetimes arrive as 'YYYY-MM-DD HH:MM:SS' (or NULL/0000-...)."""
    if not value or value.startswith("0000"):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def compute_hash(body_text: str) -> str:
    """Stable content hash for the incremental change gate."""
    return hashlib.sha256(body_text.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class TicketDocument:
    """A normalized, indexable GLPI ticket."""

    id: int
    source: str
    titulo: str
    tipo: str
    status: str
    categoria: str
    prioridade: str
    origem: str
    entidade: str
    body_text: str  # the embedded essence: the form's "Descrição" (problem)
    solution_text: str  # stored + FTS weight B; not embedded
    body_hash: str
    source_date: datetime | None
    date_mod: datetime | None
    metadata: dict[str, Any] = field(default_factory=dict)


def build_document(
    raw: dict[str, Any], *, source: str, embed_strategy: str = "full"
) -> TicketDocument:
    """Turn one raw extraction row (see extract_tickets.sql) into a Document.

    ``embed_strategy`` controls what gets embedded:
      full              -> title + category + description (title is real signal)
      form_description  -> only the form's "Descrição" (titles are boilerplate)
    """
    fups = sorted(raw.get("acompanhamentos") or [], key=lambda a: a.get("data") or "")
    solucoes = raw.get("solucoes") or []

    descricao = to_text(raw.get("descricao_html"))
    fup_texts = [
        {
            "data": a.get("data"),
            "autor": a.get("autor"),
            "privado": bool(a.get("privado")),
            "texto": to_text(a.get("texto_html")),
        }
        for a in fups
    ]
    sol_texts = [
        {
            "data": s.get("data"),
            "autor": s.get("autor"),
            "tipo": s.get("tipo") or "",
            "status": _label(SOL_STATUS, s.get("status_cod")),
            "texto": to_text(s.get("texto_html")),
        }
        for s in solucoes
    ]

    titulo = raw.get("titulo") or ""
    categoria = raw.get("categoria") or ""

    # What gets embedded depends on the instance. On form-driven GLPIs titles
    # are boilerplate, so form_description embeds only the form "Descrição".
    # Otherwise (full) the title + category carry real signal and are included.
    # The solution is always stored separately and surfaced on hit.
    if embed_strategy == "form_description":
        body_text = extract_problem(descricao)
    else:
        body_text = "\n".join(p for p in (titulo, categoria, descricao) if p).strip()
    solution_text = "\n\n".join(s["texto"] for s in sol_texts if s["texto"]).strip()

    anexos = _docids(
        raw.get("descricao_html"),
        *[a.get("texto_html") for a in fups],
        *[s.get("texto_html") for s in solucoes],
    )

    metadata: dict[str, Any] = {
        "urgencia": _label(NIVEL, raw.get("urgencia_cod")),
        "impacto": _label(NIVEL, raw.get("impacto_cod")),
        "localizacao": raw.get("localizacao") or "",
        "solicitantes": raw.get("solicitantes") or [],
        "tecnicos": raw.get("tecnicos") or [],
        "observadores": raw.get("observadores") or [],
        "grupos_atribuidos": raw.get("grupos_atribuidos") or [],
        "data_solucao": raw.get("data_solucao"),
        "data_fechamento": raw.get("data_fechamento"),
        "acompanhamentos": fup_texts,
        "solucoes": sol_texts,
        "anexos_docids": anexos,
    }

    return TicketDocument(
        id=int(raw["id"]),
        source=source,
        titulo=titulo,
        tipo=_label(TIPO, raw.get("tipo_cod")),
        status=_label(STATUS, raw.get("status_cod")),
        categoria=categoria,
        prioridade=_label(NIVEL, raw.get("prioridade_cod")),
        origem=raw.get("origem") or "",
        entidade=raw.get("entidade") or "",
        body_text=body_text,
        solution_text=solution_text,
        # Hash covers problem + solution so a changed resolution re-indexes too.
        body_hash=compute_hash(body_text + "\x00" + solution_text),
        source_date=_parse_dt(raw.get("data_abertura")),
        date_mod=_parse_dt(raw.get("data_modificacao")),
        metadata=metadata,
    )
