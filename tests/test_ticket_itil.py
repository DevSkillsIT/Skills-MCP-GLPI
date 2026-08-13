"""
Tests for the ITIL coverage added to the ticket domain.

Covers every new action of glpi_manage_ticket_operations:
  get_timeline, add_task, get_tasks, request_validation, answer_validation,
  get_validations, assign_group, link_tickets, add_document

Plus the two regressions of the silent-discard bug class (fields accepted by
the tool and dropped by the service) and the upload manifest wire format.
"""

import base64
import json
import re

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.formatters.glpi_formatters import (
    format_itil_operation,
    format_ticket_tasks,
    format_ticket_timeline,
    format_ticket_validations,
)
from src.models.exceptions import GLPIError, ValidationError
from src.services.ticket_service import (
    ACTOR_TYPE,
    VALIDATION_STATUS,
    _encode_multipart,
    _guess_mime_type,
    _resolve_link_type,
    _resolve_validation_answer,
    ticket_service,
)
from src.tools.consolidated_tickets import (
    ACTIONS_REQUIRING_TICKET_ID,
    MANAGE_ACTIONS,
    manage_tickets,
)


TICKET = {"id": 42, "name": "Impressora sem toner", "status": 2}


def _subitems(mapping):
    """Build a get_subitems side effect keyed by sub-itemtype.

    A value that is an Exception is raised, which is how an unavailable source
    is simulated.
    """

    async def _side_effect(itemtype, item_id, subitem_type, params=None):
        value = mapping.get(subitem_type)
        if value is None:
            raise GLPIError(404, f"Recurso nao encontrado: {subitem_type}")
        if isinstance(value, Exception):
            raise value
        return value

    return AsyncMock(side_effect=_side_effect)


FOLLOWUPS = [
    {"id": 1, "date": "2026-01-02 10:00:00", "users_id": 7, "content": "<p>Chamei o usuario</p>", "is_private": 0},
    {"id": 2, "date": "2026-01-04 09:00:00", "users_id": 8, "content": "Aguardando peca", "is_private": 1},
]
TASKS = [
    {"id": 11, "date": "2026-01-03 08:30:00", "users_id": 7, "users_id_tech": 8,
     "content": "Trocar toner", "actiontime": 5400, "state": 1, "is_private": 0},
]
SOLUTIONS = [
    {"id": 21, "date_creation": "2026-01-05 17:00:00", "users_id": 8, "content": "Toner trocado", "status": 3},
]
VALIDATIONS = [
    {"id": 31, "submission_date": "2026-01-01 08:00:00", "users_id": 7,
     "users_id_validate": 9, "comment_submission": "Autoriza a compra?",
     "comment_validation": "", "status": 2, "validation_date": None},
]

USER_NAMES = {7: "Ana Souza", 8: "Bruno Lima", 9: "Carla Dias"}


# ---------------------------------------------------------------------------
# get_timeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeline_merges_four_sources_in_chronological_order():
    sub = _subitems({
        "ITILFollowup": FOLLOWUPS,
        "TicketTask": TASKS,
        "ITILSolution": SOLUTIONS,
        "TicketValidation": VALIDATIONS,
    })
    names = AsyncMock(return_value=USER_NAMES)
    with patch("src.services.ticket_service.glpi_client.get_subitems", sub), \
         patch("src.services.ticket_service.dropdown_cache.get_many_names", names):
        timeline = await ticket_service.get_ticket_timeline(42)

    kinds = [e["kind"] for e in timeline["entries"]]
    assert kinds == ["validation", "followup", "task", "followup", "solution"]
    assert timeline["counts"] == {"followup": 2, "task": 1, "solution": 1, "validation": 1}
    assert timeline["failed_sources"] == []
    assert timeline["total_entries"] == 5
    assert timeline["truncated"] is False


@pytest.mark.asyncio
async def test_timeline_resolves_author_and_approver_names():
    sub = _subitems({
        "ITILFollowup": FOLLOWUPS,
        "TicketTask": TASKS,
        "ITILSolution": SOLUTIONS,
        "TicketValidation": VALIDATIONS,
    })
    names = AsyncMock(return_value=USER_NAMES)
    with patch("src.services.ticket_service.glpi_client.get_subitems", sub), \
         patch("src.services.ticket_service.dropdown_cache.get_many_names", names):
        timeline = await ticket_service.get_ticket_timeline(42)

    by_kind = {e["kind"]: e for e in timeline["entries"]}
    assert by_kind["task"]["author"] == "Ana Souza"
    assert by_kind["task"]["assignee"] == "Bruno Lima"
    assert by_kind["validation"]["approver"] == "Carla Dias"
    assert by_kind["solution"]["author"] == "Bruno Lima"


@pytest.mark.asyncio
async def test_timeline_fetches_sources_concurrently():
    """The four reads must be gathered, not awaited one after the other."""
    sub = _subitems({
        "ITILFollowup": FOLLOWUPS,
        "TicketTask": TASKS,
        "ITILSolution": SOLUTIONS,
        "TicketValidation": VALIDATIONS,
    })
    gather_calls = []
    real_gather = __import__("asyncio").gather

    def _spy(*args, **kwargs):
        gather_calls.append(len(args))
        return real_gather(*args, **kwargs)

    with patch("src.services.ticket_service.glpi_client.get_subitems", sub), \
         patch("src.services.ticket_service.dropdown_cache.get_many_names", AsyncMock(return_value={})), \
         patch("src.services.ticket_service.asyncio.gather", side_effect=_spy):
        await ticket_service.get_ticket_timeline(42)

    assert 4 in gather_calls


