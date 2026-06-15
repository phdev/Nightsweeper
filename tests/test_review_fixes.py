"""Regression tests for the adversarial code-review findings (all confirmed bugs)."""

import subprocess
from pathlib import Path

import pytest
from conftest import Clock, FakeLane, FakeValidator, make_config, task

from nightsweeper import config as cfg
from nightsweeper import report as reportmod
from nightsweeper.backends.claude_headless import ClaudeBackend
from nightsweeper.config import BackendConfig, Capability, Isolation, SourceConfig
from nightsweeper.dispatcher import Dispatcher, NightSummary
from nightsweeper.isolation import Handoff, WorktreeManager
from nightsweeper.ledger import Ledger
from nightsweeper.models import Task
from nightsweeper.sources.github_issues import GithubIssuesSource


# --- #1 escalate-once worktree branch collision (real git) ---

def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True)


def test_real_worktree_recreate_after_cleanup_does_not_collide(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(str(repo), "init", "-q")
    _git(str(repo), "config", "user.email", "t@t")
    _git(str(repo), "config", "user.name", "t")
    (repo / "f.txt").write_text("x")
    _git(str(repo), "add", "-A")
    _git(str(repo), "commit", "-q", "-m", "init")

    m = WorktreeManager(str(repo), Isolation(worktree_dir=".nightsweeper/worktrees"))
    t = Task(id="t1", source="todo_scan", title="x", body="b", est_complexity="low",
             est_context_tokens=10, validator="test", value="high")
    wd1 = m.create(t)
    assert Path(wd1).exists()
    m.cleanup(t, keep=False)
    # the escalation path: recreate the same task's worktree — must NOT raise on the
    # still-existing branch (the -B fix).
    wd2 = m.create(t)
    assert Path(wd2).exists()
    m.cleanup(t, keep=False)


# --- #2 null cost field must not crash after spend ---

class _NullCostLedger:
    def spend_since(self, backend, ts):
        return 0.0


def test_claude_null_cost_does_not_crash():
    be = ClaudeBackend(BackendConfig(
        name="claude", cost_rank=1,
        capability=Capability(validators=frozenset({"test"}), max_complexity="high"),
        options={"nightly_budget": 3.0, "per_task_floor": 0.0}))
    be.bind_runtime(_NullCostLedger(), "2026-06-15T00:00:00")
    be._run_claude = lambda task, wd: (0, '{"total_cost_usd": null, "usage": {"input_tokens": null}}', "")
    t = Task(id="t", source="s", title="x", body="y", est_complexity="low",
             est_context_tokens=1, validator="test", value="high")
    import os
    os.environ.pop("ANTHROPIC_API_KEY", None)
    r = be.dispatch(t, "/tmp")
    assert r.ok is True and r.consumed_usd == 0.0  # coerced, not crashed


# --- #3 one bad github label must not drop the whole source ---

def test_github_bad_label_coerced_not_dropped(monkeypatch):
    s = GithubIssuesSource(SourceConfig(name="github_issues", options={
        "repos": ["x/y"], "default_value": "med",
        "validator_label_prefix": "validator:", "default_validator": "test"}))
    monkeypatch.setattr(s, "_fetch_raw_issues", lambda repo: [
        {"number": 1, "title": "bad", "body": "", "labels": [{"name": "validator:foobar"}]},
        {"number": 2, "title": "good", "body": "", "labels": []},
    ])
    tasks = s.fetch()
    assert len(tasks) == 2                       # neither dropped
    assert tasks[0].validator == "test"          # typo'd label coerced to default


# --- #5 duplicate names / #10 unknown key → ConfigError ---

def test_duplicate_backend_names_rejected():
    raw = {
        "caps": {"nightly_task_cap": 5, "nightly_dollar_cap": 1.0},
        "sources": [{"name": "todo_scan"}],
        "backends": [
            {"name": "local", "cost_rank": 0, "capability": {"validators": ["test"], "max_complexity": "low"}},
            {"name": "local", "cost_rank": 1, "capability": {"validators": ["test"], "max_complexity": "high"}},
        ],
    }
    with pytest.raises(cfg.ConfigError, match="names must be unique"):
        cfg.parse(raw)


def test_unknown_schedule_key_raises_configerror_not_typeerror():
    raw = {
        "caps": {"nightly_task_cap": 5, "nightly_dollar_cap": 1.0},
        "sources": [{"name": "todo_scan"}],
        "backends": [{"name": "local", "cost_rank": 0,
                      "capability": {"validators": ["test"], "max_complexity": "low"}}],
        "schedule": {"hour": 3, "minit": 0},  # typo
    }
    with pytest.raises(cfg.ConfigError, match="unknown key"):
        cfg.parse(raw)


# --- #4/#6 downgrade metric: high-spend/low-pass triggers; unused lane does not ---

def _row(**kw):
    from nightsweeper.models import RunRow
    base = dict(task_id="t", source="s", backend="claude", consumed=0.0,
                validation_result="failed", passed=False, escalated=False,
                branch=None, ts="2026-06-15T03:05:00")
    base.update(kw)
    return RunRow(**base)


def test_high_spend_low_pass_triggers_downgrade(tmp_path):
    led = Ledger(tmp_path / "d.db")
    led.record(_row(consumed=4.5, passed=False))  # spent ~90% of $5 budget, 0 passes
    text = reportmod.generate(make_config(), led,
                              NightSummary("backlog-drained", 1, 1, 0, 1, 0), {}, "2026-06-15T03:00:00")
    assert "Recommend downgrading `claude`" in text  # paying-for-failure now caught


def test_unused_lane_not_recommended(tmp_path):
    led = Ledger(tmp_path / "d.db")  # no claude rows at all → attempts 0 in window
    text = reportmod.generate(make_config(), led,
                              NightSummary("backlog-drained", 0, 0, 0, 0, 0), {}, "2026-06-15T03:00:00")
    # an empty night is the no-run report; assert the unused lane isn't nagged when there IS activity
    led.record(_row(backend="local", consumed=0.0, passed=True, validation_result="passed"))
    text2 = reportmod.generate(make_config(), led,
                               NightSummary("backlog-drained", 1, 1, 1, 0, 0), {}, "2026-06-15T03:00:00")
    assert "Recommend downgrading `claude`" not in text2


# --- #7 a single task's isolation error must not crash the night ---

class FlakyIsolation:
    def __init__(self, bad_ids):
        self.bad = set(bad_ids)

    def create(self, task):
        if task.id in self.bad:
            raise RuntimeError("git worktree add failed")
        return f"/wd/{task.id}"

    def handoff(self, task, workdir):
        return Handoff(branch=f"nightsweeper/{task.id}", pushed=True)

    def cleanup(self, task, keep):
        pass


def test_isolation_error_parks_task_night_continues(tmp_path, state):
    led = Ledger(tmp_path / "l.db")
    local = FakeLane("local", 0, state)
    disp = Dispatcher([local], FlakyIsolation(bad_ids={"bad"}),
                      FakeValidator(state, {("good", "local"): "pass"}), led,
                      make_config(), clock=Clock())
    summary = disp.run([task("bad"), task("good")])
    rows = {r["task_id"]: r for r in led.runs_since("2026-06-15T00:00:00")}
    assert "dispatch-error" in (rows["bad"]["park_reason"] or "")
    assert rows["good"]["validation_result"] == "passed"  # night continued
    assert summary.passed == 1
