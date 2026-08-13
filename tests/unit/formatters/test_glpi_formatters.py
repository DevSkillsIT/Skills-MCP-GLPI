"""
Tests for src/formatters/glpi_formatters.py
Covers all formatter functions for tickets, assets, admin, webhooks,
AI analysis, bridge resources/prompts, and operation success.
"""

import sys

sys.path.insert(0, "/opt/mcp-servers/glpi/.base-code")


from src.formatters.glpi_formatters import (
    format_admin_detail,
    format_ai_analysis_result,
    format_asset_detail,
    format_asset_stats,
    format_assets_list,
    format_entities_list,
    format_groups_list,
    format_locations_list,
    format_operation_success,
    format_prompts_list,
    format_reservations_list,
    format_resources_list,
    format_similar_tickets,
    format_ticket_detail,
    format_ticket_followups,
    format_ticket_history,
    format_ticket_stats,
    format_tickets_list,
    format_user_detail,
    format_users_list,
    format_webhook_deliveries,
    format_webhook_detail,
    format_webhook_stats,
    format_webhooks_list,
)


# ============================================================
# Helpers
# ============================================================

DEFAULT_ARGS: dict = {"limit": 10, "offset": 0}


def _make_ticket(
    tid: int = 1,
    name: str = "Test Ticket",
    status: int = 1,
    priority: int = 3,
    ttype: int = 1,
    date: str = "2024-03-15T10:00:00",
) -> dict:
    return {
        "id": tid,
        "name": name,
        "status": status,
        "priority": priority,
        "type": ttype,
        "date": date,
    }


# ============================================================
# format_tickets_list
# ============================================================


class TestFormatTicketsList:
    """Tests for format_tickets_list()."""

    def test_three_tickets_markdown_table(self) -> None:
        tickets = [_make_ticket(tid=i, name=f"Ticket {i}") for i in range(1, 4)]
        result = format_tickets_list(tickets, DEFAULT_ARGS)
        assert "| ID | Titulo |" in result
        # The id cell renders as a clickable link to the ticket form.
        for tid in (1, 2, 3):
            assert f"ticket.form.php?id={tid}" in result
            assert f"Ticket {tid}" in result
        assert "3 resultados" in result

    def test_group_column_is_present(self) -> None:
        """assigned_group is filterable, so the table must show the group."""
        result = format_tickets_list([_make_ticket(tid=1, name="X")], DEFAULT_ARGS)
        header = result.splitlines()[2]
        assert "| Grupo |" in header
        # Header and separator must keep the same column count, otherwise the
        # Markdown table silently stops rendering.
        separator = result.splitlines()[3]
        assert header.count("|") == separator.count("|")

    def test_zero_tickets(self) -> None:
        assert format_tickets_list([], DEFAULT_ARGS) == "Nenhum ticket encontrado."

    def test_dict_data_with_items_key(self) -> None:
        data = {"items": [_make_ticket()]}
        result = format_tickets_list(data, DEFAULT_ARGS)
        assert "| ID |" in result

    def test_dict_data_with_totalcount(self) -> None:
        data = {"data": [_make_ticket()], "totalcount": 50}
        result = format_tickets_list(data, {"limit": 10, "offset": 10})
        assert "Pagina" in result

    def test_pipe_escaping(self) -> None:
        ticket = _make_ticket(name="Pipe|Test")
        result = format_tickets_list([ticket], DEFAULT_ARGS)
        # truncate_field calls esc internally: | -> \|
        assert r"Pipe\|Test" in result


# ============================================================
# format_ticket_detail
# ============================================================


class TestFormatTicketDetail:
    """Tests for format_ticket_detail()."""

    def test_full_ticket(self) -> None:
        ticket = {
            "id": 42,
            "name": "Critical Bug",
            "status": 1,
            "priority": 4,
            "type": 1,
            "entities_id": 0,
            "users_id_recipient": 5,
            "date": "2024-03-15T10:00:00",
            "date_mod": "2024-03-16T12:00:00",
            "time_to_resolve": "2024-03-17T10:00:00",
            "content": "<p>Description here</p>",
        }
        result = format_ticket_detail(ticket)
        assert "# Ticket #42" in result
        assert "Critical Bug" in result
        assert "Novo" in result
        assert "Alta" in result
        assert "Incidente" in result
        assert "15/03/2024" in result
        assert "Description here" in result

    def test_none_returns_not_found(self) -> None:
        assert format_ticket_detail(None) == "Ticket nao encontrado."

    def test_empty_dict_returns_not_found(self) -> None:
        assert format_ticket_detail({}) == "Ticket nao encontrado."

    def test_html_stripped_in_description(self) -> None:
        ticket = {"id": 1, "name": "T", "content": "<b>bold</b> text"}
        result = format_ticket_detail(ticket)
        assert "<b>" not in result
        assert "bold text" in result


