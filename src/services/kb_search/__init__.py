"""kb_search — Phase 2 unified knowledge-base search for the GLPI MCP.

Consumer side of the knowledge-base feature: a config-driven engine that runs
hybrid (vector + FTS) search over N pgvector sources and fuses them with
cross-source RRF. It is a faithful port of the reference TypeScript search
(hybrid RRF, cross-source RRF, per-source index/provider compatibility), kept
generic — each source is a registry entry (DSN + column mapping), so the public
GLPI MCP carries no source-specific SQL.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
