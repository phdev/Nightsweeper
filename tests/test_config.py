import warnings
from pathlib import Path

import pytest

from nightsweeper import config as cfg

EXAMPLE = Path(__file__).resolve().parents[1] / "nightsweeper.config.example.yaml"


def _minimal():
    return {
        "caps": {"nightly_task_cap": 20, "nightly_dollar_cap": 5.0},
        "sources": [{"name": "todo_scan", "paths": ["."]}],
        "backends": [
            {"name": "local", "cost_rank": 0,
             "capability": {"validators": ["test"], "max_complexity": "medium"}},
        ],
    }


def test_example_config_loads():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        c = cfg.load(EXAMPLE)
    assert c.caps.nightly_task_cap == 20
    assert c.caps.nightly_dollar_cap == 5.0
    assert c.backend("local").cost_rank == 0
    assert c.backend("claude").options["nightly_budget"] == 3.0
    assert c.isolation.pr_opt_in is False


def test_missing_nightly_dollar_cap_raises_not_unlimited():
    raw = _minimal()
    del raw["caps"]["nightly_dollar_cap"]
    with pytest.raises(cfg.ConfigError):
        cfg.parse(raw)


def test_per_task_cap_warns_inert_in_v1():
    raw = _minimal()
    raw["caps"]["per_task_cap"] = 1.0
    with pytest.warns(UserWarning, match="INERT in V1"):
        cfg.parse(raw)


def test_unknown_validator_type_raises():
    raw = _minimal()
    raw["backends"][0]["capability"]["validators"] = ["test", "lint"]
    with pytest.raises(cfg.ConfigError):
        cfg.parse(raw)


def test_duplicate_cost_rank_raises():
    raw = _minimal()
    raw["backends"].append(
        {"name": "claude", "cost_rank": 0,
         "capability": {"validators": ["test"], "max_complexity": "high"}}
    )
    with pytest.raises(cfg.ConfigError):
        cfg.parse(raw)


def test_capability_allows():
    c = cfg.parse(_minimal())
    cap = c.backend("local").capability
    assert cap.allows("test", "low") is True
    assert cap.allows("test", "high") is False       # exceeds max_complexity medium
    assert cap.allows("none", "low") is False         # validator type not allowed
