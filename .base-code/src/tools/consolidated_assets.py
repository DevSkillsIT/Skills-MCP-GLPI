"""
Consolidated MCP Tools - Assets (2 tools)

Consolidates 20 asset tools into 2 unified entry points:
  - search_assets: List/search/filter assets by scope
  - manage_assets: CRUD operations and reservations on individual assets

Delegates all business logic to the existing asset_tools service layer.
"""

from typing import Any, Dict, List, Optional

from src.formatters.markdown_helpers import remove_heavy_fields
from src.models.exceptions import GLPIError, NotFoundError, ValidationError
from src.services.asset_service import asset_service
from src.tools.assets import asset_tools
from src.utils.helpers import (
    DateTimeHelper,
    PaginationHelper,
    entity_resolver,
    input_sanitizer,
    logger,
    response_truncator,
)
from src.utils.safety_guard import require_safety_confirmation
from src.utils.validators import create_mcp_error, validate_positive_int

# Maximum allowed limit for any list/search query
MAX_LIMIT = 50

# Valid scope values for search_assets
VALID_SCOPES = (
    "all",
    "computers",
    "monitors",
    "software",
    "devices",
    "reservations",
    "reservable",
    "stats",
)

# Valid action values for manage_assets
VALID_ACTIONS = (
    "get",
    "get_details",
    "create",
    "update",
    "delete",
    "get_reservations",
    "create_reservation",
    "update_reservation",
)


def _cap_limit(limit: int) -> int:
    """Cap limit to MAX_LIMIT."""
    return min(max(1, limit), MAX_LIMIT)


def _clean_list_response(data: Any) -> Any:
    """Apply remove_heavy_fields to each item in a list response."""
    if isinstance(data, list):
        return [remove_heavy_fields(item) for item in data]
    if isinstance(data, dict):
        # Handle paginated responses with nested lists
        for key in ("assets", "reservable_items", "reservations", "data"):
            if key in data and isinstance(data[key], list):
                data[key] = [remove_heavy_fields(item) for item in data[key]]
                return data
        return remove_heavy_fields(data)
    return data


async def _resolve_entity(
    entity_name: Optional[str],
    entity_id: Optional[int],
) -> Optional[int]:
    """Resolve entity_name to entity_id. Raises ValidationError on miss."""
    if not entity_name:
        return entity_id
    resolved_id = await entity_resolver.resolve_entity_name(entity_name)
    if resolved_id:
        logger.info(f"Entity name '{entity_name}' resolved to ID {resolved_id}")
        return resolved_id
    available = await entity_resolver.list_available_entities()
    raise ValidationError(
        f"Entity '{entity_name}' not found. "
        f"Available: {[e['name'] for e in available[:10]]}",
        "entity_name",
    )


# ---------------------------------------------------------------------------
# Tool 1: search_assets
# ---------------------------------------------------------------------------