@pytest.mark.asyncio
async def test_timeline_tolerates_partial_failure():
    """One unavailable source must not take the whole timeline down."""
    sub = _subitems({
        "ITILFollowup": FOLLOWUPS,
        "TicketTask": TASKS,
        "ITILSolution": SOLUTIONS,
        "TicketValidation": GLPIError(403, "sem permissao de leitura"),
    })
    with patch("src.services.ticket_service.glpi_client.get_subitems", sub), \
         patch("src.services.ticket_service.dropdown_cache.get_many_names", AsyncMock(return_value=USER_NAMES)):
        timeline = await ticket_service.get_ticket_timeline(42)

    assert [e["kind"] for e in timeline["entries"]] == [
        "followup", "task", "followup", "solution"
    ]
    assert len(timeline["failed_sources"]) == 1
    assert timeline["failed_sources"][0]["source"] == "validation"
    assert "validation" not in timeline["counts"]


@pytest.mark.asyncio
async def test_timeline_reports_every_failed_source():
    sub = _subitems({
        "ITILFollowup": GLPIError(500, "boom"),
        "TicketTask": GLPIError(403, "nope"),
        "ITILSolution": SOLUTIONS,
        "TicketValidation": VALIDATIONS,
    })
    with patch("src.services.ticket_service.glpi_client.get_subitems", sub), \
         patch("src.services.ticket_service.dropdown_cache.get_many_names", AsyncMock(return_value=USER_NAMES)):
        timeline = await ticket_service.get_ticket_timeline(42)

    failed = {f["source"] for f in timeline["failed_sources"]}
    assert failed == {"followup", "task"}
    assert timeline["total_entries"] == 2


@pytest.mark.asyncio
async def test_timeline_followup_falls_back_to_legacy_itemtype():
    """ITILFollowup is tried first, TicketFollowup only when it fails."""
    sub = _subitems({
        "ITILFollowup": GLPIError(404, "nao existe nesta instancia"),
        "TicketFollowup": FOLLOWUPS,
        "TicketTask": [],
        "ITILSolution": [],
        "TicketValidation": [],
    })
    with patch("src.services.ticket_service.glpi_client.get_subitems", sub), \
         patch("src.services.ticket_service.dropdown_cache.get_many_names", AsyncMock(return_value=USER_NAMES)):
        timeline = await ticket_service.get_ticket_timeline(42)

    assert timeline["counts"]["followup"] == 2
    assert timeline["failed_sources"] == []


@pytest.mark.asyncio
async def test_timeline_limit_keeps_most_recent_entries():
    sub = _subitems({
        "ITILFollowup": FOLLOWUPS,
        "TicketTask": TASKS,
        "ITILSolution": SOLUTIONS,
        "TicketValidation": VALIDATIONS,
    })
    with patch("src.services.ticket_service.glpi_client.get_subitems", sub), \
         patch("src.services.ticket_service.dropdown_cache.get_many_names", AsyncMock(return_value=USER_NAMES)):
        timeline = await ticket_service.get_ticket_timeline(42, limit=2)

    assert timeline["truncated"] is True
    assert timeline["total_entries"] == 5
    assert [e["kind"] for e in timeline["entries"]] == ["followup", "solution"]


@pytest.mark.asyncio
async def test_timeline_rejects_invalid_ticket_id():
    with pytest.raises(ValidationError):
        await ticket_service.get_ticket_timeline(0)


# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_task_posts_expected_payload():
    post = AsyncMock(return_value={"id": 77})
    with patch("src.services.ticket_service.glpi_client.post", post), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        result = await ticket_service.add_ticket_task(
            42, "Trocar toner", actiontime=3600, is_private=True
        )

    endpoint = post.await_args.args[0]
    payload = post.await_args.kwargs["data"]
    assert endpoint == "/apirest.php/TicketTask"
    assert payload["tickets_id"] == 42
    assert payload["content"] == "Trocar toner"
    assert payload["actiontime"] == 3600
    assert payload["is_private"] == 1
    assert result["id"] == 77
    assert result["created"] is True


@pytest.mark.asyncio
async def test_add_task_defaults_to_public_and_omits_duration():
    post = AsyncMock(return_value={"id": 78})
    with patch("src.services.ticket_service.glpi_client.post", post), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        await ticket_service.add_ticket_task(42, "Sem duracao")

    payload = post.await_args.kwargs["data"]
    assert payload["is_private"] == 0
    assert "actiontime" not in payload


@pytest.mark.asyncio
async def test_add_task_rejects_non_numeric_actiontime():
    with patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        with pytest.raises(ValidationError) as exc:
            await ticket_service.add_ticket_task(42, "x", actiontime="uma hora")
    assert "actiontime" in str(exc.value.message).lower()


@pytest.mark.asyncio
async def test_add_task_refuses_to_report_success_without_confirmation():
    """A create that GLPI never acknowledged must not be reported as done."""
    with patch("src.services.ticket_service.glpi_client.post", AsyncMock(return_value=None)), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        with pytest.raises(GLPIError):
            await ticket_service.add_ticket_task(42, "conteudo")


