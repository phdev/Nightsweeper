from conftest import (
    Clock,
    FakeIsolation,
    FakeLane,
    FakeValidator,
    make_config,
    task,
)

from nightsweeper.dispatcher import Dispatcher
from nightsweeper.ledger import Ledger


def _disp(tmp_path, state, lanes, verdicts, config=None):
    led = Ledger(tmp_path / "l.db")
    iso = FakeIsolation()
    val = FakeValidator(state, verdicts)
    d = Dispatcher(lanes, iso, val, led, config or make_config(), clock=Clock())
    return d, led, iso


def test_ae1_no_backlog_no_run(tmp_path, state):
    local = FakeLane("local", 0, state)
    d, led, iso = _disp(tmp_path, state, [local], {})
    s = d.run([])
    assert s.tasks_total == 0 and s.dispatched == 0
    assert led.runs_since("2026-06-15T00:00:00") == []


def test_ae2_local_clears_no_escalation(tmp_path, state):
    local = FakeLane("local", 0, state)
    claude = FakeLane("claude", 1, state, unit="usd", dollars=5.0)
    d, led, iso = _disp(tmp_path, state, [local, claude], {("t1", "local"): "pass"})
    s = d.run([task("t1")])
    assert s.passed == 1 and s.dispatched == 1
    rows = led.runs_since("2026-06-15T00:00:00")
    assert len(rows) == 1 and rows[0]["backend"] == "local" and rows[0]["escalated"] == 0
    assert ("handoff", "t1") in iso.events


def test_ae3_local_fails_escalates_to_claude_pass(tmp_path, state):
    local = FakeLane("local", 0, state)
    claude = FakeLane("claude", 1, state, unit="usd", dollars=5.0, consumed=0.40)
    d, led, iso = _disp(tmp_path, state, [local, claude],
                        {("t1", "local"): "fail", ("t1", "claude"): "pass"})
    s = d.run([task("t1")])
    rows = led.runs_since("2026-06-15T00:00:00")
    assert [r["backend"] for r in rows] == ["local", "claude"]
    assert rows[0]["validation_result"] == "failed" and rows[0]["escalated"] == 0
    assert rows[1]["validation_result"] == "passed" and rows[1]["escalated"] == 1
    assert s.passed == 1


def test_ae3_fail_again_parks_no_second_escalation(tmp_path, state):
    local = FakeLane("local", 0, state)
    claude = FakeLane("claude", 1, state, unit="usd", dollars=5.0)
    d, led, iso = _disp(tmp_path, state, [local, claude],
                        {("t1", "local"): "fail", ("t1", "claude"): "fail"})
    s = d.run([task("t1")])
    rows = led.runs_since("2026-06-15T00:00:00")
    assert len(rows) == 2  # one escalation only
    assert rows[1]["park_reason"] == "escalation-exhausted"
    assert s.parked == 1
    assert ("cleanup", "t1", True) in iso.events  # parked worktree preserved


def test_no_escalation_lane_parks_not_crash(tmp_path, state):
    # local fails; claude is gated out (task complexity high > local? no — claude allows high).
    # Make claude unavailable so there is no untried eligible lane after local fails.
    local = FakeLane("local", 0, state)
    claude = FakeLane("claude", 1, state, available=False, unit="usd", dollars=0.0)
    d, led, iso = _disp(tmp_path, state, [local, claude], {("t1", "local"): "fail"})
    s = d.run([task("t1", complexity="medium")])
    rows = led.runs_since("2026-06-15T00:00:00")
    assert rows[-1]["park_reason"] == "no-escalation-lane" and s.parked == 1


def test_validator_none_parks_without_dispatch(tmp_path, state):
    local = FakeLane("local", 0, state)
    d, led, iso = _disp(tmp_path, state, [local], {})
    s = d.run([task("t1", validator="none")])
    rows = led.runs_since("2026-06-15T00:00:00")
    assert rows[0]["backend"] == "(none)" and rows[0]["park_reason"] == "validator-none"
    assert ("create", "t1") not in iso.events  # never dispatched
    assert s.parked == 1


def test_ae4_no_eligible_lane_parks_while_night_continues(tmp_path, state):
    # t_high: local gated out (max medium < high) + claude unavailable (budget out) → parks.
    # t_low: runnable on local, so the night CONTINUES (not an early-stop).
    local = FakeLane("local", 0, state)
    claude = FakeLane("claude", 1, state, available=False, unit="usd", dollars=0.0)
    cfg = make_config(local_max="medium")
    d, led, iso = _disp(tmp_path, state, [local, claude], {}, config=cfg)
    s = d.run([task("t_high", complexity="high"), task("t_low", complexity="medium")])
    rows = {r["task_id"]: r for r in led.runs_since("2026-06-15T00:00:00")}
    assert rows["t_high"]["park_reason"] == "no-eligible-lane-headroom"
    assert ("create", "t_high") not in iso.events
    assert rows["t_low"]["validation_result"] == "passed"  # night continued


def test_ae7_task_cap_stops_with_backlog_intact(tmp_path, state):
    local = FakeLane("local", 0, state)
    d, led, iso = _disp(tmp_path, state, [local], {}, config=make_config(task_cap=1))
    s = d.run([task("t1"), task("t2")])
    assert s.dispatched == 1 and s.stop_reason == "nightly-task-cap"
    assert s.backlog_remaining >= 1


def test_ae7_dollar_cap_stops(tmp_path, state):
    # local unavailable → claude picked; claude consumes 0.6; cap 0.5 → stop before task 2.
    local = FakeLane("local", 0, state, available=False)
    claude = FakeLane("claude", 1, state, unit="usd", dollars=5.0, consumed=0.6)
    cfg = make_config(dollar_cap=0.5)
    d, led, iso = _disp(tmp_path, state, [local, claude],
                        {("t1", "claude"): "pass", ("t2", "claude"): "pass"}, config=cfg)
    s = d.run([task("t1"), task("t2")])
    assert s.dispatched == 1 and s.stop_reason == "nightly-dollar-cap"


def test_value_order_high_before_low(tmp_path, state):
    local = FakeLane("local", 0, state)
    d, led, iso = _disp(tmp_path, state, [local],
                        {("hi", "local"): "pass", ("lo", "local"): "pass"})
    d.run([task("lo", value="low"), task("hi", value="high")])
    creates = [e[1] for e in iso.events if e[0] == "create"]
    assert creates.index("hi") < creates.index("lo")  # high dispatched first
