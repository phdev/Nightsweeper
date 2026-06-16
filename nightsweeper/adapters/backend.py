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

    def bind_runtime(self, ledger, night_start_ts: str) -> None:
        """Wire per-night runtime state (ledger + night start) before probing.

        Concrete no-op by default; budget-gated cloud lanes override it to read
        tonight's spend-so-far. Internal lifecycle hook — not part of the
        external adapter surface, so it leaves probe/dispatch/estimate unchanged.
        """
        return None

    @abc.abstractmethod
    def probe_headroom(self) -> Capacity:
        """Idle capacity for tonight. Local → unbounded/$0; cloud → remaining $ budget."""

    @abc.abstractmethod
    def dispatch(self, task: Task, workdir: str, context: Optional[str] = None) -> Result:
        """Run ``task`` inside ``workdir``. ``context`` is the dormant V2 enricher seam."""

    def estimate(self, task: Task) -> Optional[CostRange]:
        """Preflight cost band. Dormant in V1 (returns ``None``); made real in V2."""
        return None

    def usage_summary(self) -> str:
        """One-line human-readable available-usage for the interactive lane chooser.

        Default derives from ``probe_headroom``; lanes override for richer detail
        (Codex quota windows, Claude budget remaining). ``bind_runtime`` should be
        called first for budget-aware lanes.
        """
        cap = self.probe_headroom()
        if not cap.available:
            return "unavailable"
        if cap.unit == "usd":
            return f"budget ${cap.dollars_remaining:.2f} remaining"
        return "free ($0)"
