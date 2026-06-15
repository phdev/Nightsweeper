"""Preflight cost prediction (V2).

Turns a task's V1-populated ``est_context_tokens`` into a ``CostRange`` using a
per-backend cost model. Dormant in V1 (no backend supplies a cost model); in V2 a
cloud lane with a ``cost_model`` in its config returns a real estimate, the
dispatcher records ``predicted_lo/hi``, and the report reports bracket accuracy.
The per-task-cost-cap GATE is opt-in (``preflight.mode: gate``) and ships off by
default until the operator's own replay clears the ≥70% bracket bar (spike S6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .models import CostRange


@dataclass
class CostModel:
    input_per_mtok: float          # $ per million input tokens
    output_per_mtok: float         # $ per million output tokens
    expected_output_tokens: int = 1500
    hi_multiplier: float = 2.5     # upper band accounts for agentic loops / retries


def parse_cost_model(options: dict) -> Optional[CostModel]:
    cm = options.get("cost_model")
    if not cm:
        return None
    return CostModel(
        input_per_mtok=float(cm["input_per_mtok"]),
        output_per_mtok=float(cm["output_per_mtok"]),
        expected_output_tokens=int(cm.get("expected_output_tokens", 1500)),
        hi_multiplier=float(cm.get("hi_multiplier", 2.5)),
    )


def estimate_usd(est_context_tokens: Optional[int], model: Optional[CostModel]) -> Optional[CostRange]:
    if model is None:
        return None
    ctx = est_context_tokens or 0
    lo = ctx / 1_000_000 * model.input_per_mtok + \
        model.expected_output_tokens / 1_000_000 * model.output_per_mtok
    return CostRange(lo=round(lo, 4), hi=round(lo * model.hi_multiplier, 4))