# ============================================================
# format_ticket_followups
# ============================================================


class TestFormatTicketFollowups:
    """Tests for format_ticket_followups()."""

    def test_with_data(self) -> None:
        followups = [
            {"id": 1, "date": "2024-01-01T10:00:00", "content": "First followup", "is_private": False, "users_id": 5},
            {"id": 2, "date": "2024-01-02T10:00:00", "content": "Second", "is_private": True, "users_id": 6},
        ]
        result = format_ticket_followups(followups, DEFAULT_ARGS)
        assert "2 acompanhamentos" in result
        assert "Publico" in result
        assert "Privado" in result
        assert "| ID |" in result

    def test_empty(self) -> None:
        result = format_ticket_followups([], DEFAULT_ARGS)
        assert "Nenhum acompanhamento" in result


# ============================================================
# format_ticket_history
# ============================================================


class TestFormatTicketHistory:
    """Tests for format_ticket_history()."""

    def test_with_data(self) -> None:
        history = [
            {"date_mod": "2024-01-01T10:00:00", "id_search_option": "status", "old_value": "1", "new_value": "2", "users_id": 5},
        ]
        result = format_ticket_history(history, DEFAULT_ARGS)
        assert "1 alteracoes" in result
        assert "| Data |" in result

    def test_capped_at_50_entries(self) -> None:
        history = [
            {"date_mod": f"2024-01-{str(i).zfill(2)}T10:00:00", "id_search_option": "field", "old_value": "a", "new_value": "b", "users_id": 1}
            for i in range(1, 61)  # 60 entries
        ]
        result = format_ticket_history(history, DEFAULT_ARGS)
        assert "60 alteracoes" in result
        assert "Mostrando 50 de 60" in result

    def test_empty(self) -> None:
        result = format_ticket_history([], DEFAULT_ARGS)
        assert "Nenhum historico" in result


# ============================================================
# format_ticket_stats
# ============================================================


class TestFormatTicketStats:
    """Tests for format_ticket_stats()."""

    def test_with_data(self) -> None:
        stats = {
            "by_status": {"Novo": 10, "Fechado": 20},
            "total": 30,
        }
        result = format_ticket_stats(stats)
        assert "Estatisticas de Tickets" in result
        assert "by_status" in result
        assert "Novo" in result
        assert "total" in result

    def test_empty(self) -> None:
        assert format_ticket_stats(None) == "Estatisticas nao disponiveis."
        assert format_ticket_stats({}) == "Estatisticas nao disponiveis."


# ============================================================
# format_similar_tickets
# ============================================================


class TestFormatSimilarTickets:
    """Tests for format_similar_tickets()."""

    def test_with_scores(self) -> None:
        tickets = [
            {"id": 1, "name": "Similar A", "status": 1, "score": 0.95, "date": "2024-01-01T10:00:00"},
            {"id": 2, "name": "Similar B", "status": 2, "similarity": 0.80, "date": "2024-01-02T10:00:00"},
        ]
        result = format_similar_tickets(tickets, DEFAULT_ARGS)
        assert "2 tickets similares" in result
        assert "0.95" in result
        assert "0.8" in result  # "similarity" fallback
        assert "| ID |" in result

    def test_empty(self) -> None:
        result = format_similar_tickets([], DEFAULT_ARGS)
        assert "Nenhum ticket similar" in result


# ============================================================
# format_assets_list
# ============================================================


class TestFormatAssetsList:
    """Tests for format_assets_list()."""

    def test_with_data(self) -> None:
        assets = [
            {"id": 1, "name": "PC-001", "serial": "SN123", "otherserial": "PT001", "states_id": 1, "locations_id": 2},
            {"id": 2, "name": "PC-002", "serial": "SN456", "otherserial": "PT002", "states_id": 1, "locations_id": 3},
        ]
        result = format_assets_list(assets, DEFAULT_ARGS)
        assert "2 resultados" in result
        assert "| ID | Nome |" in result
        assert "PC-001" in result

    def test_empty(self) -> None:
        assert format_assets_list([], DEFAULT_ARGS) == "Nenhum ativo encontrado."


# ============================================================
# format_asset_detail
# ============================================================


