"""
Consolidated Admin Tools (2 tools replacing 13 originals).

Provides two unified entry points for GLPI admin operations:
  - search_admin: list/search across users, groups, entities, locations
  - manage_admin: get/create/update/delete for users, groups, entities, locations

Delegates all business logic to the existing AdminTools service layer.
"""

from typing import Any, Dict, Literal, Optional

from src.formatters.markdown_helpers import remove_heavy_fields
from src.tools.admin import admin_tools
from src.utils.validators import create_mcp_error, validate_positive_int

# Maximum number of items per search response
_MAX_LIMIT = 50


async def search_admin(
    resource: Literal["users", "groups", "entities", "locations"],
    query: Optional[str] = None,
    entity_id: Optional[int] = None,
    entity_name: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
) -> Dict[str, Any]:
    """Search or list admin resources.

    Consolidates: glpi_list_users, glpi_search_users, glpi_list_groups,
    glpi_list_entities, glpi_list_locations.

    Args:
        resource: Resource type to search (users, groups, entities, locations).
        query: Free-text search term. For users this triggers search_users
               (matched against name/firstname/realname/email). For other
               resources it is currently unused (list with filters).
        entity_id: Filter results by GLPI entity ID.
        entity_name: Filter by entity name (resolved automatically).
        limit: Max results to return (capped at 50).
        offset: Pagination offset.

    Returns:
        Dict with resource list and pagination metadata.
    """
    limit = min(max(limit, 1), _MAX_LIMIT)

    if resource == "users":
        if query:
            # Delegate to search_users which uses /search/User endpoint
            result = await admin_tools.search_users(
                name=query,
                firstname=query,
                realname=query,
                email=query,
                entity_id=entity_id,
                entity_name=entity_name,
                limit=limit,
                offset=offset,
            )
        else:
            result = await admin_tools.list_users(
                entity_id=entity_id,
                entity_name=entity_name,
                limit=limit,
                offset=offset,
            )

    elif resource == "groups":
        result = await admin_tools.list_groups(
            entity_id=entity_id,
            entity_name=entity_name,
            limit=limit,
            offset=offset,
        )

    elif resource == "entities":
        result = await admin_tools.list_entities(
            limit=limit,
            offset=offset,
        )

    elif resource == "locations":
        result = await admin_tools.list_locations(
            entity_id=entity_id,
            entity_name=entity_name,
            limit=limit,
            offset=offset,
        )

    else:
        return create_mcp_error(
            problem=f"Invalid resource '{resource}'",
            expected="Expected one of: users, groups, entities, locations",
            example="Example: search_admin(resource='users', query='john')",
        )

    # Strip heavy fields from list payloads to reduce token cost
    result = _strip_list_heavy_fields(result)
    return result


