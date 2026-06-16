"""V2 tests: codex lane, linear source, gbrain enricher, preflight."""

import pytest
from conftest import Clock, FakeIsolation, FakeValidator, make_config, task

from nightsweeper import config as cfg
from nightsweeper import registry
from nightsweeper.adapters.backend import BackendAdapter
from nightsweeper.backends.codex import CodexBackend
from nightsweeper.config import BackendConfig, Capability, SourceConfig
from nightsweeper.dispatcher import Dispatcher
from nightsweeper.enrichers.gbrain import GbrainEnricher
from nightsweeper.ledger import Ledger
from nightsweeper.models import Capacity, CostRange, Result
from nightsweeper.preflight import CostModel, estimate_usd
from nightsweeper.sources.linear import LinearSource


def _bcfg(name, cost_rank=1, **opts):
    return BackendConfig(name=name, cost_rank=cost_rank,
                         capability=Capability(validators=frozenset({"test"}), max_complexity="high"),
                         options=opts)


class PassValidator:
    def validate(self, task, workdir):
        from nightsweeper.validator import PASSED, ValidationResult
        return ValidationResult(PASSED, "")


# --- Codex lane (S4) ---

def test_codex_probe_reads_rate_limits(monkeypatch):
    be = CodexBackend(_bcfg("codex", max_used_percent=95))
    monkeypatch.setattr(be, "_read_rate_limits",
                        lambda: {"primary": {"used_percent": 7.0}, "secondary": {"used_percent": 19.0}})
    assert be.probe_headroom().available is True


def test_codex_probe_unavailable_when_window_high(monkeypatch):
    be = CodexBackend(_bcfg("codex", max_used_percent=95))
    monkeypatch.setattr(be, "_read_rate_limits",
                        lambda: {"primary": {"used_percent": 98.0}, "secondary": {"used_percent": 19.0}})
    assert be.probe_headroom().available is False


def test_codex_probe_optimistic_when_no_rollout(monkeypatch):
    be = CodexBackend(_bcfg("codex"))
    monkeypatch.setattr(be, "_read_rate_limits", lambda: None)
    assert be.probe_headroom().available is True  # infer-from-errors fallback


def test_codex_dispatch_rate_limited(monkeypatch):
    be = CodexBackend(_bcfg("codex"))
    monkeypatch.setattr(be, "_run_codex", lambda task, wd: (1, "", "Error: rate limit exceeded"))
    r = be.dispatch(task("t"), "/wd")
    assert r.ok is False and "rate-limited" in r.error


def test_codex_is_zero_marginal():
    be = CodexBackend(_bcfg("codex"))
    assert be.estimate(task("t")) == CostRange(0.0, 0.0)


def test_codex_run_can_edit_headlessly(monkeypatch):
    import nightsweeper.backends.codex as cmod
    be = CodexBackend(_bcfg("codex"))  # default sandbox_mode == 'workspace-write'
    captured = {}

    class _R:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(cmod.subprocess, "run", lambda cmd, **kw: captured.update(cmd=cmd) or _R())
    be._run_codex(task("t"), "/wd")
    assert "--sandbox" in captured["cmd"] and "workspace-write" in captured["cmd"]  # else read-only
    assert "--skip-git-repo-check" in captured["cmd"]


# --- Linear source ---

def test_linear_maps_priority_and_coerces(monkeypatch):
    s = LinearSource(SourceConfig(name="linear", options={"default_value": "med", "default_validator": "test"}))
    monkeypatch.setattr(s, "_fetch_raw_issues", lambda: [
        {"identifier": "ENG-1", "title": "urgent", "description": "x", "priority": 1,
         "labels": {"nodes": [{"name": "validator:bogus"}]}},
        {"identifier": "ENG-2", "title": "low", "description": "y", "priority": 4, "labels": {"nodes": []}},
    ])
    tasks = s.fetch()
    assert tasks[0].id == "linear:ENG-1" and tasks[0].value == "high"
    assert tasks[0].validator == "test"          # bogus label coerced
    assert tasks[1].value == "low" and tasks[1].source == "linear"


# --- Gbrain enricher (S5) ---

def test_gbrain_enricher_noop_without_mcp():
    assert GbrainEnricher().enrich(task("t")) is None  # graceful no-op, never invents work


def test_gbrain_enricher_returns_context_when_wired():
    e = GbrainEnricher()
    e._retrieve = lambda t: "relevant memory"
    assert e.enrich(task("t")) == "relevant memory"


# --- Preflight estimate ---

