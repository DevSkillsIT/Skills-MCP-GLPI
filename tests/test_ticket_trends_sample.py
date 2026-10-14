"""glpi_ticket_trends: numerator and denominator of a percentage come from the same set.

Categories are counted over a SAMPLE (the first 100 tickets) but the percentage
divided by the whole period (up to 500): 100 of 100 tickets in "Rede" printed 66.7%
for a period of 150. The output now states the sample and divides by it.
"""
from unittest.mock import AsyncMock, patch

from src.prompts_handlers.prompts import handle_get_prompt
from src.services.glpi_client import glpi_client

PERIOD_TOTAL = 150


async def _fake_get(path, params=None, use_cache=True):
    if path.startswith("/apirest.php/search/Ticket"):
        return {"data": [{"2": i} for i in range(1, PERIOD_TOTAL + 1)], "totalcount": PERIOD_TOTAL}
    return {"itilcategories_id": 5}


async def _run():
    with patch.object(glpi_client, "get", AsyncMock(side_effect=_fake_get)), patch(
        "src.prompts_handlers.prompts.dropdown_cache.get_many_names",
        AsyncMock(return_value={5: "Rede"}),
    ):
        return await handle_get_prompt("glpi_ticket_trends", {})


async def test_percentage_is_over_the_sampled_tickets():
    result = await _run()
    # every sampled ticket is in "Rede": 100 of 100, not 100 of 150
    assert "| 1 | Rede | 100 | 100.0% |" in result["detailed"]


async def test_output_states_the_sample_and_the_period_total():
    result = await _run()
    assert "100" in result["detailed"] and str(PERIOD_TOTAL) in result["detailed"]
    assert "amostra" in result["detailed"].lower()
    assert result["metadata"]["sampled"] == 100
    assert result["metadata"]["total"] == PERIOD_TOTAL


async def test_compact_view_also_states_the_sample():
    result = await _run()
    assert "amostra" in result["compact"].lower()
