"""
Testes para validação de modelos Pydantic.
"""

import pytest
from datetime import datetime
from src.models import (
    Ticket, Asset, User, Group, Entity, Location,
    ValidationError, NotFoundError, AuthenticationError,
    GLPIError, MCPRequest, MCPResponse
)


class TestTicketModel:
    """Testes para o modelo Ticket."""

    def test_create_valid_ticket(self):
        """Testa criação de ticket válido."""
        ticket = Ticket(
            id=1,
            name="Test Ticket",
            title="Test Title",
            status="new",
            priority=3
        )
        assert ticket.id == 1
        assert ticket.title == "Test Title"
        assert ticket.status == "new"
        assert ticket.priority == 3

    def test_ticket_priority_validation_low(self):
        """Testa validação de prioridade baixa."""
        ticket = Ticket(
            id=1,
            name="Test",
            title="Test",
            priority=1
        )
        assert ticket.priority == 1

    def test_ticket_priority_validation_high(self):
        """Testa validação de prioridade alta."""
        ticket = Ticket(
            id=1,
            name="Test",
            title="Test",
            priority=5
        )
        assert ticket.priority == 5

    def test_ticket_priority_validation_invalid_low(self):
        """Testa validação de prioridade inválida (muito baixa)."""
        with pytest.raises(ValueError):
            Ticket(
                id=1,
                name="Test",
                title="Test",
                priority=0
            )

    def test_ticket_priority_validation_invalid_high(self):
        """Testa validação de prioridade inválida (muito alta)."""
        with pytest.raises(ValueError):
            Ticket(
                id=1,
                name="Test",
                title="Test",
                priority=6
            )

    def test_ticket_with_requesters(self):
        """Testa ticket com múltiplos solicitantes."""
        ticket = Ticket(
            id=1,
            name="Test",
            title="Test",
            requesters=[1, 2, 3]
        )
        assert len(ticket.requesters) == 3


class TestAssetModel:
    """Testes para o modelo Asset."""

    def test_create_valid_asset(self):
        """Testa criação de asset válido."""
        asset = Asset(
            id=1,
            name="Computer 01",
            asset_type="Computer",
            serial_number="SN-123456"
        )
        assert asset.id == 1
        assert asset.name == "Computer 01"
        assert asset.asset_type == "Computer"

    def test_asset_with_location(self):
        """Testa asset com localização."""
        asset = Asset(
            id=1,
            name="Monitor",
            asset_type="Monitor",
            location_id=5
        )
        assert asset.location_id == 5


class TestUserModel:
    """Testes para o modelo User."""

    def test_create_valid_user(self):
        """Testa criação de usuário válido."""
        user = User(
            id=1,
            name="John Doe",
            firstname="John",
            lastname="Doe",
            email="john@example.com"
        )
        assert user.id == 1
        assert user.firstname == "John"
        assert user.lastname == "Doe"
        assert user.is_active is True

    def test_user_inactive(self):
        """Testa usuário inativo."""
        user = User(
            id=1,
            name="Jane Doe",
            firstname="Jane",
            lastname="Doe",
            is_active=False
        )
        assert user.is_active is False


class TestGroupModel:
    """Testes para o modelo Group."""

    def test_create_valid_group(self):
        """Testa criação de grupo válido."""
        group = Group(
            id=1,
            name="IT Support",
            comment="Suporte técnico"
        )
        assert group.id == 1
        assert group.name == "IT Support"


class TestEntityModel:
    """Testes para o modelo Entity."""

    def test_create_valid_entity(self):
        """Testa criação de entidade válida."""
        entity = Entity(
            id=1,
            name="ACME Corp",
            completename="ACME Corporation"
        )
        assert entity.id == 1
        assert entity.name == "ACME Corp"


class TestLocationModel:
    """Testes para o modelo Location."""

    def test_create_valid_location(self):
        """Testa criação de localização válida."""
        location = Location(
            id=1,
            name="São Paulo",
            address="Av. Paulista, 1000"
        )
        assert location.id == 1
        assert location.name == "São Paulo"


class TestErrorModels:
    """Testes para modelos de erro."""

    def test_validation_error(self):
        """Testa ValidationError."""
        error = ValidationError("Invalid email", "email")
        assert error.code == 400
        assert error.message == "Invalid email"
        assert error.details["field"] == "email"

    def test_not_found_error(self):
        """Testa NotFoundError."""
        error = NotFoundError("Ticket", 123)
        assert error.code == 404
        assert "not found" in error.message

    def test_authentication_error(self):
        """Testa AuthenticationError."""
        error = AuthenticationError()
        assert error.code == 401

    def test_glpi_error(self):
        """Testa GLPIError."""
        error = GLPIError(500, "Server error", {"detail": "test"})
        assert error.code == 500
        assert error.message == "Server error"


class TestMCPModels:
    """Testes para modelos MCP."""

    def test_mcp_request(self):
        """Testa MCPRequest."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/list",
            params={},
            id=1
        )
        assert request.jsonrpc == "2.0"
        assert request.method == "tools/list"
        assert request.id == 1

    def test_mcp_response(self):
        """Testa MCPResponse."""
        response = MCPResponse(
            jsonrpc="2.0",
            result={"tools": []},
            id=1
        )
        assert response.jsonrpc == "2.0"
        assert response.result is not None
        assert response.error is None

    def test_mcp_response_with_error(self):
        """Testa MCPResponse com erro."""
        response = MCPResponse(
            jsonrpc="2.0",
            error={"code": 400, "message": "Bad request"},
            id=1
        )
        assert response.error is not None
        assert response.result is None
