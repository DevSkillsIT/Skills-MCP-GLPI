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
import unicodedata
from collections.abc import Sequence
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
# the form's free-text field. Extract it as the high-signal text.
#
# Forms name that field differently per instance ("Descrição", "Por favor,
# descreva o problema", ...), so the labels are CONFIGURABLE. A label-matching
# pass runs first; when no configured label matches we fall back to a structural
# heuristic (longest field value), and only then to the raw text — matching a
# literal label alone silently mis-extracted half of a real corpus.
DEFAULT_DESCRIPTION_LABELS = (
    "Descrição",
    "Descreva o problema",
    "Por favor, descreva o problema",
    "Descreva a solicitação",
    "Detalhe a solicitação",
    "Relato",
    "Observação",
)

# Formcreator prefixes the body with "Dados do formulário<FormName>", i.e. the
# very title we are trying to keep out of the text.
_FORM_HEADER_RE = re.compile(r"^\s*Dados do formul[áa]rio\s*", re.IGNORECASE)

# Form fields serialize as "N) <label> : <value>" (value runs to the next marker).
_FIELD_RE = re.compile(r"(\d+)\)\s*(.*?)\s*:\s*(.*?)(?=\s*\d+\)\s|\Z)", re.DOTALL)

# Openers that carry no information; dropped when real content follows.
_GREETING_RE = re.compile(
    r"^\s*(bom dia|boa tarde|boa noite|ol[áa]|prezad[oa]s?|senhores?|caros?)\b[\s,!.:;-]*",
    re.IGNORECASE,
)

# Label family for "this field holds the free-text problem". Catches per-instance
# wordings the explicit label list does not enumerate ("Descreva as informações
# necessárias da campanha", "Motivo da solicitação", ...).
_DESC_FAMILY_RE = re.compile(r"descrev|descri|relat|problem|detalh|motivo|ocorrenc|solicit")

# Attachment fields are never the problem statement; their values ("Nenhum
# documento anexado") are long enough to beat a real answer on length alone.
_ATTACHMENT_LABEL_RE = re.compile(r"\banex")

# Values that are pure form boilerplate, regardless of which field carries them.
_BOILERPLATE_VALUES = frozenset(
    {
        "nenhum documento anexado", "documento anexado", "nenhum", "nenhuma",
        "n a", "na", "nao", "sim", "outro", "outros", "-",
    }
)

_MIN_USEFUL = 3
# Below this, a promoted free-text answer carries no more information than the
# structured answers it would replace, so it does not get to win alone.
_MIN_PROMOTED = 10

# Follow-ups that carry no resolution: GLPI's own workflow messages and bare
# acknowledgements. Matched against the WHOLE normalized follow-up, never as a
# substring — "Estamos verificando o ramal e trocamos o cabo" is real content.
#
# Do NOT filter these by length: on this corpus "normalizado" (11 chars) and
# "ramais normalizados" (19) ARE the resolution, while the single biggest noise
# source is "Solução aprovada" (292 identical occurrences, auto-generated).
_NOISE_FOLLOWUP_RE = re.compile(
    r"^(?:"
    r"solucao aprovada|solucao recusada|"
    r"(?:estamos |vamos )?verificando(?: agora)?|vamos verificar|"
    r"ok|okay|blz|certo|perfeito|entendido|"
    r"(?:muito )?obrigad[oa]s?|ok obrigad[oa]s?|de nada|"
    r"aguardando(?: retorno| material| peca)?|sem retorno|em andamento|"
    r"acompanhando|(?:ol[aá]|oi)?\s*(?:bom dia|boa tarde|boa noite)|ol[aá]|oi|"
    # Sign-offs and openers sent as a follow-up of their own.
    r"atenciosamente|att|atte|cordialmente|abracos?|abs|grat[oa]|"
    # Status-only lines: every ticket in this KB is resolved, so "Solucionado."
    # distinguishes nothing (226 verbatim repeats).
    r"solucionado|resolvido|finalizado|concluido|encerrado|"
    r"equipe de tecnologia|suporte|helpdesk|"
    r"prezad[oa]s?|senhores?|segue|segue anexo|conforme solicitado"
    r")$"
)


# Credentials pasted into tickets. Redacted BEFORE indexing so the secret never
# reaches the vector, the FTS index or the rendered result — a KB makes ticket
# text semantically discoverable, which raises the cost of leaving it in. The
# surrounding resolution stays readable; nobody searches a KB to learn a
# password. Keep the label so the reader knows something was removed.
SECRET_PLACEHOLDER = "[credencial removida]"

