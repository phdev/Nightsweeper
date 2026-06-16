"""Core data types shared across Nightsweeper.

The ``Task`` shape is the normalization contract (origin R2): all eight fields
are present from V1. ``est_context_tokens`` is intentionally dormant — carried
and persisted, populated by sources with a coarse heuristic, but unread until
the V2 preflight ``estimate()`` seam (mirrors the nullable ``predicted_lo/hi``
ledger columns).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# --- Enumerations (kept as frozensets; the brief pins these literals) ---

VALIDATORS = frozenset({"test", "typecheck", "build", "none", "custom-cmd"})
VALUES = frozenset({"high", "med", "low"})
COMPLEXITIES = frozenset({"low", "medium", "high"})

# Value ordering for dispatch (high first). Lower sort key = processed earlier.
_VALUE_ORDER = {"high": 0, "med": 1, "low": 2}
_COMPLEXITY_ORDER = {"low": 0, "medium": 1, "high": 2}


def value_rank(value: str) -> int:
    """Sort key for a task value; high < med < low (high processed first)."""
    return _VALUE_ORDER[value]


def complexity_rank(complexity: str) -> int:
    """Ordinal for a complexity tier; low < medium < high."""
    return _COMPLEXITY_ORDER[complexity]


@dataclass
class Task:
    """A normalized unit of real backlog work (origin R2 — all 8 fields)."""

    id: str
    source: str
    title: str
    body: str
    est_complexity: str  # one of COMPLEXITIES
    est_context_tokens: Optional[int]  # dormant in V1; read by V2 estimate()
    validator: str  # one of VALIDATORS
    value: str  # one of VALUES
    # optional per-task command for validator=='custom-cmd' (else the global
    # validators[<type>] command is used). Additive; sources that don't set it pass None.
    validator_cmd: Optional[str] = None

    def __post_init__(self) -> None:
        if self.validator not in VALIDATORS:
            raise ValueError(
                f"Task {self.id!r}: validator {self.validator!r} not in {sorted(VALIDATORS)}"
            )
        if self.value not in VALUES:
            raise ValueError(
                f"Task {self.id!r}: value {self.value!r} not in {sorted(VALUES)}"
            )
        if self.est_complexity not in COMPLEXITIES:
            raise ValueError(
                f"Task {self.id!r}: est_complexity {self.est_complexity!r} not in {sorted(COMPLEXITIES)}"
            )
        if self.est_context_tokens is not None and self.est_context_tokens < 0:
            raise ValueError(f"Task {self.id!r}: est_context_tokens must be >= 0 or None")


@dataclass
class Capacity:
    """A lane's idle headroom for tonight.

    ``unit == 'unbounded'`` is the free local lane ($0, no $ ceiling).
    ``unit == 'usd'`` carries the remaining nightly budget for a cloud lane.
    """

    available: bool
    dollars_remaining: Optional[float] = None
    unit: str = "unbounded"  # 'usd' | 'unbounded'

    def __post_init__(self) -> None:
        if self.unit not in ("usd", "unbounded"):
            raise ValueError(f"Capacity.unit {self.unit!r} not in ('usd','unbounded')")


@dataclass
class Result:
    """Outcome of a single ``dispatch`` call (before validation)."""

    ok: bool
    consumed_usd: float = 0.0
    tokens: Optional[int] = None
    raw: Optional[str] = None
    error: Optional[str] = None


@dataclass
class CostRange:
    """A preflight estimate band. Dormant in V1 (estimate() returns None)."""

    lo: float
    hi: float


@dataclass
class RunRow:
    """One ledger row — the stable schema (origin R16).

    ``predicted_lo``/``predicted_hi`` are nullable until the V2 preflight
    populates them. ``consumed`` is recorded for economics only, never used to
    order or select tasks (origin R20/R26).
    """

    task_id: str
    source: str
    backend: str
    consumed: float
    validation_result: str  # 'passed' | 'failed' | 'parked' | 'skipped'
    passed: bool
    escalated: bool
    branch: Optional[str]
    ts: str  # ISO-8601 timestamp
    predicted_lo: Optional[float] = None
    predicted_hi: Optional[float] = None
    park_reason: Optional[str] = field(default=None)  # e.g. 'no-escalation-lane'