@pytest.mark.asyncio
async def test_get_tasks_reads_ticket_subitem_endpoint():
    sub = AsyncMock(return_value=TASKS)
    with patch("src.services.ticket_service.glpi_client.get_subitems", sub), \
         patch("src.services.ticket_service.dropdown_cache.get_many_names", AsyncMock(return_value=USER_NAMES)):
        result = await ticket_service.get_ticket_tasks(42)

    assert sub.await_args.args == ("Ticket", 42, "TicketTask")
    assert result["total"] == 1
    assert result["tasks"][0]["author"] == "Ana Souza"
    assert result["tasks"][0]["actiontime"] == 5400


# ---------------------------------------------------------------------------
# validations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_validation_posts_modern_shape_first():
    post = AsyncMock(return_value={"id": 55})
    with patch("src.services.ticket_service.glpi_client.post", post), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        result = await ticket_service.request_ticket_validation(42, 9, comment="Autoriza?")

    assert post.await_count == 1
    payload = post.await_args.kwargs["data"]
    assert post.await_args.args[0] == "/apirest.php/TicketValidation"
    assert payload["tickets_id"] == 42
    assert payload["items_id_target"] == 9
    assert payload["itemtype_target"] == "User"
    assert payload["status"] == VALIDATION_STATUS["waiting"]
    assert payload["comment_submission"] == "Autoriza?"
    assert result["approver_id"] == 9


@pytest.mark.asyncio
async def test_request_validation_falls_back_to_legacy_column():
    post = AsyncMock(side_effect=[GLPIError(500, "Unknown column items_id_target"), {"id": 56}])
    with patch("src.services.ticket_service.glpi_client.post", post), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        result = await ticket_service.request_ticket_validation(42, 9)

    assert post.await_count == 2
    second_payload = post.await_args_list[1].kwargs["data"]
    assert second_payload["users_id_validate"] == 9
    assert "items_id_target" not in second_payload
    assert result["id"] == 56


@pytest.mark.asyncio
async def test_request_validation_raises_when_no_shape_is_accepted():
    post = AsyncMock(side_effect=GLPIError(403, "sem permissao"))
    with patch("src.services.ticket_service.glpi_client.post", post), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        with pytest.raises(GLPIError):
            await ticket_service.request_ticket_validation(42, 9)
    assert post.await_count == 2


@pytest.mark.asyncio
async def test_request_validation_resolves_approver_by_name():
    search = AsyncMock(return_value={"data": [{"2": "9", "1": "carla.dias"}]})
    post = AsyncMock(return_value={"id": 57})
    with patch("src.services.ticket_service.glpi_client.search", search), \
         patch("src.services.ticket_service.glpi_client.post", post), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        await ticket_service.request_ticket_validation(42, "carla.dias")

    assert post.await_args.kwargs["data"]["items_id_target"] == 9


@pytest.mark.asyncio
async def test_answer_validation_maps_friendly_status():
    put = AsyncMock(return_value={"success": True})
    with patch("src.services.ticket_service.glpi_client.put", put):
        result = await ticket_service.answer_ticket_validation(
            validation_id=31, status="aprovado", comment="Pode seguir"
        )

    assert put.await_args.args[0] == "/apirest.php/TicketValidation/31"
    data = put.await_args.kwargs["data"]
    assert data["status"] == VALIDATION_STATUS["accepted"] == 4
    assert data["comment_validation"] == "Pode seguir"
    assert result["validation_id"] == 31


@pytest.mark.asyncio
async def test_answer_validation_refusal_requires_comment():
    with pytest.raises(ValidationError) as exc:
        await ticket_service.answer_ticket_validation(validation_id=31, status="recusado")
    assert "comment" in str(exc.value.message).lower()


@pytest.mark.asyncio
async def test_answer_validation_refusal_uses_refused_code():
    put = AsyncMock(return_value={"success": True})
    with patch("src.services.ticket_service.glpi_client.put", put):
        await ticket_service.answer_ticket_validation(
            validation_id=31, status="recusado", comment="Fora do escopo"
        )
    assert put.await_args.kwargs["data"]["status"] == VALIDATION_STATUS["refused"] == 3


@pytest.mark.asyncio
async def test_answer_validation_resolves_single_pending_validation():
    sub = AsyncMock(return_value=VALIDATIONS)
    put = AsyncMock(return_value={"success": True})
    with patch("src.services.ticket_service.glpi_client.get_subitems", sub), \
         patch("src.services.ticket_service.dropdown_cache.get_many_names", AsyncMock(return_value=USER_NAMES)), \
         patch("src.services.ticket_service.glpi_client.put", put):
        result = await ticket_service.answer_ticket_validation(
            status="aprovado", ticket_id=42
        )

    assert put.await_args.args[0] == "/apirest.php/TicketValidation/31"
    assert result["validation_id"] == 31


@pytest.mark.asyncio
async def test_answer_validation_refuses_to_guess_between_two_pending():
    two_waiting = VALIDATIONS + [
        {"id": 32, "submission_date": "2026-01-02 08:00:00", "users_id": 7,
         "users_id_validate": 8, "status": 2}
    ]
    with patch("src.services.ticket_service.glpi_client.get_subitems", AsyncMock(return_value=two_waiting)), \
         patch("src.services.ticket_service.dropdown_cache.get_many_names", AsyncMock(return_value=USER_NAMES)):
        with pytest.raises(ValidationError) as exc:
            await ticket_service.answer_ticket_validation(status="aprovado", ticket_id=42)
    assert "validation_id" in str(exc.value.message)


