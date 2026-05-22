"""knowledge_base — Phase 1 ingestion pipeline for the GLPI MCP.

Turns the GLPI instance's own tickets into a vector knowledge base so the MCP
(Phase 2) can answer from resolved-ticket history via hybrid search.

The pipeline mirrors the proven reference ETL on purpose:
    extract (SQL) -> normalize/clean (ticket_document) -> hash-gate ->
    embed (embedder) -> upsert into pgvector (vector_store).

It is optional and self-contained: a deployment that does not want the KB
simply never runs ``ingest_tickets``. Configuration is read from the
environment (see settings); YAML-per-instance is deferred to Phase 2 where the
multi-KB registry lives.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
