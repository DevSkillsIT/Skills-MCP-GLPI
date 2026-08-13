"""Regressao da auditoria de 12/08/2026 (incidente do chamado 9449).

Uma sessao externa recebeu ERROR_RIGHT_MISSING do GLPI em todas as leituras do
chamado 9449 e concluiu, no relatorio ao usuario, que o chamado nao existia e
que a analise por IA "foi disparada com sucesso". A causa raiz do erro era o
token daquela sessao, mas a auditoria que se seguiu encontrou sete defeitos no
MCP — todos de uma mesma familia: a tool responde algo que o leitor interpreta
como fato quando nao e.

Cada teste aqui fixa um desses comportamentos.
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.models.exceptions import GLPIError


# ---------------------------------------------------------------------------
# 1. A tool de analise IA nao pode ser anunciada enquanto for um stub
# ---------------------------------------------------------------------------


class TestAIAnalysisGate:
    def test_ai_tool_not_registered_by_default(self):
        """Sem ENABLE_AI_ANALYSIS a tool fica fora de tools/list."""
        from src.config.settings import settings
        from src.handlers import MCPHandler

        assert settings.enable_ai_analysis is False
        assert "glpi_manage_ticket_ai_analysis" not in MCPHandler().tools

    @pytest.mark.asyncio
    async def test_initialize_does_not_advertise_a_gated_tool(self):
        """As instructions descrevem o que foi registrado, nao um roster fixo."""
        from src.handlers import MCPHandler

        handler = MCPHandler()
        response = await handler.handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
        instructions = response["result"]["instructions"]

        assert "glpi_manage_ticket_ai_analysis" not in instructions
        assert f"({len(handler.tools)} tools)" in instructions

    def test_ai_service_is_kept_for_future_use(self):
        """O gate esconde a tool; nao apaga o codigo."""
        from src.tools.consolidated_tickets import manage_ai_analysis

        assert callable(manage_ai_analysis)

    @pytest.mark.asyncio
    async def test_enabling_the_flag_registers_and_advertises_the_tool(self, monkeypatch):
        """O outro lado do flag: religar tem que voltar tudo, nao so a tool.

        Um gate que esconde mas nao sabe reaparecer e uma remocao disfarcada —
        e so se descobre no dia em que o agente de IA existir.
        """
        from src.config.settings import settings
        from src.handlers import MCPHandler

        monkeypatch.setattr(settings, "enable_ai_analysis", True)
        handler = MCPHandler()

        assert "glpi_manage_ticket_ai_analysis" in handler.tools

        response = await handler.handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
        instructions = response["result"]["instructions"]
        assert "glpi_manage_ticket_ai_analysis" in instructions
        assert "TICKETS (3 tools)" in instructions
        assert f"({len(handler.tools)} tools)" in instructions


# ---------------------------------------------------------------------------
# 2. get_by_number: 403 nao pode virar "nao encontrado"
# ---------------------------------------------------------------------------


class TestGetTicketByNumberErrorPropagation:
    @pytest.mark.asyncio
    async def test_permission_error_is_raised_not_swallowed(self):
        """ERROR_RIGHT_MISSING chega ao chamador como erro, nao como None."""
        from src.services.ticket_service import ticket_service

        boom = GLPIError(403, 'HTTP error: ["ERROR_RIGHT_MISSING"]')
        with patch(
            "src.services.ticket_service.glpi_client.get",
            new=AsyncMock(side_effect=boom),
        ) as mocked:
            with pytest.raises(GLPIError) as excinfo:
                await ticket_service.get_ticket_by_number("9449")

        assert excinfo.value.code == 403
        # A busca por titulo NAO pode ter sido tentada: uma segunda chamada aqui
        # e exatamente o que produzia o falso "chamado nao encontrado".
        assert mocked.await_count == 1

    @pytest.mark.asyncio
    async def test_genuine_404_still_falls_back_to_title_search(self):
        """O fallback legitimo continua existindo."""
        from src.models.exceptions import NotFoundError
        from src.services.ticket_service import ticket_service

        async def _get(path, params=None):
            if path.endswith("/Ticket/9449"):
                raise NotFoundError("Ticket", 9449)
            return {"data": []}

        with patch("src.services.ticket_service.glpi_client.get", new=AsyncMock(side_effect=_get)):
            assert await ticket_service.get_ticket_by_number("9449") is None


# ---------------------------------------------------------------------------
# 3. Busca por criterios: coluna nomeada e valor decodificado
# ---------------------------------------------------------------------------


class TestGenericSearchColumns:
    def _data(self):
        return {
            "itemtype": "Ticket",
            "scope": "search",
            "limit": 10,
            "offset": 0,
            "total": 1,
            "rows": [{"2": 9468, "1": "Ramal mudo", "12": 1, "3": 4}],
            "column_labels": {"2": "ID", "1": "Titulo", "12": "Status", "3": "Prioridade"},
            "column_columns": {"2": "id", "1": "name", "12": "status", "3": "priority"},
        }

    def test_headers_carry_the_field_name(self):
        from src.tools.consolidated_search import format_search_records

        out = format_search_records(self._data(), {})
        assert "Status (#12)" in out
        assert "Prioridade (#3)" in out

    def test_enum_values_are_decoded(self):
        from src.tools.consolidated_search import format_search_records

        out = format_search_records(self._data(), {})
        assert "| Novo |" in out
        assert "| Alta |" in out

    def test_unlabelled_column_degrades_to_the_id(self):
        """Sem catalogo, o cabecalho diz que e um id — nao finge um nome."""
        from src.tools.consolidated_search import format_search_records

        data = self._data()
        data["column_labels"] = {}
        data["column_columns"] = {}
        out = format_search_records(data, {})
        assert "#12" in out

    def test_non_itil_itemtype_is_not_decoded_as_a_ticket(self):
        """`status` de um Computer nao usa a tabela de status de chamado."""
        from src.tools.consolidated_search import format_search_records

        data = self._data()
        data["itemtype"] = "Computer"
        out = format_search_records(data, {})
        assert "Novo" not in out


# ---------------------------------------------------------------------------
# 4. Coercao de escalar: o id que a listagem imprimiu tem que ser aceito
# ---------------------------------------------------------------------------


class TestScalarCoercion:
    def _coerce(self, arguments, schema):
        from src.handlers import MCPHandler

        MCPHandler()._validate_arguments("t", arguments, schema)
        return arguments

    def test_int_is_accepted_where_schema_says_string(self):
        schema = {"type": "object", "properties": {"webhook_id": {"type": "string"}}}
        assert self._coerce({"webhook_id": 4}, schema)["webhook_id"] == "4"

    def test_numeric_string_is_accepted_where_schema_says_integer(self):
        schema = {"type": "object", "properties": {"ticket_id": {"type": "integer"}}}
        assert self._coerce({"ticket_id": "9449"}, schema)["ticket_id"] == 9449

    def test_boolean_string_is_accepted_where_schema_says_boolean(self):
        schema = {"type": "object", "properties": {"open_only": {"type": "boolean"}}}
        assert self._coerce({"open_only": "true"}, schema)["open_only"] is True

    def test_ambiguous_value_still_fails(self):
        """Coercao e para notacao, nao para valor errado."""
        from src.handlers import MCPHandler
        from src.models.exceptions import ValidationError

        schema = {"type": "object", "properties": {"ticket_id": {"type": "integer"}}}
        with pytest.raises(ValidationError):
            MCPHandler()._validate_arguments("t", {"ticket_id": "nove mil"}, schema)

    def test_bool_is_not_silently_stringified(self):
        """True nao vira '1' num campo de texto."""
        from src.handlers import MCPHandler
        from src.models.exceptions import ValidationError

        schema = {"type": "object", "properties": {"reason": {"type": "string"}}}
        with pytest.raises(ValidationError):
            MCPHandler()._validate_arguments("t", {"reason": True}, schema)


# ---------------------------------------------------------------------------
# 5. Ficha do usuario: grupos, perfis e entidades por NOME
# ---------------------------------------------------------------------------


class TestUserDetailNames:
    def test_groups_profiles_and_entities_are_named(self):
        from src.formatters.glpi_formatters import format_user_detail

        out = format_user_detail(
            {
                "id": 372,
                "name": "tecnico.teste",
                "groups_names": ["Infraestrutura", "Suporte N2"],
                "profiles_names": ["Super-Admin"],
                "entities_names": ["Entidade Raiz"],
            }
        )
        assert "Infraestrutura, Suporte N2" in out
        assert "Super-Admin" in out
        assert "Entidade Raiz" in out
        # A contagem nua era lida como "grupo 8".
        assert "| Grupos | 2 |" not in out

    def test_absent_names_degrade_to_a_dash(self):
        from src.formatters.glpi_formatters import format_user_detail

        out = format_user_detail({"id": 1, "name": "x"})
        assert "| Grupos | — |" in out

    @pytest.mark.asyncio
    async def test_get_user_resolves_the_ids_it_fetched(self):
        """Os subitens custam uma chamada cada; nao podem ser descartados."""
        from src.services.admin_service import admin_service

        subitems = {
            "Group_User": [{"groups_id": 7}],
            "Profile_User": [{"profiles_id": 4}],
            "Entity_User": [{"entities_id": 0}],
        }
        names = {"Group": {7: "Infraestrutura"}, "Profile": {4: "Super-Admin"}, "Entity": {0: "Entidade Raiz"}}

        with patch.object(admin_service.client, "get_item", new=AsyncMock(return_value={"id": 372})), \
             patch.object(
                 admin_service.client,
                 "get_subitems",
                 new=AsyncMock(side_effect=lambda *a: subitems.get(a[2], [])),
             ), \
             patch(
                 "src.services.admin_service.dropdown_cache.get_many_names",
                 new=AsyncMock(side_effect=lambda itemtype, ids: names.get(itemtype, {})),
             ):
            user = await admin_service.get_user(372)

        assert user["groups_names"] == ["Infraestrutura"]
        assert user["profiles_names"] == ["Super-Admin"]
        assert user["entities_names"] == ["Entidade Raiz"]


# ---------------------------------------------------------------------------
# 6. Historico: codigo do GLPI nao e resposta
# ---------------------------------------------------------------------------


class TestTicketHistoryDecoding:
    def test_status_codes_become_status_names(self):
        from src.formatters.glpi_formatters import format_ticket_history

        out = format_ticket_history(
            [{"date_mod": "2026-08-05 14:01:00", "id_search_option": "12", "old_value": "1", "new_value": "2"}],
            {},
        )
        assert "Novo" in out and "Atribuido" in out
        assert "| 1 | 2 |" not in out

    def test_duration_fields_are_humanised(self):
        from src.formatters.glpi_formatters import format_ticket_history

        out = format_ticket_history(
            [{"date_mod": "2026-08-05 14:01:00", "id_search_option": "150", "old_value": "0", "new_value": "11580"}],
            {},
        )
        assert "3h 13min" in out
        assert "11580" not in out
        # Zero e um valor de tempo, nao um dado ausente.
        assert "| 0 |" in out

    def test_entry_without_a_field_code_is_labelled(self):
        from src.formatters.glpi_formatters import format_ticket_history

        out = format_ticket_history(
            [
                {"date_mod": "2026-08-05 10:48:00", "itemtype_link": "ITILCategory", "new_value": "Sankhya ERP (51)"},
                {"date_mod": "2026-08-05 10:48:00"},
            ],
            {},
        )
        assert "Vinculo (ITILCategory)" in out
        assert "Evento do chamado" in out

    def test_namespaced_itemtype_link_is_shortened(self):
        from src.formatters.glpi_formatters import format_ticket_history

        out = format_ticket_history(
            [{"date_mod": "2026-08-05 10:48:00", "itemtype_link": "Glpi\\Form\\AnswersSet"}], {}
        )
        assert "Vinculo (AnswersSet)" in out

    def test_placeholder_itemtype_link_is_not_a_link(self):
        """GLPI grava itemtype_link='0' quando nao ha vinculo nenhum."""
        from src.formatters.glpi_formatters import format_ticket_history

        out = format_ticket_history(
            [{"date_mod": "2026-08-05 10:48:00", "itemtype_link": "0"}], {}
        )
        assert "Vinculo (0)" not in out
        assert "Evento do chamado" in out

    def test_free_text_values_are_untouched(self):
        from src.formatters.glpi_formatters import format_ticket_history

        out = format_ticket_history(
            [{"date_mod": "2026-08-05 10:48:00", "id_search_option": "1", "old_value": "Antigo", "new_value": "Novo titulo"}],
            {},
        )
        assert "Novo titulo" in out


# ---------------------------------------------------------------------------
# 7. KB unificada: URL clicavel em todas as fontes
# ---------------------------------------------------------------------------


class TestKnowledgeBaseUrls:
    def test_relative_ticket_path_is_made_absolute(self):
        from src.config.settings import settings
        from src.services.kb_search.service import _absolute_url

        out = _absolute_url("/front/ticket.form.php?id=9397")
        assert out.startswith(str(settings.glpi_base_url).rstrip("/"))
        assert out.endswith("/front/ticket.form.php?id=9397")

    def test_absolute_url_is_left_alone(self):
        from src.services.kb_search.service import _absolute_url

        url = "https://ajuda.sankhya.com.br/hc/pt-br/articles/360045112173"
        assert _absolute_url(url) == url

    def test_empty_url_stays_empty(self):
        from src.services.kb_search.service import _absolute_url

        assert _absolute_url("") == ""


# ---------------------------------------------------------------------------
# 8. Filtro de pessoa: qualquer parte do nome
# ---------------------------------------------------------------------------


class TestPersonFilterByAnyNamePart:
    """O nome que a listagem EXIBE nao e o texto que a Search API PROCURA.

    O GLPI guarda a pessoa em tres colunas (`name` = login, `firstname`,
    `realname`) e compara uma por vez. Quem pergunta escreve o nome como a
    tabela o mostra — "Azeredo Da Silva Guimaraes Erica" — que nao existe
    inteiro em coluna nenhuma. O filtro devolvia zero chamados, sem erro.
    """

    @pytest.mark.asyncio
    async def test_full_display_name_resolves_to_the_user_id(self):
        from src.services.ticket_service import ticket_service

        users = [
            {"id": 102, "name": "ericaguimaraes", "firstname": "Erica",
             "realname": "Azeredo Da Silva Guimaraes"},
        ]
        with patch("src.services.ticket_service.glpi_client.get",
                   new=AsyncMock(return_value=users)):
            criterion = await ticket_service._person_criterion(4, "Azeredo Da Silva Guimaraes Erica")

        assert criterion == {"field": 4, "searchtype": "equals", "value": 102}

    @pytest.mark.asyncio
    async def test_partial_surname_also_resolves(self):
        from src.services.ticket_service import ticket_service

        users = [{"id": 102, "name": "ericaguimaraes", "firstname": "Erica",
                  "realname": "Azeredo Da Silva Guimaraes"}]
        with patch("src.services.ticket_service.glpi_client.get",
                   new=AsyncMock(return_value=users)):
            criterion = await ticket_service._person_criterion(4, "guimar")

        assert criterion["value"] == 102

    @pytest.mark.asyncio
    async def test_several_matches_become_an_or_group(self):
        """Ambiguidade num FILTRO amplia o resultado; nao recusa a pergunta."""
        from src.services.ticket_service import ticket_service

        users = [
            {"id": 1, "name": "jsilva", "firstname": "Joao", "realname": "Silva"},
            {"id": 2, "name": "msilva", "firstname": "Maria", "realname": "Silva"},
        ]
        with patch("src.services.ticket_service.glpi_client.get",
                   new=AsyncMock(return_value=users)):
            criterion = await ticket_service._person_criterion(4, "Silva")

        assert [c["value"] for c in criterion["criteria"]] == [1, 2]
        assert criterion["criteria"][1]["link"] == "OR"

    @pytest.mark.asyncio
    async def test_best_coverage_wins_over_a_common_surname(self):
        """Quem casa nome E sobrenome nao concorre com quem casa so o sobrenome."""
        from src.services.ticket_service import ticket_service

        users = [
            {"id": 1, "name": "jsilva", "firstname": "Joao", "realname": "Silva"},
            {"id": 2, "name": "msilva", "firstname": "Maria", "realname": "Silva"},
        ]
        with patch("src.services.ticket_service.glpi_client.get",
                   new=AsyncMock(return_value=users)):
            criterion = await ticket_service._person_criterion(4, "Maria Silva")

        assert criterion == {"field": 4, "searchtype": "equals", "value": 2}

    @pytest.mark.asyncio
    async def test_numeric_id_is_still_taken_literally(self):
        from src.services.ticket_service import ticket_service

        criterion = await ticket_service._person_criterion(4, 372)
        assert criterion == {"field": 4, "searchtype": "equals", "value": 372}

    @pytest.mark.asyncio
    async def test_no_match_falls_back_to_a_text_search(self):
        """Sem candidato, tenta o login — melhor que descartar o filtro."""
        from src.services.ticket_service import ticket_service

        with patch("src.services.ticket_service.glpi_client.get",
                   new=AsyncMock(return_value=[])):
            criterion = await ticket_service._person_criterion(4, "ninguem")

        assert criterion["searchtype"] == "contains"

    @pytest.mark.asyncio
    async def test_surname_prepositions_are_not_used_as_probes(self):
        """'de'/'da'/'dos' casam com meia base e nao identificam ninguem."""
        from src.services.ticket_service import ticket_service

        seen = []

        async def _get(path, params=None, **kwargs):
            seen.append((params or {}))
            return []

        with patch("src.services.ticket_service.glpi_client.get", new=AsyncMock(side_effect=_get)):
            await ticket_service._find_users_by_any_name_part("Maria De Souza")

        probes = {v for p in seen for k, v in p.items() if k.startswith("searchText")}
        assert "De" not in probes and "de" not in probes
        assert probes <= {"Maria", "Souza"}


# ---------------------------------------------------------------------------
# 9. Inventario de computador: hardware basico sem segunda tool
# ---------------------------------------------------------------------------


class TestComputerHardwareInListing:
    def _computer(self, **over):
        base = {
            "id": 3, "name": "PCTESTE01", "serial": "AAA111", "asset_type": "Computer",
            "states_id": "Ativo em Uso", "types_id": "Notebook",
            "cpu": "Intel(R) Core(TM) i7-8700 CPU @ 3.20GHz",
            "memory_mb": "16384.0000", "memory_type": "DDR4 - 2666 - DIMM",
            "disk_names": ["HGST HTS721010A9E630", "Reletech P400 SSD 1024GB"],
            "disk_capacity_mb": "2024413.0000",
            "volume_total_mb": ["1246", "974591"],
            "volume_free_mb": ["498", "602177"],
        }
        base.update(over)
        return base

    def test_hardware_columns_are_present(self):
        from src.formatters.glpi_formatters import format_assets_list

        out = format_assets_list([self._computer()], {"limit": 10})
        assert "| Tipo | CPU | RAM | Disco | Uso |" in out
        assert "Notebook" in out
        assert "16.0 GB DDR4-2666" in out

    def test_disk_kind_comes_from_the_model_not_the_type_column(self):
        """GLPI colapsa 'Disco rigido: Tipo' e diz HDD numa maquina HDD+SSD."""
        from src.formatters.glpi_formatters import format_assets_list

        out = format_assets_list([self._computer()], {"limit": 10})
        assert "SSD+HDD" in out
        assert "(2 discos)" in out

    def test_usage_reports_the_largest_volume(self):
        """A particao de recuperacao de 1 GB nao descreve a maquina."""
        from src.formatters.glpi_formatters import format_assets_list

        out = format_assets_list([self._computer()], {"limit": 10})
        assert "38% de 951.7 GB" in out

    def test_non_computer_assets_get_no_hardware_columns(self):
        from src.formatters.glpi_formatters import format_assets_list

        out = format_assets_list(
            [{"id": 1, "name": "Monitor X", "asset_type": "Monitor"}], {"limit": 10}
        )
        assert "| Tipo | CPU | RAM |" not in out

    def test_missing_hardware_degrades_to_a_dash(self):
        from src.formatters.glpi_formatters import format_assets_list

        out = format_assets_list(
            [{"id": 9, "name": "SEM-INVENTARIO", "asset_type": "Computer"}], {"limit": 10}
        )
        assert "N/A" in out or "—" in out

    def test_paginated_shape_is_rendered(self):
        """{'assets': [...]} era renderizado como 'Nenhum ativo encontrado'."""
        from src.formatters.glpi_formatters import format_assets_list

        out = format_assets_list(
            {"assets": [self._computer()], "pagination": {"total": 119}}, {"limit": 4}
        )
        assert "PCTESTE01" in out
        assert "119" in out
        assert "Nenhum ativo encontrado" not in out


# ---------------------------------------------------------------------------
# 10. Sanitizacao: gravar o texto, nao a sua representacao em HTML
# ---------------------------------------------------------------------------


class TestSanitizerDoesNotCorruptText:
    """O escape duplo que chegava ao cliente final.

    sanitize_string aplicava html.escape antes de mandar ao GLPI, e o GLPI
    escapava de novo ao gravar. Uma nota com `"copia de 3"` era EXIBIDA no
    chamado como `&quot;copia de 3&quot;`, literal, para o cliente ler. Escapar
    e responsabilidade de quem renderiza, nunca de quem grava.
    """

    def test_quotes_survive(self):
        from src.utils.helpers import input_sanitizer

        text = 'Este chamado e "copia de 3" de uma serie'
        assert input_sanitizer.sanitize_string(text, allow_html=True) == text
        assert "&quot;" not in input_sanitizer.sanitize_string(text)

    def test_ampersand_survives(self):
        from src.utils.helpers import input_sanitizer

        assert input_sanitizer.sanitize_string("Setor P&D & Compras") == "Setor P&D & Compras"

    def test_accents_and_dashes_survive(self):
        from src.utils.helpers import input_sanitizer

        text = "Impressora não imprime — ação urgente"
        assert input_sanitizer.sanitize_string(text) == text

    def test_rich_text_keeps_formatting_tags(self):
        """<p>/<strong> sao o formato que o editor do GLPI grava."""
        from src.utils.helpers import input_sanitizer

        text = "<p>Diagnostico com <strong>causa raiz</strong></p>"
        assert input_sanitizer.sanitize_string(text, allow_html=True) == text

    def test_scalar_field_still_drops_tags(self):
        from src.utils.helpers import input_sanitizer

        assert input_sanitizer.sanitize_string("<p>Nome</p>") == "Nome"

    def test_script_is_removed_even_in_rich_text(self):
        from src.utils.helpers import input_sanitizer

        out = input_sanitizer.sanitize_string(
            "Antes<script>alert(1)</script>Depois", allow_html=True
        )
        assert out == "AntesDepois"

    def test_event_handlers_are_removed(self):
        from src.utils.helpers import input_sanitizer

        out = input_sanitizer.sanitize_string('<img src=x onerror=alert(1)>foto', allow_html=True)
        assert "onerror" not in out
        assert "foto" in out

    def test_javascript_url_is_neutralised_without_breaking_the_tag(self):
        """Apagar o atributo inteiro deixava `<a ">` no meio da nota."""
        from src.utils.helpers import input_sanitizer

        out = input_sanitizer.sanitize_string(
            '<a href="javascript:alert(1)">clique</a>', allow_html=True
        )
        assert out == '<a href="#">clique</a>'

    def test_legitimate_link_is_untouched(self):
        from src.utils.helpers import input_sanitizer

        text = '<a href="https://intranet/rel?a=1&b=2">relatorio</a>'
        assert input_sanitizer.sanitize_string(text, allow_html=True) == text

    def test_search_query_keeps_quotes(self):
        """html.escape virava `&quot;`, e o filtro de caracteres deixava `quot`."""
        from src.utils.helpers import input_sanitizer

        assert input_sanitizer.sanitize_search_query('"impressora HP"') == '"impressora HP"'

    def test_rich_text_limit_is_not_the_short_field_limit(self):
        """10.000 caracteres mutilava laudo tecnico e log colado no chamado."""
        from src.utils.helpers import input_sanitizer

        long_note = "a" * 50_000
        assert len(input_sanitizer.sanitize_string(long_note, allow_html=True)) == 50_000

    def test_truncation_says_how_much_was_lost(self):
        from src.utils.helpers import input_sanitizer

        out = input_sanitizer.sanitize_string("a" * 12_000)
        assert "TEXTO CORTADO PELO MCP" in out
        assert "2000" in out
