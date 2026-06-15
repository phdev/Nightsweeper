from conftest import make_config

from nightsweeper import report
from nightsweeper.dispatcher import NightSummary
from nightsweeper.ledger import Ledger
from nightsweeper.models import RunRow

NS = "2026-06-15T03:00:00"


def _led(tmp_path):
    return Ledger(tmp_path / "r.db")


def _row(**kw):
    base = dict(task_id="t1", source="todo_scan", backend="local", consumed=0.0,
                validation_result="passed", passed=True, escalated=False,
                branch="nightsweeper/t1", ts="2026-06-15T03:05:00")
    base.update(kw)
    return RunRow(**base)


def test_ae1_no_run_report(tmp_path):
    led = _led(tmp_path)
    s = NightSummary("backlog-drained", 0, 0, 0, 0, 0)
    text = report.generate(make_config(), led, s, {}, NS)
    assert "No backlog, no run" in text


def test_mixed_night_sections_and_always_on_utilization(tmp_path):
    led = _led(tmp_path)
    led.record(_row())                                   # local pass
    led.record(_row(task_id="t2", backend="claude", consumed=0.40,
                    branch="nightsweeper/t2", ts="2026-06-15T03:06:00"))
    s = NightSummary("backlog-drained", 2, 2, 2, 0, 0)
    text = report.generate(make_config(), led, s, {"bare_todo_count": 3}, NS)
    assert "Per-lane consumption" in text
    assert "$0.40" in text                               # claude spend printed
    assert "passes/$" in text                            # passes-per-dollar always shown
    assert "Bare (un-enrolled) TODO/FIXME markers (not dispatched): **3**" in text


def test_ae6_underused_paid_lane_recommends_downgrade(tmp_path):
    led = _led(tmp_path)
    # claude paid lane: this week almost no spend, zero passes → recommend downgrade
    led.record(_row(task_id="t2", backend="claude", consumed=0.05, passed=False,
                    validation_result="failed", branch=None, ts="2026-06-15T03:06:00"))
    s = NightSummary("backlog-drained", 1, 1, 0, 1, 0)
    text = report.generate(make_config(), led, s, {}, NS)
    assert "Recommend downgrading `claude`" in text


def test_well_used_lane_not_recommended(tmp_path):
    led = _led(tmp_path)
    # heavy spend + passes over the window → no downgrade recommendation
    for i in range(5):
        led.record(_row(task_id=f"t{i}", backend="claude", consumed=2.0, passed=True,
                        ts=f"2026-06-15T03:0{i}:00"))
    s = NightSummary("backlog-drained", 5, 5, 0, 0, 0)
    text = report.generate(make_config(), led, s, {}, NS)
    assert "Recommend downgrading `claude`" not in text
    assert "utilization always reported" in text  # honesty structural either way
