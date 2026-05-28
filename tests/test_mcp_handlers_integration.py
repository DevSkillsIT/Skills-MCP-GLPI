"""
Integration Tests for MCP Handlers - JSON-RPC 2.0 Protocol.

Atualizado para a arquitetura consolidada (SPEC-GLPI-ENHANCE-001/F04):
- 15 tools consolidadas baseadas em `action`/`resource` (não mais ~48 tools
  per-action).
- O envelope de `tools/call` agora retorna o array `content` do protocolo MCP
  (texto Markdown), não mais `data`/`_execution_metadata`.

Os mocks miram os mesmos singletons usados pelos handlers consolidados
(ticket_service / webhook_tools / admin_tools / asset_tools).
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.handlers import mcp_handler
from src.models.exceptions import GLPIError


def _result(response):
    """Garante sucesso e devolve o bloco `result`."""
    assert "error" not in response, f"erro inesperado: {response.get('error')}"
    assert "result" in response
    return response["result"]


def _text(response):
    """Extrai o texto Markdown do envelope content[] de tools/call."""
    result = _result(response)
    assert "content" in result, f"sem content[] em {result}"
    assert result["content"][0]["type"] == "text"
    return result["content"][0]["text"]


class TestMCPHandlersIntegration:
    """Testes de integração para MCP Handlers JSON-RPC 2.0 (15 tools consolidadas)."""

    @pytest.fixture
    def sample_list_tools_request(self):
        """Request JSON-RPC 2.0 para tools/list"""
        return {"jsonrpc": "2.0", "method": "tools/list", "id": 1}

    @pytest.fixture
    def sample_call_tool_request(self):
        """Request JSON-RPC 2.0 para tools/call (tool de busca consolidada)"""
        return {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "glpi_search_helpdesk_tickets",
                "arguments": {"limit": 10},
            },
            "id": 2,
        }

    @pytest.fixture
    def invalid_request(self):
        """Request JSON-RPC 2.0 com método inexistente"""
        return {"jsonrpc": "2.0", "method": "invalid_method", "id": 3}

    @pytest.mark.asyncio
    async def test_tools_list_integration(self, sample_list_tools_request):
        """AC01: tools/list deve retornar as 15 tools consolidadas"""
        response = await mcp_handler.handle_request(sample_list_tools_request)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        result = _result(response)

        assert "tools" in result
        assert "total_count" in result
        assert "categories" in result

        # Arquitetura consolidada: 15 tools (SPEC-GLPI-ENHANCE-001/F04)
        assert result["total_count"] == 15
        assert len(result["tools"]) == 15

        # Categorias consolidadas
        categories = result["categories"]
        assert categories["tickets"] >= 3
        assert categories["assets"] >= 2
        assert categories["admin"] >= 2
        assert categories["webhooks"] >= 2

    @pytest.mark.asyncio
    async def test_tools_call_integration_success(self, sample_call_tool_request):
        """AC02: tools/call deve executar a tool e retornar content[] Markdown"""
        with patch(
            "src.services.ticket_service.ticket_service.list_tickets",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = [
                {"id": 1, "title": "Test Ticket", "status": 1}
            ]

            response = await mcp_handler.handle_request(sample_call_tool_request)

            assert response["jsonrpc"] == "2.0"
            assert response["id"] == 2
            text = _text(response)
            assert isinstance(text, str) and text  # Markdown não vazio
            mock_list.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_tools_call_integration_tool_not_found(self, invalid_request):
        """AC03: método inexistente deve retornar erro -32601"""
        response = await mcp_handler.handle_request(invalid_request)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 3
        assert "error" in response
        assert "result" not in response

        error = response["error"]
        assert error["code"] == -32601  # Method not found
        assert "not found" in error["message"].lower()
        assert "data" in error
        assert error["data"]["type"] == "MethodNotFoundError"

    @pytest.mark.asyncio
    async def test_tools_call_integration_validation_error(self):
        """AC04: tools/call deve validar que arguments é um objeto"""
        invalid_args_request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "glpi_search_helpdesk_tickets",
                "arguments": "invalid_string",  # Deve ser objeto
            },
            "id": 4,
        }

        response = await mcp_handler.handle_request(invalid_args_request)

        assert "error" in response
        error = response["error"]
        assert error["code"] == -32602  # Invalid params
        assert (
            "validation" in error["message"].lower()
            or "object" in error["message"].lower()
        )

    @pytest.mark.asyncio
    async def test_tools_call_integration_missing_tool_name(self):
        """AC05: tools/call deve requerer nome da tool"""
        missing_name_request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"arguments": {"limit": 10}},
            "id": 5,
        }

        response = await mcp_handler.handle_request(missing_name_request)

        assert "error" in response
        error = response["error"]
        assert error["code"] == -32602  # Invalid params
        assert "required" in error["message"].lower()

    @pytest.mark.asyncio
    async def test_jsonrpc_invalid_request_format(self):
        """AC06: Handler deve lidar com requests JSON-RPC inválidos"""
        invalid_jsonrpc_request = {
            "method": "tools/list",
            "id": 6,
            # Missing jsonrpc version
        }

        response = await mcp_handler.handle_request(invalid_jsonrpc_request)

        assert "error" in response
        error = response["error"]
        assert error["code"] == -32600  # Invalid Request

    @pytest.mark.asyncio
    async def test_tools_by_category_filtering(self):
        """AC07: Deve filtrar tools por categoria corretamente"""
        ticket_tools = mcp_handler.get_tools_by_category("tickets")
        asset_tools = mcp_handler.get_tools_by_category("assets")
        admin_tools = mcp_handler.get_tools_by_category("admin")
        webhook_tools = mcp_handler.get_tools_by_category("webhooks")

        # Quantidades na arquitetura consolidada
        assert len(ticket_tools) >= 3
        assert len(asset_tools) >= 2
        assert len(admin_tools) >= 2
        assert len(webhook_tools) >= 2

        # Cada tool deve ter a categoria correta
        for tool in ticket_tools:
            assert tool["category"] == "tickets"
        for tool in asset_tools:
            assert tool["category"] == "assets"
        for tool in admin_tools:
            assert tool["category"] == "admin"
        for tool in webhook_tools:
            assert tool["category"] == "webhooks"

    @pytest.mark.asyncio
    async def test_tool_info_retrieval(self):
        """AC08: Deve recuperar informações específicas de tool"""
        info = mcp_handler.get_tool_info("glpi_search_helpdesk_tickets")

        assert info is not None
        assert info["name"] == "glpi_search_helpdesk_tickets"
        assert info["category"] == "tickets"
        assert "description" in info
        assert "input_schema" in info
        assert "handler" in info

        # Tool inexistente
        assert mcp_handler.get_tool_info("nonexistent_tool") is None

    @pytest.mark.asyncio
    async def test_handler_stats_completeness(self):
        """AC09: Stats do handler devem ser completas"""
        stats = mcp_handler.get_handler_stats()

        assert "total_tools" in stats
        assert "categories" in stats
        assert "available_methods" in stats
        assert "protocol" in stats
        assert "last_updated" in stats

        assert stats["total_tools"] == 15
        assert len(stats["categories"]) >= 4
        assert "tools/list" in stats["available_methods"]
        assert "tools/call" in stats["available_methods"]
        assert stats["protocol"] == "JSON-RPC 2.0"

    @pytest.mark.asyncio
    async def test_error_handling_glpi_service_error(self):
        """AC10: Handler deve mapear erros do serviço GLPI para JSON-RPC"""
        glpi_error_request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "glpi_manage_ticket_operations",
                "arguments": {"action": "get", "ticket_id": 99999},
            },
            "id": 7,
        }

        with patch(
            "src.services.ticket_service.ticket_service.get_ticket",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.side_effect = GLPIError(404, "Ticket not found")

            response = await mcp_handler.handle_request(glpi_error_request)

            assert "error" in response
            error = response["error"]
            assert error["code"] == -32004  # Not found mapeado conforme SPEC
            assert "not found" in error["message"].lower()
            assert error["data"]["type"] == "GLPIError"

    @pytest.mark.asyncio
    async def test_error_handling_validation_error(self):
        """AC11: Handler deve lidar com erros de validação (-32602)"""
        validation_error_request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "glpi_manage_ticket_operations",
                "arguments": {
                    "action": "create",
                    "title": "",  # Título vazio deve falhar validação no handler
                    "description": "Test",
                },
            },
            "id": 8,
        }

        response = await mcp_handler.handle_request(validation_error_request)

        assert "error" in response
        error = response["error"]
        assert error["code"] == -32602  # Invalid params
        assert (
            "validation" in error["message"].lower()
            or "required" in error["message"].lower()
            or "title" in error["message"].lower()
        )

    @pytest.mark.asyncio
    async def test_concurrent_requests_handling(self):
        """AC12: Handler deve lidar com requisições concorrentes"""
        requests = [
            {"jsonrpc": "2.0", "method": "tools/list", "id": i} for i in range(10)
        ]

        tasks = [mcp_handler.handle_request(req) for req in requests]
        responses = await asyncio.gather(*tasks)

        for i, response in enumerate(responses):
            assert response["jsonrpc"] == "2.0"
            assert response["id"] == i
            result = _result(response)
            assert result["total_count"] == 15

    @pytest.mark.asyncio
    async def test_response_truncation_large_data(self):
        """AC13: Respostas grandes devem ser tratadas sem erro (RNF01)"""
        large_data_request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "glpi_search_helpdesk_tickets",
                "arguments": {"limit": 50},  # Hard cap do schema é 50
            },
            "id": 9,
        }

        with patch(
            "src.services.ticket_service.ticket_service.list_tickets",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = [
                {"id": i, "name": f"Ticket {i}"} for i in range(50)
            ]

            response = await mcp_handler.handle_request(large_data_request)

            # Resposta válida com content[] (truncamento ocorre internamente)
            assert _text(response)

    @pytest.mark.asyncio
    async def test_input_sanitization_security(self):
        """AC14: Inputs devem ser sanitizados/validados (RNF02)"""
        xss_request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "glpi_search_helpdesk_tickets",
                "arguments": {"query": "<script>alert('xss')</script>"},
            },
            "id": 10,
        }

        with patch(
            "src.services.ticket_service.ticket_service.search_tickets",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = []

            response = await mcp_handler.handle_request(xss_request)

            # Defense-in-depth: input malicioso é sanitizado e rejeitado por
            # ficar curto demais após a remoção das tags.
            assert "error" in response
            error = response["error"]
            assert error["code"] == -32602  # Invalid params
            assert "at least 2 characters" in error["message"]

    @pytest.mark.asyncio
    async def test_similarity_algorithm_integration(self):
        """AC15: find_similar via manage_ticket_operations (RNF03)"""
        similarity_request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "glpi_manage_ticket_operations",
                "arguments": {
                    "action": "find_similar",
                    "ticket_id": 1,
                    "threshold": 0.5,
                },
            },
            "id": 11,
        }

        with patch(
            "src.services.ticket_service.ticket_service.find_similar_tickets",
            new_callable=AsyncMock,
        ) as mock_similarity:
            mock_similarity.return_value = [
                {"id": 2, "similarity": 0.8, "title": "Similar ticket"}
            ]

            response = await mcp_handler.handle_request(similarity_request)

            assert _text(response)
            mock_similarity.assert_awaited_once()
            call_kwargs = mock_similarity.call_args.kwargs
            assert call_kwargs["ticket_id"] == 1
            assert call_kwargs["threshold"] == 0.5

    @pytest.mark.asyncio
    async def test_webhook_lifecycle_integration(self):
        """AC16: criação de webhook via manage_webhook_integrations"""
        create_webhook_request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "glpi_manage_webhook_integrations",
                "arguments": {
                    "action": "create",
                    "name": "Test Webhook",
                    "url": "https://example.com/webhook",
                    "event_type": "ticket.created",
                },
            },
            "id": 12,
        }

        with patch(
            "src.tools.webhooks.webhook_tools.create_webhook",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = {
                "id": "abc123",
                "name": "Test Webhook",
                "url": "https://example.com/webhook",
                "event_type": "ticket.created",
            }

            response = await mcp_handler.handle_request(create_webhook_request)

            assert _text(response)
            mock_create.assert_awaited_once()
            ck = mock_create.call_args.kwargs
            assert ck["name"] == "Test Webhook"
            assert ck["url"] == "https://example.com/webhook"
            assert ck["event_type"] == "ticket.created"

    @pytest.mark.asyncio
    async def test_admin_user_management_integration(self):
        """AC17: criação de usuário via manage_admin_resources"""
        create_user_request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "glpi_manage_admin_resources",
                "arguments": {
                    "resource": "users",
                    "action": "create",
                    "name": "Test User",
                    "email": "test@example.com",
                },
            },
            "id": 13,
        }

        with patch(
            "src.tools.admin.admin_tools.create_user",
            new_callable=AsyncMock,
        ) as mock_create_user:
            mock_create_user.return_value = {
                "id": 123,
                "name": "Test User",
                "email": "test@example.com",
            }

            response = await mcp_handler.handle_request(create_user_request)

            assert _text(response)
            mock_create_user.assert_awaited_once()
            assert mock_create_user.call_args.kwargs["email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_asset_reservation_integration(self):
        """AC18: criação de reserva via manage_asset_operations"""
        create_reservation_request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "glpi_manage_asset_operations",
                "arguments": {
                    "action": "create_reservation",
                    "asset_type": "Computer",
                    "asset_id": 456,
                    "user_id": 123,
                    "date_start": "2026-01-01 08:00:00",
                    "date_end": "2026-01-02 17:00:00",
                },
            },
            "id": 14,
        }

        with patch(
            "src.tools.assets.asset_tools.create_reservation",
            new_callable=AsyncMock,
        ) as mock_reservation:
            mock_reservation.return_value = {
                "id": 789,
                "asset_id": 456,
                "user_id": 123,
                "status": "confirmed",
            }

            response = await mcp_handler.handle_request(create_reservation_request)

            assert _text(response)
            mock_reservation.assert_awaited_once()
            assert mock_reservation.call_args.kwargs["asset_id"] == 456

    @pytest.mark.asyncio
    async def test_ticket_followup_integration(self):
        """AC19: acompanhamento de ticket via manage_ticket_operations"""
        followup_request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "glpi_manage_ticket_operations",
                "arguments": {
                    "action": "add_followup",
                    "ticket_id": 1,
                    "content": "Followup content",
                },
            },
            "id": 15,
        }

        with patch(
            "src.services.ticket_service.ticket_service.add_ticket_followup",
            new_callable=AsyncMock,
        ) as mock_followup:
            mock_followup.return_value = {
                "id": 999,
                "ticket_id": 1,
                "content": "Followup content",
                "date": "2026-01-01",
            }

            response = await mcp_handler.handle_request(followup_request)

            assert _text(response)
            mock_followup.assert_awaited_once()
            assert mock_followup.call_args.kwargs["ticket_id"] == 1

    @pytest.mark.asyncio
    async def test_complete_workflow_integration(self):
        """AC20: workflow create -> list -> close end-to-end (tools consolidadas)"""
        # 1. Criar ticket
        create_request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "glpi_manage_ticket_operations",
                "arguments": {
                    "action": "create",
                    "title": "Integration Test Ticket",
                    "description": "Testing complete workflow",
                },
            },
            "id": 16,
        }

        with patch(
            "src.services.ticket_service.ticket_service.create_ticket",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = {"id": 1001, "title": "Integration Test Ticket"}

            create_response = await mcp_handler.handle_request(create_request)
            assert _text(create_response)

            # 2. Listar tickets
            list_request = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "glpi_search_helpdesk_tickets",
                    "arguments": {"limit": 10},
                },
                "id": 17,
            }

            with patch(
                "src.services.ticket_service.ticket_service.list_tickets",
                new_callable=AsyncMock,
            ) as mock_list:
                mock_list.return_value = [
                    {"id": 1001, "title": "Integration Test Ticket", "status": 1}
                ]

                list_response = await mcp_handler.handle_request(list_request)
                assert _text(list_response)

                # 3. Fechar ticket
                close_request = {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "glpi_manage_ticket_operations",
                        "arguments": {
                            "action": "close",
                            "ticket_id": 1001,
                            "solution": "Test completed",
                        },
                    },
                    "id": 18,
                }

                with patch(
                    "src.services.ticket_service.ticket_service.close_ticket",
                    new_callable=AsyncMock,
                ) as mock_close:
                    mock_close.return_value = {"id": 1001, "status": 6}

                    close_response = await mcp_handler.handle_request(close_request)
                    assert _text(close_response)
                    mock_close.assert_awaited_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
