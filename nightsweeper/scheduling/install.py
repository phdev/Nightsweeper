"""Render the launchd LaunchAgent + caffeinate wrapper (U15).

Writes ``run.sh`` into the repo's ``.nightsweeper/`` dir and the LaunchAgent
plist into ``~/Library/LaunchAgents``. Does NOT load it or touch ``pmset`` (that
needs the operator + sudo) — it prints the exact commands instead. ``RunAtLoad``
is false and ``KeepAlive`` is unset so the job fires only on its nightly schedule.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

LABEL = "com.nightsweeper.run"
_DIR = Path(__file__).resolve().parent


def _render(template_name: str, **kw) -> str:
    return (_DIR / template_name).read_text().format(**kw)


def _git_root() -> str:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    return out.stdout.strip()


def install(config, *, agents_dir=None, repo=None, python=None,
            config_path="nightsweeper.config.yaml") -> int:
    repo = repo or _git_root()
    python = python or sys.executable
    agents_dir = Path(agents_dir or (Path.home() / "Library" / "LaunchAgents"))
    agents_dir.mkdir(parents=True, exist_ok=True)
    logs = Path.home() / "Library" / "Logs" / "nightsweeper"
    logs.mkdir(parents=True, exist_ok=True)

    state = Path(repo) / ".nightsweeper"
    state.mkdir(parents=True, exist_ok=True)
    run_sh = state / "run.sh"
    run_sh.write_text(_render("run.sh.template", repo=repo, python=python, config=config_path))
    os.chmod(run_sh, 0o755)

    plist_path = agents_dir / f"{LABEL}.plist"
    plist_path.write_text(_render(
        "com.nightsweeper.run.plist.template",
        label=LABEL, run_sh=str(run_sh),
        hour=config.schedule.hour, minute=config.schedule.minute,
        stdout=str(logs / "run.log"), stderr=str(logs / "run.err"),
    ))

    h, m = config.schedule.hour, config.schedule.minute
    wake_h, wake_m = (h, m - 1) if m > 0 else ((h - 1) % 24, 59)
    print(f"Wrote {run_sh}")
    print(f"Wrote {plist_path}")
    print("\nNext steps (run yourself):")
    print(f"  launchctl load {plist_path}")
    print(f"  sudo pmset repeat wakeorpoweron MTWRFSU {wake_h:02d}:{wake_m:02d}:00   "
          "# guarantee the Mac is awake a minute before the run")
    return 0
