"""U6 seam proof: a stub 'v2' backend that uses BOTH dormant hooks (estimate +
context) registers and runs without touching the ABC or the dispatcher."""

import pytest

from nightsweeper import config as cfg
from nightsweeper import registry
from nightsweeper.adapters.backend import BackendAdapter
from nightsweeper.adapters.backlog import BacklogSource
from nightsweeper.models import Capacity, CostRange, Result, Task


def _config_with(backend_name, source_name):
    return cfg.parse({
        "caps": {"nightly_task_cap": 5, "nightly_dollar_cap": 1.0},
        "sources": [{"name": source_name, "paths": ["."]}],
        "backends": [
            {"name": backend_name, "cost_rank": 0,
             "capability": {"validators": ["test"], "max_complexity": "high"}},
        ],
    })


def test_build_registered_adapters():
    @registry.register_backend("fake_be")
    class FakeBackend(BackendAdapter):
        def __init__(self, c):
            self.cost_rank = c.cost_rank

        def probe_headroom(self):
            return Capacity(available=True)

        def dispatch(self, task, workdir, context=None):
            return Result(ok=True)

    @registry.register_source("fake_src")
    class FakeSource(BacklogSource):
        def __init__(self, c):
            self.c = c

        def fetch(self):
            return []

    c = _config_with("fake_be", "fake_src")
    backends = registry.build_backends(c)
    sources = registry.build_sources(c)
    assert backends[0].name == "fake_be" and backends[0].cost_rank == 0
    assert sources[0].name == "fake_src"


def test_v2_stub_uses_both_dormant_hooks_without_core_change():
    @registry.register_backend("v2_stub")
    class V2Backend(BackendAdapter):
        def __init__(self, c):
            self.cost_rank = c.cost_rank

        def probe_headroom(self):
            return Capacity(available=True, dollars_remaining=5.0, unit="usd")

        def dispatch(self, task, workdir, context=None):
            # reads the dormant context seam
            return Result(ok=True, raw=f"ctx={context}")

        def estimate(self, task):  # activates the dormant preflight seam
            return CostRange(lo=0.1, hi=0.5)

    c = _config_with("v2_stub", "fake_src")
    be = registry.build_backends(c)[0]
    t = Task(id="t", source="s", title="x", body="y", est_complexity="low",
             est_context_tokens=100, validator="test", value="high")
    est = be.estimate(t)
    assert isinstance(est, CostRange) and est.lo == 0.1
    assert be.dispatch(t, "/tmp", context="enriched").raw == "ctx=enriched"


def test_unknown_backend_name_raises():
    c = _config_with("does_not_exist", "fake_src")
    with pytest.raises(registry.RegistryError):
        registry.build_backends(c)
