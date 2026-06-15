import pytest

from nightsweeper.config import BackendConfig, Capability
from nightsweeper.backends.claude_headless import ClaudeBackend
from nightsweeper.models import Task


class FakeLedger:
    def __init__(self, spent=0.0):
        self._spent = spent

    def spend_since(self, backend, ts):
        return self._spent


def _be(budget=3.0, floor=0.5, spent=0.0):
    be = ClaudeBackend(BackendConfig(
        name="claude", cost_rank=1,
        capability=Capability(validators=frozenset({"test"}), max_complexity="high"),
        options={"model": "claude-sonnet-4-6", "nightly_budget": budget, "per_task_floor": floor},
    ))
    be.bind_runtime(FakeLedger(spent), "2026-06-15T00:00:00")
    return be


def _task():
    return Task(id="t", source="github_issues", title="x", body="y", est_complexity="high",
                est_context_tokens=8000, validator="test", value="high")


def test_budget_remaining_available(monkeypatch):
    be = _be(budget=3.0, spent=0.5)
    cap = be.probe_headroom()
    assert cap.available is True and cap.unit == "usd"
    assert abs(cap.dollars_remaining - 2.5) < 1e-9


def test_fail_closed_when_below_floor():
    be = _be(budget=3.0, floor=0.5, spent=2.7)  # remaining 0.3 < floor 0.5
    assert be.probe_headroom().available is False


def test_dispatch_parses_cost(monkeypatch):
    be = _be()
    monkeypatch.setattr(be, "_run_claude",
                        lambda task, wd: (0, '{"total_cost_usd": 0.42, "usage": {"input_tokens": 1000, "output_tokens": 200}}', ""))
    r = be.dispatch(_task(), "/tmp/wd")
    assert r.ok is True and r.consumed_usd == 0.42 and r.tokens == 1200


def test_dispatch_refuses_when_api_key_present(monkeypatch):
    be = _be()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xxx")
    r = be.dispatch(_task(), "/tmp/wd")
    assert r.ok is False and "ANTHROPIC_API_KEY" in r.error  # hard refuse, uncapped-bill guard


def test_dispatch_unparseable_json_fails(monkeypatch):
    be = _be()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(be, "_run_claude", lambda task, wd: (0, "not json", ""))
    r = be.dispatch(_task(), "/tmp/wd")
    assert r.ok is False and "unparseable" in r.error
