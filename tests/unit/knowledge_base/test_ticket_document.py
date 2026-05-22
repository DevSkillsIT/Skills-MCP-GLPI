"""Unit tests for the pure normalization logic in ticket_document."""

from __future__ import annotations

from knowledge_base.ticket_document import (
    NIVEL,
    _docids,
    _label,
    build_document,
    compute_hash,
    extract_problem,
    to_text,
)


class TestExtractProblem:
    def test_pulls_form_descricao(self) -> None:
        text = "1) Categoria : Falha 2) Descrição : impressora sem toner 3) Anexo : x.png"
        assert extract_problem(text) == "impressora sem toner"

    def test_stops_at_next_field_marker(self) -> None:
        text = "2) Descrição : conta de email bloqueada 3) Anexo : nada"
        assert extract_problem(text) == "conta de email bloqueada"

    def test_handles_accent_variants(self) -> None:
        assert extract_problem("Descricao : sem acento aqui") == "sem acento aqui"

    def test_falls_back_to_full_text_for_non_form(self) -> None:
        text = "Servidor de arquivos fora do ar desde as 9h"
        assert extract_problem(text) == text

    def test_blank_description_guard_falls_back(self) -> None:
        # Capture is < 3 chars -> fall back to the whole text.
        text = "Descrição :   2) Categoria : X"
        assert extract_problem(text) == text.strip()

    def test_empty_input(self) -> None:
        assert extract_problem("") == ""


class TestToText:
    def test_strips_tags_and_inserts_newlines(self) -> None:
        out = to_text("<p>linha um</p><div>linha dois</div>")
        assert "linha um" in out
        assert "linha dois" in out
        assert "<" not in out

    def test_double_encoded_entities(self) -> None:
        # GLPI sometimes stores &#60;p&#62; instead of <p>.
        out = to_text("&#60;p&#62;conteudo&#60;/p&#62;")
        assert out == "conteudo"

    def test_empty_and_none(self) -> None:
        assert to_text("") == ""
        assert to_text(None) == ""


class TestComputeHash:
    def test_deterministic(self) -> None:
        assert compute_hash("abc") == compute_hash("abc")

    def test_sensitive_to_change(self) -> None:
        assert compute_hash("abc") != compute_hash("abc ")


class TestDocids:
    def test_dedup_preserving_order(self) -> None:
        html = 'a docid=5 b docid=3 c docid=5'
        assert _docids(html) == [5, 3]

    def test_none_when_absent(self) -> None:
        assert _docids("no documents here") == []

    def test_found_in_double_encoded(self) -> None:
        assert _docids("&#60;a href=&#34;...docid=42&#34;&#62;") == [42]


class TestLabel:
    def test_none_returns_empty(self) -> None:
        assert _label(NIVEL, None) == ""

    def test_known_code(self) -> None:
        assert _label(NIVEL, 6) == "Critica"

    def test_unknown_code_stringified(self) -> None:
        assert _label(NIVEL, 99) == "99"


def _raw(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": 1,
        "titulo": "ERP System",
        "categoria": "Sistemas",
        "status_cod": 5,
        "tipo_cod": 1,
        "descricao_html": "2) Descrição : pedido de venda nao aparece 3) Anexo : x",
        "solucoes": [{"texto_html": "limpamos o cache do navegador", "status_cod": 2}],
        "acompanhamentos": [],
    }
    base.update(over)
    return base


class TestBuildDocument:
    def test_form_strategy_embeds_only_description(self) -> None:
        doc = build_document(_raw(), source="x", embed_strategy="form_description")
        assert doc.body_text == "pedido de venda nao aparece"
        assert "ERP System" not in doc.body_text  # title excluded

    def test_full_strategy_includes_title(self) -> None:
        doc = build_document(_raw(), source="x", embed_strategy="full")
        assert "ERP System" in doc.body_text
        assert "pedido de venda" in doc.body_text

    def test_solution_stored_separately_not_in_body(self) -> None:
        doc = build_document(_raw(), source="x", embed_strategy="form_description")
        assert doc.solution_text == "limpamos o cache do navegador"
        assert "cache" not in doc.body_text

    def test_hash_covers_solution_change(self) -> None:
        a = build_document(_raw(), source="x", embed_strategy="form_description")
        b = build_document(
            _raw(solucoes=[{"texto_html": "outra solucao diferente", "status_cod": 2}]),
            source="x",
            embed_strategy="form_description",
        )
        assert a.body_text == b.body_text  # problem unchanged
        assert a.body_hash != b.body_hash  # but solution changed -> re-index

    def test_translates_codes(self) -> None:
        doc = build_document(_raw(), source="site-a", embed_strategy="full")
        assert doc.status == "Solucionado"
        assert doc.tipo == "Incidente"
        assert doc.source == "site-a"
