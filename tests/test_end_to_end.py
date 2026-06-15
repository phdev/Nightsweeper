"""End-to-end (U16): ingest → dispatch → executable validate → ledger → report.

Uses the real todo_scan source, the real Validator running a real shell command
in a real temp workdir, the real ledger and report — with a writing stub lane.
Proves the whole loop produces a real pass + ledger row + report, and that AE1
(no backlog → no run) holds.
"""

import tempfile
from pathlib import Path

from conftest import make_config

from nightsweeper import config as cfg
from nightsweeper import report as reportmod
from nightsweeper.adapters.backend import BackendAdapter
from nightsweeper.dispatcher import Dispatcher
from nightsweeper.isolation import Handoff
from nightsweeper.ledger import Ledger
from nightsweeper.models import Capacity, Result
from nightsweeper.sources.todo_scan import TodoScanSource


class DirIsolation:
    """Real temp workdirs so the validator runs a real command; no git needed."""

    def create(self, task):
        d = tempfile.mkdtemp(prefix="ns-e2e-")
        return d

    def handoff(self, task, workdir):
        return Handoff(branch=f"nightsweeper/{task.id}", pushed=False)

    def cleanup(self, task, keep):
        pass


class WritingLocalLane(BackendAdapter):
    name = "local"

    def __init__(self):
        self.cost_rank = 0

    def probe_headroom(self):
        return Capacity(available=True)

    def dispatch(self, task, workdir, context=None):
        Path(workdir, "fixed").write_text("done")  # "fixes" the task
        return Result(ok=True, consumed_usd=0.0)


def _e2e_config(report_path):
    return cfg.parse({
        "caps": {"nightly_task_cap": 20, "nightly_dollar_cap": 5.0},
        "sources": [{"name": "todo_scan", "paths": ["."]}],
        "backends": [
            {"name": "local", "cost_rank": 0,
             "capability": {"validators": ["custom-cmd"], "max_complexity": "high"}},
        ],
        "validators": {"custom-cmd": "test -f fixed"},
        "report": {"path": report_path},
    })


def test_full_loop_pass_and_report(tmp_path):
    # fixture: one ENROLLED marker (dispatched) + one BARE marker (inventory only)
    src_dir = tmp_path / "code"
    src_dir.mkdir()
    (src_dir / "a.py").write_text(
        "# TODO(nightsweeper: validator=custom-cmd value=high) make it pass\n"
        "# TODO just a note\n"
    )
    source = TodoScanSource(cfg.SourceConfig(name="todo_scan", options={"paths": [str(src_dir)]}))
    tasks = source.fetch()
    assert len(tasks) == 1 and source.inventory()["bare_todo_count"] == 1

    report_path = str(tmp_path / "report.md")
    config = _e2e_config(report_path)
    ledger = Ledger(tmp_path / "ledger.db")
    disp = Dispatcher([WritingLocalLane()], DirIsolation(),
                      _validator(config), ledger, config)
    summary = disp.run(tasks)

    assert summary.dispatched == 1 and summary.passed == 1
    rows = ledger.runs_since("2026-06-15T00:00:00")
    assert rows[0]["validation_result"] == "passed" and rows[0]["backend"] == "local"

    text = reportmod.generate(config, ledger, summary, source.inventory(), disp.night_start)
    assert "Passed: **1**" in text
    assert "not dispatched): **1**" in text
    assert Path(report_path).exists()


def test_ae1_no_backlog_no_run(tmp_path):
    report_path = str(tmp_path / "report.md")
    config = _e2e_config(report_path)
    ledger = Ledger(tmp_path / "ledger.db")
    disp = Dispatcher([WritingLocalLane()], DirIsolation(), _validator(config), ledger, config)
    summary = disp.run([])
    text = reportmod.generate(config, ledger, summary, {}, disp.night_start)
    assert "No backlog, no run" in text


def _validator(config):
    from nightsweeper.validator import Validator
    return Validator(config.validators)
