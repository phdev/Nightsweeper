import pytest

from nightsweeper.models import (
    Capacity,
    Task,
    complexity_rank,
    value_rank,
)


def _task(**kw):
    base = dict(
        id="t1", source="github_issues", title="x", body="y",
        est_complexity="medium", est_context_tokens=1000,
        validator="test", value="high",
    )
    base.update(kw)
    return Task(**base)


def test_task_has_all_eight_fields():
    t = _task()
    assert set(vars(t)) == {
        "id", "source", "title", "body",
        "est_complexity", "est_context_tokens", "validator", "value",
    }


def test_task_rejects_bad_validator():
    with pytest.raises(ValueError):
        _task(validator="lint")


def test_task_rejects_bad_value():
    with pytest.raises(ValueError):
        _task(value="medium")  # value uses high|med|low, not 'medium'


def test_task_rejects_bad_complexity():
    with pytest.raises(ValueError):
        _task(est_complexity="med")  # complexity uses low|medium|high


def test_task_allows_none_context_tokens():
    assert _task(est_context_tokens=None).est_context_tokens is None


def test_value_ordering_high_first():
    assert value_rank("high") < value_rank("med") < value_rank("low")


def test_complexity_ordering():
    assert complexity_rank("low") < complexity_rank("medium") < complexity_rank("high")


def test_capacity_unit_validation():
    Capacity(available=True, unit="unbounded")
    Capacity(available=True, dollars_remaining=3.0, unit="usd")
    with pytest.raises(ValueError):
        Capacity(available=True, unit="euros")
