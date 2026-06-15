"""Shared test doubles for the dispatcher/report integration tests."""

import pytest

from nightsweeper import config as cfg
from nightsweeper.adapters.backend import BackendAdapter
from nightsweeper.isolation import Handoff
from nightsweeper.models import Capacity, Result, Task
from nightsweeper.validator import FAILED, PASSED, ValidationResult


class State:
    last = None


class FakeLane(BackendAdapter):
    def __init__(self, name, cost_rank, state, available=True, dollars=None,
                 unit="unbounded", consumed=0.0, dispatch_ok=True):
        self.name = name
        self.cost_rank = cost_rank
        self.state = state
        self._avail = available
        self._dollars = dollars
        self._unit = unit
        self._consumed = consumed
        self._dispatch_ok = dispatch_ok

    def probe_headroom(self):
        return Capacity(self._avail, self._dollars, self._unit)

    def dispatch(self, task, workdir, context=None):
        self.state.last = (task.id, self.name)
        return Result(ok=self._dispatch_ok, consumed_usd=self._consumed)


class FakeValidator:
    def __init__(self, state, verdicts):
        self.state = state
        self.verdicts = verdicts  # {(task_id, lane): 'pass'|'fail'}

    def validate(self, task, workdir):
        v = self.verdicts.get(self.state.last, "pass")
        return ValidationResult(PASSED if v == "pass" else FAILED, "")


class FakeIsolation:
    def __init__(self):
        self.events = []

    def create(self, task):
        self.events.append(("create", task.id))
        return f"/wd/{task.id}"

    def handoff(self, task, workdir):
        self.events.append(("handoff", task.id))
        return Handoff(branch=f"nightsweeper/{task.id}", pushed=True)

    def cleanup(self, task, keep):
        self.events.append(("cleanup", task.id, keep))


class Clock:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return f"2026-06-15T03:{self.n:02d}:00"


def make_config(task_cap=50, dollar_cap=100.0, local_max="medium"):
    return cfg.parse({
        "caps": {"nightly_task_cap": task_cap, "nightly_dollar_cap": dollar_cap},
        "sources": [{"name": "todo_scan", "paths": ["."]}],
        "backends": [
            {"name": "local", "cost_rank": 0,
             "capability": {"validators": ["test"], "max_complexity": local_max}},
            {"name": "claude", "cost_rank": 1,
             "capability": {"validators": ["test", "none"], "max_complexity": "high"},
             "nightly_budget": 5.0},
        ],
        "report": {"path": "/tmp/ns-test-report.md",
                   "downgrade": {"window_nights": 7, "spend_pct_threshold": 0.10, "min_passes": 1}},
    })


def task(tid="t1", validator="test", value="high", complexity="medium"):
    return Task(id=tid, source="todo_scan", title=f"task {tid}", body="b",
                est_complexity=complexity, est_context_tokens=100,
                validator=validator, value=value)


@pytest.fixture
def state():
    return State()