class TestFormatAssetDetail:
    """Tests for format_asset_detail()."""

    def test_full_asset(self) -> None:
        asset = {
            "id": 1,
            "name": "Server-01",
            "serial": "SRV001",
            "otherserial": "PT100",
            "states_id": 1,
            "locations_id": 2,
            "entities_id": 0,
            "manufacturers_id": 5,
            "models_id": 3,
            "users_id": 10,
            "groups_id": 2,
            "comment": "Production server",
        }
        result = format_asset_detail(asset)
        assert "# Ativo: Server-01" in result
        assert "SRV001" in result
        assert "| Campo | Valor |" in result

    def test_none_returns_not_found(self) -> None:
        assert format_asset_detail(None) == "Ativo nao encontrado."

    def test_empty_returns_not_found(self) -> None:
        assert format_asset_detail({}) == "Ativo nao encontrado."


# ============================================================
# format_asset_stats
# ============================================================


class TestFormatAssetStats:
    """Tests for format_asset_stats()."""

    def test_with_data(self) -> None:
        stats = {"by_type": {"Computer": 50, "Monitor": 30}, "total": 80}
        result = format_asset_stats(stats)
        assert "Estatisticas de Ativos" in result
        assert "Computer" in result

    def test_empty(self) -> None:
        assert format_asset_stats(None) == "Estatisticas de ativos nao disponiveis."


# ============================================================
# format_reservations_list
# ============================================================


class TestFormatReservationsList:
    """Tests for format_reservations_list()."""

    def test_with_data(self) -> None:
        reservations = [
            {"id": 1, "items_id": 10, "begin": "2024-01-01T08:00:00", "end": "2024-01-01T17:00:00", "users_id": 5, "comment": "Meeting room"},
        ]
        result = format_reservations_list(reservations, DEFAULT_ARGS)
        assert "1 reservas" in result
        assert "| ID |" in result

    def test_empty(self) -> None:
        result = format_reservations_list([], DEFAULT_ARGS)
        assert "Nenhuma reserva" in result


# ============================================================
# format_users_list
# ============================================================


class TestFormatUsersList:
    """Tests for format_users_list()."""

    def test_with_data(self) -> None:
        users = [
            {"id": 1, "name": "admin", "realname": "Admin", "firstname": "User", "is_active": 1, "last_login": "2024-03-15T10:00:00"},
        ]
        result = format_users_list(users, DEFAULT_ARGS)
        assert "1 resultados" in result
        assert "admin" in result
        assert "| ID | Login |" in result

    def test_empty(self) -> None:
        assert format_users_list([], DEFAULT_ARGS) == "Nenhum usuario encontrado."


# ============================================================
# format_user_detail
# ============================================================


class TestFormatUserDetail:
    """Tests for format_user_detail()."""

    def test_full_user(self) -> None:
        user = {
            "id": 1,
            "name": "jdoe",
            "realname": "Doe",
            "firstname": "John",
            "email": "jdoe@example.com",
            "phone": "555-1234",
            "is_active": True,
            "entities_id": 0,
            "last_login": "2024-03-15T10:00:00",
        }
        result = format_user_detail(user)
        assert "# Usuario: jdoe" in result
        assert "Doe" in result
        assert "John" in result
        assert "jdoe@example.com" in result
        assert "Sim" in result  # is_active == True

    def test_inactive_user(self) -> None:
        user = {"id": 2, "name": "inactive", "is_active": False}
        result = format_user_detail(user)
        assert "Nao" in result

    def test_none_returns_not_found(self) -> None:
        assert format_user_detail(None) == "Usuario nao encontrado."


# ============================================================
# format_groups_list
# ============================================================


class TestFormatGroupsList:
    """Tests for format_groups_list()."""

    def test_with_data(self) -> None:
        groups = [
            {"id": 1, "name": "IT Support", "comment": "IT team", "entities_id": 0},
            {"id": 2, "name": "HR", "comment": "", "entities_id": 0},
        ]
        result = format_groups_list(groups, DEFAULT_ARGS)
        assert "2 grupos" in result
        assert "IT Support" in result

    def test_empty(self) -> None:
        assert format_groups_list([], DEFAULT_ARGS) == "Nenhum grupo encontrado."


# ============================================================
# format_entities_list
# ============================================================


class TestFormatEntitiesList:
    """Tests for format_entities_list()."""

    def test_with_data(self) -> None:
        entities = [
            {"id": 0, "name": "Root Entity", "comment": "Main entity"},
        ]
        result = format_entities_list(entities, DEFAULT_ARGS)
        assert "1 entidades" in result
        assert "Root Entity" in result

    def test_empty(self) -> None:
        assert format_entities_list([], DEFAULT_ARGS) == "Nenhuma entidade encontrada."


