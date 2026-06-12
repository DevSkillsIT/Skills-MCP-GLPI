"""
Consolidated MCP Tools - Tickets + AI (3 tools).

Reduces 18 ticket tools + 3 AI tools = 21 tools into 3 consolidated tools:
  1. search_tickets   - list/search tickets with filters
  2. manage_tickets   - CRUD + actions on individual tickets
  3. manage_ai_analysis - trigger/get/publish AI analysis
"""

from typing import Any, Dict, List, Optional

from src.formatters.markdown_helpers import remove_heavy_fields
from src.models.exceptions import GLPIError, NotFoundError, SimilarityError, ValidationError
from src.services.ai_integration import ai_integration
from src.services.ticket_service import ticket_service
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

# Hard cap for result limits across all search/list operations
MAX_LIMIT = 50

# Valid ticket statuses accepted by the GLPI API
VALID_STATUSES = ["new", "assigned", "planned", "pending", "solved", "closed"]

# Reverse map: GLPI status code -> string enum. Lets us accept a numeric status
# (4 or "4") from a less-strict external agent and normalize to "pending".
_INT_TO_STATUS = {1: "new", 2: "assigned", 3: "planned", 4: "pending", 5: "solved", 6: "closed"}


def _coerce_int(value):
    """Best-effort int coercion for loose inputs (e.g. priority='6' from an
    agent that ignores the JSON Schema type). Leaves non-numeric values intact."""
    if isinstance(value, bool):  # bool is a subclass of int — never coerce silently
        return value
    if isinstance(value, str):
        s = value.strip()
        if s.lstrip("-").isdigit():
            return int(s)
    return value


def _normalize_status(value):
    """Accept the string enum ('pending'), an int code (4) or a numeric string
    ('4') and normalize to the string enum the rest of the pipeline expects."""
    if value is None:
        return None
    coerced = _coerce_int(value)
    if isinstance(coerced, int):
        return _INT_TO_STATUS.get(coerced, value)
    return coerced

# Valid actions for manage_tickets
MANAGE_ACTIONS = [
    "get",
    "get_by_number",
    "create",
    "update",
    "delete",
    "assign",
    "close",
    "resolve",
    "add_followup",
    "get_followups",
    "get_history",
    "get_stats",
    "find_similar",
]

# Actions that require a valid ticket_id
ACTIONS_REQUIRING_TICKET_ID = [
    "get",
    "update",
    "delete",
    "assign",
    "close",
    "resolve",
    "add_followup",
    "get_followups",
    "get_history",
    "find_similar",
]

# Valid actions for manage_ai_analysis
AI_ACTIONS = ["trigger", "get_result", "publish"]


async def _resolve_entity(entity_name: str) -> int:
    """Resolve entity_name to entity_id, raising ValidationError if not found.

    @MX:NOTE: `is not None` em vez de truthy — entity_id=0 (root) e valido.
    @MX:REASON: Bug Ramada — entity_name='RAMADA' resolvia para 0 mas era rejeitado.
    """
    resolved_id = await entity_resolver.resolve_entity_name(entity_name)
    if resolved_id is not None:
        return resolved_id
    available = await entity_resolver.list_available_entities()
    raise ValidationError(
        f"Entity '{entity_name}' not found. Available: "
        f"{[e['name'] for e in available[:10]]}",
        "entity_name",
    )


def _remove_heavy_from_list(items: list) -> list:
    """Apply remove_heavy_fields to each item in a list."""
    return [remove_heavy_fields(item, mode="list") for item in items]


# ---------------------------------------------------------------------------
# Tool 1: search_tickets
# ---------------------------------------------------------------------------