@pytest.mark.asyncio
async def test_get_validations_reads_subitem_and_resolves_approver():
    sub = AsyncMock(return_value=VALIDATIONS)
    with patch("src.services.ticket_service.glpi_client.get_subitems", sub), \
         patch("src.services.ticket_service.dropdown_cache.get_many_names", AsyncMock(return_value=USER_NAMES)):
        result = await ticket_service.get_ticket_validations(42)

    assert sub.await_args.args == ("Ticket", 42, "TicketValidation")
    assert result["validations"][0]["approver"] == "Carla Dias"
    assert result["validations"][0]["validation_status"] == 2


@pytest.mark.asyncio
async def test_get_validations_reads_polymorphic_target():
    """GLPI 11 stores the approver in itemtype_target/items_id_target."""
    modern = [{"id": 33, "submission_date": "2026-02-01 08:00:00", "users_id": 7,
               "itemtype_target": "Group", "items_id_target": 3, "status": 2}]
    groups = AsyncMock(return_value={3: "Suporte N2"})
    with patch("src.services.ticket_service.glpi_client.get_subitems", AsyncMock(return_value=modern)), \
         patch("src.services.ticket_service.dropdown_cache.get_many_names", groups):
        result = await ticket_service.get_ticket_validations(42)

    assert result["validations"][0]["approver"] == "Suporte N2"
    assert result["validations"][0]["approver_type"] == "Group"


def test_validation_answer_aliases():
    assert _resolve_validation_answer("aprovado") == 4
    assert _resolve_validation_answer("APPROVED") == 4
    assert _resolve_validation_answer("recusado") == 3
    assert _resolve_validation_answer(4) == 4
    assert _resolve_validation_answer("3") == 3
    with pytest.raises(ValidationError):
        _resolve_validation_answer("talvez")
    with pytest.raises(ValidationError):
        _resolve_validation_answer(2)  # waiting is not an answer


# ---------------------------------------------------------------------------
# assign_group
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_group_uses_group_ticket_with_assigned_type():
    search = AsyncMock(return_value={"data": [{"2": "5", "1": "Suporte N1"}]})
    post = AsyncMock(return_value={"id": 91})
    with patch("src.services.ticket_service.glpi_client.search", search), \
         patch("src.services.ticket_service.glpi_client.post", post), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)), \
         patch("src.services.ticket_service.dropdown_cache.get_name", AsyncMock(return_value="Suporte N1")):
        result = await ticket_service.assign_ticket_group(42, "Suporte N1")

    assert post.await_args.args[0] == "/apirest.php/Group_Ticket"
    payload = post.await_args.kwargs["data"]
    assert payload == {"tickets_id": 42, "groups_id": 5, "type": ACTOR_TYPE["assigned"]}
    # @MX:NOTE: ASSIGN is 2 in GLPI (see ACTOR_TYPE). Pinned as a literal so a
    # future edit of the constant cannot silently turn assignments into
    # watchers, which is invisible in the ticket detail.
    assert payload["type"] == 2
    assert result["group_name"] == "Suporte N1"


@pytest.mark.asyncio
async def test_assign_group_accepts_numeric_id_without_lookup():
    search = AsyncMock()
    post = AsyncMock(return_value={"id": 92})
    with patch("src.services.ticket_service.glpi_client.search", search), \
         patch("src.services.ticket_service.glpi_client.post", post), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)), \
         patch("src.services.ticket_service.dropdown_cache.get_name", AsyncMock(return_value="Suporte N1")):
        await ticket_service.assign_ticket_group(42, "5")

    search.assert_not_awaited()
    assert post.await_args.kwargs["data"]["groups_id"] == 5


@pytest.mark.asyncio
async def test_assign_group_supports_observer_role():
    post = AsyncMock(return_value={"id": 93})
    with patch("src.services.ticket_service.glpi_client.post", post), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)), \
         patch("src.services.ticket_service.dropdown_cache.get_name", AsyncMock(return_value="G")):
        await ticket_service.assign_ticket_group(42, 5, group_type="observer")

    assert post.await_args.kwargs["data"]["type"] == ACTOR_TYPE["observer"] == 3


@pytest.mark.asyncio
async def test_assign_group_rejects_unknown_role():
    with pytest.raises(ValidationError):
        await ticket_service.assign_ticket_group(42, 5, group_type="chefe")


@pytest.mark.asyncio
async def test_assign_group_refuses_ambiguous_name():
    search = AsyncMock(return_value={"data": [
        {"2": "5", "1": "Suporte N1"},
        {"2": "6", "1": "Suporte N2"},
    ]})
    with patch("src.services.ticket_service.glpi_client.search", search):
        with pytest.raises(ValidationError) as exc:
            await ticket_service.assign_ticket_group(42, "Suporte")
    assert "ambiguo" in str(exc.value.message)


@pytest.mark.asyncio
async def test_assign_group_prefers_exact_name_match():
    search = AsyncMock(return_value={"data": [
        {"2": "5", "1": "Suporte"},
        {"2": "6", "1": "Suporte N2"},
    ]})
    post = AsyncMock(return_value={"id": 94})
    with patch("src.services.ticket_service.glpi_client.search", search), \
         patch("src.services.ticket_service.glpi_client.post", post), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)), \
         patch("src.services.ticket_service.dropdown_cache.get_name", AsyncMock(return_value="Suporte")):
        await ticket_service.assign_ticket_group(42, "Suporte")

    assert post.await_args.kwargs["data"]["groups_id"] == 5