_SECRET_LABEL = r"senh[ao]|password|passwd|pwd|token|chave de acesso"

# Rule 1 — the labelled form: "Senha: X", "password=X", "Senha - X".
# Same-line only: crossing a newline with a bare `\s*` swallowed the next line's
# first word ("Senha:\nnova senha: X" redacted "nova"). A value on the following
# line is still covered by rule 2, which demands the credential shape.
_SECRET_LABELLED_RE = re.compile(
    rf"(?i)\b({_SECRET_LABEL})\b[^\S\n]*[:=-][^\S\n]*(?!\[credencial)(\S+)"
)

# Rule 2 — proximity. Real tickets write it as prose: "Resetei sua senha para:
# X", "Senha temporária: X", "a senha do computador no momento é: X", or with no
# separator at all ("Senha X"). Rule 1 alone left 65 of them in the index.
# Anchored on the VALUE looking like a credential (>=6 chars with a digit AND a
# letter) inside a short window after the label, so prose survives: in "a senha
# do usuário expirou" no nearby token has a digit, and nothing is touched.
_SECRET_NEARBY_RE = re.compile(
    rf"(?i)(\b(?:{_SECRET_LABEL})\b[^\n]{{0,60}}?[\s:=-]\s*)"
    # Never re-consume what rule 1 already replaced, nor step past a placeholder
    # into the text after it.
    r"(?!\[credencial)"
    # Error codes ("C-002", "E0390") sit in the same sentence as a password reset
    # and match the shape; they are not secrets. One real casualty: ticket 8567.
    r"(?![A-Za-z]{1,2}-?\d{2,4}\b)"
    r"(?=[^\s]{6,})(?=[^\s]*\d)(?=[^\s]*[A-Za-z])([^\s]+)"
)


# Rule 4 — a line that is NOTHING BUT a credential. Technicians write handover
# blocks as "login do computador:" / e-mail / password, each on its own line, so
# the password can sit two lines away from any label. Requires a symbol and
# forbids a dot, which keeps hostnames, versions, IPs and e-mails out.
# Up to two short words may lead the line: real tickets write "para Jk@202Pc"
# after listing the affected e-mails, which puts the label three lines away —
# out of rule 2's reach, since its window cannot cross a newline. Only the token
# is replaced, so the sentence keeps its shape.
_SECRET_STANDALONE_RE = re.compile(
    r"^(?:\S{1,8}[^\S\n]+){0,2}"
    r"(?=[^\s.]{6,}$)(?=[^\s]*[A-Za-z])(?=[^\s]*\d)(?=[^\s]*[@#$%&*!+=])([^\s]+)$"
)


# A harvested value is applied to EVERY ticket, so a false positive here is not a
# local mistake — it erases a word corpus-wide. "Senha - Padrão" once promoted
# "Padrão" to a global literal and mutilated 61 tickets ("Acesso Padrão
# Limitado"). Only values that look like a credential on their own may travel:
# letters AND digits, no money, no XXXX-style placeholders. Values that fail this
# gate are still redacted where the rules actually saw them — they just do not
# get to speak for the whole corpus.
_HARVEST_MONEY_RE = re.compile(r"^R?\$?\d[\d.,]*$")
_HARVEST_PLACEHOLDER_RE = re.compile(r"(.)\1{3,}")


def _plausible_secret(value: str) -> bool:
    """Not money, not an XXXX-style placeholder — used wherever a match would
    destroy content, whether locally (rule 4) or corpus-wide (harvest)."""
    return not (_HARVEST_MONEY_RE.match(value) or _HARVEST_PLACEHOLDER_RE.search(value))


def _may_travel(value: str) -> bool:
    if len(value) < 6:
        return False
    if not (any(c.isdigit() for c in value) and any(c.isalpha() for c in value)):
        return False
    return _plausible_secret(value)