# ============================================================
# format_locations_list
# ============================================================


class TestFormatLocationsList:
    """Tests for format_locations_list()."""

    def test_with_data(self) -> None:
        locations = [
            {"id": 1, "name": "Building A", "address": "123 Main St", "entities_id": 0},
        ]
        result = format_locations_list(locations, DEFAULT_ARGS)
        assert "1 localizacoes" in result
        assert "Building A" in result
        assert "123 Main St" in result

    def test_empty(self) -> None:
        assert format_locations_list([], DEFAULT_ARGS) == "Nenhuma localizacao encontrada."


# ============================================================
# format_admin_detail
# ============================================================


class TestFormatAdminDetail:
    """Tests for format_admin_detail()."""

    def test_generic_detail(self) -> None:
        data = {"id": 1, "name": "Test Group", "comment": "A group"}
        result = format_admin_detail(data, "groups")
        assert "# Groups" in result
        assert "Test Group" in result
        assert "| Campo | Valor |" in result

    def test_none_returns_not_found(self) -> None:
        result = format_admin_detail(None, "groups")
        assert "Groups nao encontrado(a)" in result

    def test_skips_internal_fields(self) -> None:
        data = {"id": 1, "name": "X", "links": [1], "_links": {}, "completename": "Root > X", "_internal": "skip"}
        result = format_admin_detail(data, "entity")
        assert "links" not in result.split("| Campo")[0]  # Not in the table body
        assert "_links" not in result
        assert "_internal" not in result


# ============================================================
# format_webhooks_list
# ============================================================


class TestFormatWebhooksList:
    """Tests for format_webhooks_list()."""

    def test_with_data(self) -> None:
        webhooks = [
            {"id": 1, "name": "Alert Hook", "url": "https://example.com/hook", "is_active": True, "event": "ticket.create"},
        ]
        result = format_webhooks_list(webhooks, DEFAULT_ARGS)
        assert "1 webhooks" in result
        assert "Alert Hook" in result
        assert "Ativo" in result

    def test_inactive_webhook(self) -> None:
        webhooks = [{"id": 1, "name": "WH", "is_active": False, "event": "test"}]
        result = format_webhooks_list(webhooks, DEFAULT_ARGS)
        assert "Inativo" in result

    def test_empty(self) -> None:
        assert format_webhooks_list([], DEFAULT_ARGS) == "Nenhum webhook encontrado."


# ============================================================
# format_webhook_detail
# ============================================================


class TestFormatWebhookDetail:
    """Tests for format_webhook_detail()."""

    def test_full_webhook(self) -> None:
        webhook = {
            "id": 1,
            "name": "My Webhook",
            "url": "https://hooks.example.com/glpi",
            "event": "ticket.update",
            "is_active": True,
            "secret": "abc123",
        }
        result = format_webhook_detail(webhook)
        assert "# Webhook: My Webhook" in result
        assert "Sim" in result  # is_active
        assert "Configurado" in result  # secret is set

    def test_no_secret(self) -> None:
        webhook = {"id": 1, "name": "WH", "is_active": False}
        result = format_webhook_detail(webhook)
        assert "Nao configurado" in result
        assert "Nao" in result

    def test_none_returns_not_found(self) -> None:
        assert format_webhook_detail(None) == "Webhook nao encontrado."


# ============================================================
# format_webhook_stats
# ============================================================


class TestFormatWebhookStats:
    """Tests for format_webhook_stats()."""

    def test_with_data(self) -> None:
        stats = {"total_deliveries": 100, "success_rate": "95%"}
        result = format_webhook_stats(stats)
        assert "Estatisticas de Webhooks" in result
        assert "total_deliveries" in result
        assert "100" in result

    def test_empty(self) -> None:
        assert format_webhook_stats(None) == "Estatisticas de webhooks nao disponiveis."


# ============================================================
# format_webhook_deliveries
# ============================================================


class TestFormatWebhookDeliveries:
    """Tests for format_webhook_deliveries()."""

    def test_with_data(self) -> None:
        deliveries = [
            {"id": 1, "date": "2024-03-15T10:00:00", "status_code": 200, "event": "ticket.create", "response": "OK"},
        ]
        result = format_webhook_deliveries(deliveries, DEFAULT_ARGS)
        assert "1 entregas" in result
        assert "200" in result

    def test_empty(self) -> None:
        result = format_webhook_deliveries([], DEFAULT_ARGS)
        assert "Nenhuma entrega" in result


# ============================================================
# format_ai_analysis_result
# ============================================================