@pytest.mark.asyncio
async def test_assign_group_translates_duplicate_link_error():
    search = AsyncMock(return_value={"data": [{"2": "5", "1": "Suporte"}]})
    post = AsyncMock(side_effect=GLPIError(400, "ERROR_GLPI_ADD"))
    with patch("src.services.ticket_service.glpi_client.search", search), \
         patch("src.services.ticket_service.glpi_client.post", post), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        with pytest.raises(GLPIError) as exc:
            await ticket_service.assign_ticket_group(42, "Suporte")
    assert exc.value.code == 409


# ---------------------------------------------------------------------------
# link_tickets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_tickets_posts_ticket_ticket():
    post = AsyncMock(return_value={"id": 101})
    with patch("src.services.ticket_service.glpi_client.post", post), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        result = await ticket_service.link_tickets(42, 43, link_type="duplicate")

    assert post.await_args.args[0] == "/apirest.php/Ticket_Ticket"
    assert post.await_args.kwargs["data"] == {
        "tickets_id_1": 42, "tickets_id_2": 43, "link": 2,
    }
    assert result["link_type"] == 2


@pytest.mark.asyncio
async def test_link_tickets_rejects_self_link():
    with pytest.raises(ValidationError):
        await ticket_service.link_tickets(42, 42)


@pytest.mark.asyncio
async def test_link_tickets_rejects_unknown_type():
    with pytest.raises(ValidationError):
        await ticket_service.link_tickets(42, 43, link_type="irmao")


def test_link_type_friendly_names():
    assert _resolve_link_type("link") == 1
    assert _resolve_link_type("duplicado") == 2
    assert _resolve_link_type("filho") == 3
    assert _resolve_link_type("parent") == 4
    assert _resolve_link_type(2) == 2
    assert _resolve_link_type(None) == 1


# ---------------------------------------------------------------------------
# add_document (multipart upload)
# ---------------------------------------------------------------------------


def _upload_mocks(status_code=201, payload=None):
    response = MagicMock()
    response.status_code = status_code
    response.text = json.dumps(payload if payload is not None else {"id": 501})
    response.json = MagicMock(return_value=payload if payload is not None else {"id": 501})

    client = MagicMock()
    client.post = AsyncMock(return_value=response)

    session = MagicMock()
    session._ensure_session = AsyncMock(return_value=client)
    session.clear_cache = MagicMock()
    return session, client


def _parse_upload(client):
    """Return (endpoint, body_text, content_type) from the recorded upload."""
    endpoint = client.post.await_args.args[0]
    body = client.post.await_args.kwargs["content"]
    content_type = client.post.await_args.kwargs["headers"]["Content-Type"]
    return endpoint, body.decode("utf-8", errors="replace"), content_type


@pytest.mark.asyncio
async def test_add_document_declares_ticket_link_inside_manifest():
    """The Ticket link travels in uploadManifest, never as a Document_Item POST."""
    session, client = _upload_mocks()
    json_post = AsyncMock()
    with patch("src.services.ticket_service.glpi_client.session", session), \
         patch("src.services.ticket_service.glpi_client.post", json_post), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        result = await ticket_service.add_ticket_document(
            42, file_base64=base64.b64encode(b"%PDF-1.4 fake").decode(), file_name="laudo.pdf"
        )

    endpoint, body, content_type = _parse_upload(client)
    assert endpoint == "/apirest.php/Document"
    assert content_type.startswith("multipart/form-data; boundary=")

    manifest_raw = re.search(r'name="uploadManifest".*?\r\n\r\n(\{.*?\})\r\n--', body, re.S).group(1)
    manifest = json.loads(manifest_raw)
    assert manifest["input"]["itemtype"] == "Ticket"
    assert manifest["input"]["items_id"] == 42
    assert manifest["input"]["_filename"] == ["laudo.pdf"]
    assert manifest["input"]["name"] == "laudo.pdf"

    # No separate Document_Item call: restricted profiles cannot create it.
    json_post.assert_not_awaited()
    assert result["linked_to_ticket"] is True
    assert result["id"] == 501


@pytest.mark.asyncio
async def test_add_document_sends_manifest_as_text_and_file_as_file_part():
    session, client = _upload_mocks()
    with patch("src.services.ticket_service.glpi_client.session", session), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        await ticket_service.add_ticket_document(
            42, file_base64=base64.b64encode(b"conteudo").decode(), file_name="nota.txt"
        )

    _, body, _ = _parse_upload(client)
    # The manifest part carries no filename -> lands in $_POST.
    assert 'Content-Disposition: form-data; name="uploadManifest"\r\n' in body
    assert 'name="uploadManifest"; filename' not in body
    # The file part carries filename -> lands in $_FILES.
    assert 'Content-Disposition: form-data; name="filename[0]"; filename="nota.txt"' in body
    assert "Content-Type: text/plain" in body
    assert "conteudo" in body


@pytest.mark.asyncio
async def test_add_document_derives_mime_from_extension():
    session, client = _upload_mocks()
    with patch("src.services.ticket_service.glpi_client.session", session), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        result = await ticket_service.add_ticket_document(
            42, file_base64=base64.b64encode(b"x").decode(), file_name="print.png"
        )

    _, body, _ = _parse_upload(client)
    assert "Content-Type: image/png" in body
    assert result["mime_type"] == "image/png"


