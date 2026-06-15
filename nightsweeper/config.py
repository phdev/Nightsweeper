"""Load and validate ``nightsweeper.config.yaml``.

A single config file defines backlog sources, backend lanes + caps, the nightly
task/$ caps, the per-task cap, validators, the lane capability matrix, isolation,
and report thresholds (origin R21). Validation never silently defaults a cap to
unlimited, and it warns that ``per_task_cap`` is inert in V1 (enforced in V2).
"""

from __future__ import annotations

import dataclasses
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from .models import COMPLEXITIES, VALIDATORS


class ConfigError(ValueError):
    """Raised on a malformed or incomplete config."""


@dataclass
class Capability:
    validators: frozenset
    max_complexity: str

    def allows(self, validator: str, complexity: str) -> bool:
        from .models import complexity_rank

        return (
            validator in self.validators
            and complexity_rank(complexity) <= complexity_rank(self.max_complexity)
        )


@dataclass
class BackendConfig:
    name: str
    cost_rank: int
    capability: Capability
    options: dict = field(default_factory=dict)


@dataclass
class SourceConfig:
    name: str
    options: dict = field(default_factory=dict)


@dataclass
class Caps:
    nightly_task_cap: int
    nightly_dollar_cap: float
    per_task_cap: Optional[float] = None


@dataclass
class Isolation:
    worktree_dir: str = ".nightsweeper/worktrees"
    pr_opt_in: bool = False
    branch_prefix: str = "nightsweeper/"
    label_prefix: str = "nightsweeper:"
    base_ref: str = "origin/HEAD"


@dataclass
class Downgrade:
    window_nights: int = 7
    spend_pct_threshold: float = 0.10
    min_passes: int = 1


@dataclass
class ReportConfig:
    path: str = "nightsweeper-report.md"
    downgrade: Downgrade = field(default_factory=Downgrade)


@dataclass
class Schedule:
    hour: int = 3
    minute: int = 0


@dataclass
class Config:
    sources: list
    backends: list
    caps: Caps
    validators: dict
    isolation: Isolation
    report: ReportConfig
    schedule: Schedule

    def backend(self, name: str) -> BackendConfig:
        for b in self.backends:
            if b.name == name:
                return b
        raise KeyError(name)


def _require(d: dict, key: str, ctx: str) -> Any:
    if key not in d or d[key] is None:
        raise ConfigError(f"{ctx}: missing required key '{key}'")
    return d[key]


def _construct(cls, raw: dict, ctx: str):
    """Build a dataclass from a YAML mapping, rejecting unknown keys with a clear error."""
    allowed = {f.name for f in dataclasses.fields(cls)}
    unknown = set(raw) - allowed
    if unknown:
        raise ConfigError(f"{ctx}: unknown key(s) {sorted(unknown)}; allowed {sorted(allowed)}")
    return cls(**raw)


def _parse_capability(raw: dict, ctx: str) -> Capability:
    vals = raw.get("validators", sorted(VALIDATORS))
    bad = set(vals) - VALIDATORS
    if bad:
        raise ConfigError(f"{ctx}: unknown validator type(s) {sorted(bad)}")
    max_complexity = raw.get("max_complexity", "high")
    if max_complexity not in COMPLEXITIES:
        raise ConfigError(
            f"{ctx}: max_complexity {max_complexity!r} not in {sorted(COMPLEXITIES)}"
        )
    return Capability(validators=frozenset(vals), max_complexity=max_complexity)


def load(path: str | Path) -> Config:
    """Load and validate the config at ``path``."""
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as e:  # pragma: no cover - message passthrough
        raise ConfigError(f"malformed YAML in {p}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{p}: top-level config must be a mapping")
    return parse(raw)


def parse(raw: dict) -> Config:
    """Validate an already-parsed config mapping into a typed ``Config``."""
    # Caps — nightly caps are hard stops and must be present (never default to unlimited).
    caps_raw = _require(raw, "caps", "config")
    caps = Caps(
        nightly_task_cap=int(_require(caps_raw, "nightly_task_cap", "caps")),
        nightly_dollar_cap=float(_require(caps_raw, "nightly_dollar_cap", "caps")),
        per_task_cap=(
            float(caps_raw["per_task_cap"])
            if caps_raw.get("per_task_cap") is not None
            else None
        ),
    )
    if caps.nightly_task_cap <= 0 or caps.nightly_dollar_cap < 0:
        raise ConfigError("caps: nightly_task_cap must be > 0 and nightly_dollar_cap >= 0")
    if caps.per_task_cap is not None:
        warnings.warn(
            "caps.per_task_cap is accepted but INERT in V1 (no preflight estimate); "
            "it is enforced only in V2.",
            stacklevel=2,
        )

    # Sources
    sources = []
    for s in _require(raw, "sources", "config"):
        name = _require(s, "name", "source")
        opts = {k: v for k, v in s.items() if k != "name"}
        sources.append(SourceConfig(name=name, options=opts))
    if not sources:
        raise ConfigError("config: at least one source is required")
    if len({s.name for s in sources}) != len(sources):
        raise ConfigError("sources: names must be unique")

    # Backends + capability matrix
    backends = []
    for b in _require(raw, "backends", "config"):
        name = _require(b, "name", "backend")
        ctx = f"backend '{name}'"
        cost_rank = int(_require(b, "cost_rank", ctx))
        capability = _parse_capability(b.get("capability", {}), ctx + ".capability")
        opts = {k: v for k, v in b.items() if k not in ("name", "cost_rank", "capability")}
        backends.append(
            BackendConfig(name=name, cost_rank=cost_rank, capability=capability, options=opts)
        )
    if not backends:
        raise ConfigError("config: at least one backend is required")
    ranks = [b.cost_rank for b in backends]
    if len(set(ranks)) != len(ranks):
        raise ConfigError("backends: cost_rank values must be unique (defines lane ordering)")
    if len({b.name for b in backends}) != len(backends):
        raise ConfigError("backends: names must be unique")

    validators = dict(raw.get("validators", {}))
    isolation = _construct(Isolation, raw.get("isolation", {}), "isolation")
    report_raw = dict(raw.get("report", {}))
    downgrade = _construct(Downgrade, report_raw.pop("downgrade", {}), "report.downgrade")
    report = _construct(ReportConfig, {**report_raw, "downgrade": downgrade}, "report")
    schedule = _construct(Schedule, raw.get("schedule", {}), "schedule")

    return Config(
        sources=sources,
        backends=backends,
        caps=caps,
        validators=validators,
        isolation=isolation,
        report=report,
        schedule=schedule,
    )
