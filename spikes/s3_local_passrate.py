#!/usr/bin/env python3
"""Spike S3 — local lane pass rate, bucketed by complexity (plan U3).

Resolves: does the local lane clear ENOUGH real tasks to be the default first
lane, and at what complexity? Grounding §3: Qwen3-Coder-30B (~52% SWE-bench-
Verified), gate on EXECUTABLE validation, expect ~half of hard tasks to escalate.
Sets the local lane's `max_complexity` cutoff from the MEASURED per-tier pass
rate (not asserted).

PREREQUISITES (not installed in this environment by default):
  - OpenClaw (`openclaw`) — the local agent harness
  - Ollama serving the model (default qwen3-coder:30b, ~18GB pull)

SAFE BY DEFAULT: prints the plan + a prereq check, exits. Pass --go to run.

    python spikes/s3_local_passrate.py                       # dry + prereq check
    python spikes/s3_local_passrate.py --tasks spike10.json --go

Each task in the JSON: {"id","prompt","complexity":"low|medium|high","validator_cmd","setup_dir"}
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def run_task(t: dict, model: str) -> bool:
    workdir = tempfile.mkdtemp(prefix="s3-")
    if t.get("setup_dir"):
        shutil.copytree(t["setup_dir"], workdir, dirs_exist_ok=True)
    agent = subprocess.run(
        ["openclaw", "infer", "model", "run", "--model", f"ollama/{model}",
         "--prompt", t["prompt"], "--json"],
        capture_output=True, text=True, cwd=workdir, timeout=1800,
    )
    if agent.returncode != 0:
        return False
    check = subprocess.run(t["validator_cmd"], shell=True, cwd=workdir,
                           capture_output=True, text=True, timeout=600)
    return check.returncode == 0  # executable validation only


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", help="path to the 10-task JSON fixture")
    ap.add_argument("--model", default="qwen3-coder:30b")
    ap.add_argument("--go", action="store_true")
    a = ap.parse_args()

    prereqs = {"openclaw": have("openclaw"), "ollama": have("ollama")}
    print("Prereqs:", ", ".join(f"{k}={'ok' if v else 'MISSING'}" for k, v in prereqs.items()))

    if not a.go or not a.tasks:
        print(__doc__)
        if not all(prereqs.values()):
            print("\nInstall the missing prereqs, then re-run with --tasks <file> --go.")
        return 0
    if not all(prereqs.values()):
        print("ABORT: prereqs missing.", file=sys.stderr)
        return 2

    tasks = json.loads(Path(a.tasks).read_text())
    by_tier = defaultdict(lambda: [0, 0])  # tier -> [passes, total]
    for t in tasks:
        ok = run_task(t, a.model)
        by_tier[t["complexity"]][1] += 1
        by_tier[t["complexity"]][0] += int(ok)
        print(f"  {t['id']:20} {t['complexity']:7} -> {'PASS' if ok else 'fail'}")

    total_p = sum(v[0] for v in by_tier.values())
    total_n = sum(v[1] for v in by_tier.values())
    print(f"\nAggregate pass rate: {total_p}/{total_n} = {100*total_p/max(1,total_n):.0f}%")
    for tier in ("low", "medium", "high"):
        p, n = by_tier.get(tier, [0, 0])
        if n:
            print(f"  {tier:7}: {p}/{n} = {100*p/n:.0f}%")
    print("\nSet local.capability.max_complexity to the highest tier whose pass rate clears your "
          "bar, and record it in docs/research/2026-06-15-grounding.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
