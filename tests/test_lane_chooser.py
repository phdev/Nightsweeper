"""Interactive/explicit lane selection + per-lane usage summaries."""

from types import SimpleNamespace

import pytest
from conftest import FakeLane, State

from nightsweeper.backends.claude_headless import ClaudeBackend
from nightsweeper.backends.codex import CodexBackend
from nightsweeper.cli import select_lanes
from nightsweeper.config import BackendConfig, Capability


def _lanes():
    s = State()
    return [
        FakeLane("aider", 0, s),
        FakeLane("codex", 1, s, unit="unbounded"),
        FakeLane("claude", 2, s, unit="usd", dollars=3.0),
    ]


def _args(lanes=None, choose=False):
    return SimpleNamespace(lanes=lanes, choose_lanes=choose)


def test_lanes_flag_filters():
    out = select_lanes(_lanes(), _args(lanes="codex"))
    assert [b.name for b in out] == ["codex"]


def test_lanes_flag_multiple():
    out = select_lanes(_lanes(), _args(lanes="aider,codex"))
    assert {b.name for b in out} == {"aider", "codex"}


def test_lanes_flag_unknown_exits():
    with pytest.raises(SystemExit):
        select_lanes(_lanes(), _args(lanes="bogus"))


def test_no_flags_returns_all():
    assert len(select_lanes(_lanes(), _args())) == 3


def test_choose_lanes_by_number(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "2")   # ordered: 1 aider, 2 codex, 3 claude
    out = select_lanes(_lanes(), _args(choose=True))
    assert [b.name for b in out] == ["codex"]


def test_choose_lanes_by_name(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "aider, claude")
    out = select_lanes(_lanes(), _args(choose=True))
    assert {b.name for b in out} == {"aider", "claude"}


def test_choose_lanes_blank_is_all(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "")
    assert len(select_lanes(_lanes(), _args(choose=True))) == 3


# --- usage summaries (what the chooser shows) ---

def _bcfg(name, **opts):
    return BackendConfig(name=name, cost_rank=1,
                         capability=Capability(validators=frozenset({"test"}), max_complexity="high"),
                         options=opts)


def test_codex_usage_summary_shows_quota_windows(monkeypatch):
    be = CodexBackend(_bcfg("codex"))
    monkeypatch.setattr(be, "_read_rate_limits",
                        lambda: {"primary": {"used_percent": 7.0}, "secondary": {"used_percent": 19.0}})
    s = be.usage_summary()
    assert "ChatGPT quota" in s and "$0" in s and "5h 7% used" in s and "weekly 19% used" in s


def test_claude_usage_summary_shows_budget():
    class _L:
        def spend_since(self, b, t):
            return 1.0

    be = ClaudeBackend(_bcfg("claude", nightly_budget=3.0, per_task_floor=0.5))
    be.bind_runtime(_L(), "2026-06-15T00:00:00")
    s = be.usage_summary()
    assert "Agent SDK credit" in s and "$2.00 of $3.00" in s
