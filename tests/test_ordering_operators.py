"""
GLPI's ordering operators are only ordering on date columns.

Measured on the reference instance, with ground truth read row by row before
any operator was trusted:

  * Date columns (Ticket.date, Contract.begin_date): real, strict inequality,
    insensitive to whether the value carries a time. Two itemtypes agree.
  * Integer columns (Ticket.priority, 6 distinct real values): a full sweep of
    0..7 gave morethan(N) == lessthan(N) == equals(N) at EVERY point. Not an
    off-by-one, not inclusive-vs-exclusive -- the comparison is discarded.

A range filter on a numeric column therefore returns an exact slice wearing the
shape of an interval: a plausible number, no error, and nobody doubts it. The
tool refuses instead.
"""

import pytest
from unittest.mock import AsyncMock, patch

from src.models.exceptions import ValidationError
from src.tools.consolidated_search import _resolve_criterion


def _catalogue(datatype):
    """Patch the catalogue so a field reports one datatype."""
    return patch.multiple(
        "src.services.search_options.search_options_cache",
        resolve=AsyncMock(return_value=15),
        datatype_of=AsyncMock(return_value=datatype),
    )


@pytest.mark.asyncio
class TestOrderingOperators:
    async def test_a_range_on_a_date_column_is_allowed(self):
        with _catalogue("datetime"):
            crit = await _resolve_criterion(
                "Ticket", {"field": "date", "searchtype": "morethan", "value": "2026-01-01"}, 0
            )
        assert crit["searchtype"] == "morethan"

    async def test_plain_date_and_date_delay_are_allowed_too(self):
        for datatype in ("date", "date_delay"):
            with _catalogue(datatype):
                crit = await _resolve_criterion(
                    "Contract",
                    {"field": "begin_date", "searchtype": "lessthan", "value": "2026-01-01"},
                    0,
                )
            assert crit["searchtype"] == "lessthan"

    async def test_a_range_on_an_integer_column_is_refused(self):
        """`morethan 2` on priority silently means `equals 2`."""
        with _catalogue("number"):
            with pytest.raises(ValidationError) as excinfo:
                await _resolve_criterion(
                    "Ticket", {"field": "priority", "searchtype": "morethan", "value": 2}, 0
                )
        assert "equals" in str(excinfo.value)

    async def test_a_range_on_a_dropdown_column_is_refused(self):
        with _catalogue("specific"):
            with pytest.raises(ValidationError):
                await _resolve_criterion(
                    "Ticket", {"field": "status", "searchtype": "lessthan", "value": 5}, 0
                )

    async def test_equality_is_never_blocked(self):
        """Only the two ordering operators are constrained."""
        for searchtype in ("equals", "contains", "notequals", "under"):
            with _catalogue("number"):
                crit = await _resolve_criterion(
                    "Ticket", {"field": "priority", "searchtype": searchtype, "value": 2}, 0
                )
            assert crit["searchtype"] == searchtype

    async def test_an_unknown_datatype_does_not_block_the_search(self):
        """A catalogue that will not load must not turn every range into an error.

        The guard exists to stop a wrong answer, not to make the tool depend on
        a lookup that is already allowed to fail everywhere else in this server.
        """
        with _catalogue(None):
            crit = await _resolve_criterion(
                "Ticket", {"field": "date", "searchtype": "morethan", "value": "2026-01-01"}, 0
            )
        assert crit["searchtype"] == "morethan"

    async def test_the_refusal_names_the_field_and_a_way_forward(self):
        with _catalogue("number"):
            with pytest.raises(ValidationError) as excinfo:
                await _resolve_criterion(
                    "Ticket", {"field": "priority", "searchtype": "morethan", "value": 2}, 3
                )
        message = str(excinfo.value)
        assert "priority" in message
        assert "OR" in message  # aponta a alternativa, nao so o bloqueio
