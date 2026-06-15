from nightsweeper.models import Task
from nightsweeper.validator import FAILED, PARKED, PASSED, Validator


class FakeRun:
    def __init__(self, rc):
        self.returncode = rc


def _task(validator):
    return Task(id="t", source="todo_scan", title="x", body="y", est_complexity="low",
                est_context_tokens=10, validator=validator, value="high")


def _val(monkeypatch, rc):
    v = Validator({"test": "pytest -q", "build": "make build"})
    monkeypatch.setattr(v, "_run", lambda cmd, wd: FakeRun(rc))
    return v


def test_none_always_parks(monkeypatch):
    v = _val(monkeypatch, 0)
    assert v.validate(_task("none"), "/wd").result == PARKED


def test_pass_when_command_exits_zero(monkeypatch):
    v = _val(monkeypatch, 0)
    r = v.validate(_task("test"), "/wd")
    assert r.result == PASSED and r.passed is True


def test_fail_when_command_nonzero(monkeypatch):
    v = _val(monkeypatch, 1)
    assert v.validate(_task("test"), "/wd").result == FAILED


def test_missing_command_fails_cleanly():
    v = Validator({})  # no command configured for 'test'
    assert v.validate(_task("test"), "/wd").result == FAILED