class TestFormatAiAnalysisResult:
    """Tests for format_ai_analysis_result()."""

    def test_with_data(self) -> None:
        data = {
            "classification": "Hardware issue",
            "confidence": 0.92,
            "recommendation": "x" * 400,  # long text triggers truncation section
        }
        result = format_ai_analysis_result(data)
        assert "Analise IA" in result
        assert "Hardware issue" in result
        assert "0.92" in result
        # Long recommendation goes to ## section
        assert "## recommendation" in result

    def test_empty(self) -> None:
        assert format_ai_analysis_result(None) == "Resultado de analise nao disponivel."


# ============================================================
# format_resources_list
# ============================================================


class TestFormatResourcesList:
    """Tests for format_resources_list()."""

    def test_with_uri_data(self) -> None:
        resources = [
            {"uri": "glpi://tickets", "name": "Tickets", "description": "Ticket resource"},
            {"uri": "glpi://assets", "name": "Assets", "description": "Asset resource"},
        ]
        result = format_resources_list(resources)
        assert "2 resources disponiveis" in result
        assert "glpi://tickets" in result
        assert "| URI | Nome |" in result

    def test_empty(self) -> None:
        assert format_resources_list([]) == "Nenhum resource disponivel."


# ============================================================
# format_prompts_list
# ============================================================


class TestFormatPromptsList:
    """Tests for format_prompts_list()."""

    def test_with_prompt_data(self) -> None:
        prompts = [
            {
                "name": "analyze_ticket",
                "description": "Analyze a ticket",
                "category": "ai",
                "arguments": [{"name": "ticket_id"}, {"name": "depth"}],
            },
        ]
        result = format_prompts_list(prompts)
        assert "1 prompts disponiveis" in result
        assert "analyze_ticket" in result
        assert "ticket_id, depth" in result

    def test_empty(self) -> None:
        assert format_prompts_list([]) == "Nenhum prompt disponivel."


# ============================================================
# format_operation_success
# ============================================================


class TestFormatOperationSuccess:
    """Tests for format_operation_success()."""

    def test_with_message(self) -> None:
        data = {"message": "Ticket created successfully"}
        result = format_operation_success(data, "criar ticket")
        assert "criar ticket" in result
        assert "Ticket created successfully" in result

    def test_with_id(self) -> None:
        data = {"id": 42, "message": "Done"}
        result = format_operation_success(data, "atualizar ticket")
        assert "ID: 42" in result
        assert "Done" in result

    def test_none_data(self) -> None:
        result = format_operation_success(None, "excluir ticket")
        assert "excluir ticket" in result
        assert "realizada com sucesso" in result

    def test_empty_data(self) -> None:
        result = format_operation_success({}, "fechar ticket")
        assert "fechar ticket" in result


# ============================================================
# Pipe escaping test across all formatters
# ============================================================


class TestPipeEscapingAcrossFormatters:
    """Verify pipe characters are escaped in all list/detail formatters."""

    def test_tickets_list_pipe(self) -> None:
        ticket = _make_ticket(name="A|B")
        result = format_tickets_list([ticket], DEFAULT_ARGS)
        # Single escape: truncate_field calls esc internally
        assert r"A\|B" in result

    def test_ticket_detail_pipe(self) -> None:
        ticket = {"id": 1, "name": "C|D", "content": ""}
        result = format_ticket_detail(ticket)
        assert "C\\|D" in result

    def test_assets_list_pipe(self) -> None:
        asset = {"id": 1, "name": "X|Y"}
        result = format_assets_list([asset], DEFAULT_ARGS)
        # Single escape: truncate_field calls esc internally
        assert r"X\|Y" in result

    def test_users_list_pipe(self) -> None:
        user = {"id": 1, "name": "u|v"}
        result = format_users_list([user], DEFAULT_ARGS)
        assert "u\\|v" in result

    def test_webhooks_list_pipe(self) -> None:
        webhook = {"id": 1, "name": "w|h", "is_active": True, "event": "e"}
        result = format_webhooks_list([webhook], DEFAULT_ARGS)
        assert "w\\|h" in result

    def test_groups_list_pipe(self) -> None:
        group = {"id": 1, "name": "g|p"}
        result = format_groups_list([group], DEFAULT_ARGS)
        assert "g\\|p" in result

    def test_entities_list_pipe(self) -> None:
        entity = {"id": 1, "name": "e|n"}
        result = format_entities_list([entity], DEFAULT_ARGS)
        assert "e\\|n" in result

    def test_locations_list_pipe(self) -> None:
        loc = {"id": 1, "name": "l|o"}
        result = format_locations_list([loc], DEFAULT_ARGS)
        assert "l\\|o" in result