def harvest_secrets(text: str) -> set[str]:
    """Credential VALUES this text reveals, for propagation across the corpus.

    The same password appears labelled in one ticket and bare in another; a
    per-ticket view cannot see that. Harvesting turns the corpus into its own
    literal list, so a value identified anywhere is removed everywhere.
    """
    found: set[str] = set()
    if not text:
        return found
    for match in _SECRET_LABELLED_RE.finditer(text):
        found.add(match.group(2))
    for match in _SECRET_NEARBY_RE.finditer(text):
        found.add(match.group(2))
    for line in text.split("\n"):
        if standalone := _SECRET_STANDALONE_RE.match(line.strip()):
            found.add(standalone.group(1))
    return {
        v for v in found
        if v and not v.startswith(SECRET_PLACEHOLDER[:12]) and _may_travel(v)
    }


def redact_secrets(text: str, literals: Sequence[str] = ()) -> str:
    """Strip credentials pasted into ticket text, keeping the sentence readable.

    Four mechanisms, because no single one is enough (numbered as the rule
    constants above, plus the literals):
      - literals: known values, applied first and word-bounded;
      - rule 1: explicit `label: value`, same line;
      - rule 2: proximity, anchored on the value LOOKING like a credential —
        real tickets write prose ("Resetei sua senha para: X");
      - rule 4: a line that is only a credential (optionally after up to two
        short words), because a password often sits next to a username with no
        label anywhere near it. Patterns cannot see that; the corpus-wide
        harvest feeds those values back in as literals.

    Near-idempotent, not idempotent: a second pass can redact MORE (rule 2's
    window can step over an inserted placeholder and reach the next token — e.g.
    "hash da senha X: <hash>" loses the hash only on the second pass). The
    direction is safe and the pipeline always starts from raw GLPI text, so it
    never happens in practice; do not rely on redact(redact(x)) == redact(x).
    """
    if not text:
        return text
    out = text
    for literal in literals:
        if literal:
            # Word-bounded: a bare substring replace would hit a literal embedded
            # inside a longer word or number and silently corrupt it.
            out = re.sub(
                rf"(?<![\w]){re.escape(literal)}(?![\w])", SECRET_PLACEHOLDER, out
            )
    out = _SECRET_LABELLED_RE.sub(rf"\1: {SECRET_PLACEHOLDER}", out)
    out = _SECRET_NEARBY_RE.sub(rf"\1{SECRET_PLACEHOLDER}", out)
    return "\n".join(_redact_standalone_line(line) for line in out.split("\n"))


def _redact_standalone_line(line: str) -> str:
    """Replace a credential that is the whole (or the tail) of a line.

    The shape alone is not enough: "Balde 56533 R$134,84" satisfies every
    structural test (letter, digit, symbol, no dot) and is a price. Money and
    placeholder runs are excluded here for the same reason they are excluded
    from harvesting — a false positive destroys real content.
    """
    match = _SECRET_STANDALONE_RE.match(line.strip())
    if not match or not _plausible_secret(match.group(1)):
        return line
    return line.replace(match.group(1), SECRET_PLACEHOLDER)


def _is_noise_followup(text: str) -> bool:
    return bool(_NOISE_FOLLOWUP_RE.match(_normalize_label(text)))


def clean_followup(text: str) -> str:
    """Drop boilerplate LINES from a follow-up, keeping the real content.

    Whole-follow-up matching is not enough: a genuine "Trocamos o cabo." arrives
    wrapped in a signature block ("Atenciosamente," / "Equipe de Tecnologia"),
    which on this corpus repeats 518 and 115 times respectively. Those lines
    carry no resolution and repeat verbatim, so they only dilute.
    """
    kept = [
        line
        for raw in text.split("\n")
        if (line := raw.strip()) and not _is_noise_followup(line)
    ]
    return "\n".join(kept).strip()


def _is_boilerplate(label: str, value: str) -> bool:
    """True when a form field cannot plausibly hold the problem statement."""
    return bool(_ATTACHMENT_LABEL_RE.search(label)) or _normalize_label(value) in _BOILERPLATE_VALUES