async def search_assets(
    asset_type: Optional[str] = None,
    scope: str = "all",
    query: Optional[str] = None,
    entity_id: Optional[int] = None,
    entity_name: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
    # Pass-through filters for specific scopes
    device_type: Optional[str] = None,
    location_id: Optional[int] = None,
    manufacturer_id: Optional[int] = None,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    is_active: Optional[bool] = None,
    itemtype: Optional[str] = None,
    status: Optional[str] = None,
    fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Consolidated search/list tool for GLPI assets.

    Scopes:
        all          - List all assets (optionally filtered by asset_type)
        computers    - List computers
        monitors     - List monitors
        software     - List software
        devices      - List network devices / peripherals
        reservations - List all reservations
        reservable   - List reservable items
        stats        - Get asset statistics

    When ``query`` is provided the scope is overridden to perform a
    free-text search across assets (equivalent to glpi_search_assets).

    Args:
        asset_type: GLPI asset type (Computer, Monitor, etc.)
        scope: One of 'all', 'computers', 'monitors', 'software',
               'devices', 'reservations', 'reservable', 'stats'.
        query: Free-text search string. When provided, performs search
               regardless of scope value.
        entity_id: Filter by entity (numeric ID).
        entity_name: Filter by entity name (resolved automatically).
        limit: Max results (default 10, capped at 50).
        offset: Pagination offset (default 0).
        device_type: Device type for scope='devices' (default NetworkEquipment).
        location_id: Filter by location.
        manufacturer_id: Filter by manufacturer.
        user_id: Filter by user ID.
        username: Filter by username.
        is_active: Filter reservable items by active status.
        itemtype: Filter reservable items by GLPI type.
        status: Filter by asset status.
        fields: Specific fields to return (search mode only).

    Returns:
        Dict with results and pagination metadata.
    """
    try:
        # -- Validate scope
        scope = (scope or "all").strip().lower()
        if scope not in VALID_SCOPES:
            return create_mcp_error(
                f"Invalid scope '{scope}'",
                f"Expected one of: {', '.join(VALID_SCOPES)}",
                "Example: search_assets(scope='computers', entity_name='Skills IT')",
            )

        # -- Cap and validate pagination
        limit = _cap_limit(limit)
        offset, limit = PaginationHelper.validate_pagination_params(offset, limit)

        # -- Resolve entity
        entity_id = await _resolve_entity(entity_name, entity_id)

        logger.info(
            f"consolidated search_assets: scope={scope}, query={query}, "
            f"asset_type={asset_type}, entity_id={entity_id}, "
            f"limit={limit}, offset={offset}"
        )

        # -- Free-text search takes priority
        if query:
            result = await asset_tools.search_assets(
                query=query,
                asset_type=asset_type,
                entity_id=entity_id,
                fields=fields,
                limit=limit,
                offset=offset,
            )
            return _clean_list_response(result)

        # -- Scope-based dispatch
        if scope == "stats":
            return await asset_tools.get_asset_stats(
                asset_type=asset_type,
                entity_id=entity_id,
            )

        if scope == "computers":
            result = await asset_tools.list_computers(
                entity_id=entity_id,
                location_id=location_id,
                manufacturer_id=manufacturer_id,
                user_id=user_id,
                username=username,
                limit=limit,
                offset=offset,
            )
            return _clean_list_response(result)

        if scope == "monitors":
            result = await asset_tools.list_monitors(
                entity_id=entity_id,
                location_id=location_id,
                manufacturer_id=manufacturer_id,
                limit=limit,
                offset=offset,
            )
            return _clean_list_response(result)

        if scope == "software":
            result = await asset_tools.list_software(
                entity_id=entity_id,
                limit=limit,
                offset=offset,
            )
            return _clean_list_response(result)

        if scope == "devices":
            result = await asset_tools.list_devices(
                device_type=device_type or "NetworkEquipment",
                limit=limit,
                offset=offset,
            )
            return _clean_list_response(result)

        if scope == "reservations":
            result = await asset_tools.list_reservations(
                limit=limit,
                offset=offset,
            )
            return _clean_list_response(result)

        if scope == "reservable":
            result = await asset_tools.list_reservable_items(
                entity_id=entity_id,
                is_active=is_active,
                itemtype=itemtype,
                limit=limit,
                offset=offset,
            )
            return _clean_list_response(result)

        # scope == "all" (default)
        result = await asset_tools.list_assets(
            asset_type=asset_type,
            entity_id=entity_id,
            location_id=location_id,
            manufacturer_id=manufacturer_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return _clean_list_response(result)

    except ValidationError as e:
        logger.error(f"search_assets validation error: {e.message}")
        raise
    except Exception as e:
        logger.error(f"search_assets unexpected error: {e}")
        raise GLPIError(500, f"Failed in search_assets: {str(e)}")


# ---------------------------------------------------------------------------
# Tool 2: manage_assets
# ---------------------------------------------------------------------------

async def manage_assets(
    action: str,
    asset_type: Optional[str] = None,
    asset_id: Optional[int] = None,
    # create / update fields
    name: Optional[str] = None,
    serial_number: Optional[str] = None,
    other_serial: Optional[str] = None,
    status: Optional[int] = None,
    entity_id: Optional[int] = None,
    location_id: Optional[int] = None,
    manufacturer_id: Optional[int] = None,
    model_id: Optional[int] = None,
    user_id: Optional[int] = None,
    group_id: Optional[int] = None,
    comment: Optional[str] = None,
    # delete safety guard
    confirmationToken: Optional[str] = None,
    reason: Optional[str] = None,
    # reservation fields
    reservation_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    # generic extra fields for update / update_reservation
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Consolidated CRUD + reservation management tool for GLPI assets.

    Actions:
        get               - Get a single asset by type and ID
        get_details       - Get full computer details (components, etc.)
        create            - Create a new asset
        update            - Update an existing asset
        delete            - Delete an asset (safety guard may apply)
        get_reservations  - List reservations for a specific asset
        create_reservation - Create a reservation for an asset
        update_reservation - Update an existing reservation

    Args:
        action: One of the supported actions listed above.
        asset_type: GLPI asset type (Computer, Monitor, Software, etc.).
        asset_id: Numeric ID of the asset (required for most actions).
        name: Asset name (required for 'create').
        serial_number: Serial number (create/update).
        other_serial: Alternate serial (create/update).
        status: Status ID (create/update).
        entity_id: Entity ID (create/update).
        location_id: Location ID (create/update).
        manufacturer_id: Manufacturer ID (create/update).
        model_id: Model ID (create/update).
        user_id: User ID (create/update/create_reservation).
        group_id: Group ID (create/update).
        comment: Comment (create/update/create_reservation).
        confirmationToken: Safety token (delete).
        reason: Deletion reason (delete).
        reservation_id: Reservation ID (update_reservation).
        date_from: Start date filter for get_reservations (YYYY-MM-DD).
        date_to: End date filter for get_reservations (YYYY-MM-DD).
        date_start: Reservation start datetime (YYYY-MM-DD HH:MM:SS).
        date_end: Reservation end datetime (YYYY-MM-DD HH:MM:SS).
        **kwargs: Additional fields passed through to update/update_reservation.

    Returns:
        Dict with operation result.
    """
    try:
        # -- Validate action
        action = (action or "").strip().lower()
        if action not in VALID_ACTIONS:
            return create_mcp_error(
                f"Invalid action '{action}'",
                f"Expected one of: {', '.join(VALID_ACTIONS)}",
                "Example: manage_assets(action='get', asset_type='Computer', asset_id=42)",
            )

        logger.info(
            f"consolidated manage_assets: action={action}, "
            f"asset_type={asset_type}, asset_id={asset_id}"
        )

        # -- Actions that require asset_id
        if action in (
            "get",
            "get_details",
            "update",
            "delete",
            "get_reservations",
            "create_reservation",
        ):
            check = validate_positive_int(asset_id, "asset_id")
            if not check["valid"]:
                return create_mcp_error(
                    check["error"],
                    "Expected a positive integer for asset_id",
                    "Example: manage_assets(action='get', asset_type='Computer', asset_id=42)",
                )
            asset_id = check["value"]

        # -- Actions that require asset_type
        if action in ("get", "get_details", "create", "update", "delete",
                       "get_reservations", "create_reservation"):
            if not asset_type or len(str(asset_type).strip()) < 2:
                return create_mcp_error(
                    "asset_type is required and must be at least 2 characters",
                    "Provide a valid GLPI asset type",
                    "Example: asset_type='Computer'",
                )

        # -- update_reservation requires reservation_id
        if action == "update_reservation":
            check = validate_positive_int(reservation_id, "reservation_id")
            if not check["valid"]:
                return create_mcp_error(
                    check["error"],
                    "Expected a positive integer for reservation_id",
                    "Example: manage_assets(action='update_reservation', reservation_id=7)",
                )
            reservation_id = check["value"]

        # -- Dispatch by action

        if action == "get":
            return await asset_tools.get_asset(asset_type, asset_id)

        if action == "get_details":
            return await asset_tools.get_computer_details(asset_id)

        if action == "create":
            if not name or len(str(name).strip()) < 2:
                return create_mcp_error(
                    "name is required for create action",
                    "Provide a name with at least 2 characters",
                    "Example: manage_assets(action='create', asset_type='Computer', name='PC-001')",
                )
            return await asset_tools.create_asset(
                asset_type=asset_type,
                name=name,
                serial_number=serial_number,
                other_serial=other_serial,
                status=status,
                entity_id=entity_id,
                location_id=location_id,
                manufacturer_id=manufacturer_id,
                model_id=model_id,
                user_id=user_id,
                group_id=group_id,
                comment=comment,
            )

        if action == "update":
            update_data = dict(kwargs)
            # Include explicitly provided fields in update_data
            if name is not None:
                update_data["name"] = name
            if serial_number is not None:
                update_data["serial_number"] = serial_number
            if other_serial is not None:
                update_data["other_serial"] = other_serial
            if status is not None:
                update_data["status"] = status
            if entity_id is not None:
                update_data["entity_id"] = entity_id
            if location_id is not None:
                update_data["location_id"] = location_id
            if manufacturer_id is not None:
                update_data["manufacturer_id"] = manufacturer_id
            if model_id is not None:
                update_data["model_id"] = model_id
            if user_id is not None:
                update_data["user_id"] = user_id
            if group_id is not None:
                update_data["group_id"] = group_id
            if comment is not None:
                update_data["comment"] = comment
            return await asset_tools.update_asset(
                asset_type=asset_type,
                asset_id=asset_id,
                **update_data,
            )

        if action == "delete":
            return await asset_tools.delete_asset(
                asset_type=asset_type,
                asset_id=asset_id,
                confirmationToken=confirmationToken,
                reason=reason,
            )

        if action == "get_reservations":
            return await asset_tools.get_asset_reservations(
                asset_type=asset_type,
                asset_id=asset_id,
                date_from=date_from,
                date_to=date_to,
            )

        if action == "create_reservation":
            # Validate required reservation fields
            if not user_id:
                return create_mcp_error(
                    "user_id is required for create_reservation",
                    "Provide a valid GLPI user ID",
                    "Example: manage_assets(action='create_reservation', "
                    "asset_type='Computer', asset_id=42, user_id=5, "
                    "date_start='2026-04-01 08:00:00', date_end='2026-04-01 17:00:00')",
                )
            if not date_start or not date_end:
                return create_mcp_error(
                    "date_start and date_end are required for create_reservation",
                    "Format: YYYY-MM-DD HH:MM:SS",
                    "Example: date_start='2026-04-01 08:00:00', date_end='2026-04-01 17:00:00'",
                )
            return await asset_tools.create_reservation(
                asset_type=asset_type,
                asset_id=asset_id,
                user_id=user_id,
                date_start=date_start,
                date_end=date_end,
                comment=comment,
            )

        if action == "update_reservation":
            return await asset_tools.update_reservation(
                reservation_id=reservation_id,
                **kwargs,
            )

        # Should never reach here due to validation above
        return create_mcp_error(
            f"Unhandled action '{action}'",
            f"Expected one of: {', '.join(VALID_ACTIONS)}",
            "Example: manage_assets(action='get', asset_type='Computer', asset_id=42)",
        )

    except (NotFoundError, ValidationError) as e:
        logger.error(f"manage_assets error: {e.message}")
        raise
    except Exception as e:
        logger.error(f"manage_assets unexpected error: {e}")
        raise GLPIError(500, f"Failed in manage_assets: {str(e)}")