async def search_tickets(
    status: Optional[str] = None,
    entity_id: Optional[int] = None,
    entity_name: Optional[str] = None,
    query: Optional[str] = None,
    priority: Optional[int] = None,
    limit: int = 10,
    offset: int = 0,
    date_after: Optional[str] = None,
    date_before: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Consolidated search/list tool for GLPI tickets.

    If *query* is provided, performs a text search.
    Otherwise, lists tickets filtered by the remaining parameters.

    Args:
        status: Filter by status (new, assigned, planned, pending, solved, closed).
        entity_id: Filter by entity ID.
        entity_name: Filter by entity name (resolved to entity_id automatically).
        query: Free-text search string (min 2 chars). Triggers search mode.
        priority: Filter by priority (1-5).
        limit: Max results (default 10, hard cap 50).
        offset: Pagination offset (default 0).
        date_after: Only tickets created after this date (YYYY-MM-DD).
        date_before: Only tickets created before this date (YYYY-MM-DD).

    Returns:
        Dict with ticket list and pagination metadata.
    """
    try:
        # Normalize loose inputs from less-strict external agents (Codex suggestion).
        status = _normalize_status(status)
        priority = _coerce_int(priority)
        entity_id = _coerce_int(entity_id)

        # Cap limit
        limit = min(int(limit), MAX_LIMIT)

        logger.info(
            f"search_tickets: query={query}, status={status}, "
            f"entity_name={entity_name}, limit={limit}, offset={offset}"
        )

        # Resolve entity name
        if entity_name:
            entity_id = await _resolve_entity(entity_name)
            logger.info(f"search_tickets: entity_name '{entity_name}' resolved to ID {entity_id}")

        # Validate status
        if status:
            status = input_sanitizer.sanitize_string(status)
            if status not in VALID_STATUSES:
                raise ValidationError(
                    f"Status must be one of: {VALID_STATUSES}", "status"
                )

        # Validate priority
        if priority is not None:
            if not isinstance(priority, int) or priority < 1 or priority > 6:
                raise ValidationError(
                    "Priority must be integer between 1 and 6", "priority"
                )

        # Validate dates
        if date_after or date_before:
            date_after, date_before = DateTimeHelper.parse_date_range(
                date_after, date_before
            )

        # Validate pagination
        offset, limit = PaginationHelper.validate_pagination_params(offset, limit)
        limit = min(limit, MAX_LIMIT)

        # --- Branch: text search vs filter list ---
        if query:
            query = input_sanitizer.sanitize_search_query(query)
            if not query or len(query) < 2:
                raise ValidationError(
                    "Search query must be at least 2 characters", "query"
                )

            result = await ticket_service.search_tickets(
                query=query,
                entity_id=entity_id,
                limit=limit,
                offset=offset,
            )
        else:
            result = await ticket_service.list_tickets(
                status=status,
                priority=priority,
                entity_id=entity_id,
                date_created_after=date_after,
                date_created_before=date_before,
                limit=limit,
                offset=offset,
                use_cache=True,
            )

        # Strip heavy fields from list items
        if isinstance(result, dict) and "tickets" in result:
            result["tickets"] = _remove_heavy_from_list(result["tickets"])
            result["tickets"] = response_truncator.truncate_json_response(
                result["tickets"]
            )
        elif isinstance(result, list):
            result = _remove_heavy_from_list(result)
            result = response_truncator.truncate_json_response(result)
        else:
            result = response_truncator.truncate_json_response(result)

        return result

    except (ValidationError, GLPIError) as e:
        logger.error(f"search_tickets error: {e.message}")
        raise
    except Exception as e:
        logger.error(f"search_tickets unexpected error: {e}")
        raise GLPIError(500, f"Failed to search/list tickets: {str(e)}")


# ---------------------------------------------------------------------------
# Tool 2: manage_tickets
# ---------------------------------------------------------------------------


async def manage_tickets(
    action: str,
    ticket_id: Optional[int] = None,
    # create / update fields
    title: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[int] = None,
    urgency: Optional[int] = None,
    type: Optional[str] = None,
    category_id: Optional[int] = None,
    entity_id: Optional[int] = None,
    entity_name: Optional[str] = None,
    requester_id: Optional[int] = None,
    assignee_id: Optional[int] = None,
    location_id: Optional[int] = None,
    status: Optional[str] = None,
    solution: Optional[str] = None,
    # assign
    user_id: Optional[int] = None,
    # close
    resolution: Optional[str] = None,
    solution_type: int = 5,
    # followup
    content: Optional[str] = None,
    is_private: bool = False,
    # delete safety
    confirmation_token: Optional[str] = None,
    reason: Optional[str] = None,
    # get_by_number
    ticket_number: Optional[str] = None,
    # stats
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    # find_similar
    threshold: float = 0.3,
    max_results: int = 10,
) -> Dict[str, Any]:
    """
    Consolidated management tool for individual GLPI tickets.

    Args:
        action: One of get, get_by_number, create, update, delete, assign,
                close, resolve, add_followup, get_followups, get_history,
                get_stats, find_similar.
        ticket_id: Ticket ID (required for most actions).
        title: Ticket title (create/update).
        description: Ticket description (create/update).
        priority: Priority 1-5 (create/update).
        urgency: Urgency 1-5 (create/update).
        type: Ticket type: incident, request, change (create).
        category_id: Category ID (create/update).
        entity_id: Entity ID (create/update/get_stats).
        entity_name: Entity name, resolved automatically (create/update/get_stats).
        requester_id: Requester user ID (create).
        assignee_id: Assignee user ID (create/update).
        location_id: Location ID (create).
        status: New status (update).
        solution: Solution text (update/resolve).
        user_id: User ID to assign (assign action).
        resolution: Resolution text (close action).
        solution_type: Solution type int (close action, default 5).
        content: Followup content text (add_followup action).
        is_private: Whether followup is private (add_followup action).
        confirmation_token: Safety token (delete action).
        reason: Deletion reason (delete action).
        ticket_number: Ticket number string (get_by_number action).
        date_from: Start date YYYY-MM-DD (get_stats).
        date_to: End date YYYY-MM-DD (get_stats).
        threshold: Similarity threshold 0.0-1.0 (find_similar).
        max_results: Max similar results (find_similar).

    Returns:
        Dict with action-specific response data.
    """
    try:
        # Normalize loose inputs from less-strict external agents (Codex suggestion):
        # accept numeric strings for ints and int/numeric status codes.
        ticket_id = _coerce_int(ticket_id)
        priority = _coerce_int(priority)
        urgency = _coerce_int(urgency)
        category_id = _coerce_int(category_id)
        entity_id = _coerce_int(entity_id)
        requester_id = _coerce_int(requester_id)
        assignee_id = _coerce_int(assignee_id)
        location_id = _coerce_int(location_id)
        user_id = _coerce_int(user_id)
        max_results = _coerce_int(max_results)
        status = _normalize_status(status)

        # Validate action
        if action not in MANAGE_ACTIONS:
            return create_mcp_error(
                f"Unknown action '{action}'",
                f"Expected one of: {MANAGE_ACTIONS}",
                "Example: manage_tickets(action='get', ticket_id=42)",
            )

        logger.info(f"manage_tickets: action={action}, ticket_id={ticket_id}")

        # Validate ticket_id for actions that require it
        if action in ACTIONS_REQUIRING_TICKET_ID:
            check = validate_positive_int(ticket_id, "ticket_id")
            if not check["valid"]:
                return create_mcp_error(
                    check["error"],
                    "ticket_id must be a positive integer",
                    "Example: manage_tickets(action='get', ticket_id=42)",
                )
            ticket_id = check["value"]

        # Resolve entity_name when applicable
        if entity_name and action in ("create", "update", "get_stats"):
            entity_id = await _resolve_entity(entity_name)
            logger.info(
                f"manage_tickets: entity_name '{entity_name}' resolved to ID {entity_id}"
            )

        # --- Dispatch per action ---

        if action == "get":
            # Detalhe MAXIMO: atores resolvidos, categoria/SLA/origem por nome,
            # contagem de anexos (1-2 chamadas extras, conforme escolhido).
            ticket = await ticket_service.get_ticket_detail(ticket_id)
            return response_truncator.truncate_json_response(ticket)

        if action == "get_by_number":
            if not ticket_number or not ticket_number.strip():
                raise ValidationError("ticket_number is required", "ticket_number")
            ticket = await ticket_service.get_ticket_by_number(ticket_number)
            # Reenriquecer pelo id encontrado para o mesmo detalhe completo.
            if ticket and ticket.get("id"):
                ticket = await ticket_service.get_ticket_detail(int(ticket["id"]))
            return response_truncator.truncate_json_response(ticket or {})

        if action == "create":
            if not title:
                raise ValidationError(
                    "title is required for create action", "title"
                )
            if not description:
                raise ValidationError(
                    "description is required for create action", "description"
                )
            title = input_sanitizer.sanitize_string(title)
            description = input_sanitizer.sanitize_string(description)

            type_map = {"incident": 1, "request": 2, "change": 3}
            type_int = type_map.get((type or "incident").lower(), 1)

            ticket = await ticket_service.create_ticket(
                title=title,
                description=description,
                priority=priority or 3,
                urgency=urgency,
                type=type_int,
                category_id=category_id,
                entity_id=entity_id,
                requester_id=requester_id,
                assignee_id=assignee_id,
                location_id=location_id,
            )
            return response_truncator.truncate_json_response(ticket)

        if action == "update":
            update_data: Dict[str, Any] = {}
            if title:
                update_data["title"] = input_sanitizer.sanitize_string(title)
            if description:
                update_data["description"] = input_sanitizer.sanitize_string(
                    description
                )
            if solution:
                update_data["solution"] = input_sanitizer.sanitize_string(solution)
            if status:
                update_data["status"] = status
            if priority:
                update_data["priority"] = priority
            if urgency:
                update_data["urgency"] = urgency
            if category_id:
                update_data["category_id"] = category_id
            if assignee_id:
                update_data["assignee_id"] = assignee_id

            ticket = await ticket_service.update_ticket(ticket_id, **update_data)
            return response_truncator.truncate_json_response(ticket)

        if action == "delete":
            require_safety_confirmation(
                "delete_ticket",
                confirmation_token=confirmation_token,
                reason=reason,
                target_id=ticket_id,
                target_type="Ticket",
            )
            success = await ticket_service.delete_ticket(ticket_id)
            return {
                "success": success,
                "ticket_id": ticket_id,
                "message": f"Ticket {ticket_id} deleted successfully",
            }

        if action == "assign":
            check_user = validate_positive_int(user_id, "user_id")
            if not check_user["valid"]:
                return create_mcp_error(
                    check_user["error"],
                    "user_id must be a positive integer",
                    "Example: manage_tickets(action='assign', ticket_id=42, user_id=5)",
                )
            ticket = await ticket_service.assign_ticket(ticket_id, check_user["value"])
            return response_truncator.truncate_json_response(ticket)

        if action == "close":
            # Accept both "solution" (aligned with resolve/public schema) and
            # "resolution" (legacy). At least one must be provided.
            close_text = resolution or solution
            if not close_text:
                raise ValidationError(
                    "solution (or resolution) is required for close action",
                    "solution",
                )
            sanitized_resolution = input_sanitizer.sanitize_string(close_text)
            ticket = await ticket_service.close_ticket(
                ticket_id, sanitized_resolution, solution_type=solution_type
            )
            return response_truncator.truncate_json_response(ticket)

        if action == "resolve":
            if not solution:
                raise ValidationError(
                    "solution is required for resolve action", "solution"
                )
            ticket = await ticket_service.resolve_ticket(ticket_id, solution)
            return response_truncator.truncate_json_response(ticket)

        if action == "add_followup":
            if not content or len(content) < 5:
                raise ValidationError(
                    "content must be at least 5 characters", "content"
                )
            content = input_sanitizer.sanitize_string(content)
            result = await ticket_service.add_ticket_followup(
                ticket_id=ticket_id, content=content, is_private=is_private
            )
            return response_truncator.truncate_json_response(result)

        if action == "get_followups":
            followups = await ticket_service.get_ticket_followups(ticket_id)
            return response_truncator.truncate_json_response(followups)

        if action == "get_history":
            # Use the dedicated /Ticket/{id}/Log endpoint. get_ticket() does NOT
            # include a "history" field, so the old ticket.get("history", [])
            # always returned empty. The formatter expects a list (like
            # get_followups), not a {history: [...]} wrapper.
            history = await ticket_service.get_ticket_history(ticket_id)
            return response_truncator.truncate_json_response(history)

        if action == "get_stats":
            if date_from or date_to:
                date_from, date_to = DateTimeHelper.parse_date_range(
                    date_from, date_to
                )
            stats = await ticket_service.get_ticket_stats(
                entity_id=entity_id, date_from=date_from, date_to=date_to
            )
            return stats

        if action == "find_similar":
            if not isinstance(threshold, (int, float)) or threshold < 0 or threshold > 1:
                raise ValidationError(
                    "Threshold must be number between 0.0 and 1.0", "threshold"
                )
            if not isinstance(max_results, int) or max_results <= 0 or max_results > 50:
                raise ValidationError(
                    "Max results must be integer between 1 and 50", "max_results"
                )
            similar = await ticket_service.find_similar_tickets(
                ticket_id=ticket_id, threshold=threshold, max_results=max_results
            )
            # Return a list (like get_followups/get_history): format_similar_tickets
            # expects a list, not a {similar_tickets: [...]} wrapper.
            return response_truncator.truncate_json_response(similar)

        # Should never reach here given the action validation above
        return create_mcp_error(
            f"Unhandled action '{action}'",
            f"Expected one of: {MANAGE_ACTIONS}",
            "Example: manage_tickets(action='get', ticket_id=42)",
        )

    except (NotFoundError, ValidationError, SimilarityError) as e:
        logger.error(f"manage_tickets ({action}) error: {e.message}")
        raise
    except GLPIError as e:
        logger.error(f"manage_tickets ({action}) GLPI error: {e.message}")
        raise
    except Exception as e:
        logger.error(f"manage_tickets ({action}) unexpected error: {e}")
        raise GLPIError(500, f"Failed to {action} ticket: {str(e)}")


# ---------------------------------------------------------------------------
# Tool 3: manage_ai_analysis
# ---------------------------------------------------------------------------


async def manage_ai_analysis(
    action: str,
    ticket_id: Optional[int] = None,
    job_id: Optional[str] = None,
    response: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Consolidated AI analysis tool for GLPI tickets.

    Args:
        action: One of trigger, get_result, publish.
        ticket_id: Ticket ID (required for trigger).
        job_id: Job ID returned by trigger (required for get_result, publish).
        response: AI response payload to publish (required for publish).

    Returns:
        Dict with action-specific response data.
    """
    try:
        if action not in AI_ACTIONS:
            return create_mcp_error(
                f"Unknown action '{action}'",
                f"Expected one of: {AI_ACTIONS}",
                "Example: manage_ai_analysis(action='trigger', ticket_id=42)",
            )

        logger.info(f"manage_ai_analysis: action={action}, ticket_id={ticket_id}, job_id={job_id}")

        if action == "trigger":
            check = validate_positive_int(ticket_id, "ticket_id")
            if not check["valid"]:
                return create_mcp_error(
                    check["error"],
                    "ticket_id must be a positive integer",
                    "Example: manage_ai_analysis(action='trigger', ticket_id=42)",
                )
            result_job_id = await ai_integration.trigger_analysis(check["value"])
            return {"job_id": result_job_id, "status": "processing"}

        if action == "get_result":
            if not job_id:
                raise ValidationError("job_id is required for get_result", "job_id")
            result = await ai_integration.get_analysis_result(job_id)
            if result is None:
                raise GLPIError(404, "Job not found", {"job_id": job_id})
            return response_truncator.truncate_json_response(result)

        if action == "publish":
            if not job_id:
                raise ValidationError("job_id is required for publish", "job_id")
            if not response:
                raise ValidationError(
                    "response payload is required for publish", "response"
                )
            ok = await ai_integration.publish_ai_response(job_id, response)
            if not ok:
                raise GLPIError(404, "Job not found", {"job_id": job_id})
            return {"job_id": job_id, "status": "completed"}

        # Should never reach here
        return create_mcp_error(
            f"Unhandled action '{action}'",
            f"Expected one of: {AI_ACTIONS}",
            "Example: manage_ai_analysis(action='trigger', ticket_id=42)",
        )

    except (ValidationError, GLPIError):
        raise
    except Exception as e:
        logger.error(f"manage_ai_analysis ({action}) unexpected error: {e}")
        raise GLPIError(500, f"Failed to {action} AI analysis: {str(e)}")
