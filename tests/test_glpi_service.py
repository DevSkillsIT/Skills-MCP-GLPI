"""
Testes para o serviço GLPI.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.glpi_service import GLPIService
from src.models import (
    Ticket, Asset, User, Group, Entity, Location,
    NotFoundError, ValidationError, GLPIError
)


@pytest.fixture
def glpi_service():
    """Cria instância de GLPIService com cliente mockado."""
    service = GLPIService()
    service.client = AsyncMock()
    return service


class TestTickets:
    """Testes para operações de tickets."""

    @pytest.mark.asyncio
    async def test_list_tickets_empty(self, glpi_service):
        """Testa listagem vazia de tickets."""
        glpi_service.client.get.return_value = {"data": []}

        result = await glpi_service.list_tickets()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_tickets_with_data(self, glpi_service):
        """Testa listagem com tickets."""
        glpi_service.client.get.return_value = {
            "data": [
                {"id": 1, "name": "Ticket 1", "title": "Title 1", "status": "new", "priority": 3}
            ]
        }

        result = await glpi_service.list_tickets()
        assert len(result) == 1
        assert result[0].id == 1

    @pytest.mark.asyncio
    async def test_get_ticket_not_found(self, glpi_service):
        """Testa obtenção de ticket não encontrado."""
        glpi_service.client.get.return_value = {}

        with pytest.raises(NotFoundError):
            await glpi_service.get_ticket(999)

    @pytest.mark.asyncio
    async def test_get_ticket_success(self, glpi_service):
        """Testa obtenção de ticket com sucesso."""
        glpi_service.client.get.return_value = {
            "id": 1,
            "name": "Test Ticket",
            "title": "Test Title",
            "status": "new",
            "priority": 3
        }

        result = await glpi_service.get_ticket(1)
        assert result.id == 1
        assert result.title == "Test Title"

    @pytest.mark.asyncio
    async def test_create_ticket_invalid_title(self, glpi_service):
        """Testa criação de ticket com título inválido."""
        with pytest.raises(ValidationError):
            await glpi_service.create_ticket(
                title="a",
                description="Test"
            )

    @pytest.mark.asyncio
    async def test_create_ticket_invalid_priority(self, glpi_service):
        """Testa criação de ticket com prioridade inválida."""
        with pytest.raises(ValidationError):
            await glpi_service.create_ticket(
                title="Valid Title",
                description="Test",
                priority=6
            )

    @pytest.mark.asyncio
    async def test_create_ticket_success(self, glpi_service):
        """Testa criação de ticket com sucesso."""
        glpi_service.client.post.return_value = {"id": 1}
        glpi_service.client.get.return_value = {
            "id": 1,
            "name": "Test",
            "title": "Test Ticket",
            "status": "new",
            "priority": 3
        }

        result = await glpi_service.create_ticket(
            title="Test Ticket",
            description="Test Description"
        )
        assert result.id == 1

    @pytest.mark.asyncio
    async def test_update_ticket_success(self, glpi_service):
        """Testa atualização de ticket."""
        glpi_service.client.put.return_value = {}
        glpi_service.client.get.return_value = {
            "id": 1,
            "name": "Updated",
            "title": "Updated Title",
            "status": "assigned",
            "priority": 4
        }

        result = await glpi_service.update_ticket(
            ticket_id=1,
            title="Updated Title",
            status="assigned"
        )
        assert result.title == "Updated Title"
        assert result.status == "assigned"

    @pytest.mark.asyncio
    async def test_delete_ticket_success(self, glpi_service):
        """Testa deleção de ticket."""
        glpi_service.client.delete.return_value = {}

        result = await glpi_service.delete_ticket(1)
        assert result is True

    @pytest.mark.asyncio
    async def test_assign_ticket_success(self, glpi_service):
        """Testa atribuição de ticket."""
        glpi_service.client.put.return_value = {}
        glpi_service.client.get.return_value = {
            "id": 1,
            "name": "Ticket",
            "title": "Title",
            "status": "assigned",
            "priority": 3
        }

        result = await glpi_service.assign_ticket(1, 5)
        assert result.id == 1


class TestAssets:
    """Testes para operações de assets."""

    @pytest.mark.asyncio
    async def test_list_assets_empty(self, glpi_service):
        """Testa listagem vazia de assets."""
        glpi_service.client.get.return_value = {"data": []}

        result = await glpi_service.list_assets("Computer")
        assert result == []

    @pytest.mark.asyncio
    async def test_list_assets_with_data(self, glpi_service):
        """Testa listagem com assets."""
        glpi_service.client.get.return_value = {
            "data": [
                {"id": 1, "name": "Computer 1", "asset_type": "Computer"}
            ]
        }

        result = await glpi_service.list_assets("Computer")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_asset_success(self, glpi_service):
        """Testa obtenção de asset."""
        glpi_service.client.get.return_value = {
            "id": 1,
            "name": "Computer 1",
            "asset_type": "Computer"
        }

        result = await glpi_service.get_asset("Computer", 1)
        assert result.id == 1

    @pytest.mark.asyncio
    async def test_create_asset_invalid_name(self, glpi_service):
        """Testa criação de asset com nome inválido."""
        with pytest.raises(ValidationError):
            await glpi_service.create_asset("Computer", "a")

    @pytest.mark.asyncio
    async def test_create_asset_success(self, glpi_service):
        """Testa criação de asset com sucesso."""
        glpi_service.client.post.return_value = {"id": 1}
        glpi_service.client.get.return_value = {
            "id": 1,
            "name": "Computer 1",
            "asset_type": "Computer"
        }

        result = await glpi_service.create_asset("Computer", "Computer 1")
        assert result.id == 1


class TestUsers:
    """Testes para operações de usuários."""

    @pytest.mark.asyncio
    async def test_list_users_empty(self, glpi_service):
        """Testa listagem vazia de usuários."""
        glpi_service.client.get.return_value = {"data": []}

        result = await glpi_service.list_users()
        assert result == []

    @pytest.mark.asyncio
    async def test_create_user_invalid_firstname(self, glpi_service):
        """Testa criação de usuário com primeiro nome inválido."""
        with pytest.raises(ValidationError):
            await glpi_service.create_user(
                firstname="a",
                lastname="Doe"
            )

    @pytest.mark.asyncio
    async def test_create_user_invalid_lastname(self, glpi_service):
        """Testa criação de usuário com último nome inválido."""
        with pytest.raises(ValidationError):
            await glpi_service.create_user(
                firstname="John",
                lastname="a"
            )

    @pytest.mark.asyncio
    async def test_create_user_success(self, glpi_service):
        """Testa criação de usuário com sucesso."""
        glpi_service.client.post.return_value = {"id": 1}
        glpi_service.client.get.return_value = {
            "id": 1,
            "name": "John Doe",
            "firstname": "John",
            "lastname": "Doe",
            "email": "john@example.com"
        }

        result = await glpi_service.create_user("John", "Doe")
        assert result.id == 1


class TestGroups:
    """Testes para operações de grupos."""

    @pytest.mark.asyncio
    async def test_create_group_invalid_name(self, glpi_service):
        """Testa criação de grupo com nome inválido."""
        with pytest.raises(ValidationError):
            await glpi_service.create_group("a")

    @pytest.mark.asyncio
    async def test_create_group_success(self, glpi_service):
        """Testa criação de grupo com sucesso."""
        glpi_service.client.post.return_value = {"id": 1}
        glpi_service.client.get.return_value = {
            "id": 1,
            "name": "IT Team"
        }

        result = await glpi_service.create_group("IT Team")
        assert result.id == 1


class TestEntities:
    """Testes para operações de entidades."""

    @pytest.mark.asyncio
    async def test_create_entity_invalid_name(self, glpi_service):
        """Testa criação de entidade com nome inválido."""
        with pytest.raises(ValidationError):
            await glpi_service.create_entity("a")

    @pytest.mark.asyncio
    async def test_create_entity_success(self, glpi_service):
        """Testa criação de entidade com sucesso."""
        glpi_service.client.post.return_value = {"id": 1}
        glpi_service.client.get.return_value = {
            "id": 1,
            "name": "ACME Corp"
        }

        result = await glpi_service.create_entity("ACME Corp")
        assert result.id == 1


class TestLocations:
    """Testes para operações de localizações."""

    @pytest.mark.asyncio
    async def test_create_location_invalid_name(self, glpi_service):
        """Testa criação de localização com nome inválido."""
        with pytest.raises(ValidationError):
            await glpi_service.create_location("a")

    @pytest.mark.asyncio
    async def test_create_location_success(self, glpi_service):
        """Testa criação de localização com sucesso."""
        glpi_service.client.post.return_value = {"id": 1}
        glpi_service.client.get.return_value = {
            "id": 1,
            "name": "São Paulo"
        }

        result = await glpi_service.create_location("São Paulo")
        assert result.id == 1
