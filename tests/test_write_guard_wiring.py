"""
A política de escrita e a idempotência têm de estar NO CAMINHO de execução.

Existiam módulos completos e testados para as duas coisas, com 281 testes — e
nenhuma tool os chamava. A proteção existia no repositório e não em produção:
repetir uma criação abria dois chamados, e o modo somente-leitura não impedia
nada. Testar os módulos isoladamente não revela isso; só um teste que passe
pelo despacho revela.
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.handlers import MCPHandler
from src.security.write_policy import (
    PROFILE_READ_ONLY,
    WritePolicy,
    reset_write_policy,
    set_write_policy,
)
from src.security.idempotency import reset_idempotency_store, set_idempotency_store


@pytest.fixture(autouse=True)
def _clean_singletons():
    """Isola cada teste, inclusive do estado que sobrevive em disco.

    A idempotência usa SQLite por padrão justamente para sobreviver a
    reinício — o que significa que dois testes com o mesmo payload se
    contaminam, e o segundo recebe o replay do primeiro. Aqui usamos o
    backend em memória para que cada teste comece limpo de verdade.
    """
    from src.security.idempotency import IdempotencyStore, MemoryIdempotencyBackend

    reset_write_policy()
    set_idempotency_store(IdempotencyStore(backend=MemoryIdempotencyBackend()))
    yield
    reset_write_policy()
    reset_idempotency_store()


@pytest.fixture
def handler():
    return MCPHandler()


def _request(tool, arguments):
    return {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
        "id": 1,
    }


class TestPolicyIsOnThePath:
    async def test_read_only_mode_blocks_ticket_creation(self, handler):
        """O modo somente-leitura precisa deter a chamada ANTES do GLPI."""
        set_write_policy(WritePolicy(env=PROFILE_READ_ONLY.as_environment()))
        service = AsyncMock()

        with patch("src.tools.consolidated_tickets.ticket_service.create_ticket", service):
            response = await handler.handle_request(
                _request("glpi_manage_ticket_operations", {
                    "action": "create", "title": "x", "description": "y",
                })
            )

        assert "error" in response
        # E o mais importante: o GLPI nunca foi tocado.
        service.assert_not_awaited()

    async def test_read_only_mode_does_not_block_reads(self, handler):
        set_write_policy(WritePolicy(env=PROFILE_READ_ONLY.as_environment()))
        service = AsyncMock(return_value=[])

        with patch("src.tools.consolidated_tickets.ticket_service.list_tickets", service):
            response = await handler.handle_request(
                _request("glpi_search_helpdesk_tickets", {"limit": 2})
            )

        assert "error" not in response

    async def test_disabling_one_operation_leaves_the_others(self, handler):
        set_write_policy(WritePolicy(env={"GLPI_ALLOW_TICKET_CREATE": "false"}))
        create = AsyncMock()
        followup = AsyncMock(return_value={"id": 1})

        with patch("src.tools.consolidated_tickets.ticket_service.create_ticket", create), \
             patch("src.tools.consolidated_tickets.ticket_service.add_ticket_followup", followup):
            blocked = await handler.handle_request(
                _request("glpi_manage_ticket_operations", {
                    "action": "create", "title": "x", "description": "y",
                })
            )
            allowed = await handler.handle_request(
                _request("glpi_manage_ticket_operations", {
                    "action": "add_followup", "ticket_id": 1,
                    "content": "acompanhamento de verificacao",
                })
            )

        assert "error" in blocked
        create.assert_not_awaited()
        assert "error" not in allowed


class TestIdempotencyIsOnThePath:
    async def test_repeating_a_creation_does_not_create_twice(self, handler):
        """O caso real: o cliente MCP repete a chamada apos um timeout."""
        service = AsyncMock(return_value={"id": 4242, "name": "Impressora"})

        with patch("src.tools.consolidated_tickets.ticket_service.create_ticket", service):
            args = {"action": "create", "title": "Impressora", "description": "nao imprime"}
            first = await handler.handle_request(_request("glpi_manage_ticket_operations", args))
            second = await handler.handle_request(_request("glpi_manage_ticket_operations", args))

        assert "error" not in first
        assert "error" not in second
        # Duas chamadas, UMA criacao.
        assert service.await_count == 1

    async def test_different_content_creates_again(self, handler):
        """Chamados diferentes têm de passar — a guarda é por conteúdo."""
        service = AsyncMock(return_value={"id": 1})

        with patch("src.tools.consolidated_tickets.ticket_service.create_ticket", service):
            await handler.handle_request(_request("glpi_manage_ticket_operations", {
                "action": "create", "title": "Impressora", "description": "a",
            }))
            await handler.handle_request(_request("glpi_manage_ticket_operations", {
                "action": "create", "title": "Monitor", "description": "b",
            }))

        assert service.await_count == 2

    async def test_updates_are_not_deduplicated(self, handler):
        """Atualizar duas vezes converge no mesmo estado — não é para deter."""
        service = AsyncMock(return_value={"id": 1})

        with patch("src.tools.consolidated_tickets.ticket_service.update_ticket", service):
            args = {"action": "update", "ticket_id": 1, "priority": 5}
            await handler.handle_request(_request("glpi_manage_ticket_operations", args))
            await handler.handle_request(_request("glpi_manage_ticket_operations", args))

        assert service.await_count == 2

    async def test_a_failed_creation_is_not_cached_as_success(self, handler):
        """Se a primeira falhou, a segunda tem de tentar de verdade."""
        service = AsyncMock(side_effect=[RuntimeError("GLPI fora"), {"id": 7}])

        with patch("src.tools.consolidated_tickets.ticket_service.create_ticket", service):
            args = {"action": "create", "title": "Impressora", "description": "a"}
            first = await handler.handle_request(_request("glpi_manage_ticket_operations", args))
            second = await handler.handle_request(_request("glpi_manage_ticket_operations", args))

        assert "error" in first
        assert "error" not in second
        assert service.await_count == 2


class TestEveryWriteToolIsGated:
    """Nenhuma tool de escrita pode ficar fora do portão por esquecimento.

    A política foi ligada ao despacho cobrindo quatro domínios, e as escritas
    ITIL — problemas, mudanças, contratos — ficaram de fora: criar um problema
    escapava do modo somente-leitura e da proteção contra repetição. O mapa é
    manual, então precisa de um teste que o confronte com o catálogo real.
    """

    def test_all_manage_tools_have_a_write_domain(self, handler):
        from src.handlers import MCPHandler

        manage_tools = {
            name for name, spec in handler.tools.items()
            if spec["annotations"].get("destructiveHint") is True
        }
        ungated = manage_tools - set(MCPHandler._WRITE_DOMAINS)
        assert ungated == set(), f"tools de escrita sem portao: {sorted(ungated)}"

    async def test_itil_creation_is_blocked_in_read_only(self, handler):
        set_write_policy(WritePolicy(env=PROFILE_READ_ONLY.as_environment()))
        service = AsyncMock()

        with patch("src.tools.consolidated_itil.itil_service.create_record", service):
            response = await handler.handle_request(
                _request("glpi_manage_itil_records", {
                    "record_type": "problems", "action": "create",
                    "name": "Falha recorrente", "content": "x",
                })
            )

        assert "error" in response
        service.assert_not_awaited()

    async def test_repeating_an_itil_creation_does_not_create_twice(self, handler):
        service = AsyncMock(return_value={"id": 99})

        with patch("src.tools.consolidated_itil.itil_service.create_record", service):
            args = {
                "record_type": "problems", "action": "create",
                "name": "Falha recorrente", "content": "mesma causa",
            }
            await handler.handle_request(_request("glpi_manage_itil_records", args))
            await handler.handle_request(_request("glpi_manage_itil_records", args))

        assert service.await_count == 1