def _dedup_keep_order(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


_ACCENT_CLASS = {
    "a": "[aáàâã]", "e": "[eéêë]", "i": "[ií]", "o": "[oóôõ]",
    "u": "[uúü]", "c": "[cç]",
}


def _deaccent(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _accent_tolerant(label: str) -> str:
    """Regex for a label that matches with or without Portuguese diacritics.
    The label itself is de-accented first, so "Descrição" and "Descricao" in the
    CONFIG both produce a pattern matching either spelling in the TEXT."""
    return "".join(_ACCENT_CLASS.get(ch.lower(), re.escape(ch)) for ch in _deaccent(label))


def _bare_label_value(text: str, labels: Sequence[str]) -> str:
    """Value of a '<label> : value' pair on forms that omit the 'N)' markers."""
    for label in labels:
        m = re.search(
            rf"\b{_accent_tolerant(label)}\s*:\s*(.*?)(?=\s*\d+\)\s|\Z)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if m and len(m.group(1).strip()) >= _MIN_USEFUL:
            return m.group(1).strip()
    return ""


def _pick_primary(
    usable: Sequence[tuple[str, str]], labels: Sequence[str]
) -> int | None:
    """Index of the free-text problem answer, if this form has one. Configured
    labels win; otherwise a wording in the same family. None when the form is
    purely structured, so no answer is promoted over the others."""
    for want in (_normalize_label(lab) for lab in labels):
        for i, (label, _) in enumerate(usable):
            if want and want in label:
                return i
    for i, (label, _) in enumerate(usable):
        if _DESC_FAMILY_RE.search(label):
            return i
    return None


_MAX_GREETINGS = 3


def _greeting_residue(text: str) -> str:
    """What is left after greetings, WITHOUT the preservation guard.

    `_strip_greeting` deliberately returns the greeting when nothing else is
    there, so its output length cannot answer "does this field hold real
    content?" — "Boa tarde!" is exactly _MIN_PROMOTED chars and would pass.
    """
    out = text.strip()
    for _ in range(_MAX_GREETINGS):
        nxt = _GREETING_RE.sub("", out, count=1).strip()
        if nxt == out:
            break
        out = nxt
    return out


def _strip_greeting(text: str) -> str:
    """Drop leading greetings when substantive text follows them.

    Loops because they stack: "Prezados,\\n\\nBom dia!\\n\\nFavor ajustar..." needs
    two passes. Bounded, and never returns less than the minimum useful text, so
    a body that is nothing but a greeting is preserved rather than emptied.
    """
    stripped = text.strip()
    for _ in range(_MAX_GREETINGS):
        nxt = _GREETING_RE.sub("", stripped, count=1).strip()
        if nxt == stripped:
            break
        if len(nxt) < _MIN_USEFUL:
            return stripped
        stripped = nxt
    return stripped


def _normalize_label(label: str) -> str:
    """Lowercase, strip accents and punctuation so label matching is tolerant."""
    nfd = unicodedata.normalize("NFD", label)
    no_marks = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", no_marks.lower()).strip()


def extract_problem(
    descricao: str, labels: Sequence[str] = DEFAULT_DESCRIPTION_LABELS
) -> str:
    """Pull the form's free-text problem statement.

    Order: configured label -> longest field value -> whole text. The form header
    ("Dados do formulário<FormName>") and a leading greeting are always removed,
    since both are boilerplate that collapses unrelated tickets together.
    """
    if not descricao:
        return ""
    text = _FORM_HEADER_RE.sub("", descricao, count=1)

    fields = [(_normalize_label(lab), val.strip()) for _, lab, val in _FIELD_RE.findall(text)]
    usable = [
        (lab, val)
        for lab, val in fields
        if len(val) >= _MIN_USEFUL and not _is_boilerplate(lab, val)
    ]
    if usable:
        idx = _pick_primary(usable, labels)
        if idx is not None:
            promoted = _strip_greeting(usable[idx][1])
            # A free-text field that exists but was left effectively empty ("Bom
            # dia!") must NOT win over the structured answers around it — that
            # would throw away the only real signal the ticket has (e.g. the
            # selected system). Measure the residue AFTER greetings, not the
            # preserved text, or a greeting long enough passes the guard.
            if len(_greeting_residue(usable[idx][1])) >= _MIN_PROMOTED or len(usable) == 1:
                return promoted
        # Purely structured form (new-user request, software install): there is
        # no free-text problem, and the ANSWERS are the content. Keep them all;
        # only the repeated scaffolding — form header and field LABELS — is
        # dropped, since that is what dilutes the vector.
        return "\n".join(_dedup_keep_order([v for _, v in usable])).strip()

    # Unnumbered form ("Descrição : ..." with no "N)" markers).
    bare = _bare_label_value(text, labels)
    if bare:
        return _strip_greeting(bare)

    problem = _strip_greeting(text)
    return problem if len(problem) >= _MIN_USEFUL else descricao.strip()


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
    body_text: str  # the problem, as the user stated it — stored and displayed
    solution_text: str  # the resolution (formal solution + technician follow-ups)
    embed_text: str  # what actually gets vectorized; see build_document
    body_hash: str
    source_date: datetime | None
    date_mod: datetime | None
    metadata: dict[str, Any] = field(default_factory=dict)


def build_document(
    raw: dict[str, Any],
    *,
    source: str,
    embed_strategy: str = "full",
    description_labels: Sequence[str] = DEFAULT_DESCRIPTION_LABELS,
    include_followups: bool = True,
    redact_literals: Sequence[str] = (),
) -> TicketDocument:
    """Turn one raw extraction row (see extract_tickets.sql) into a Document.

    ``embed_strategy`` controls what gets embedded:
      full              -> title + category + description (title is real signal)
      form_description  -> only the form's free-text problem (titles are boilerplate)
      problem_solution  -> problem + resolution (findable by symptom AND by fix)

    ``description_labels`` names the form field holding the free-text problem.
    ``include_followups`` folds technician follow-ups into the resolution text.
    """
    fups = sorted(raw.get("acompanhamentos") or [], key=lambda a: a.get("data") or "")
    solucoes = raw.get("solucoes") or []

    # Redact HERE, at the single point where raw GLPI text enters the document.
    # Redacting only body/solution left every credential sitting in `metadata`
    # (which keeps follow-ups and solutions verbatim) — including individual user
    # passwords, not just the shared default. A secret must not survive anywhere
    # in a row the contract exposes.
    def _clean(html_text: str | None) -> str:
        return redact_secrets(to_text(html_text), redact_literals)

    descricao = _clean(raw.get("descricao_html"))
    fup_texts = [
        {
            "data": a.get("data"),
            "autor": a.get("autor"),
            "privado": bool(a.get("privado")),
            "texto": _clean(a.get("texto_html")),
        }
        for a in fups
    ]
    sol_texts = [
        {
            "data": s.get("data"),
            "autor": s.get("autor"),
            "tipo": s.get("tipo") or "",
            "status": _label(SOL_STATUS, s.get("status_cod")),
            "texto": _clean(s.get("texto_html")),
        }
        for s in solucoes
    ]

    titulo = raw.get("titulo") or ""
    categoria = raw.get("categoria") or ""

    # The resolution is what a technician actually did. GLPI stores it in two
    # different places and only one of them is the formal "solution" record: on
    # this corpus 883 of the 936 tickets WITHOUT a formal solution carry the fix
    # in a follow-up instead. Indexing only formal solutions silently drops it.
    resolution_parts = [c for s in sol_texts if (c := clean_followup(s["texto"]))]
    if include_followups:
        resolution_parts += [
            f"{a['autor']}: {cleaned}" if a.get("autor") else cleaned
            for a in fup_texts
            if a.get("texto") and (cleaned := clean_followup(a["texto"]))
        ]
    solution_text = "\n\n".join(resolution_parts).strip()

    # What gets embedded depends on the instance. On form-driven GLPIs titles
    # are boilerplate, so they are excluded; `full` keeps them for instances
    # where the title is real signal.
    # Redact on the problem side too: users paste credentials into the form as
    # readily as technicians do into the resolution.
    problem_text = redact_secrets(extract_problem(descricao, description_labels), redact_literals)
    if embed_strategy == "full":
        body_text = redact_secrets(
            "\n".join(p for p in (titulo, categoria, descricao) if p).strip(), redact_literals
        )
    else:
        body_text = problem_text

    # `embed_text` is deliberately separate from `body_text`: the vector may
    # cover more than what we display. problem_solution embeds the resolution
    # too (findable by the fix, not just the symptom) while the displayed body
    # stays the problem alone — otherwise every result row would print the
    # solution twice, once in the snippet and once in its own column.
    if embed_strategy == "problem_solution":
        embed_text = "\n\n".join(p for p in (problem_text, solution_text) if p).strip()
    else:
        embed_text = body_text

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
        embed_text=embed_text,
        # Hash covers the displayed text, the resolution AND the embedded text.
        # embed_text is not redundant: switching embed_strategy changes only what
        # is vectorized, leaving body/solution identical — without it the gate
        # would report "unchanged" and every vector would silently stay stale.
        body_hash=compute_hash("\x00".join((body_text, solution_text, embed_text))),
        source_date=_parse_dt(raw.get("data_abertura")),
        date_mod=_parse_dt(raw.get("data_modificacao")),
        metadata=metadata,
    )
