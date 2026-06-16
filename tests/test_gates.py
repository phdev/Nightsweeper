"""Multi-validator adjudication gates (e.g. Depthfinder)."""

import pytest
from conftest import Clock, FakeIsolation, make_config, task

from nightsweeper import config as cfg
from nightsweeper import report as reportmod
from nightsweeper.config import Gate
from nightsweeper.dispatcher import Dispatcher, NightSummary
from nightsweeper.ledger import Ledger
from nightsweeper.models import RunRow
from nightsweeper.validator import FAILED, PASSED, ValidationResult, Validator


class _R:
    def __init__(self, rc):
        self.returncode = rc


def _v(monkeypatch, results):
    """results: dict cmd -> returncode."""
    v = Validator({"test": "pytest -q"}, gates=[Gate("depthfinder", "depthfinder scan . --warn-below 0.85")])
    calls = []

    def run(cmd, wd):
        calls.append(cmd)
        return _R(results[cmd])

    monkeypatch.setattr(v, "_run", run)
    v.calls = calls
    return v


# --- validator gate behavior ---

def test_gate_runs_after_primary_and_both_pass(monkeypatch):
    v = _v(monkeypatch, {"pytest -q": 0, "depthfinder scan . --warn-below 0.85": 0})
    r = v.validate(task(), "/wd")
    assert r.result == PASSED
    assert v.calls == ["pytest -q", "depthfinder scan . --warn-below 0.85"]  # gate after functional


def test_gate_rejection_fails_with_gate_name(monkeypatch):
    v = _v(monkeypatch, {"pytest -q": 0, "depthfinder scan . --warn-below 0.85": 1})
    r = v.validate(task(), "/wd")
    assert r.result == FAILED and r.failed_gate == "depthfinder"  # passed tests, gate rejected


def test_gate_not_run_when_primary_fails(monkeypatch):
    v = _v(monkeypatch, {"pytest -q": 1})
    r = v.validate(task(), "/wd")
    assert r.result == FAILED and r.failed_gate is None and v.calls == ["pytest -q"]


def test_optional_gate_missing_command_is_skipped(monkeypatch):
    v = Validator({"test": "pytest -q"}, gates=[Gate("df", "df", required=False)])
    monkeypatch.setattr(v, "_run", lambda cmd, wd: _R(0 if cmd == "pytest -q" else 127))
    assert v.validate(task(), "/wd").result == PASSED  # not installed + optional → skipped


# --- config ---

def _base(extra):
    return {"caps": {"nightly_task_cap": 5, "nightly_dollar_cap": 1.0},
            "sources": [{"name": "todo_scan"}],
            "backends": [{"name": "local", "cost_rank": 0,
                          "capability": {"validators": ["test"], "max_complexity": "high"}}],
            **extra}


def test_gates_parse():
    c = cfg.parse(_base({"gates": [{"name": "depthfinder", "cmd": "depthfinder scan ."}]}))
    assert c.gates[0].name == "depthfinder" and c.gates[0].required is True


def test_gate_missing_cmd_raises():
    with pytest.raises(cfg.ConfigError):
        cfg.parse(_base({"gates": [{"name": "df"}]}))


def test_duplicate_gate_names_raise():
    with pytest.raises(cfg.ConfigError, match="unique"):
        cfg.parse(_base({"gates": [{"name": "df", "cmd": "a"}, {"name": "df", "cmd": "b"}]}))


# --- dispatcher records the gate rejection; report breaks it out ---

class GateFailValidator:
    def validate(self, task, workdir):
        return ValidationResult(FAILED, "health 0.78 < 0.85", failed_gate="depthfinder")


def test_dispatcher_records_failed_gate(tmp_path, state):
    from conftest import FakeLane
    led = Ledger(tmp_path / "l.db")
    disp = Dispatcher([FakeLane("local", 0, state)], FakeIsolation(), GateFailValidator(),
                      led, make_config(), clock=Clock())
    disp.run([task("t1")])
    row = led.runs_since("2026-06-15T00:00:00")[0]
    assert row["validation_result"] == "failed:gate:depthfinder"


def test_report_breaks_out_gate_failures(tmp_path):
    led = Ledger(tmp_path / "r.db")
    led.record(RunRow(task_id="t1", source="s", backend="local", consumed=0.0,
                      validation_result="failed:gate:depthfinder", passed=False, escalated=False,
                      branch=None, ts="2026-06-15T03:05:00", park_reason="no-escalation-lane"))
    text = reportmod.generate(make_config(), led,
                              NightSummary("backlog-drained", 1, 1, 0, 1, 0), {}, "2026-06-15T03:00:00")
    assert "Adjudication gates" in text and "depthfinder" in text
