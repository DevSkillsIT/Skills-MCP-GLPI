"""
Consolidated MCP Tools - Tickets + AI (3 tools).

Reduces 18 ticket tools + 3 AI tools = 21 tools into 3 consolidated tools:
  1. search_tickets   - list/search tickets with filters
  2. manage_tickets   - CRUD + actions on individual tickets
  3. manage_ai_analysis - trigger/get/publish AI analysis
"""

from typing import Any, Dict, Optional

from src.formatters.glpi_formatters import (
    format_itil_operation,
    format_ticket_tasks,
    format_ticket_timeline,
    format_ticket_validations,
)
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
    # ITIL coverage
    "get_timeline",
    "add_task",
    "get_tasks",
    "request_validation",
    "answer_validation",
    "get_validations",
    "assign_group",
    "link_tickets",
    "add_document",
]

# Actions that require a valid ticket_id.
# answer_validation is deliberately absent: it acts on a validation_id, and
# only falls back to the ticket when the caller did not supply one.
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
    "get_timeline",
    "add_task",
    "get_tasks",
    "request_validation",
    "get_validations",
    "assign_group",
    "link_tickets",
    "add_document",
]

# Actions that WRITE and therefore have to pass through the safety guard.
# @MX:NOTE: none of them is protected by default (the guard only ships with the
# delete_* operations), so this is a no-op today.
# @MX:REASON: an operator who adds "add_document" to
# SafetyGuard.PROTECTED_OPERATIONS expects it to start requiring a token. That
# only works if the write already asks the guard, so the call is wired now
# instead of the next time someone is surprised by a silent write.
ITIL_WRITE_ACTIONS = {
    "add_task": "Criar tarefa no chamado",
    "request_validation": "Solicitar aprovacao do chamado",
    "answer_validation": "Responder aprovacao do chamado",
    "assign_group": "Atribuir chamado a um grupo",
    "link_tickets": "Vincular chamados",
    "add_document": "Anexar documento ao chamado",
}

# Valid actions for manage_ai_analysis
AI_ACTIONS = ["trigger", "get_result", "publish"]