@pytest.mark.asyncio
async def test_add_document_reads_file_from_disk(tmp_path):
    target = tmp_path / "relatorio.csv"
    target.write_bytes(b"col1,col2\n1,2\n")
    session, client = _upload_mocks()
    with patch("src.services.ticket_service.glpi_client.session", session), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        result = await ticket_service.add_ticket_document(
            42, file_path=str(target), title="Relatorio mensal"
        )

    _, body, _ = _parse_upload(client)
    manifest_raw = re.search(r'name="uploadManifest".*?\r\n\r\n(\{.*?\})\r\n--', body, re.S).group(1)
    assert json.loads(manifest_raw)["input"]["name"] == "Relatorio mensal"
    assert result["file_name"] == "relatorio.csv"
    assert result["size_bytes"] == 14


@pytest.mark.asyncio
async def test_add_document_clears_read_cache_after_upload():
    session, _client = _upload_mocks()
    with patch("src.services.ticket_service.glpi_client.session", session), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        await ticket_service.add_ticket_document(
            42, file_base64=base64.b64encode(b"x").decode(), file_name="a.txt"
        )
    session.clear_cache.assert_called_once()


@pytest.mark.asyncio
async def test_add_document_surfaces_http_failure():
    session, _client = _upload_mocks(status_code=400, payload={"error": "ERROR_UPLOAD"})
    with patch("src.services.ticket_service.glpi_client.session", session), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        with pytest.raises(GLPIError):
            await ticket_service.add_ticket_document(
                42, file_base64=base64.b64encode(b"x").decode(), file_name="a.txt"
            )


@pytest.mark.asyncio
async def test_add_document_surfaces_upload_result_error_on_201():
    """GLPI answers 201 even when it refused the file — never report success."""
    session, _client = _upload_mocks(
        payload={"id": 9, "upload_result": {"filename": [{"error": "extensao nao permitida"}]}}
    )
    with patch("src.services.ticket_service.glpi_client.session", session), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        with pytest.raises(GLPIError) as exc:
            await ticket_service.add_ticket_document(
                42, file_base64=base64.b64encode(b"x").decode(), file_name="a.exe"
            )
    assert "extensao nao permitida" in str(exc.value.message)


@pytest.mark.asyncio
async def test_add_document_requires_a_payload():
    with pytest.raises(ValidationError):
        await ticket_service.add_ticket_document(42)


@pytest.mark.asyncio
async def test_add_document_rejects_invalid_base64():
    with pytest.raises(ValidationError):
        await ticket_service.add_ticket_document(42, file_base64="nao@base64!", file_name="a.txt")


@pytest.mark.asyncio
async def test_add_document_rejects_missing_file():
    with pytest.raises(ValidationError):
        await ticket_service.add_ticket_document(42, file_path="/nao/existe/arquivo.txt")


def test_encode_multipart_wire_format():
    body, content_type = _encode_multipart(
        {"uploadManifest": '{"input":{"name":"a"}}'},
        "filename[0]", "a.txt", b"dados", "text/plain",
    )
    boundary = content_type.split("boundary=")[1]
    text = body.decode()
    assert text.startswith(f"--{boundary}\r\n")
    assert text.endswith(f"--{boundary}--\r\n")
    assert text.count(f"--{boundary}") == 3  # manifest + file + closing
    assert '\r\n\r\ndados\r\n' in text


def test_guess_mime_type_defaults_to_octet_stream():
    assert _guess_mime_type("a.pdf") == "application/pdf"
    assert _guess_mime_type("arquivo_sem_extensao") == "application/octet-stream"


# ---------------------------------------------------------------------------
# Silent-discard regressions (same bug class fixed in the ticket filters)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_ticket_writes_location_instead_of_dropping_it():
    post = AsyncMock(return_value={"id": 1})
    with patch("src.services.ticket_service.glpi_client.post", post):
        await ticket_service.create_ticket("t", "d", location_id=12, category_id=3)

    payload = post.await_args.kwargs["data"]
    assert payload["locations_id"] == 12
    assert payload["itilcategories_id"] == 3


@pytest.mark.asyncio
async def test_create_ticket_keeps_defaults_when_caller_sends_none():
    post = AsyncMock(return_value={"id": 1})
    with patch("src.services.ticket_service.glpi_client.post", post):
        await ticket_service.create_ticket(
            "t", "d", priority=None, urgency=None, entity_id=None, location_id=None
        )

    payload = post.await_args.kwargs["data"]
    assert payload["priority"] == 3
    assert payload["urgency"] == 3
    assert payload["entities_id"] == 0
    assert "locations_id" not in payload


@pytest.mark.asyncio
async def test_update_ticket_applies_category_instead_of_dropping_it():
    put = AsyncMock(return_value={"success": True})
    with patch("src.services.ticket_service.glpi_client.put", put), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        await ticket_service.update_ticket(42, category_id=7, title="novo")

    data = put.await_args.kwargs["data"]
    assert data["itilcategories_id"] == 7
    assert data["name"] == "novo"


