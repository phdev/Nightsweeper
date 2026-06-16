"""Tests for the Aider local lane and the task-list file source."""

import pytest
from conftest import task

from nightsweeper.backends.aider import AiderBackend
from nightsweeper.config import BackendConfig, Capability, SourceConfig
from nightsweeper.models import CostRange
from nightsweeper.sources.tasklist import TaskListSource


def _aider(**opts):
    return AiderBackend(BackendConfig(
        name="aider", cost_rank=0,
        capability=Capability(validators=frozenset({"test"}), max_complexity="medium"),
        options={"model": "qwen2.5-coder:7b", "ollama_host": "http://192.168.1.54:11434", **opts}))


# --- Aider lane ---

def test_aider_probe_reflects_ollama(monkeypatch):
    be = _aider()
    monkeypatch.setattr(be, "_ollama_up", lambda: True)
    assert be.probe_headroom().available is True
    monkeypatch.setattr(be, "_ollama_up", lambda: False)
    assert be.probe_headroom().available is False


def test_aider_points_at_remote_ollama_and_model(monkeypatch):
    import nightsweeper.backends.aider as amod
    be = _aider()
    captured = {}

    class _R:
        returncode, stdout, stderr = 0, "", ""

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["env"] = kw.get("env")
        return _R()

    monkeypatch.setattr(amod.subprocess, "run", fake_run)
    be._run_aider(task("t"), "/wd", "msg")
    assert captured["env"]["OLLAMA_API_BASE"] == "http://192.168.1.54:11434"
    assert "ollama_chat/qwen2.5-coder:7b" in captured["cmd"]
    assert "--no-auto-commits" in captured["cmd"]  # Nightsweeper owns git


def test_aider_dispatch_appends_context(monkeypatch):
    be = _aider()
    seen = {}
    monkeypatch.setattr(be, "_run_aider", lambda task, wd, msg: seen.update(msg=msg) or (0, "", ""))
    be.dispatch(task("t"), "/wd", context="prior memory")
    assert "Relevant context:\nprior memory" in seen["msg"]


def test_aider_dispatch_failure_escalatable(monkeypatch):
    be = _aider()
    monkeypatch.setattr(be, "_run_aider", lambda task, wd, msg: (1, "", "boom"))
    r = be.dispatch(task("t"), "/wd")
    assert r.ok is False and r.consumed_usd == 0.0


def test_aider_is_free():
    assert _aider().estimate(task("t")) == CostRange(0.0, 0.0)


# --- task-list source ---

def _src(path):
    return TaskListSource(SourceConfig(name="tasklist", options={"path": str(path)}))


def test_tasklist_ingests_yaml(tmp_path):
    f = tmp_path / "tasks.yaml"
    f.write_text(
        "- id: add-fn\n"
        "  title: Implement add\n"
        "  body: write add(a,b)\n"
        "  validator: custom-cmd\n"
        "  value: high\n"
        "- title: Only a title\n"  # id derived, defaults applied
    )
    tasks = _src(f).fetch()
    assert len(tasks) == 2
    assert tasks[0].id == "add-fn" and tasks[0].validator == "custom-cmd" and tasks[0].value == "high"
    assert tasks[0].source == "tasklist"
    assert tasks[1].id.startswith("task:") and tasks[1].validator == "test"  # default


def test_tasklist_ingests_json(tmp_path):
    f = tmp_path / "tasks.json"
    f.write_text('[{"id": "j1", "title": "t", "body": "b", "validator": "test", "value": "low"}]')
    tasks = _src(f).fetch()  # JSON is valid YAML
    assert tasks[0].id == "j1" and tasks[0].value == "low"


def test_tasklist_missing_file_is_empty(tmp_path):
    assert _src(tmp_path / "nope.yaml").fetch() == []  # never invents work


def test_tasklist_non_list_raises(tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text("not: a list\n")
    with pytest.raises(ValueError):
        _src(f).fetch()


def test_tasklist_coerces_bad_values(tmp_path):
    f = tmp_path / "t.yaml"
    f.write_text("- title: x\n  validator: bogus\n  value: nope\n  est_complexity: huge\n")
    t = _src(f).fetch()[0]
    assert t.validator == "test" and t.value == "med" and t.est_complexity == "low"


def test_tasklist_per_task_validator_cmd(tmp_path):
    f = tmp_path / "t.yaml"
    f.write_text("- id: docfix\n  title: fix doc\n  validator_cmd: \"grep -q 141 README.md\"\n")
    t = _src(f).fetch()[0]
    assert t.validator == "custom-cmd"               # implied by validator_cmd
    assert t.validator_cmd == "grep -q 141 README.md"


def test_validator_runs_per_task_command(monkeypatch):
    from nightsweeper.models import Task
    from nightsweeper.validator import PASSED, Validator
    v = Validator({"custom-cmd": "GLOBAL"})           # global custom-cmd would be "GLOBAL"
    seen = {}

    class _R:
        returncode = 0

    monkeypatch.setattr(v, "_run", lambda cmd, wd: seen.update(cmd=cmd) or _R())
    t = Task(id="t", source="tasklist", title="x", body="y", est_complexity="low",
             est_context_tokens=1, validator="custom-cmd", value="high",
             validator_cmd="MY-TASK-CMD")
    assert v.validate(t, "/wd").result == PASSED
    assert seen["cmd"] == "MY-TASK-CMD"               # per-task command, not the global one
