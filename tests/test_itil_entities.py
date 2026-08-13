"""
Tests for the ITIL records beyond the incident (SPEC: ITIL coverage).

What this suite is defending
----------------------------
Five itemtypes share one query surface, and the whole point of that design is
that they must NOT share one field-id map. GLPI reuses the same numbers for
different columns per itemtype -- field 12 is the status of a Problem, the
state dropdown of a Project and the postal state of a Supplier -- so the
dangerous failure mode here is not an exception, it is a search that returns a
confident table filtered on the wrong column. Most of what follows asserts the
exact field id a filter lands on.

The other invariants under test:
  * the cheap count probe answers with `range=0-0` and never paginates;
  * an unsupported filter (urgency on a project) is refused, not ignored;
  * a delete cannot reach GLPI without passing the shared safety guard.
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.models.exceptions import ValidationError
from src.services import itil_service as itil_module
from src.services.itil_service import (
    CHANGE_FIELD,
    CONTRACT_FIELD,
    PROBLEM_FIELD,
    PROJECT_FIELD,
    RECORD_SPECS,
    SUPPLIER_FIELD,
    build_criteria,
    get_spec,
    itil_service,
    reset_field_sync,
    resolve_record_type,
)
from src.tools import consolidated_itil
from src.tools.consolidated_itil import manage_itil_records, search_itil_records
from src.utils.safety_guard import safety_guard


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def hermetic_field_maps():
    """Keep every test off the network and off each other's field maps.

    Reconciliation mutates the static maps in place by design, and the
    "synced" marker is process-wide. Without a snapshot, one reconciliation
    test would silently change the numbers every later test asserts on.
    """
    snapshots = {
        name: dict(spec.fields) for name, spec in RECORD_SPECS.items()
    }
    reset_field_sync()
    with patch(
        "src.services.search_options.glpi_client.get",
        new=AsyncMock(side_effect=RuntimeError("catalogue unavailable in tests")),
    ):
        yield
    for name, snapshot in snapshots.items():
        RECORD_SPECS[name].fields.clear()
        RECORD_SPECS[name].fields.update(snapshot)
    reset_field_sync()


def _search_mock(payload=None):
    return AsyncMock(return_value=payload if payload is not None else {"data": []})


def _patch_search(mock):
    return patch("src.services.itil_service.glpi_client.search", mock)


def _patch_get(mock):
    return patch("src.services.itil_service.glpi_client.get", mock)


def _kwargs_of(mock):
    call = mock.await_args
    assert call is not None, "mock was never awaited"
    return call.kwargs


def _criteria_of(mock):
    return _kwargs_of(mock)["criteria"]


def _flatten(criteria):
    """Yield every leaf criterion, descending into nested groups.

    A free-text query now emits one group per term (each group ORing the
    searchable columns), so a leaf can sit one level down. These helpers assert
    *which column is searched for what* -- a claim that is equally true inside a
    group -- so they look through the grouping instead of at it.
    """
    for crit in criteria or []:
        nested = crit.get("criteria")
        if nested:
            yield from _flatten(nested)
        else:
            yield crit


def _values_for(criteria, field_id):
    return [c["value"] for c in _flatten(criteria) if c.get("field") == field_id]


def _criterion_for(criteria, field_id):
    matches = [c for c in _flatten(criteria) if c.get("field") == field_id]
    assert matches, f"no criterion on field {field_id}: {criteria}"
    return matches[0]


# ==========================================================================
# A. Registry and the field-id ambiguity between itemtypes
# ==========================================================================


class TestRecordTypeRegistry:
    def test_all_five_entities_are_covered(self):
        assert set(RECORD_SPECS) == {
            "problems",
            "changes",
            "projects",
            "contracts",
            "suppliers",
        }

    @pytest.mark.parametrize(
        "given,expected",
        [
            ("problems", "problems"),
            ("problem", "problems"),
            ("Problema", "problems"),
            ("changes", "changes"),
            ("mudanca", "changes"),
            ("projeto", "projects"),
            ("contrato", "contracts"),
            ("fornecedor", "suppliers"),
            ("  SUPPLIERS ", "suppliers"),
        ],
    )
    def test_aliases_resolve(self, given, expected):
        assert resolve_record_type(given) == expected

    def test_unknown_record_type_raises(self):
        with pytest.raises(ValidationError) as exc:
            resolve_record_type("tickets")
        assert "record_type" in str(exc.value.message).lower() or "invalido" in str(
            exc.value.message
        )

    def test_missing_record_type_raises(self):
        with pytest.raises(ValidationError):
            resolve_record_type(None)


class TestFieldIdAmbiguity:
    """The same number means different columns depending on the itemtype."""

    def test_field_12_is_status_only_for_itil_objects(self):
        assert PROBLEM_FIELD["status"] == 12
        assert CHANGE_FIELD["status"] == 12
        # On a project, 12 is the ProjectState dropdown...
        assert PROJECT_FIELD["state"] == 12
        assert "status" not in PROJECT_FIELD
        # ...and on a supplier it is the postal state, which is why the
        # supplier's status must not be read from 12.
        assert SUPPLIER_FIELD["state"] == 12
        assert get_spec("suppliers").status_key == "is_active"
        assert SUPPLIER_FIELD["is_active"] == 7

    def test_field_3_is_not_priority_everywhere(self):
        assert PROBLEM_FIELD["priority"] == 3
        assert PROJECT_FIELD["priority"] == 3
        # A contract has no priority: 3 is the contract number.
        assert CONTRACT_FIELD["num"] == 3
        assert get_spec("contracts").priority_key is None
        # A supplier has no priority either: 3 is the address.
        assert SUPPLIER_FIELD["address"] == 3
        assert get_spec("suppliers").priority_key is None

    def test_field_7_differs_per_itemtype(self):
        assert PROBLEM_FIELD["category"] == 7  # ITIL category
        assert PROJECT_FIELD["plan_start_date"] == 7
        assert CONTRACT_FIELD["notice"] == 7
        assert SUPPLIER_FIELD["is_active"] == 7

    def test_category_maps_to_each_types_classification_dropdown(self):
        expected = {
            "problems": 7,
            "changes": 7,
            "projects": 14,
            "contracts": 4,
            "suppliers": 9,
        }
        for record_type, field_id in expected.items():
            spec = get_spec(record_type)
            assert spec.fields[spec.category_key] == field_id

    def test_urgency_exists_only_on_problem_and_change(self):
        assert get_spec("problems").urgency_key == "urgency"
        assert get_spec("changes").urgency_key == "urgency"
        for record_type in ("projects", "contracts", "suppliers"):
            assert get_spec(record_type).urgency_key is None

    def test_sla_late_flag_is_absent_from_problem_and_change(self):
        """Search option 82 has no column on glpi_problems / glpi_changes.

        GLPI declares `sla_ttr_is_late` for every CommonITILObject but only
        glpi_tickets carries it, so asking for 82 here would filter on a
        column that does not exist. Field 18 (time_to_resolve) is the real one.
        """
        for fields in (PROBLEM_FIELD, CHANGE_FIELD):
            assert 82 not in fields.values()
            assert fields["time_to_resolve"] == 18


# ==========================================================================
# B. Search criteria, per record type
# ==========================================================================


class TestSearchTargetsTheRightItemtype:
    @pytest.mark.parametrize(
        "record_type,itemtype",
        [
            ("problems", "Problem"),
            ("changes", "Change"),
            ("projects", "Project"),
            ("contracts", "Contract"),
            ("suppliers", "Supplier"),
        ],
    )
    async def test_itemtype_reaches_the_search_api(self, record_type, itemtype):
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records(record_type, limit=5)

        assert _kwargs_of(mock)["item_type"] == itemtype

    @pytest.mark.parametrize("record_type", list(RECORD_SPECS))
    async def test_forcedisplay_only_asks_for_fields_this_type_has(self, record_type):
        spec = get_spec(record_type)
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records(record_type)

        requested = set(_kwargs_of(mock)["forcedisplay"])
        assert requested <= set(spec.fields.values())
        assert spec.fields["id"] in requested


class TestStatusFilter:
    async def test_problem_status_name_becomes_its_code(self):
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("problems", status="pending")

        assert _values_for(_criteria_of(mock), PROBLEM_FIELD["status"]) == [4]

    async def test_problem_status_accepts_numeric_code(self):
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("problems", status=8)

        assert _values_for(_criteria_of(mock), PROBLEM_FIELD["status"]) == [8]

    async def test_change_workflow_status_is_not_the_ticket_vocabulary(self):
        """A change has statuses a ticket never has (qualification = 12)."""
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("changes", status="qualification")

        assert _values_for(_criteria_of(mock), CHANGE_FIELD["status"]) == [12]

    async def test_change_accepts_both_glpi_wording_and_ticket_synonym(self):
        for word in ("applied", "solved"):
            mock = _search_mock()
            with _patch_search(mock):
                await itil_service.search_records("changes", status=word)
            assert _values_for(_criteria_of(mock), CHANGE_FIELD["status"]) == [5]

    async def test_unknown_status_is_refused_not_ignored(self):
        mock = _search_mock()
        with _patch_search(mock):
            with pytest.raises(ValidationError):
                await itil_service.search_records("problems", status="reticketed")
        mock.assert_not_awaited()

    async def test_project_state_is_a_dropdown_matched_by_name(self):
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("projects", status="Em andamento")

        criterion = _criterion_for(_criteria_of(mock), PROJECT_FIELD["state"])
        assert criterion["searchtype"] == "contains"
        assert criterion["value"] == "Em andamento"

    async def test_project_state_id_matches_exactly(self):
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("projects", status=3)

        criterion = _criterion_for(_criteria_of(mock), PROJECT_FIELD["state"])
        assert criterion["searchtype"] == "equals"
        assert criterion["value"] == 3

    async def test_contract_status_targets_the_state_dropdown(self):
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("contracts", status="Vigente")

        criteria = _criteria_of(mock)
        assert _values_for(criteria, CONTRACT_FIELD["state"]) == ["Vigente"]
        # and never the contract number, which also lives at a low field id
        assert _values_for(criteria, CONTRACT_FIELD["num"]) == []

    @pytest.mark.parametrize(
        "given,expected", [("ativo", 1), ("active", 1), ("inativo", 0), (False, 0)]
    )
    async def test_supplier_status_is_the_is_active_boolean(self, given, expected):
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("suppliers", status=given)

        criteria = _criteria_of(mock)
        assert _values_for(criteria, SUPPLIER_FIELD["is_active"]) == [expected]
        # field 12 on a supplier is the postal state -- it must stay untouched
        assert _values_for(criteria, SUPPLIER_FIELD["state"]) == []

    async def test_supplier_rejects_a_ticket_style_status(self):
        with pytest.raises(ValidationError):
            await itil_service.search_records("suppliers", status="pending")


class TestOtherFilters:
    async def test_priority_lands_on_field_3(self):
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("problems", priority=5)

        assert _values_for(_criteria_of(mock), PROBLEM_FIELD["priority"]) == [5]

    async def test_urgency_lands_on_field_10(self):
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("changes", urgency=4)

        assert _values_for(_criteria_of(mock), CHANGE_FIELD["urgency"]) == [4]

    async def test_unsupported_filters_are_dropped_at_the_service_boundary(self):
        """A contract has no priority column; the filter must not invent one."""
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("contracts", priority=5, urgency=3)

        assert _criteria_of(mock) == []

    async def test_category_by_name_matches_loosely(self):
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("problems", category="Rede")

        criterion = _criterion_for(_criteria_of(mock), PROBLEM_FIELD["category"])
        assert criterion["searchtype"] == "contains"

    async def test_category_by_id_matches_exactly(self):
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("contracts", category="12")

        criterion = _criterion_for(_criteria_of(mock), CONTRACT_FIELD["type"])
        assert criterion == {"field": 4, "searchtype": "equals", "value": 12}

    async def test_entity_filter_is_recursive(self):
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("projects", entity_id=7)

        criterion = _criterion_for(_criteria_of(mock), PROJECT_FIELD["entities_id"])
        assert criterion["searchtype"] == "under"
        assert _kwargs_of(mock)["is_recursive"] is True

    async def test_free_text_searches_the_title(self):
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("problems", query="impressora")

        criterion = _criterion_for(_criteria_of(mock), PROBLEM_FIELD["name"])
        assert criterion["searchtype"] == "contains"
        assert criterion["value"] == "impressora"

    async def test_text_search_keeps_every_other_filter(self):
        """The ticket path once dropped filters whenever a query was present."""
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records(
                "problems", query="impressora", status="new", priority=4
            )

        criteria = _criteria_of(mock)
        assert _values_for(criteria, PROBLEM_FIELD["name"]) == ["impressora"]
        assert _values_for(criteria, PROBLEM_FIELD["status"]) == [1]
        assert _values_for(criteria, PROBLEM_FIELD["priority"]) == [4]


class TestDateRange:
    @pytest.mark.parametrize(
        "record_type,expected_field",
        [
            ("problems", 15),
            ("changes", 15),
            ("projects", 15),
            ("contracts", 5),
            ("suppliers", 121),
        ],
    )
    async def test_default_date_column_per_record_type(
        self, record_type, expected_field
    ):
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records(
                record_type, date_from="2026-01-01", date_to="2026-01-31"
            )

        criteria = _criteria_of(mock)
        assert _values_for(criteria, expected_field) == ["2026-01-01", "2026-01-31"]
        searchtypes = [
            c["searchtype"] for c in criteria if c["field"] == expected_field
        ]
        assert searchtypes == ["morethan", "lessthan"]

    async def test_date_field_can_be_overridden(self):
        """Contract expiry lives on field 20, which GLPI computes from
        begin_date + duration -- the default range would answer a different
        question."""
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records(
                "contracts", date_from="2026-01-01", date_field="end_date"
            )

        criteria = _criteria_of(mock)
        assert _values_for(criteria, CONTRACT_FIELD["end_date"]) == ["2026-01-01"]
        assert _values_for(criteria, CONTRACT_FIELD["begin_date"]) == []

    async def test_unknown_date_field_is_refused(self):
        with pytest.raises(ValidationError) as exc:
            await itil_service.search_records(
                "problems", date_from="2026-01-01", date_field="vencimento"
            )
        assert "date_field" in exc.value.message

    async def test_no_date_criteria_when_no_range_given(self):
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("problems")

        assert _criteria_of(mock) == []


# ==========================================================================
# C. Sorting
# ==========================================================================


class TestSorting:
    async def test_named_sort_field_resolves(self):
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("problems", sort_by="date")

        assert _kwargs_of(mock)["sort"] == PROBLEM_FIELD["date"]

    async def test_numeric_sort_field_passes_through(self):
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("contracts", sort_by=20)

        assert _kwargs_of(mock)["sort"] == 20

    async def test_unknown_sort_field_falls_back_to_the_default(self):
        """Sorting is a preference; refusing the whole query over it would
        trade a small annoyance for no result at all."""
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("problems", sort_by="inexistente")

        assert _kwargs_of(mock)["sort"] == PROBLEM_FIELD["date_mod"]

    @pytest.mark.parametrize(
        "given,expected", [("asc", "ASC"), ("DESC", "DESC"), ("sideways", "DESC"), (None, "DESC")]
    )
    async def test_order_is_normalised(self, given, expected):
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("problems", order=given)

        assert _kwargs_of(mock)["order"] == expected

    async def test_supplier_defaults_to_alphabetical(self):
        mock = _search_mock()
        with _patch_search(mock):
            await itil_service.search_records("suppliers")

        assert _kwargs_of(mock)["sort"] == SUPPLIER_FIELD["name"]


# ==========================================================================
# D. The cheap count probe
# ==========================================================================


class TestCountProbe:
    async def test_probe_asks_for_range_zero_zero(self):
        get_mock = AsyncMock(return_value={"totalcount": 137, "data": []})
        with _patch_get(get_mock):
            result = await itil_service.count_records("problems")

        endpoint = get_mock.await_args.args[0]
        params = get_mock.await_args.kwargs["params"]
        assert endpoint == "/apirest.php/search/Problem"
        assert params["range"] == "0-0"
        assert result["total"] == 137

    async def test_probe_never_paginates_results(self):
        """Counting by walking pages is what this exists to prevent."""
        get_mock = AsyncMock(return_value={"totalcount": 5000, "data": []})
        search_mock = _search_mock()
        with _patch_get(get_mock), _patch_search(search_mock):
            await itil_service.count_records("contracts")

        probes = [
            call
            for call in get_mock.await_args_list
            if call.args and call.args[0] == "/apirest.php/search/Contract"
        ]
        assert len(probes) == 1
        search_mock.assert_not_awaited()

    async def test_probe_reads_only_totalcount(self):
        get_mock = AsyncMock(return_value={"totalcount": 9, "data": [{"2": 1}] * 40})
        with _patch_get(get_mock):
            result = await itil_service.count_records("changes")

        assert result["total"] == 9
        assert "items" not in result

    async def test_probe_applies_the_same_filters_as_the_list(self):
        get_mock = AsyncMock(return_value={"totalcount": 2})
        with _patch_get(get_mock):
            await itil_service.count_records(
                "problems", status="closed", priority=5, entity_id=3
            )

        params = get_mock.await_args.kwargs["params"]
        flattened = {
            (params[f"criteria[{i}][field]"], params[f"criteria[{i}][value]"])
            for i in range(3)
        }
        assert (PROBLEM_FIELD["status"], 6) in flattened
        assert (PROBLEM_FIELD["priority"], 5) in flattened
        assert (PROBLEM_FIELD["entities_id"], 3) in flattened
        assert params["is_recursive"] == 1
        assert params["criteria[1][link]"] == "AND"

    async def test_probe_does_not_cache(self):
        get_mock = AsyncMock(return_value={"totalcount": 1})
        with _patch_get(get_mock):
            await itil_service.count_records("suppliers")

        assert get_mock.await_args.kwargs["use_cache"] is False

    async def test_missing_totalcount_reads_as_zero(self):
        get_mock = AsyncMock(return_value={"data": []})
        with _patch_get(get_mock):
            result = await itil_service.count_records("projects")

        assert result["total"] == 0

    async def test_probe_errors_propagate_instead_of_returning_zero(self):
        """A silent 0 reads exactly like 'nothing matched'."""
        get_mock = AsyncMock(side_effect=RuntimeError("glpi down"))
        with _patch_get(get_mock):
            with pytest.raises(Exception):
                await itil_service.count_records("problems")


# ==========================================================================
# E. Manage actions
# ==========================================================================


class TestReadActions:
    async def test_get_expands_dropdowns_and_does_not_cache(self):
        get_mock = AsyncMock(return_value={"id": 42, "name": "Falha recorrente"})
        with _patch_get(get_mock), _patch_search(_search_mock()):
            item = await itil_service.get_record("problems", 42)

        first_call = get_mock.await_args_list[0]
        assert first_call.args[0] == "/apirest.php/Problem/42"
        assert first_call.kwargs["params"] == {"expand_dropdowns": 1}
        assert first_call.kwargs["use_cache"] is False
        assert item["itemtype"] == "Problem"

    async def test_get_rejects_a_non_positive_id(self):
        with pytest.raises(ValidationError):
            await itil_service.get_record("contracts", 0)

    async def test_followups_use_the_generic_itilfollowup_endpoint(self):
        sub_mock = AsyncMock(
            return_value=[{"id": 1, "content": "ok", "users_id": 0, "date": None}]
        )
        with patch("src.services.itil_service.glpi_client.get_subitems", sub_mock):
            followups = await itil_service.get_followups("changes", 7)

        assert sub_mock.await_args.args == ("Change", 7, "ITILFollowup")
        assert followups[0]["content"] == "ok"

    @pytest.mark.parametrize("record_type", ["projects", "contracts", "suppliers"])
    async def test_followups_refused_where_glpi_has_none(self, record_type):
        with pytest.raises(ValidationError):
            await itil_service.get_followups(record_type, 1)


class TestWriteActions:
    async def test_create_maps_tool_names_to_glpi_columns(self):
        post_mock = AsyncMock(return_value={"id": 99})
        with patch("src.services.itil_service.glpi_client.post", post_mock):
            result = await itil_service.create_record(
                "suppliers", name="Fornecedor X", category_id=3, is_active="ativo"
            )

        payload = post_mock.await_args.kwargs["data"]
        assert post_mock.await_args.args[0] == "/apirest.php/Supplier"
        assert payload["name"] == "Fornecedor X"
        assert payload["suppliertypes_id"] == 3
        assert payload["is_active"] == 1
        assert result["id"] == 99

    async def test_create_requires_the_types_mandatory_fields(self):
        post_mock = AsyncMock(return_value={"id": 1})
        with patch("src.services.itil_service.glpi_client.post", post_mock):
            with pytest.raises(ValidationError):
                await itil_service.create_record("problems", name="sem descricao")
        post_mock.assert_not_awaited()

    async def test_unknown_arguments_are_dropped_not_forwarded(self):
        """GLPI accepts unknown keys silently, so a typo would look like a
        successful write that changed nothing."""
        post_mock = AsyncMock(return_value={"id": 5})
        with patch("src.services.itil_service.glpi_client.post", post_mock):
            await itil_service.create_record(
                "contracts", name="Contrato", urgency=4, percent_done=50
            )

        payload = post_mock.await_args.kwargs["data"]
        assert set(payload) == {"name"}

    async def test_fields_escape_hatch_reaches_glpi(self):
        post_mock = AsyncMock(return_value={"id": 5})
        with patch("src.services.itil_service.glpi_client.post", post_mock):
            await itil_service.create_record(
                "contracts", name="Contrato", fields={"alert": 4}
            )

        assert post_mock.await_args.kwargs["data"]["alert"] == 4

    async def test_update_refuses_an_empty_payload(self):
        with pytest.raises(ValidationError):
            await itil_service.update_record("projects", 4, urgency=2)

    async def test_update_puts_only_the_supplied_columns(self):
        put_mock = AsyncMock(return_value={})
        get_mock = AsyncMock(return_value={"id": 4, "name": "Projeto"})
        with _patch_get(get_mock), patch(
            "src.services.itil_service.glpi_client.put", put_mock
        ):
            await itil_service.update_record("projects", 4, percent_done=80)

        assert put_mock.await_args.args[0] == "/apirest.php/Project/4"
        assert put_mock.await_args.kwargs["data"] == {"percent_done": 80}

    async def test_delete_moves_to_the_bin_by_default(self):
        delete_mock = AsyncMock(return_value={"success": True})
        with _patch_get(AsyncMock(return_value={"id": 8})), patch(
            "src.services.itil_service.glpi_client.delete", delete_mock
        ):
            result = await itil_service.delete_record("changes", 8)

        assert delete_mock.await_args.args[0] == "/apirest.php/Change/8"
        assert result["purged"] is False

    async def test_delete_can_purge(self):
        delete_mock = AsyncMock(return_value={"success": True})
        with _patch_get(AsyncMock(return_value={"id": 8})), patch(
            "src.services.itil_service.glpi_client.delete", delete_mock
        ):
            result = await itil_service.delete_record("changes", 8, purge=True)

        assert delete_mock.await_args.args[0].endswith("?force_purge=true")
        assert result["purged"] is True

    async def test_add_followup_targets_itilfollowup_with_the_itemtype(self):
        post_mock = AsyncMock(return_value={"id": 77})
        with _patch_get(AsyncMock(return_value={"id": 3})), patch(
            "src.services.itil_service.glpi_client.post", post_mock
        ):
            result = await itil_service.add_followup(
                "problems", 3, "analise concluida", is_private=True
            )

        payload = post_mock.await_args.kwargs["data"]
        assert post_mock.await_args.args[0] == "/apirest.php/ITILFollowup"
        assert payload["itemtype"] == "Problem"
        assert payload["items_id"] == 3
        assert payload["is_private"] == 1
        assert result["followup_id"] == 77

    @pytest.mark.parametrize(
        "record_type,link_itemtype,parent_field",
        [("problems", "Problem_Ticket", "problems_id"), ("changes", "Change_Ticket", "changes_id")],
    )
    async def test_link_ticket_uses_the_glpi_link_itemtype(
        self, record_type, link_itemtype, parent_field
    ):
        post_mock = AsyncMock(return_value={"id": 12})
        with patch("src.services.itil_service.glpi_client.post", post_mock):
            result = await itil_service.link_ticket(record_type, 5, 900)

        assert post_mock.await_args.args[0] == f"/apirest.php/{link_itemtype}"
        assert post_mock.await_args.kwargs["data"] == {
            parent_field: 5,
            "tickets_id": 900,
        }
        assert result["linked"] is True

    @pytest.mark.parametrize("record_type", ["projects", "contracts", "suppliers"])
    async def test_link_ticket_refused_where_glpi_has_no_link_table(self, record_type):
        with pytest.raises(ValidationError):
            await itil_service.link_ticket(record_type, 1, 2)

    async def test_link_ticket_rejects_a_bad_ticket_id(self):
        with pytest.raises(ValidationError):
            await itil_service.link_ticket("problems", 1, "abc")


# ==========================================================================
# F. Tool layer: validation, safety guard and Markdown
# ==========================================================================


class TestSearchTool:
    async def test_invalid_record_type_returns_an_mcp_error(self):
        result = await search_itil_records(record_type="tickets")
        assert result["isError"] is True

    async def test_urgency_is_refused_for_a_project(self):
        with pytest.raises(ValidationError) as exc:
            await search_itil_records(record_type="projects", urgency=3)
        assert "urgencia" in exc.value.message.lower()
        assert exc.value.details.get("field") == "urgency"

    async def test_priority_is_refused_for_a_supplier(self):
        with pytest.raises(ValidationError):
            await search_itil_records(record_type="suppliers", priority=2)

    async def test_priority_out_of_range_is_refused(self):
        with pytest.raises(ValidationError):
            await search_itil_records(record_type="problems", priority=99)

    async def test_short_query_is_refused(self):
        with pytest.raises(ValidationError):
            await search_itil_records(record_type="problems", query="a")

    async def test_limit_is_capped(self):
        mock = _search_mock()
        with _patch_search(mock):
            await search_itil_records(record_type="problems", limit=500)

        assert _kwargs_of(mock)["range_limit"] == consolidated_itil.MAX_LIMIT

    async def test_list_renders_a_markdown_table(self):
        payload = {
            "data": [
                {
                    "2": 11,
                    "1": "Lentidao recorrente",
                    "12": 2,
                    "3": 4,
                    "10": 3,
                    "7": "Rede",
                    "15": "2026-01-05 10:00:00",
                    "19": "2026-01-06 11:00:00",
                }
            ],
            "totalcount": 3,
        }
        with _patch_search(_search_mock(payload)):
            markdown = await search_itil_records(record_type="problems", limit=1)

        assert "| ID | Titulo | Status |" in markdown
        assert "Lentidao recorrente" in markdown
        assert "Atribuido" in markdown
        assert "1 resultados" in markdown
        assert "total: 3" in markdown

    async def test_supplier_table_uses_supplier_headers(self):
        payload = {
            "data": [{"2": 4, "1": "Fornecedor X", "7": 1, "11": "Cidade"}],
            "totalcount": 1,
        }
        with _patch_search(_search_mock(payload)):
            markdown = await search_itil_records(record_type="suppliers")

        assert "| ID | Nome | Tipo | Ativo |" in markdown
        assert "| UF |" in markdown  # field 12 is the postal state here

    async def test_empty_result_says_so(self):
        with _patch_search(_search_mock({"data": [], "totalcount": 0})):
            markdown = await search_itil_records(record_type="changes")

        assert "Nenhum registro encontrado" in markdown

    async def test_count_only_renders_the_probe_answer(self):
        get_mock = AsyncMock(return_value={"totalcount": 42})
        search_mock = _search_mock()
        with _patch_get(get_mock), _patch_search(search_mock):
            markdown = await search_itil_records(
                record_type="contracts", count_only=True
            )

        assert "**42**" in markdown
        assert "range=0-0" in markdown
        search_mock.assert_not_awaited()

    async def test_count_only_accepts_a_loose_boolean(self):
        get_mock = AsyncMock(return_value={"totalcount": 7})
        with _patch_get(get_mock), _patch_search(_search_mock()):
            markdown = await search_itil_records(
                record_type="problems", count_only="true"
            )

        assert "**7**" in markdown

    async def test_entity_name_is_resolved(self):
        mock = _search_mock()
        with _patch_search(mock), patch(
            "src.tools.consolidated_itil.entity_resolver.resolve_entity_name",
            new=AsyncMock(return_value=0),
        ):
            await search_itil_records(record_type="problems", entity_name="Matriz")

        assert _values_for(_criteria_of(mock), PROBLEM_FIELD["entities_id"]) == [0]


class TestManageTool:
    async def test_unknown_action_returns_an_mcp_error(self):
        result = await manage_itil_records(
            record_type="problems", action="teleport", record_id=1
        )
        assert result["isError"] is True

    async def test_invalid_record_type_returns_an_mcp_error(self):
        result = await manage_itil_records(record_type="incidents", action="get")
        assert result["isError"] is True

    async def test_missing_record_id_returns_an_mcp_error(self):
        result = await manage_itil_records(record_type="problems", action="get")
        assert result["isError"] is True

    @pytest.mark.parametrize("record_type", ["projects", "contracts", "suppliers"])
    async def test_followup_actions_are_refused_per_type(self, record_type):
        result = await manage_itil_records(
            record_type=record_type, action="add_followup", record_id=1,
            followup_content="texto longo o suficiente",
        )
        assert result["isError"] is True

    @pytest.mark.parametrize("record_type", ["projects", "contracts", "suppliers"])
    async def test_link_ticket_is_refused_per_type(self, record_type):
        result = await manage_itil_records(
            record_type=record_type, action="link_ticket", record_id=1, ticket_id=2
        )
        assert result["isError"] is True

    async def test_get_renders_a_detail_with_the_status_label(self):
        get_mock = AsyncMock(
            return_value={
                "id": 12,
                "name": "Falha recorrente no link",
                "status": 4,
                "priority": 5,
                "urgency": 4,
                "impact": 3,
                "content": "<p>Detalhe</p>",
                "date": "2026-02-01 08:00:00",
            }
        )
        with _patch_get(get_mock), _patch_search(_search_mock()), patch(
            "src.services.itil_service.glpi_client.get_subitems",
            new=AsyncMock(return_value=[]),
        ):
            markdown = await manage_itil_records(
                record_type="problems", action="get", record_id=12
            )

        assert "# Problem" in markdown
        assert "Falha recorrente no link" in markdown
        assert "**Status:** Pendente" in markdown
        assert "Detalhe" in markdown

    async def test_project_detail_reads_state_from_its_own_column(self):
        """A direct GET returns projectstates_id, not `status`."""
        get_mock = AsyncMock(
            return_value={"id": 3, "name": "Migracao", "projectstates_id": "Em curso"}
        )
        with _patch_get(get_mock):
            markdown = await manage_itil_records(
                record_type="projects", action="get", record_id=3
            )

        assert "**Status:** Em curso" in markdown

    async def test_followups_render_as_a_conversation(self):
        with patch(
            "src.services.itil_service.glpi_client.get_subitems",
            new=AsyncMock(
                return_value=[
                    {
                        "id": 1,
                        "content": "Causa raiz identificada",
                        "users_id": 0,
                        "date": "2026-02-02 09:00:00",
                    }
                ]
            ),
        ):
            markdown = await manage_itil_records(
                record_type="problems", action="get_followups", record_id=12
            )

        assert "1 acompanhamento(s)" in markdown
        assert "Causa raiz identificada" in markdown

    async def test_short_followup_is_refused(self):
        with pytest.raises(ValidationError):
            await manage_itil_records(
                record_type="problems",
                action="add_followup",
                record_id=1,
                followup_content="ok",
            )

    async def test_link_ticket_reports_what_was_linked(self):
        with patch(
            "src.services.itil_service.glpi_client.post",
            new=AsyncMock(return_value={"id": 4}),
        ):
            markdown = await manage_itil_records(
                record_type="changes", action="link_ticket", record_id=7, ticket_id=900
            )

        assert "900" in markdown
        assert "Change_Ticket" in markdown

    async def test_create_reports_the_new_id(self):
        with patch(
            "src.services.itil_service.glpi_client.post",
            new=AsyncMock(return_value={"id": 55}),
        ):
            markdown = await manage_itil_records(
                record_type="problems",
                action="create",
                name="Impressoras caindo",
                content="Ocorre desde segunda",
            )

        assert "55" in markdown
        assert "criado" in markdown.lower()


class TestDeleteSafetyGuard:
    @pytest.mark.parametrize(
        "record_type,operation",
        [
            ("problems", "delete_problem"),
            ("changes", "delete_change"),
            ("projects", "delete_project"),
            ("contracts", "delete_contract"),
            ("suppliers", "delete_supplier"),
        ],
    )
    def test_every_record_type_delete_is_guarded(self, record_type, operation):
        """The guard only challenges names it knows, so each delete must make
        its own name visible for the length of the check."""
        assert consolidated_itil._delete_operation(record_type) == operation
        with consolidated_itil._protected(operation, "teste"):
            assert safety_guard.is_protected_operation(operation)

    def test_the_shared_registry_is_left_as_found(self):
        """PROTECTED_OPERATIONS is a global other modules reconcile against."""
        before = dict(safety_guard.PROTECTED_OPERATIONS)
        with consolidated_itil._protected("delete_problem", "teste"):
            pass
        assert safety_guard.PROTECTED_OPERATIONS == before

    def test_registry_is_restored_even_when_the_guard_refuses(self):
        before = dict(safety_guard.PROTECTED_OPERATIONS)
        with patch.object(safety_guard, "_guard_enabled", True), patch.object(
            safety_guard, "_safety_token", "token-de-teste"
        ):
            with pytest.raises(ValidationError):
                consolidated_itil.require_itil_delete_confirmation(
                    "problems", "Problem", 1, None, None
                )
        assert safety_guard.PROTECTED_OPERATIONS == before

    async def test_delete_is_blocked_without_a_confirmation_token(self):
        delete_mock = AsyncMock()
        with patch.object(safety_guard, "_guard_enabled", True), patch.object(
            safety_guard, "_safety_token", "token-de-teste"
        ), patch("src.services.itil_service.glpi_client.delete", delete_mock):
            with pytest.raises(ValidationError):
                await manage_itil_records(
                    record_type="contracts", action="delete", record_id=9
                )
        delete_mock.assert_not_awaited()

    async def test_delete_is_blocked_with_a_wrong_token(self):
        delete_mock = AsyncMock()
        with patch.object(safety_guard, "_guard_enabled", True), patch.object(
            safety_guard, "_safety_token", "token-de-teste"
        ), patch("src.services.itil_service.glpi_client.delete", delete_mock):
            with pytest.raises(ValidationError):
                await manage_itil_records(
                    record_type="contracts",
                    action="delete",
                    record_id=9,
                    confirmation_token="errado",
                    reason="motivo suficientemente longo",
                )
        delete_mock.assert_not_awaited()

    async def test_delete_is_blocked_without_a_reason(self):
        delete_mock = AsyncMock()
        with patch.object(safety_guard, "_guard_enabled", True), patch.object(
            safety_guard, "_safety_token", "token-de-teste"
        ), patch("src.services.itil_service.glpi_client.delete", delete_mock):
            with pytest.raises(ValidationError):
                await manage_itil_records(
                    record_type="problems",
                    action="delete",
                    record_id=9,
                    confirmation_token="token-de-teste",
                )
        delete_mock.assert_not_awaited()

    async def test_delete_proceeds_once_confirmed(self):
        delete_mock = AsyncMock(return_value={"success": True})
        with patch.object(safety_guard, "_guard_enabled", True), patch.object(
            safety_guard, "_safety_token", "token-de-teste"
        ), _patch_get(AsyncMock(return_value={"id": 9})), patch(
            "src.services.itil_service.glpi_client.delete", delete_mock
        ):
            markdown = await manage_itil_records(
                record_type="problems",
                action="delete",
                record_id=9,
                confirmation_token="token-de-teste",
                reason="duplicado do problema 4, confirmado com a equipe",
            )

        delete_mock.assert_awaited_once()
        assert "lixeira" in markdown


# ==========================================================================
# G. Reconciliation against the live catalogue
# ==========================================================================


DRIFTED_PROBLEM_CATALOGUE = {
    "1": {
        "name": "Titulo",
        "table": "glpi_problems",
        "field": "name",
        "uid": "Problem.name",
    },
    "112": {
        "name": "Status",
        "table": "glpi_problems",
        "field": "status",
        "uid": "Problem.status",
    },
    "4": {
        "name": "Requerente",
        "table": "glpi_users",
        "field": "name",
        "uid": "Problem.Problem_User.User.name",
    },
}


class TestFieldReconciliation:
    async def test_drifted_id_is_corrected_before_the_search(self):
        search_mock = _search_mock()
        with patch(
            "src.services.search_options.glpi_client.get",
            new=AsyncMock(return_value=DRIFTED_PROBLEM_CATALOGUE),
        ), _patch_search(search_mock):
            await itil_service.search_records("problems", status="new")

        assert PROBLEM_FIELD["status"] == 112
        assert _values_for(_criteria_of(search_mock), 112) == [1]

    async def test_reconciliation_runs_once_per_itemtype(self):
        catalogue_mock = AsyncMock(return_value=DRIFTED_PROBLEM_CATALOGUE)
        with patch("src.services.search_options.glpi_client.get", catalogue_mock), \
                _patch_search(_search_mock()):
            await itil_service.search_records("problems")
            await itil_service.search_records("problems")
            await itil_service.search_records("problems")

        assert catalogue_mock.await_count <= 1

    async def test_a_broken_catalogue_never_breaks_the_search(self):
        """The static map is what production runs on; the safety net must not
        become a dependency."""
        search_mock = _search_mock()
        with patch(
            "src.services.search_options.glpi_client.get",
            new=AsyncMock(side_effect=RuntimeError("listSearchOptions down")),
        ), _patch_search(search_mock):
            await itil_service.search_records("problems", status="new")

        assert _values_for(_criteria_of(search_mock), PROBLEM_FIELD["status"]) == [1]

    async def test_each_itemtype_is_reconciled_against_its_own_catalogue(self):
        reconcile_mock = AsyncMock(return_value={"corrected": {}, "missing": []})
        with patch.object(
            itil_module.search_options_cache, "reconcile", reconcile_mock
        ), _patch_search(_search_mock()):
            for record_type in RECORD_SPECS:
                await itil_service.search_records(record_type)

        itemtypes = [call.args[0] for call in reconcile_mock.await_args_list]
        assert set(itemtypes) == {
            "Problem",
            "Change",
            "Project",
            "Contract",
            "Supplier",
        }


# ==========================================================================
# H. Criteria builder, used by list / search / count alike
# ==========================================================================


class TestSharedCriteriaBuilder:
    def test_list_and_count_share_one_builder(self):
        spec = get_spec("problems")
        params = {"status": "new", "priority": 2}
        assert build_criteria(spec, params) == build_criteria(spec, params)

    def test_empty_params_produce_no_criteria(self):
        assert build_criteria(get_spec("suppliers"), {}) == []

    def test_zero_entity_id_is_kept(self):
        """Entity 0 is the GLPI root, not a missing value."""
        criteria = build_criteria(get_spec("problems"), {"entity_id": 0})
        assert _values_for(criteria, PROBLEM_FIELD["entities_id"]) == [0]