async def _resolve_entity(entity_name: str) -> int:
    """Resolve entity_name to entity_id, raising ValidationError if not found.

    @MX:NOTE: `is not None` em vez de truthy — entity_id=0 (root) e valido.
    @MX:REASON: defeito real: entity_name com o nome do cliente principal resolvia para 0 mas era rejeitado.
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
    assigned_tech: Optional[Any] = None,
    assigned_group: Optional[Any] = None,
    requester: Optional[Any] = None,
    category: Optional[Any] = None,
    urgency: Optional[int] = None,
    open_only: bool = False,
    sort_by: Optional[str] = None,
    order: Optional[str] = None,
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

        # Validate urgency — a distinct axis from priority in GLPI, scaled 1..5
        if urgency is not None:
            urgency = _coerce_int(urgency)
            if not isinstance(urgency, int) or urgency < 1 or urgency > 5:
                raise ValidationError(
                    "Urgency must be integer between 1 and 5", "urgency"
                )

        # Validate dates
        if date_after or date_before:
            date_after, date_before = DateTimeHelper.parse_date_range(
                date_after, date_before
            )

        # Validate pagination
        offset, limit = PaginationHelper.validate_pagination_params(offset, limit)
        limit = min(limit, MAX_LIMIT)

        # Filters apply to both branches. Built once so the text-search path
        # can never diverge from the listing path — it used to accept these
        # values and drop them, silently widening the result set.
        filters = {
            "status": status,
            "priority": priority,
            "urgency": urgency,
            "assigned_tech": assigned_tech,
            "assigned_group": assigned_group,
            "requester": requester,
            "category": category,
            "open_only": open_only,
            "entity_id": entity_id,
            "date_created_after": date_after,
            "date_created_before": date_before,
            "sort_by": sort_by,
            "order": order,
            "limit": limit,
            "offset": offset,
        }

        # --- Branch: text search vs filter list ---
        if query:
            query = input_sanitizer.sanitize_search_query(query)
            if not query or len(query) < 2:
                raise ValidationError(
                    "Search query must be at least 2 characters", "query"
                )

            result = await ticket_service.search_tickets(query=query, **filters)
        else:
            result = await ticket_service.list_tickets(use_cache=True, **filters)

        # Strip heavy fields from list items
        # @MX:NOTE: the text-search path returns {items, totalcount, search_notice}.
        # @MX:REASON: a widened search has to say so, and a bare list has nowhere
        # to carry that. Truncating the envelope instead of its rows would drop
        # the rows' heavy-field stripping and mangle the metadata.
        if isinstance(result, dict) and "items" in result:
            rows = _remove_heavy_from_list(result.get("items") or [])
            result["items"] = response_truncator.truncate_json_response(rows)
        elif isinstance(result, dict) and "tickets" in result:
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
    # get_timeline
    limit: int = 100,
    # add_task
    actiontime: Optional[int] = None,
    task_category_id: Optional[int] = None,
    # validations
    approver: Optional[Any] = None,
    comment: Optional[str] = None,
    validation_id: Optional[int] = None,
    validation_status: Optional[Any] = None,
    # assign_group
    group: Optional[Any] = None,
    group_type: str = "assigned",
    # link_tickets
    linked_ticket_id: Optional[int] = None,
    link_type: Optional[Any] = "link",
    # add_document
    file_path: Optional[str] = None,
    file_base64: Optional[str] = None,
    file_name: Optional[str] = None,
    document_title: Optional[str] = None,
) -> Any:
    """
    Consolidated management tool for individual GLPI tickets.

    Args:
        action: One of get, get_by_number, create, update, delete, assign,
                close, resolve, add_followup, get_followups, get_history,
                get_stats, find_similar, get_timeline, add_task, get_tasks,
                request_validation, answer_validation, get_validations,
                assign_group, link_tickets, add_document.
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
        limit: Max timeline entries, most recent kept (get_timeline, default 100).
        actiontime: Planned task duration in SECONDS (add_task).
        task_category_id: Task category ID (add_task, optional).
        approver: Approver user, by name or ID (request_validation).
        comment: Comment text (request_validation / answer_validation;
                 mandatory when refusing).
        validation_id: TicketValidation ID (answer_validation). When omitted,
                 the single pending approval of ticket_id is used.
        validation_status: Approval answer: aprovado/recusado (answer_validation).
        group: Group to assign, by name or ID (assign_group).
        group_type: Actor role of the group: requester, observer or assigned
                 (assign_group, default assigned).
        linked_ticket_id: The other ticket ID (link_tickets).
        link_type: link (1), duplicate (2), son (3) or parent (4) (link_tickets).
        file_path: Server-side path of the file to attach (add_document).
        file_base64: Base64 payload of the file to attach (add_document).
        file_name: File name, required with file_base64 (add_document).
        document_title: Document title in GLPI, defaults to the file name
                 (add_document).

    Returns:
        Dict with action-specific response data, or a Markdown string for the
        ITIL actions.

    @MX:NOTE: the ITIL actions return Markdown directly instead of a payload.
    @MX:REASON: the response interceptor passes a string straight through, but
    dispatches a dict for this tool through the ticket-detail formatter — which
    would render a timeline as an empty ticket. Formatting here keeps the new
    actions correct without a second registry to keep in sync.
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
        actiontime = _coerce_int(actiontime)
        task_category_id = _coerce_int(task_category_id)
        validation_id = _coerce_int(validation_id)
        linked_ticket_id = _coerce_int(linked_ticket_id)
        limit = _coerce_int(limit)

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

        # Destructive-write gate. See ITIL_WRITE_ACTIONS for why this runs even
        # though none of these operations is protected out of the box.
        if action in ITIL_WRITE_ACTIONS:
            require_safety_confirmation(
                action,
                confirmation_token=confirmation_token,
                reason=reason,
                target_id=ticket_id,
                target_type="Ticket",
            )

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
            description = input_sanitizer.sanitize_string(description, allow_html=True)

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
                    description, allow_html=True
                )
            if solution:
                update_data["solution"] = input_sanitizer.sanitize_string(solution, allow_html=True)
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
            sanitized_resolution = input_sanitizer.sanitize_string(close_text, allow_html=True)
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
            content = input_sanitizer.sanitize_string(content, allow_html=True)
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

        # --- ITIL coverage ---

        if action == "get_timeline":
            timeline = await ticket_service.get_ticket_timeline(
                ticket_id, limit=limit or 100
            )
            return format_ticket_timeline(timeline, {"action": action})

        if action == "add_task":
            if not content or len(str(content).strip()) < 5:
                raise ValidationError(
                    "content must be at least 5 characters", "content"
                )
            task_result = await ticket_service.add_ticket_task(
                ticket_id,
                input_sanitizer.sanitize_string(content, allow_html=True),
                actiontime=actiontime,
                is_private=is_private,
                task_category_id=task_category_id,
            )
            return format_itil_operation(task_result, "adicionar tarefa")

        if action == "get_tasks":
            tasks = await ticket_service.get_ticket_tasks(ticket_id)
            return format_ticket_tasks(tasks, {"action": action})

        if action == "request_validation":
            if approver in (None, ""):
                raise ValidationError(
                    "approver e obrigatorio (nome ou id do usuario aprovador)",
                    "approver",
                )
            validation_result = await ticket_service.request_ticket_validation(
                ticket_id,
                approver,
                comment=input_sanitizer.sanitize_string(comment, allow_html=True) if comment else None,
            )
            return format_itil_operation(validation_result, "solicitar aprovacao")

        if action == "answer_validation":
            answer_result = await ticket_service.answer_ticket_validation(
                validation_id=validation_id,
                status=validation_status,
                comment=input_sanitizer.sanitize_string(comment, allow_html=True) if comment else None,
                ticket_id=ticket_id,
            )
            return format_itil_operation(answer_result, "responder aprovacao")

        if action == "get_validations":
            validations = await ticket_service.get_ticket_validations(ticket_id)
            return format_ticket_validations(validations, {"action": action})

        if action == "assign_group":
            if group in (None, ""):
                raise ValidationError(
                    "group e obrigatorio (nome ou id do grupo)", "group"
                )
            group_result = await ticket_service.assign_ticket_group(
                ticket_id, group, group_type=group_type
            )
            return format_itil_operation(group_result, "atribuir chamado a grupo")

        if action == "link_tickets":
            check_linked = validate_positive_int(linked_ticket_id, "linked_ticket_id")
            if not check_linked["valid"]:
                return create_mcp_error(
                    check_linked["error"],
                    "linked_ticket_id must be a positive integer",
                    "Example: manage_tickets(action='link_tickets', ticket_id=42, "
                    "linked_ticket_id=43, link_type='duplicate')",
                )
            link_result = await ticket_service.link_tickets(
                ticket_id, check_linked["value"], link_type=link_type
            )
            return format_itil_operation(link_result, "vincular chamados")

        if action == "add_document":
            document_result = await ticket_service.add_ticket_document(
                ticket_id,
                file_path=file_path,
                file_base64=file_base64,
                file_name=file_name,
                title=input_sanitizer.sanitize_string(document_title)
                if document_title
                else None,
            )
            return format_itil_operation(document_result, "anexar documento")

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
