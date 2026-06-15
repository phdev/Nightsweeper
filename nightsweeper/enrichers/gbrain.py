"""Gbrain read-only context enricher (V2).

Spike S5: no Gbrain MCP backlog surface is confirmed, so Gbrain is an ENRICHER,
not a source. ``enrich(task)`` queries the Gbrain MCP for context relevant to the
task and returns it as a string to thread through ``dispatch(..., context=)``.
When no Gbrain MCP is available (the common case here), it is a graceful no-op
(returns ``None``) — it never fabricates a backlog item.
"""

from __future__ import annotations

from ..registry import register_enricher


@register_enricher("gbrain")
class GbrainEnricher:
    name = "gbrain"

    def __init__(self, cfg=None):
        self.cfg = getattr(cfg, "options", {}) if cfg is not None else {}

    def enrich(self, task):
        return self._retrieve(task)

    # injectable for tests / runtime MCP wiring
    def _retrieve(self, task):
        # Real impl: query the gbrain MCP (memory/backlog retrieval) for context
        # relevant to `task` and return a short context string. No MCP available →
        # None (no-op). Wired at runtime where MCP tools exist.
        return None
