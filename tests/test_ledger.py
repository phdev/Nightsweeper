from nightsweeper.ledger import Ledger
from nightsweeper.models import RunRow


def _row(**kw):
    base = dict(
        task_id="t1", source="github_issues", backend="local", consumed=0.0,
        validation_result="passed", passed=True, escalated=False,
        branch="nightsweeper/t1", ts="2026-06-15T03:01:00",
    )
    base.update(kw)
    return RunRow(**base)


def test_record_and_has_run(tmp_path):
    led = Ledger(tmp_path / "ledger.db")
    assert led.has_run("t1") is False
    led.record(_row())
    assert led.has_run("t1") is True


def test_parked_row_without_branch(tmp_path):
    led = Ledger(tmp_path / "ledger.db")
    led.record(_row(task_id="t2", validation_result="parked", passed=False,
                     branch=None, park_reason="no-escalation-lane"))
    # parked task has a ledger row even with no branch → dedupe still works
    assert led.has_run("t2") is True


def test_predicted_null_roundtrip(tmp_path):
    led = Ledger(tmp_path / "ledger.db")
    led.record(_row())
    rows = led.runs_since("2026-06-15T00:00:00")
    assert rows[0]["predicted_lo"] is None and rows[0]["predicted_hi"] is None


def test_spend_and_lane_summary(tmp_path):
    led = Ledger(tmp_path / "ledger.db")
    led.record(_row(backend="claude", consumed=0.40, ts="2026-06-15T03:02:00"))
    led.record(_row(task_id="t3", backend="claude", consumed=0.60,
                    validation_result="failed", passed=False, escalated=True,
                    ts="2026-06-15T03:03:00"))
    assert led.spend_since("claude", "2026-06-15T00:00:00") == 1.0
    summ = led.lane_summary("2026-06-15T00:00:00")
    assert summ["claude"]["consumed"] == 1.0
    assert summ["claude"]["passes"] == 1
    assert summ["claude"]["attempts"] == 2