async def manage_admin(
    resource: Literal["users", "groups", "entities", "locations"],
    action: Literal["get", "create", "update", "delete"],
    resource_id: Optional[int] = None,
    # --- user-specific params ---
    name: Optional[str] = None,
    password: Optional[str] = None,
    password2: Optional[str] = None,
    firstname: Optional[str] = None,
    realname: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    phone2: Optional[str] = None,
    mobile: Optional[str] = None,
    entity_id: Optional[int] = None,
    entity_name: Optional[str] = None,
    profile_id: Optional[int] = None,
    group_id: Optional[int] = None,
    location_id: Optional[int] = None,
    usertitle_id: Optional[int] = None,
    usercategory_id: Optional[int] = None,
    registration_number: Optional[str] = None,
    comment: Optional[str] = None,
    authtype: int = 1,
    is_active: Optional[bool] = None,
    # --- delete-specific ---
    purge: bool = False,
    confirmationToken: Optional[str] = None,
    reason: Optional[str] = None,
    # --- group-specific ---
    is_user_group: bool = True,
    is_technical_group: bool = False,
    is_requester: bool = True,
    is_assign: bool = True,
    is_notify: bool = True,
    # --- location-specific ---
    parent_location_id: Optional[int] = None,
    building: Optional[str] = None,
    room: Optional[str] = None,
    town: Optional[str] = None,
    address: Optional[str] = None,
) -> Dict[str, Any]:
    """Manage (get/create/update/delete) admin resources.

    Consolidates: glpi_get_user, glpi_get_group, glpi_get_entity,
    glpi_get_location, glpi_create_user, glpi_update_user, glpi_delete_user,
    glpi_create_group.

    Args:
        resource: Resource type (users, groups, entities, locations).
        action: Operation to perform (get, create, update, delete).
        resource_id: ID of the resource (required for get/update/delete).
        **kwargs: Action-specific parameters forwarded to the underlying tool.

    Returns:
        Dict with operation result.
    """
    # Validate resource_id for actions that require it
    if action in ("get", "update", "delete"):
        if resource_id is None:
            return create_mcp_error(
                problem=f"resource_id is required for action '{action}'",
                expected="Provide a positive integer resource_id",
                example=f"Example: manage_admin(resource='{resource}', action='{action}', resource_id=42)",
            )
        validation = validate_positive_int(resource_id, "resource_id")
        if not validation["valid"]:
            return create_mcp_error(
                problem=validation["error"],
                expected="resource_id must be a positive integer",
                example=f"Example: manage_admin(resource='{resource}', action='{action}', resource_id=42)",
            )
        resource_id = validation["value"]

    # --- Dispatch by resource + action ---

    if resource == "users":
        return await _manage_user(
            action=action,
            resource_id=resource_id,
            name=name,
            password=password,
            password2=password2,
            firstname=firstname,
            realname=realname,
            email=email,
            phone=phone,
            phone2=phone2,
            mobile=mobile,
            entity_id=entity_id,
            entity_name=entity_name,
            profile_id=profile_id,
            group_id=group_id,
            location_id=location_id,
            usertitle_id=usertitle_id,
            usercategory_id=usercategory_id,
            registration_number=registration_number,
            comment=comment,
            authtype=authtype,
            is_active=is_active,
            purge=purge,
            confirmationToken=confirmationToken,
            reason=reason,
        )

    if resource == "groups":
        return await _manage_group(
            action=action,
            resource_id=resource_id,
            name=name,
            entity_id=entity_id,
            entity_name=entity_name,
            comment=comment,
            is_user_group=is_user_group,
            is_technical_group=is_technical_group,
            is_requester=is_requester,
            is_assign=is_assign,
            is_notify=is_notify,
        )

    if resource == "entities":
        return await _manage_entity(action=action, resource_id=resource_id)

    if resource == "locations":
        return await _manage_location(
            action=action,
            resource_id=resource_id,
            name=name,
            entity_id=entity_id,
            entity_name=entity_name,
            parent_location_id=parent_location_id,
            building=building,
            room=room,
            town=town,
            address=address,
            comment=comment,
        )

    return create_mcp_error(
        problem=f"Invalid resource '{resource}'",
        expected="Expected one of: users, groups, entities, locations",
        example="Example: manage_admin(resource='users', action='get', resource_id=1)",
    )


# ---------------------------------------------------------------------------
# Private dispatch helpers
# ---------------------------------------------------------------------------


async def _manage_user(
    action: str,
    resource_id: Optional[int],
    **kwargs: Any,
) -> Dict[str, Any]:
    if action == "get":
        return await admin_tools.get_user(resource_id)

    if action == "create":
        if not kwargs.get("name"):
            return create_mcp_error(
                problem="'name' is required to create a user",
                expected="Provide the login name for the new user",
                example="Example: manage_admin(resource='users', action='create', name='jdoe')",
            )
        return await admin_tools.create_user(
            name=kwargs["name"],
            password=kwargs.get("password"),
            password2=kwargs.get("password2"),
            firstname=kwargs.get("firstname"),
            realname=kwargs.get("realname"),
            email=kwargs.get("email"),
            phone=kwargs.get("phone"),
            phone2=kwargs.get("phone2"),
            mobile=kwargs.get("mobile"),
            entity_id=kwargs.get("entity_id"),
            entity_name=kwargs.get("entity_name"),
            profile_id=kwargs.get("profile_id"),
            group_id=kwargs.get("group_id"),
            location_id=kwargs.get("location_id"),
            usertitle_id=kwargs.get("usertitle_id"),
            usercategory_id=kwargs.get("usercategory_id"),
            registration_number=kwargs.get("registration_number"),
            comment=kwargs.get("comment"),
            authtype=kwargs.get("authtype", 1),
            is_active=kwargs.get("is_active") if kwargs.get("is_active") is not None else True,
        )

    if action == "update":
        update_fields = {}
        passthrough_keys = (
            "firstname", "realname", "email", "phone", "phone2", "mobile",
            "entity_id", "entity_name", "profile_id", "group_id",
            "location_id", "usertitle_id", "usercategory_id",
            "registration_number", "comment", "is_active",
        )
        for key in passthrough_keys:
            if kwargs.get(key) is not None:
                update_fields[key] = kwargs[key]
        return await admin_tools.update_user(resource_id, **update_fields)

    if action == "delete":
        return await admin_tools.delete_user(
            user_id=resource_id,
            purge=kwargs.get("purge", False),
            confirmationToken=kwargs.get("confirmationToken"),
            reason=kwargs.get("reason"),
        )

    return _unsupported_action("users", action)


