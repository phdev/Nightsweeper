"""Deterministic dispatcher — the core IP (U13).

Rules (no ML, origin R7–R11, R24, R26):
- Process tasks in VALUE order (high→med→low); ties by original order. Cost and
  complexity never affect ordering or selection (R26).
- A lane is *eligible* for a task when the capability matrix allows
  (validator, complexity) AND ``probe_headroom().available``. Among eligible
  lanes, pick the cheapest by ``cost_rank`` only (local-first = prefer-local-
  when-eligible; a high-complexity task whose gate excludes local may go straight
  to cloud).
- On validation failure, escalate ONCE to the next-cheapest UNTRIED eligible lane;
  if none exists, park (``no-escalation-lane``). After one escalation, park
  (``escalation-exhausted``). ``validator: none`` parks without dispatch. Any
  isolation/dispatch exception parks the task (``dispatch-error``) — the night
  never crashes on a single task.
- Stop the night on the first of: nightly task cap, nightly $ cap, or no remaining
  task is processable (subsumes "all lanes out of headroom"). The $ cap is checked
  before each task; a single task's full escalation chain (up to two lane runs in
  V1) may overshoot the cap, then the next task is gated — bounded overshoot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from .models import RunRow, Task, value_rank
from .validator import FAILED, PARKED, PASSED, ValidationResult


def _default_clock() -> str:
    return datetime.utcnow().isoformat()


@dataclass
class NightSummary:
    stop_reason: str
    tasks_total: int
    dispatched: int
    passed: int
    parked: int
    backlog_remaining: int


class Dispatcher:
    def __init__(self, backends, isolation, validator, ledger, config,
                 enricher=None, clock: Optional[Callable[[], str]] = None):
        self.backends = sorted(backends, key=lambda b: b.cost_rank)
        self.isolation = isolation
        self.validator = validator
        self.ledger = ledger
        self.config = config
        self.caps = config.caps
        self.enricher = enricher  # V2 read-only context (dormant dispatch context= hook)
        self.preflight_gate = getattr(config, "preflight", None) and config.preflight.mode == "gate"
        self.clock = clock or _default_clock
        self.night_start = self.clock()
        for b in self.backends:
            b.bind_runtime(ledger, self.night_start)
        self.total_spend = 0.0
        self.dispatched = 0
        self.passed = 0
        self.parked = 0
        self._probe_cache: dict = {}

    # --- eligibility (probe results cached per loop iteration; cleared after a dispatch) ---

    def _capability(self, backend_name: str):
        return self.config.backend(backend_name).capability

    def _probe(self, lane):
        if lane.name not in self._probe_cache:
            self._probe_cache[lane.name] = lane.probe_headroom()
        return self._probe_cache[lane.name]

    def eligible_lanes(self, task: Task, exclude=()):
        out = []
        for b in self.backends:
            if b.name in exclude:
                continue
            if not self._capability(b.name).allows(task.validator, task.est_complexity):
                continue
            if not self._probe(b).available:
                continue
            out.append(b)
        return out  # already cost_rank-ordered

    def _processable(self, task: Task) -> bool:
        # 'none' parks without dispatch, so it is always processable
        return task.validator == "none" or bool(self.eligible_lanes(task))

    # --- ledger ---

    def _record(self, task, backend, result, passed, escalated, branch, park_reason,
                consumed, plo=None, phi=None):
        self.ledger.record(RunRow(
            task_id=task.id, source=task.source, backend=backend, consumed=consumed,
            validation_result=result, passed=passed, escalated=escalated, branch=branch,
            ts=self.clock(), predicted_lo=plo, predicted_hi=phi, park_reason=park_reason,
        ))
        if passed:
            self.passed += 1
        elif park_reason:  # a terminal park (no-dispatch, no-escalation-lane, etc.)
            self.parked += 1

    # --- per-task processing (every iteration is exception-guarded) ---

    def _process(self, task: Task) -> None:
        # Preflight gate (V2, opt-in): skip if the cheapest eligible lane's estimate
        # exceeds the per-task cap. Falls through to the stop-check, like park (KTD10).
        if self.preflight_gate and self.caps.per_task_cap is not None:
            elig0 = self.eligible_lanes(task)
            if elig0:
                est0 = elig0[0].estimate(task)
                if est0 is not None and est0.lo > self.caps.per_task_cap:
                    self._record(task, elig0[0].name, "skipped", False, False, None,
                                 "over-per-task-cap", 0.0, est0.lo, est0.hi)
                    return
        self.dispatched += 1
        context = self.enricher.enrich(task) if self.enricher else None
        tried: set = set()
        escalated = False
        while True:
            try:
                elig = self.eligible_lanes(task, exclude=tried)
                if not elig:
                    reason = "escalation-exhausted" if escalated else "no-escalation-lane"
                    self.isolation.cleanup(task, keep=True)
                    self._record(task, "(none)", FAILED, False, escalated, None, reason, 0.0)
                    return
                lane = elig[0]
                wdir = self.isolation.create(task)
                est = lane.estimate(task)  # dormant in V1 → None
                plo, phi = (est.lo, est.hi) if est else (None, None)
                result = lane.dispatch(task, wdir, context=context)
                self.total_spend += result.consumed_usd
                self._probe_cache = {}  # spend changed → re-probe lanes for escalation
                if result.ok:
                    validation = self.validator.validate(task, wdir)
                else:
                    validation = ValidationResult(FAILED, result.error or "dispatch failed")

                if validation.passed:
                    handoff = self.isolation.handoff(task, wdir)
                    self.isolation.cleanup(task, keep=False)
                    self._record(task, lane.name, PASSED, True, escalated, handoff.branch,
                                 None, result.consumed_usd, plo, phi)
                    return

                tried.add(lane.name)
                next_elig = [] if escalated else self.eligible_lanes(task, exclude=tried)
                if next_elig:
                    self._record(task, lane.name, FAILED, False, escalated, None, None,
                                 result.consumed_usd, plo, phi)
                    self.isolation.cleanup(task, keep=False)
                    escalated = True
                    continue
                reason = "escalation-exhausted" if escalated else "no-escalation-lane"
                self.isolation.cleanup(task, keep=True)
                self._record(task, lane.name, FAILED, False, escalated, None, reason,
                             result.consumed_usd, plo, phi)
                return
            except Exception as e:  # one task must never crash the night
                try:
                    self.isolation.cleanup(task, keep=True)
                except Exception:
                    pass
                self._record(task, "(none)", FAILED, False, escalated, None,
                             f"dispatch-error: {str(e)[:80]}", 0.0)
                return

    def _park_no_dispatch(self, task: Task, reason: str) -> None:
        self._record(task, "(none)", PARKED, False, False, None, reason, 0.0)

    # --- night loop ---

    def run(self, tasks) -> NightSummary:
        ordered = sorted(tasks, key=lambda t: value_rank(t.value))
        total = len(ordered)
        i = 0
        stop_reason = "backlog-drained"
        while i < total:
            self._probe_cache = {}  # fresh probes per iteration (budget may have changed)
            if self.dispatched >= self.caps.nightly_task_cap:
                stop_reason = "nightly-task-cap"
                break
            if self.total_spend >= self.caps.nightly_dollar_cap:
                stop_reason = "nightly-dollar-cap"
                break
            if not any(self._processable(t) for t in ordered[i:]):
                stop_reason = "no-processable-task-remaining"
                break
            task = ordered[i]
            i += 1
            if task.validator == "none":
                self._park_no_dispatch(task, "validator-none")
                continue
            if not self.eligible_lanes(task):
                self._park_no_dispatch(task, "no-eligible-lane-headroom")
                continue
            self._process(task)
        return NightSummary(
            stop_reason=stop_reason, tasks_total=total, dispatched=self.dispatched,
            passed=self.passed, parked=self.parked, backlog_remaining=total - i,
        )
