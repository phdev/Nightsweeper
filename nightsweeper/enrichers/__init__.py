"""Read-only context enrichers (V2).

An enricher turns a task into extra context passed to a lane via the dormant
``dispatch(..., context=)`` hook — it never produces tasks (honors "never invent
work"). Gbrain ships here as an enricher rather than a backlog source because no
Gbrain MCP backlog surface is confirmed (spike S5).
"""

from __future__ import annotations


class CompositeEnricher:
    """Chains several enrichers; concatenates their non-empty context."""

    name = "composite"

    def __init__(self, enrichers: list):
        self.enrichers = enrichers

    def enrich(self, task):
        parts = [e.enrich(task) for e in self.enrichers]
        parts = [p for p in parts if p]
        return "\n\n".join(parts) if parts else None