async def _manage_group(
    action: str,
    resource_id: Optional[int],
    **kwargs: Any,
) -> Dict[str, Any]:
    if action == "get":
        return await admin_tools.get_group(resource_id)

    if action == "create":
        if not kwargs.get("name"):
            return create_mcp_error(
                problem="'name' is required to create a group",
                expected="Provide the name for the new group",
                example="Example: manage_admin(resource='groups', action='create', name='Support')",
            )
        return await admin_tools.create_group(
            name=kwargs["name"],
            entity_id=kwargs.get("entity_id"),
            entity_name=kwargs.get("entity_name"),
            comment=kwargs.get("comment"),
            is_user_group=kwargs.get("is_user_group", True),
            is_technical_group=kwargs.get("is_technical_group", False),
            is_requester=kwargs.get("is_requester", True),
            is_assign=kwargs.get("is_assign", True),
            is_notify=kwargs.get("is_notify", True),
        )

    if action in ("update", "delete"):
        return create_mcp_error(
            problem=f"Action '{action}' is not supported for groups",
            expected="Supported group actions: get, create",
            example="Example: manage_admin(resource='groups', action='get', resource_id=5)",
        )

    return _unsupported_action("groups", action)


async def _manage_entity(
    action: str,
    resource_id: Optional[int],
) -> Dict[str, Any]:
    if action == "get":
        return await admin_tools.get_entity(resource_id)

    if action in ("create", "update", "delete"):
        return create_mcp_error(
            problem=f"Action '{action}' is not supported for entities",
            expected="Supported entity actions: get",
            example="Example: manage_admin(resource='entities', action='get', resource_id=0)",
        )

    return _unsupported_action("entities", action)


async def _manage_location(
    action: str,
    resource_id: Optional[int],
    **kwargs: Any,
) -> Dict[str, Any]:
    if action == "get":
        return await admin_tools.get_location(resource_id)

    if action == "create":
        if not kwargs.get("name"):
            return create_mcp_error(
                problem="'name' is required to create a location",
                expected="Provide the name for the new location",
                example="Example: manage_admin(resource='locations', action='create', name='DC-01')",
            )
        return await admin_tools.create_location(
            name=kwargs["name"],
            entity_id=kwargs.get("entity_id"),
            entity_name=kwargs.get("entity_name"),
            parent_location_id=kwargs.get("parent_location_id"),
            building=kwargs.get("building"),
            room=kwargs.get("room"),
            town=kwargs.get("town"),
            address=kwargs.get("address"),
            comment=kwargs.get("comment"),
        )

    if action in ("update", "delete"):
        return create_mcp_error(
            problem=f"Action '{action}' is not supported for locations",
            expected="Supported location actions: get, create",
            example="Example: manage_admin(resource='locations', action='get', resource_id=3)",
        )

    return _unsupported_action("locations", action)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _unsupported_action(resource: str, action: str) -> Dict[str, Any]:
    return create_mcp_error(
        problem=f"Invalid action '{action}' for resource '{resource}'",
        expected="Expected one of: get, create, update, delete",
        example=f"Example: manage_admin(resource='{resource}', action='get', resource_id=1)",
    )


def _strip_list_heavy_fields(data: Any) -> Any:
    """Apply remove_heavy_fields to every item in a list response."""
    if isinstance(data, dict):
        for key in ("users", "groups", "entities", "locations", "data"):
            if key in data and isinstance(data[key], list):
                data[key] = [
                    remove_heavy_fields(item) if isinstance(item, dict) else item
                    for item in data[key]
                ]
        return data
    if isinstance(data, list):
        return [
            remove_heavy_fields(item) if isinstance(item, dict) else item
            for item in data
        ]
    return data