@pytest.mark.asyncio
async def test_update_ticket_refuses_solution_instead_of_dropping_it():
    put = AsyncMock(return_value={"success": True})
    with patch("src.services.ticket_service.glpi_client.put", put), \
         patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        with pytest.raises(ValidationError) as exc:
            await ticket_service.update_ticket(42, status="solved", solution="Trocado")

    put.assert_not_awaited()
    assert "resolve" in str(exc.value.message)


@pytest.mark.asyncio
async def test_update_ticket_refuses_unknown_field():
    with patch("src.services.ticket_service.glpi_client.get", AsyncMock(return_value=TICKET)):
        with pytest.raises(ValidationError):
            await ticket_service.update_ticket(42, campo_inventado="x")


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def _timeline_payload(**overrides):
    payload = {
        "ticket_id": 42,
        "entries": [
            {"kind": "validation", "date": "2026-01-01 08:00:00", "author": "Ana Souza",
             "approver": "Carla Dias", "content": "Autoriza a compra?", "validation_status": 2,
             "answer": "", "is_private": False},
            {"kind": "followup", "date": "2026-01-02 10:00:00", "author": "Ana Souza",
             "content": "<p>Chamei o usuario</p>", "is_private": False},
            {"kind": "task", "date": "2026-01-03 08:30:00", "author": "Ana Souza",
             "assignee": "Bruno Lima", "content": "Trocar toner", "actiontime": 5400,
             "is_private": True},
            {"kind": "solution", "date": "2026-01-05 17:00:00", "author": "Bruno Lima",
             "content": "Toner trocado", "is_private": False},
        ],
        "counts": {"followup": 1, "task": 1, "solution": 1, "validation": 1},
        "total_entries": 4,
        "truncated": False,
        "failed_sources": [],
    }
    payload.update(overrides)
    return payload


def test_format_timeline_renders_type_author_date_and_content():
    out = format_ticket_timeline(_timeline_payload(), {})
    assert "# Timeline do chamado #42" in out
    assert "| Data | Tipo | Autor | Detalhe |" in out
    assert "Acompanhamento" in out and "Tarefa (privado)" in out
    assert "Solucao" in out and "Aprovacao" in out
    assert "02/01/2026 10:00" in out
    assert "Ana Souza" in out and "Bruno Lima" in out
    # HTML stripped, single line
    assert "Chamei o usuario" in out and "<p>" not in out
    assert "duracao prevista: 1h 30min" in out
    assert "Aguardando" in out


def test_format_timeline_warns_about_unreadable_sources():
    payload = _timeline_payload(failed_sources=[{"source": "validation", "error": "403 sem permissao"}])
    out = format_ticket_timeline(payload, {})
    assert "AVISO" in out
    assert "INCOMPLETA" in out
    assert "aprovacoes" in out


def test_format_timeline_empty_without_failures_states_the_fact():
    payload = _timeline_payload(entries=[], counts={}, total_entries=0)
    assert "Nenhum evento registrado neste chamado" in format_ticket_timeline(payload, {})


def test_format_timeline_empty_with_failures_does_not_claim_no_history():
    payload = _timeline_payload(
        entries=[], counts={}, total_entries=0,
        failed_sources=[{"source": "followup", "error": "500"}],
    )
    out = format_ticket_timeline(payload, {})
    assert "AVISO" in out
    assert "NAO esta confirmada" in out
    assert "Nenhum evento registrado neste chamado" not in out


def test_format_timeline_flags_truncation():
    payload = _timeline_payload(truncated=True, total_entries=120)
    out = format_ticket_timeline(payload, {})
    assert "mais recentes" in out


def test_format_tasks_table():
    data = {"ticket_id": 42, "total": 1, "tasks": [
        {"id": 11, "date": "2026-01-03 08:30:00", "author": "Ana Souza",
         "assignee": "Bruno Lima", "actiontime": 3600, "state": 2,
         "is_private": True, "content": "Trocar toner"},
    ]}
    out = format_ticket_tasks(data, {})
    assert "1 tarefa(s)" in out
    assert "chamado #42" in out
    assert "1h" in out and "Concluida" in out and "Privada" in out


def test_format_tasks_empty():
    assert "Nenhuma tarefa" in format_ticket_tasks({"tasks": []}, {})


def test_format_validations_table():
    data = {"ticket_id": 42, "validations": [
        {"id": 31, "date": "2026-01-01 08:00:00", "author": "Ana Souza",
         "approver": "Carla Dias", "validation_status": 4,
         "validation_date": "2026-01-02 09:00:00",
         "content": "Autoriza?", "answer": "Aprovado pela diretoria"},
    ]}
    out = format_ticket_validations(data, {})
    assert "1 aprovacao(oes)" in out
    assert "Carla Dias" in out
    assert "Aceita" in out
    assert "Aprovado pela diretoria" in out


def test_format_validations_empty():
    assert "Nenhuma aprovacao" in format_ticket_validations({"validations": []}, {})


def test_format_itil_operation_renders_details():
    out = format_itil_operation(
        {"id": 91, "ticket_id": 42, "group_id": 5, "group_name": "Suporte N1",
         "type": 2, "created": True},
        "atribuir chamado a grupo",
    )
    assert "realizada com sucesso" in out
    assert "| Grupo | Suporte N1 |" in out
    assert "| Papel do ator | Atribuido |" in out


def test_format_itil_operation_labels_observer_role():
    out = format_itil_operation({"id": 1, "ticket_id": 42, "type": 3}, "atribuir chamado a grupo")
    assert "| Papel do ator | Observador |" in out