def test_estimate_usd_math():
    cm = CostModel(input_per_mtok=3.0, output_per_mtok=15.0, expected_output_tokens=1500)
    est = estimate_usd(1_000_000, cm)
    assert abs(est.lo - 3.0225) < 1e-6 and est.hi == round(est.lo * 2.5, 4)


def test_estimate_none_without_cost_model():
    assert estimate_usd(1000, None) is None


# --- Preflight gate vs advisory in the dispatcher ---

class PricedLane(BackendAdapter):
    name = "local"

    def __init__(self, est, state=None):
        self.cost_rank = 0
        self._est = est
        self.seen_context = None

    def probe_headroom(self):
        return Capacity(available=True)

    def dispatch(self, task, workdir, context=None):
        self.seen_context = context
        return Result(ok=True, consumed_usd=0.0)

    def estimate(self, task):
        return self._est


def _cfg(mode, per_task_cap=0.5):
    return cfg.parse({
        "caps": {"nightly_task_cap": 10, "nightly_dollar_cap": 10.0, "per_task_cap": per_task_cap},
        "sources": [{"name": "todo_scan"}],
        "backends": [{"name": "local", "cost_rank": 0,
                      "capability": {"validators": ["test"], "max_complexity": "high"}}],
        "preflight": {"mode": mode},
    })


def test_preflight_gate_skips_over_cap_task(tmp_path):
    led = Ledger(tmp_path / "l.db")
    lane = PricedLane(CostRange(lo=1.0, hi=2.0))  # > 0.5 cap
    with pytest.warns(UserWarning):
        c = _cfg("gate")
    disp = Dispatcher([lane], FakeIsolation(), PassValidator(), led, c, clock=Clock())
    s = disp.run([task("t")])
    rows = led.runs_since("2026-06-15T00:00:00")
    assert rows[0]["validation_result"] == "skipped" and rows[0]["park_reason"] == "over-per-task-cap"
    assert s.dispatched == 0 and lane.seen_context is None  # never dispatched


def test_preflight_advisory_does_not_skip(tmp_path):
    led = Ledger(tmp_path / "l.db")
    lane = PricedLane(CostRange(lo=1.0, hi=2.0))
    with pytest.warns(UserWarning):
        c = _cfg("advisory")
    disp = Dispatcher([lane], FakeIsolation(), PassValidator(), led, c, clock=Clock())
    s = disp.run([task("t")])
    rows = led.runs_since("2026-06-15T00:00:00")
    assert s.dispatched == 1                                  # advisory dispatches anyway
    assert rows[0]["predicted_lo"] == 1.0 and rows[0]["predicted_hi"] == 2.0  # recorded


# --- Enricher context threaded through dispatch ---

class FixedEnricher:
    def enrich(self, task):
        return "CTX"


def test_enricher_context_passed_to_dispatch(tmp_path):
    led = Ledger(tmp_path / "l.db")
    lane = PricedLane(None)
    disp = Dispatcher([lane], FakeIsolation(), PassValidator(), led,
                      _cfg_no_cap("advisory"), enricher=FixedEnricher(), clock=Clock())
    disp.run([task("t")])
    assert lane.seen_context == "CTX"


def _cfg_no_cap(mode):
    return cfg.parse({
        "caps": {"nightly_task_cap": 10, "nightly_dollar_cap": 10.0},
        "sources": [{"name": "todo_scan"}],
        "backends": [{"name": "local", "cost_rank": 0,
                      "capability": {"validators": ["test"], "max_complexity": "high"}}],
        "preflight": {"mode": mode},
    })


# --- registry wiring ---

def test_v2_adapters_registered():
    registry.register_builtins()
    assert "codex" in registry.BACKENDS
    assert "linear" in registry.SOURCES
    assert "gbrain" in registry.ENRICHERS


def test_report_renders_preflight_accuracy(tmp_path):
    from nightsweeper import report as reportmod
    from nightsweeper.dispatcher import NightSummary
    from nightsweeper.models import RunRow
    led = Ledger(tmp_path / "r.db")
    led.record(RunRow(task_id="a", source="s", backend="claude", consumed=0.3,
                      validation_result="passed", passed=True, escalated=False, branch="b",
                      ts="2026-06-15T03:05:00", predicted_lo=0.1, predicted_hi=0.5))  # bracketed
    led.record(RunRow(task_id="b", source="s", backend="claude", consumed=0.4,
                      validation_result="failed", passed=False, escalated=False, branch=None,
                      ts="2026-06-15T03:06:00", predicted_lo=0.1, predicted_hi=0.2))  # missed
    text = reportmod.generate(make_config(), led,
                              NightSummary("backlog-drained", 2, 2, 1, 1, 0), {}, "2026-06-15T03:00:00")
    assert "Preflight accuracy (V2)" in text and "1/2" in text
