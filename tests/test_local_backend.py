from nightsweeper.config import BackendConfig, Capability
from nightsweeper.backends.local import LocalBackend
from nightsweeper.models import Task


def _be():
    return LocalBackend(BackendConfig(
        name="local", cost_rank=0,
        capability=Capability(validators=frozenset({"test"}), max_complexity="medium"),
        options={"model": "qwen3-coder:30b"},
    ))


def _task():
    return Task(id="t", source="todo_scan", title="x", body="y", est_complexity="low",
                est_context_tokens=50, validator="test", value="high")


def test_probe_up(monkeypatch):
    be = _be()
    monkeypatch.setattr(be, "_ollama_up", lambda: True)
    cap = be.probe_headroom()
    assert cap.available is True and cap.unit == "unbounded" and cap.dollars_remaining is None


def test_probe_down_when_ollama_unreachable(monkeypatch):
    be = _be()
    monkeypatch.setattr(be, "_ollama_up", lambda: False)
    assert be.probe_headroom().available is False  # lane skipped, not crashed


def test_dispatch_success_is_free(monkeypatch):
    be = _be()
    monkeypatch.setattr(be, "_run_agent", lambda task, wd: (True, '{"edited": true}', None))
    r = be.dispatch(_task(), "/tmp/wd")
    assert r.ok is True and r.consumed_usd == 0.0


def test_dispatch_loop_failure_escalatable(monkeypatch):
    be = _be()
    monkeypatch.setattr(be, "_run_agent", lambda task, wd: (False, None, "tool-call loop"))
    r = be.dispatch(_task(), "/tmp/wd")
    assert r.ok is False and "loop" in r.error


def test_run_agent_points_openclaw_at_remote_ollama(monkeypatch):
    import nightsweeper.backends.local as localmod
    be = LocalBackend(BackendConfig(
        name="local", cost_rank=0,
        capability=Capability(validators=frozenset({"test"}), max_complexity="medium"),
        options={"model": "qwen2.5-coder:7b", "ollama_host": "http://192.168.1.54:11434"}))

    captured = {}

    class _R:
        returncode, stdout, stderr = 0, "{}", ""

    def fake_run(cmd, **kw):
        captured.update(kw)
        return _R()

    monkeypatch.setattr(localmod.subprocess, "run", fake_run)
    ok, _, _ = be._run_agent(_task(), "/wd")
    assert ok is True
    assert captured["env"]["OLLAMA_HOST"] == "http://192.168.1.54:11434"  # remote Ollama
    assert captured["cwd"] == "/wd"  # dispatcher will escalate
