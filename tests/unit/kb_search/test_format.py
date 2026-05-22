"""Unit tests: Markdown formatting + weak-title display fallback (pure)."""

from __future__ import annotations

from src.services.kb_search.rrf import UnifiedHit
from src.services.kb_search.service import _display_title, format_markdown


def _hit(**over: object) -> UnifiedHit:
    base: dict[str, object] = dict(
        source="HELP", is_official=True, id="1", title="Titulo bem grande aqui",
        context="Ctx", url="http://x", source_rank=1, rrf_score=0.5, similarity=0.812,
    )
    base.update(over)
    return UnifiedHit(**base)  # type: ignore[arg-type]


class TestFormatMarkdown:
    def test_empty(self) -> None:
        assert "Nenhum" in format_markdown([])

    def test_table_renders(self) -> None:
        md = format_markdown([_hit()])
        assert "| HELP |" in md and "Sim" in md and "0.812" in md and "http://x" in md

    def test_keyword_score_is_dash(self) -> None:
        md = format_markdown([_hit(is_official=False, similarity=None)])
        assert "Nao" in md and "—" in md

    def test_pipe_escaped(self) -> None:
        md = format_markdown([_hit(title="a | b")])
        assert "a \\| b" in md


class TestDisplayTitle:
    def test_weak_title_uses_body_snippet(self) -> None:
        h = _hit(title="Sankhya", body="nota fiscal nao emite por erro de imposto")
        assert "nota fiscal" in _display_title(h)

    def test_strong_title_kept(self) -> None:
        h = _hit(title="Como configurar o boleto no financeiro", body="x")
        assert _display_title(h) == "Como configurar o boleto no financeiro"

    def test_weak_title_no_body_kept_as_is(self) -> None:
        h = _hit(title="GLPI", body="")
        assert _display_title(h) == "GLPI"
