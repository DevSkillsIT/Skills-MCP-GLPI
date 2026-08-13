"""Unit tests for the pure normalization logic in ticket_document."""

from __future__ import annotations

from knowledge_base.ticket_document import (
    NIVEL,
    _docids,
    _label,
    build_document,
    compute_hash,
    extract_problem,
    harvest_secrets,
    SECRET_PLACEHOLDER,
    redact_secrets,
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

    # -- regressions from the live form-driven corpus (form-driven GLPI) -----------

    def test_matches_label_wording_outside_the_default_list(self) -> None:
        """The literal label "Descrição" covered only half a real corpus; the
        rest used "Por favor, descreva o problema"."""
        text = (
            "Dados do formulário Falha no Equipamento "
            "1) Para qual serviço deseja atendimento? : Problema no Ramal "
            "2) Qual o número do ramal? : 201 "
            "3) Por favor, descreva o problema : Ramal mudo 201 "
            "4) Anexo : Nenhum documento anexado"
        )
        assert extract_problem(text) == "Ramal mudo 201"

    def test_strips_formcreator_header(self) -> None:
        text = "Dados do formulárioConta de E-mail 1) Descrição : caixa cheia"
        assert "Dados do formul" not in extract_problem(text)

    def test_never_picks_an_attachment_field(self) -> None:
        """"Nenhum documento anexado" is longer than a real short answer, so a
        pure longest-value heuristic selected it."""
        text = (
            "1) Descreva as informações necessárias da campanha : Frequência RCA "
            "2) Anexar planilha .XLS : Nenhum documento anexado"
        )
        assert extract_problem(text) == "Frequência RCA"

    def test_structured_form_keeps_every_answer(self) -> None:
        """New-user/software-request forms have no free-text problem field; the
        answers ARE the content, so none may be dropped."""
        text = "1) Departamento : Televendas 2) Nome do novo usuário : Marcele"
        got = extract_problem(text)
        assert "Televendas" in got
        assert "Marcele" in got

    def test_drops_leading_greeting(self) -> None:
        text = "1) Descrição : Bom dia! Ramal mudo 201"
        assert extract_problem(text) == "Ramal mudo 201"

    def test_greeting_only_body_is_preserved(self) -> None:
        """Stripping must not empty out a body that is nothing but a greeting."""
        assert extract_problem("1) Descrição : Bom dia!") == "Bom dia!"

    def test_degenerate_free_text_does_not_discard_structured_answers(self) -> None:
        """Real ticket 7263: the free-text field held only "Bom dia!", so
        promoting it dropped "Rhub" — the ticket's only real signal."""
        text = (
            "1) Selecione o Sistema ou Aplicativo Mobile : Rhub "
            "2) Descreva o problema : Bom dia!"
        )
        got = extract_problem(text)
        assert "Rhub" in got

    def test_greeting_exactly_at_the_promotion_threshold(self) -> None:
        """"Boa tarde!" is exactly _MIN_PROMOTED chars: measuring the PRESERVED
        text instead of the residue let it pass the guard (real ticket 7331)."""
        text = "1) Selecione o Sistema : Sankhya 2) Descreva o problema : Boa tarde!"
        assert "Sankhya" in extract_problem(text)

    def test_stacked_greetings_are_all_removed(self) -> None:
        """Greetings stack; a single substitution left "Bom dia!" leading 2,1%
        of the corpus."""
        text = "1) Descrição : Prezados,\nBom dia!\nFavor ajustar o cadastro do cliente"
        got = extract_problem(text)
        assert got.startswith("Favor ajustar")

    def test_custom_labels_override_defaults(self) -> None:
        text = "1) Qual o chamado do cliente : servidor caiu 2) Outro : x"
        assert extract_problem(text, ["Qual o chamado do cliente"]) == "servidor caiu"


class TestSecretRedaction:
    """A KB makes ticket text semantically discoverable; a default password
    repeated across 128 tickets must not ride along into the index."""

    def test_redacts_password_keeping_the_surrounding_text(self) -> None:
        got = redact_secrets("Usuario criado. Senha: Mudar@123 - orientar troca.")
        assert "Mudar@123" not in got
        assert "Usuario criado." in got
        assert "orientar troca." in got

    def test_covers_common_credential_labels(self) -> None:
        for raw in ("password=hunter2", "PWD: abc123", "Token = xyz789"):
            assert redact_secrets(raw).count("[credencial removida]") == 1

    def test_error_codes_near_a_password_survive(self) -> None:
        """Ticket 8567: "o erro C-002" sat inside rule 2's window after "redefinir
        a senha" and matched the credential shape."""
        text = "Ao redefinir a senha aparece o erro C-002, favor verificar"
        assert "C-002" in redact_secrets(text)

    def test_redaction_reaches_the_metadata_copies(self) -> None:
        """metadata keeps follow-ups verbatim; redacting only body/solution left
        every credential there, including individual user passwords."""
        doc = build_document(
            {
                "id": 1, "titulo": "T", "categoria": "C",
                "descricao_html": "1) Descrição : criar usuario",
                "acompanhamentos": [{"autor": "Tec", "texto_html": "Senha: gU2@3Pi#"}],
                "solucoes": [{"texto_html": "usuario criado, senha: Ki98@h2025"}],
            },
            source="glpi",
        )
        import json as _json

        blob = _json.dumps(doc.metadata, ensure_ascii=False)
        assert "gU2@3Pi#" not in blob
        assert "Ki98@h2025" not in blob

    def test_password_alone_on_a_line_with_no_label(self) -> None:
        """Handover blocks put the password two lines from any label; 5 real
        passwords survived rules 1-2 this way (tickets 6977, 7183, 7218, ...)."""
        block = "login do computador:\nfulano.silva\nSi89mK@25\n"
        got = redact_secrets(block)
        assert "Si89mK@25" not in got
        assert "fulano.silva" in got  # the login is not the secret

    def test_standalone_rule_spares_lookalikes(self) -> None:
        """Hostnames, versions and e-mails share the shape minus the symbol/dot."""
        for keep in ("PCVENDAS01", "v1.2.3", "fulano@empresa.com.br", "192.168.0.10"):
            assert keep in redact_secrets(f"maquina\n{keep}\nfim")

    def test_credential_after_a_connector_word(self) -> None:
        """Ticket 8143: the label sits three lines up, past two e-mail lines, so
        rule 2 (which cannot cross a newline) never reaches "para Jk@202Pc"."""
        text = (
            "Alteramos a senha dos emails\n"
            "a@empresa.com.br\nb@empresa.com.br\n"
            "para Jk@202Pc"
        )
        got = redact_secrets(text)
        assert "Jk@202Pc" not in got
        assert got.rstrip().endswith(f"para {SECRET_PLACEHOLDER}")  # sentence intact

    def test_connector_form_still_spares_lookalikes(self) -> None:
        for keep in ("para PCVENDAS01", "no servidor SRV2024", "ramal 219"):
            assert redact_secrets(keep) == keep

    def test_money_is_not_a_credential(self) -> None:
        """Ticket 7131: "Balde 56533 R$134,84" passes every structural test —
        letter, digit, symbol, no dot — and is a price."""
        text = "Balde 56533 R$134,84"
        assert redact_secrets(text) == text

    def test_harvest_refuses_words_that_would_travel_badly(self) -> None:
        """A harvested value is applied to EVERY ticket. "Senha - Padrão" once
        promoted "Padrão" to a global literal and mutilated 61 real tickets
        ("Acesso Padrão Limitado")."""
        assert harvest_secrets("Senha - Padrão") == set()
        assert harvest_secrets("Balde 56533 R$134,84") == set()
        assert harvest_secrets("ligue 0+DDD+9XXXXXXXX") == set()

    def test_literals_replace_on_word_boundaries(self) -> None:
        """A bare substring replace corrupts a literal embedded in a longer
        token."""
        got = redact_secrets("chamado 1234567 sobre abc123", literals=["abc123"])
        assert "1234567" in got
        assert "abc123" not in got.replace(SECRET_PLACEHOLDER, "")

    def test_harvest_finds_values_for_propagation(self) -> None:
        """A password labelled in one ticket and bare in another is only caught
        corpus-wide: harvest turns the corpus into its own literal list."""
        assert "Si89mK@25" in harvest_secrets("IT Skills: Senha: Si89mK@25 criada")
        assert "u6@JeY45" in harvest_secrets("acesso:\njoao\nu6@JeY45")

    def test_leaves_ordinary_text_alone(self) -> None:
        text = "A senha do usuario expirou e ele nao consegue entrar"
        assert redact_secrets(text) == text

    def test_redaction_reaches_problem_and_resolution(self) -> None:
        doc = build_document(
            {
                "id": 1, "titulo": "T", "categoria": "C",
                "descricao_html": "1) Descrição : nao consigo entrar, senha: Velha@1",
                "acompanhamentos": [{"autor": "Tec", "texto_html": "resetei. Senha: Mudar@123"}],
                "solucoes": [],
            },
            source="glpi",
            embed_strategy="problem_solution",
        )
        for field in (doc.body_text, doc.solution_text, doc.embed_text):
            assert "Mudar@123" not in field
            assert "Velha@1" not in field
        assert "resetei." in doc.solution_text


class TestResolutionAndEmbedText:
    @staticmethod
    def _raw(**over: object) -> dict:
        base = {
            "id": 1, "titulo": "Falha no Ramal", "categoria": "TELEFONIA",
            "descricao_html": "1) Descrição : Ramal mudo 201",
            "acompanhamentos": [], "solucoes": [],
        }
        base.update(over)
        return base

    def test_followups_fold_into_the_resolution(self) -> None:
        """GLPI keeps the fix in a follow-up on many tickets; indexing only the
        formal solution dropped it for 883 of one corpus's 936 such tickets."""
        doc = build_document(
            self._raw(acompanhamentos=[{"autor": "Tec", "texto_html": "reiniciei o telefone"}]),
            source="glpi",
            embed_strategy="form_description",
        )
        assert "reiniciei o telefone" in doc.solution_text
        assert "Tec" in doc.solution_text

    def test_followups_can_be_excluded(self) -> None:
        doc = build_document(
            self._raw(acompanhamentos=[{"autor": "Tec", "texto_html": "reiniciei"}]),
            source="glpi",
            include_followups=False,
        )
        assert doc.solution_text == ""

    def test_problem_solution_embeds_more_than_it_displays(self) -> None:
        """The vector covers the fix; the displayed body stays the problem, so a
        result row does not print the solution twice."""
        doc = build_document(
            self._raw(solucoes=[{"texto_html": "troca do aparelho"}]),
            source="glpi",
            embed_strategy="problem_solution",
        )
        assert doc.body_text == "Ramal mudo 201"
        assert "troca do aparelho" in doc.embed_text
        assert "Ramal mudo 201" in doc.embed_text

    def test_drops_glpi_workflow_and_signature_followups(self) -> None:
        """"Solução aprovada" is auto-generated by GLPI and appeared 292 times
        identically; sign-offs like "Atenciosamente," another 170. Repeated
        boilerplate dilutes the vector exactly like the form header did."""
        doc = build_document(
            self._raw(
                acompanhamentos=[
                    {"autor": "Sis", "texto_html": "Solução aprovada"},
                    {"autor": "Tec", "texto_html": "Atenciosamente,"},
                    {"autor": "Tec", "texto_html": "Estamos verificando"},
                    {"autor": "Tec", "texto_html": "troquei o cabo de rede"},
                ]
            ),
            source="glpi",
        )
        assert "troquei o cabo de rede" in doc.solution_text
        for noise in ("Solução aprovada", "Atenciosamente", "Estamos verificando"):
            assert noise not in doc.solution_text

    def test_keeps_short_but_real_resolutions(self) -> None:
        """Length is the WRONG filter: "normalizado" (11 chars) is the fix, while
        the biggest noise source is longer than it."""
        doc = build_document(
            self._raw(acompanhamentos=[{"autor": "Tec", "texto_html": "normalizado"}]),
            source="glpi",
        )
        assert "normalizado" in doc.solution_text

    def test_noise_words_inside_real_text_are_kept(self) -> None:
        """The denylist matches whole follow-ups only."""
        doc = build_document(
            self._raw(
                acompanhamentos=[
                    {"autor": "Tec", "texto_html": "Estamos verificando o ramal e trocamos o cabo"}
                ]
            ),
            source="glpi",
        )
        assert "trocamos o cabo" in doc.solution_text

    def test_hash_reacts_to_the_embedding_strategy(self) -> None:
        """Switching strategy changes only what is vectorized; if the hash misses
        it the ETL reports "unchanged" and every vector silently stays stale."""
        raw = self._raw(solucoes=[{"texto_html": "troca do aparelho"}])
        a = build_document(raw, source="glpi", embed_strategy="form_description")
        b = build_document(raw, source="glpi", embed_strategy="problem_solution")
        assert a.body_text == b.body_text
        assert a.solution_text == b.solution_text
        assert a.embed_text != b.embed_text
        assert a.body_hash != b.body_hash

    def test_other_strategies_embed_exactly_what_they_display(self) -> None:
        doc = build_document(
            self._raw(solucoes=[{"texto_html": "troca do aparelho"}]),
            source="glpi",
            embed_strategy="form_description",
        )
        assert doc.embed_text == doc.body_text


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
