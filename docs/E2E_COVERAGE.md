# E2E & KB test coverage matrix

Traceability for what the automated suites validate vs. what needs credentials.

## Suites

| Suite | Path | Needs | Run |
|-------|------|-------|-----|
| Unit | `tests/unit/` | nothing | `pytest tests/unit -o asyncio_mode=auto` |
| E2E (MCP server) | `tests/e2e/test_mcp_server.py` | a running instance | `GLPI_MCP_E2E_URL=http://localhost:8826 [GLPI_MCP_E2E_USER_TOKEN=…] pytest tests/e2e -o asyncio_mode=auto` |
| Golden (KB ranking) | `tests/integration/test_kb_golden.py` | live pgvector + embeddings | `RUN_GOLDEN=1 GLPI_MCP_CONFIG=<instance json> pytest tests/integration/test_kb_golden.py -o asyncio_mode=auto` |

## E2E coverage (tools / prompts / resources)

Discovered dynamically via `tools/list`, `prompts/list`, `resources/list`.

**Read-only / GET tools (10) — all smoke-tested** (`test_all_readonly_tools_reachable`):
`glpi_search_helpdesk_tickets`, `glpi_search_asset_inventory`, `glpi_search_admin_resources`,
`glpi_search_webhook_integrations`, `glpi_list_available_resources`, `glpi_read_resource_by_uri`,
`glpi_list_available_prompts`, `glpi_get_prompt_template`, `glpi_search_knowledge_articles`,
`glpi_search_knowledge_unified`.

**Write/manage tools (5)** — GET path covered for tickets (`search → manage action=get`):
`glpi_manage_ticket_operations`, `glpi_manage_ticket_ai_analysis`, `glpi_manage_asset_operations`,
`glpi_manage_admin_resources`, `glpi_manage_webhook_integrations`.

**Prompts (15)** — each exercised via `prompts/get` (`test_prompts_list_and_get_each`).

**Resources (4)** — each via `resources/read` (`test_resources_read_each`): `glpi://entities`,
`glpi://ticket-status`, `glpi://ticket-categories`, `glpi://priorities`.

**Knowledge base (real DB queries)** — `glpi_search_knowledge_unified`: `source=all/help`,
limit respected, invalid-source graceful, Markdown table shape.

## Credential gating

| Capability | No token | With `GLPI_MCP_E2E_USER_TOKEN` |
|------------|----------|-------------------------------|
| GLPI-backed tools (search/get/manage) & `glpi://entities` | **skipped** (server returns -32001) | fully asserted |
| KB search, static resources, prompts, annotations | fully asserted | fully asserted |

The token is per-GLPI-instance (Ramada `.15` vs Skills `.26` use different tokens).

## Golden-set (KB ranking regression guard)

Validates the v1.1.0 ranking changes against the live corpus:
- **Recall scaling** — `limit=50` returns ≥45 results (per-source fetch = `max(20, limit)`).
- **AD-C02 similarity tiebreak** — at an identical RRF position, no weak (sim<0.55) result
  sits above a strong (sim>0.70) one; official anti-burying preserved (≥1 HELP in top-8).
- **#1 quality floors** are empirical (measured 2026-05-22); they guard against regressions.
