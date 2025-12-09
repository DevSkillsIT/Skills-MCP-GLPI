"""
Serviço principal de integração com GLPI.
"""

from typing import Optional, List, Dict, Any
from src.http_client import http_client
from src.models import (
    Ticket, Asset, User, Group, Entity, Location,
    NotFoundError, ValidationError, GLPIError
)
from src.logger import logger


class GLPIService:
    """Serviço de integração com GLPI."""

    def __init__(self):
        """Inicializa o serviço."""
        self.client = http_client

    # ============= TICKETS =============

    async def list_tickets(
        self,
        status: Optional[str] = None,
        limit: int = 250,
        offset: int = 0
    ) -> List[Ticket]:
        """Lista tickets com filtros opcionais."""
        params = {
            "range": f"{offset}-{offset + limit - 1}",
        }
        if status:
            params["searchText"] = f"status:{status}"

        logger.info(f"Listing tickets with params: {params}")
        result = await self.client.get("/apirest.php/Ticket", params=params)

        tickets = []
        if isinstance(result, dict) and "data" in result:
            for item in result.get("data", []):
                tickets.append(Ticket(**item))
        return tickets

    async def get_ticket(self, ticket_id: int) -> Ticket:
        """Obtém detalhes de um ticket."""
        logger.info(f"Getting ticket {ticket_id}")
        result = await self.client.get(f"/apirest.php/Ticket/{ticket_id}")

        if not result or "id" not in result:
            raise NotFoundError("Ticket", ticket_id)

        return Ticket(**result)

    async def create_ticket(
        self,
        title: str,
        description: str,
        priority: int = 3,
        requesters: Optional[List[int]] = None
    ) -> Ticket:
        """Cria um novo ticket."""
        if not title or len(title) < 3:
            raise ValidationError("Title must be at least 3 characters", "title")

        if priority < 1 or priority > 5:
            raise ValidationError("Priority must be between 1 and 5", "priority")

        payload = {
            "name": title,
            "content": description,
            "urgency": priority,
        }

        if requesters:
            payload["_users_id_requester"] = requesters

        logger.info(f"Creating ticket: {title}")
        result = await self.client.post("/apirest.php/Ticket", json=payload)

        if "id" not in result:
            raise GLPIError(500, "Failed to create ticket")

        return await self.get_ticket(result["id"])

    async def update_ticket(
        self,
        ticket_id: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[int] = None
    ) -> Ticket:
        """Atualiza um ticket existente."""
        payload = {}

        if title:
            payload["name"] = title
        if description:
            payload["content"] = description
        if status:
            payload["status"] = status
        if priority:
            if priority < 1 or priority > 5:
                raise ValidationError("Priority must be between 1 and 5", "priority")
            payload["urgency"] = priority

        logger.info(f"Updating ticket {ticket_id}")
        await self.client.put(f"/apirest.php/Ticket/{ticket_id}", json=payload)

        return await self.get_ticket(ticket_id)

    async def delete_ticket(self, ticket_id: int) -> bool:
        """Deleta um ticket."""
        logger.info(f"Deleting ticket {ticket_id}")
        await self.client.delete(f"/apirest.php/Ticket/{ticket_id}")
        return True

    async def assign_ticket(self, ticket_id: int, user_id: int) -> Ticket:
        """Atribui um ticket a um usuário."""
        logger.info(f"Assigning ticket {ticket_id} to user {user_id}")
        payload = {"_users_id_assign": [{"users_id": user_id}]}
        await self.client.put(f"/apirest.php/Ticket/{ticket_id}", json=payload)
        return await self.get_ticket(ticket_id)

    async def close_ticket(self, ticket_id: int, resolution: str = "") -> Ticket:
        """Fecha um ticket."""
        logger.info(f"Closing ticket {ticket_id}")
        payload = {
            "status": "closed",
            "solution": resolution
        }
        await self.client.put(f"/apirest.php/Ticket/{ticket_id}", json=payload)
        return await self.get_ticket(ticket_id)

    # ============= ASSETS =============

    async def list_assets(
        self,
        asset_type: Optional[str] = None,
        limit: int = 250,
        offset: int = 0
    ) -> List[Asset]:
        """Lista assets com filtros opcionais."""
        endpoint = f"/apirest.php/{asset_type or 'Computer'}"
        params = {"range": f"{offset}-{offset + limit - 1}"}

        logger.info(f"Listing assets: {asset_type}")
        result = await self.client.get(endpoint, params=params)

        assets = []
        if isinstance(result, dict) and "data" in result:
            for item in result.get("data", []):
                item_copy = dict(item)
                item_copy.pop("asset_type", None)
                assets.append(Asset(asset_type=asset_type or "Computer", **item_copy))
        return assets

    async def get_asset(self, asset_type: str, asset_id: int) -> Asset:
        """Obtém detalhes de um asset."""
        logger.info(f"Getting {asset_type} {asset_id}")
        result = await self.client.get(f"/apirest.php/{asset_type}/{asset_id}")

        if not result or "id" not in result:
            raise NotFoundError(asset_type, asset_id)

        result_copy = dict(result)
        result_copy.pop("asset_type", None)
        return Asset(asset_type=asset_type, **result_copy)

    async def create_asset(
        self,
        asset_type: str,
        name: str,
        serial_number: Optional[str] = None,
        model: Optional[str] = None,
        manufacturer: Optional[str] = None
    ) -> Asset:
        """Cria um novo asset."""
        if not name or len(name) < 2:
            raise ValidationError("Name must be at least 2 characters", "name")

        payload = {"name": name}
        if serial_number:
            payload["serial"] = serial_number
        if model:
            payload["model"] = model
        if manufacturer:
            payload["manufacturer"] = manufacturer

        logger.info(f"Creating {asset_type}: {name}")
        result = await self.client.post(f"/apirest.php/{asset_type}", json=payload)

        if "id" not in result:
            raise GLPIError(500, f"Failed to create {asset_type}")

        return await self.get_asset(asset_type, result["id"])

    async def update_asset(
        self,
        asset_type: str,
        asset_id: int,
        **kwargs
    ) -> Asset:
        """Atualiza um asset existente."""
        logger.info(f"Updating {asset_type} {asset_id}")
        await self.client.put(f"/apirest.php/{asset_type}/{asset_id}", json=kwargs)
        return await self.get_asset(asset_type, asset_id)

    async def delete_asset(self, asset_type: str, asset_id: int) -> bool:
        """Deleta um asset."""
        logger.info(f"Deleting {asset_type} {asset_id}")
        await self.client.delete(f"/apirest.php/{asset_type}/{asset_id}")
        return True

    # ============= USERS =============

    async def list_users(self, limit: int = 250, offset: int = 0) -> List[User]:
        """Lista usuários."""
        params = {"range": f"{offset}-{offset + limit - 1}"}
        logger.info("Listing users")
        result = await self.client.get("/apirest.php/User", params=params)

        users = []
        if isinstance(result, dict) and "data" in result:
            for item in result.get("data", []):
                users.append(User(**item))
        return users

    async def get_user(self, user_id: int) -> User:
        """Obtém detalhes de um usuário."""
        logger.info(f"Getting user {user_id}")
        result = await self.client.get(f"/apirest.php/User/{user_id}")

        if not result or "id" not in result:
            raise NotFoundError("User", user_id)

        return User(**result)

    async def create_user(
        self,
        firstname: str,
        lastname: str,
        email: Optional[str] = None,
        phone: Optional[str] = None
    ) -> User:
        """Cria um novo usuário."""
        if not firstname or len(firstname) < 2:
            raise ValidationError("First name must be at least 2 characters", "firstname")

        if not lastname or len(lastname) < 2:
            raise ValidationError("Last name must be at least 2 characters", "lastname")

        payload = {
            "firstname": firstname,
            "lastname": lastname,
        }
        if email:
            payload["email"] = email
        if phone:
            payload["phone"] = phone

        logger.info(f"Creating user: {firstname} {lastname}")
        result = await self.client.post("/apirest.php/User", json=payload)

        if "id" not in result:
            raise GLPIError(500, "Failed to create user")

        return await self.get_user(result["id"])

    async def update_user(self, user_id: int, **kwargs) -> User:
        """Atualiza um usuário."""
        logger.info(f"Updating user {user_id}")
        await self.client.put(f"/apirest.php/User/{user_id}", json=kwargs)
        return await self.get_user(user_id)

    async def delete_user(self, user_id: int) -> bool:
        """Deleta um usuário."""
        logger.info(f"Deleting user {user_id}")
        await self.client.delete(f"/apirest.php/User/{user_id}")
        return True

    # ============= GROUPS =============

    async def list_groups(self, limit: int = 250, offset: int = 0) -> List[Group]:
        """Lista grupos."""
        params = {"range": f"{offset}-{offset + limit - 1}"}
        logger.info("Listing groups")
        result = await self.client.get("/apirest.php/Group", params=params)

        groups = []
        if isinstance(result, dict) and "data" in result:
            for item in result.get("data", []):
                groups.append(Group(**item))
        return groups

    async def get_group(self, group_id: int) -> Group:
        """Obtém detalhes de um grupo."""
        logger.info(f"Getting group {group_id}")
        result = await self.client.get(f"/apirest.php/Group/{group_id}")

        if not result or "id" not in result:
            raise NotFoundError("Group", group_id)

        return Group(**result)

    async def create_group(self, name: str, comment: Optional[str] = None) -> Group:
        """Cria um novo grupo."""
        if not name or len(name) < 2:
            raise ValidationError("Name must be at least 2 characters", "name")

        payload = {"name": name}
        if comment:
            payload["comment"] = comment

        logger.info(f"Creating group: {name}")
        result = await self.client.post("/apirest.php/Group", json=payload)

        if "id" not in result:
            raise GLPIError(500, "Failed to create group")

        return await self.get_group(result["id"])

    async def update_group(self, group_id: int, **kwargs) -> Group:
        """Atualiza um grupo."""
        logger.info(f"Updating group {group_id}")
        await self.client.put(f"/apirest.php/Group/{group_id}", json=kwargs)
        return await self.get_group(group_id)

    async def delete_group(self, group_id: int) -> bool:
        """Deleta um grupo."""
        logger.info(f"Deleting group {group_id}")
        await self.client.delete(f"/apirest.php/Group/{group_id}")
        return True

    # ============= ENTITIES =============

    async def list_entities(self, limit: int = 250, offset: int = 0) -> List[Entity]:
        """Lista entidades."""
        params = {"range": f"{offset}-{offset + limit - 1}"}
        logger.info("Listing entities")
        result = await self.client.get("/apirest.php/Entity", params=params)

        entities = []
        if isinstance(result, dict) and "data" in result:
            for item in result.get("data", []):
                entities.append(Entity(**item))
        return entities

    async def get_entity(self, entity_id: int) -> Entity:
        """Obtém detalhes de uma entidade."""
        logger.info(f"Getting entity {entity_id}")
        result = await self.client.get(f"/apirest.php/Entity/{entity_id}")

        if not result or "id" not in result:
            raise NotFoundError("Entity", entity_id)

        return Entity(**result)

    async def create_entity(
        self,
        name: str,
        entity_type: Optional[str] = None,
        phone: Optional[str] = None
    ) -> Entity:
        """Cria uma nova entidade."""
        if not name or len(name) < 2:
            raise ValidationError("Name must be at least 2 characters", "name")

        payload = {"name": name}
        if entity_type:
            payload["type"] = entity_type
        if phone:
            payload["phone"] = phone

        logger.info(f"Creating entity: {name}")
        result = await self.client.post("/apirest.php/Entity", json=payload)

        if "id" not in result:
            raise GLPIError(500, "Failed to create entity")

        return await self.get_entity(result["id"])

    async def update_entity(self, entity_id: int, **kwargs) -> Entity:
        """Atualiza uma entidade."""
        logger.info(f"Updating entity {entity_id}")
        await self.client.put(f"/apirest.php/Entity/{entity_id}", json=kwargs)
        return await self.get_entity(entity_id)

    async def delete_entity(self, entity_id: int) -> bool:
        """Deleta uma entidade."""
        logger.info(f"Deleting entity {entity_id}")
        await self.client.delete(f"/apirest.php/Entity/{entity_id}")
        return True

    # ============= LOCATIONS =============

    async def list_locations(self, limit: int = 250, offset: int = 0) -> List[Location]:
        """Lista localizações."""
        params = {"range": f"{offset}-{offset + limit - 1}"}
        logger.info("Listing locations")
        result = await self.client.get("/apirest.php/Location", params=params)

        locations = []
        if isinstance(result, dict) and "data" in result:
            for item in result.get("data", []):
                locations.append(Location(**item))
        return locations

    async def get_location(self, location_id: int) -> Location:
        """Obtém detalhes de uma localização."""
        logger.info(f"Getting location {location_id}")
        result = await self.client.get(f"/apirest.php/Location/{location_id}")

        if not result or "id" not in result:
            raise NotFoundError("Location", location_id)

        return Location(**result)

    async def create_location(
        self,
        name: str,
        address: Optional[str] = None,
        phone: Optional[str] = None
    ) -> Location:
        """Cria uma nova localização."""
        if not name or len(name) < 2:
            raise ValidationError("Name must be at least 2 characters", "name")

        payload = {"name": name}
        if address:
            payload["address"] = address
        if phone:
            payload["phone"] = phone

        logger.info(f"Creating location: {name}")
        result = await self.client.post("/apirest.php/Location", json=payload)

        if "id" not in result:
            raise GLPIError(500, "Failed to create location")

        return await self.get_location(result["id"])

    async def update_location(self, location_id: int, **kwargs) -> Location:
        """Atualiza uma localização."""
        logger.info(f"Updating location {location_id}")
        await self.client.put(f"/apirest.php/Location/{location_id}", json=kwargs)
        return await self.get_location(location_id)

    async def delete_location(self, location_id: int) -> bool:
        """Deleta uma localização."""
        logger.info(f"Deleting location {location_id}")
        await self.client.delete(f"/apirest.php/Location/{location_id}")
        return True


# Instância global
glpi_service = GLPIService()