def test_format_itil_operation_translates_link_type():
    out = format_itil_operation(
        {"id": 1, "ticket_id": 42, "linked_ticket_id": 43, "link_type": 2}, "vincular chamados"
    )
    assert "| Tipo de vinculo | Duplicado |" in out


def test_format_itil_operation_never_masks_failure():
    envelope = {"isError": True, "content": [{"type": "text", "text": "sem permissao"}]}
    out = format_itil_operation(envelope, "anexar documento")
    assert "FALHOU" in out
    assert "sem permissao" in out
    assert "| Campo | Valor |" not in out


def test_format_itil_operation_shows_warning_when_id_missing():
    out = format_itil_operation(
        {"id": None, "created": True, "ticket_id": 42,
         "warning": "O GLPI aceitou mas nao devolveu o id"},
        "adicionar tarefa",
    )
    assert "Aviso" in out


# ---------------------------------------------------------------------------
# Tool layer (glpi_manage_ticket_operations)
# ---------------------------------------------------------------------------


def test_new_actions_are_registered():
    for action in (
        "get_timeline", "add_task", "get_tasks", "request_validation",
        "answer_validation", "get_validations", "assign_group",
        "link_tickets", "add_document",
    ):
        assert action in MANAGE_ACTIONS
    assert "get_timeline" in ACTIONS_REQUIRING_TICKET_ID
    # answer_validation acts on a validation_id, so it must NOT demand a ticket
    assert "answer_validation" not in ACTIONS_REQUIRING_TICKET_ID


@pytest.mark.asyncio
async def test_tool_get_timeline_returns_markdown():
    payload = _timeline_payload()
    with patch("src.tools.consolidated_tickets.ticket_service.get_ticket_timeline",
               AsyncMock(return_value=payload)) as svc:
        out = await manage_tickets(action="get_timeline", ticket_id=42, limit=25)

    assert isinstance(out, str)
    assert "# Timeline do chamado #42" in out
    assert svc.await_args.kwargs["limit"] == 25


@pytest.mark.asyncio
async def test_tool_actions_require_ticket_id():
    for action in ("get_timeline", "add_task", "assign_group", "add_document"):
        out = await manage_tickets(action=action)
        assert out["isError"] is True


@pytest.mark.asyncio
async def test_tool_add_task_forwards_duration_and_visibility():
    with patch("src.tools.consolidated_tickets.ticket_service.add_ticket_task",
               AsyncMock(return_value={"id": 7, "ticket_id": 42, "created": True})) as svc:
        out = await manage_tickets(
            action="add_task", ticket_id=42, content="Trocar o toner",
            actiontime="3600", is_private=True,
        )

    assert svc.await_args.kwargs["actiontime"] == 3600
    assert svc.await_args.kwargs["is_private"] is True
    assert "realizada com sucesso" in out


@pytest.mark.asyncio
async def test_tool_add_task_validates_content():
    with pytest.raises(ValidationError):
        await manage_tickets(action="add_task", ticket_id=42, content="oi")


@pytest.mark.asyncio
async def test_tool_request_validation_requires_approver():
    with pytest.raises(ValidationError):
        await manage_tickets(action="request_validation", ticket_id=42)


@pytest.mark.asyncio
async def test_tool_answer_validation_forwards_friendly_status():
    with patch("src.tools.consolidated_tickets.ticket_service.answer_ticket_validation",
               AsyncMock(return_value={"validation_id": 31, "status": 4, "updated": True})) as svc:
        out = await manage_tickets(
            action="answer_validation", validation_id="31",
            validation_status="aprovado", comment="ok",
        )

    assert svc.await_args.kwargs["validation_id"] == 31
    assert svc.await_args.kwargs["status"] == "aprovado"
    assert isinstance(out, str)


@pytest.mark.asyncio
async def test_tool_assign_group_requires_group():
    with pytest.raises(ValidationError):
        await manage_tickets(action="assign_group", ticket_id=42)


@pytest.mark.asyncio
async def test_tool_link_tickets_validates_linked_id():
    out = await manage_tickets(action="link_tickets", ticket_id=42, linked_ticket_id=0)
    assert out["isError"] is True


@pytest.mark.asyncio
async def test_tool_add_document_forwards_payload():
    with patch("src.tools.consolidated_tickets.ticket_service.add_ticket_document",
               AsyncMock(return_value={"id": 501, "ticket_id": 42, "file_name": "a.pdf",
                                       "linked_to_ticket": True, "created": True})) as svc:
        out = await manage_tickets(
            action="add_document", ticket_id=42, file_base64="AAAA", file_name="a.pdf",
        )

    assert svc.await_args.kwargs["file_base64"] == "AAAA"
    assert svc.await_args.kwargs["file_name"] == "a.pdf"
    assert "| Arquivo | a.pdf |" in out


@pytest.mark.asyncio
async def test_tool_itil_writes_consult_the_safety_guard():
    """Every ITIL write must ask the guard, so enabling it actually protects."""
    calls = []
    with patch("src.tools.consolidated_tickets.require_safety_confirmation",
               side_effect=lambda op, **kw: calls.append(op) or True), \
         patch("src.tools.consolidated_tickets.ticket_service.add_ticket_task",
               AsyncMock(return_value={"id": 1, "created": True})):
        await manage_tickets(action="add_task", ticket_id=42, content="Trocar toner")

    assert calls == ["add_task"]
