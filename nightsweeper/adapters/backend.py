"""``BackendAdapter`` — the agent-lane seam (origin core interface).

V1 lanes: local (OpenClaw/Ollama), claude (headless ``claude -p``).
V2 lane: codex (``codex exec``).

Two dormant V2 hooks exist from day one so V2 changes no signature:
- ``estimate(task)`` returns ``None`` in V1 (the preflight seam).
- ``dispatch(task, workdir, context=None)`` accepts and ignores ``context`` in
  V1 (the Gbrain read-only-enricher seam).
"""

from __future__ import annotations

import abc
from typing import Optional

from ..models import Capacity, CostRange, Result, Task


class BackendAdapter(abc.ABC):
    """An agent backend. ``cost_rank`` orders lanes (lower = cheaper)."""

    name: str
    cost_rank: int

    @abc.abstractmethod
    def probe_headroom(self) -> Capacity:
        """Idle capacity for tonight. Local → unbounded/$0; cloud → remaining $ budget."""

    @abc.abstractmethod
    def dispatch(self, task: Task, workdir: str, context: Optional[str] = None) -> Result:
        """Run ``task`` inside ``workdir``. ``context`` is the dormant V2 enricher seam."""

    def estimate(self, task: Task) -> Optional[CostRange]:
        """Preflight cost band. Dormant in V1 (returns ``None``); made real in V2."""
        return None
