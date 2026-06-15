"""Nightsweeper CLI (U15/U16).

Commands: ``run`` (the nightly loop), ``probe`` (preview per-lane headroom),
``report`` (print the latest report), ``install-scheduler`` (render the launchd
LaunchAgent).

Single-instance is enforced here with an ``fcntl`` advisory lock — portable
across macOS (no ``flock`` binary) and Linux. A sentinel ``last_run_date`` plus
``run --if-missed`` gives the scheduler self-heal without double-running.
"""

from __future__ import annotations

import argparse
import fcntl
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from . import config as configmod
from . import registry
from . import report as reportmod
from .dispatcher import Dispatcher
from .isolation import WorktreeManager
from .ledger import Ledger
from .validator import Validator


def _git_root() -> str:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit("nightsweeper: not inside a git repository")
    return out.stdout.strip()


def _repo_slug() -> str | None:
    out = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner",
                          "-q", ".nameWithOwner"], capture_output=True, text=True)
    return out.stdout.strip() or None if out.returncode == 0 else None


def _state_dir(root: str) -> Path:
    d = Path(root) / ".nightsweeper"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _night_start() -> str:
    n = datetime.now()
    return n.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def cmd_run(args) -> int:
    cfg = configmod.load(args.config)
    root = _git_root()
    sd = _state_dir(root)
    sentinel = sd / "last_run_date"
    today = date.today().isoformat()
    if args.if_missed and sentinel.exists() and sentinel.read_text().strip() == today:
        print("nightsweeper: already ran today — skipping (self-heal no-op)")
        return 0

    lock_fh = open(sd / "run.lock", "w")
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("nightsweeper: another run is in progress — exiting")
        return 0
    try:
        registry.register_builtins()
        sources = registry.build_sources(cfg)
        backends = registry.build_backends(cfg)
        ledger = Ledger(args.db or (sd / "ledger.db"))

        tasks, inventory = [], {}
        for s in sources:
            try:
                fetched = s.fetch()
            except Exception as e:  # one broken source must not crash the night
                print(f"nightsweeper: source '{s.name}' failed: {e}", file=sys.stderr)
                fetched = []
            tasks.extend(fetched)
            for k, v in s.inventory().items():
                inventory[k] = inventory.get(k, 0) + v

        # ledger dedupe: never re-queue a task that already has a run row
        tasks = [t for t in tasks if not ledger.has_run(t.id)]

        iso = WorktreeManager(root, cfg.isolation, repo_slug=_repo_slug())
        validator = Validator(cfg.validators)
        disp = Dispatcher(backends, iso, validator, ledger, cfg)
        summary = disp.run(tasks)
        text = reportmod.generate(cfg, ledger, summary, inventory, disp.night_start)
        sentinel.write_text(today)
        if args.print:
            print(text)
        else:
            print(f"nightsweeper: {summary.dispatched} dispatched, {summary.passed} passed, "
                  f"{summary.parked} parked; stop={summary.stop_reason}; "
                  f"report → {cfg.report.path}")
        return 0
    finally:
        fcntl.flock(lock_fh, fcntl.LOCK_UN)
        lock_fh.close()


def cmd_probe(args) -> int:
    cfg = configmod.load(args.config)
    root = _git_root()
    registry.register_builtins()
    backends = registry.build_backends(cfg)
    ledger = Ledger(args.db or (_state_dir(root) / "ledger.db"))
    ns = _night_start()
    print("Lane headroom (preview):")
    for b in sorted(backends, key=lambda x: x.cost_rank):
        b.bind_runtime(ledger, ns)
        cap = b.probe_headroom()
        rem = "unbounded ($0)" if cap.unit == "unbounded" else f"${cap.dollars_remaining:.2f}"
        print(f"  {b.name:8} cost_rank={b.cost_rank}  available={cap.available}  remaining={rem}")
    return 0


def cmd_report(args) -> int:
    cfg = configmod.load(args.config)
    p = Path(cfg.report.path)
    if not p.exists():
        print("nightsweeper: no report yet — run `nightsweeper run` first")
        return 1
    print(p.read_text())
    return 0


def cmd_install_scheduler(args) -> int:
    from .scheduling.install import install
    return install(configmod.load(args.config))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nightsweeper", description=__doc__)
    ap.add_argument("--config", default="nightsweeper.config.yaml")
    ap.add_argument("--db", default=None, help="override ledger path")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run the nightly loop")
    r.add_argument("--if-missed", action="store_true",
                   help="only run if today's run hasn't happened (scheduler self-heal)")
    r.add_argument("--print", action="store_true", help="print the report to stdout")
    r.set_defaults(func=cmd_run)

    sub.add_parser("probe", help="preview per-lane headroom").set_defaults(func=cmd_probe)
    sub.add_parser("report", help="print the latest morning report").set_defaults(func=cmd_report)
    sub.add_parser("install-scheduler", help="render the launchd LaunchAgent").set_defaults(
        func=cmd_install_scheduler)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
