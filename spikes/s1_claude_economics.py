#!/usr/bin/env python3
"""Spike S1 — Claude headless economics + routing verification (plan U1).

Resolves: does the June 15 2026 headless billing change make the Claude lane
uneconomical overnight? Grounding §1: `claude -p` bills a separate, capped
monthly credit; a set ANTHROPIC_API_KEY bills uncapped (~$1,800/2 days, #37686);
#43333 can mis-route even under OAuth.

SAFE BY DEFAULT: prints the plan and exits. Pass --go to actually spend (bounded
by --ceiling). After the FIRST call, STOP and verify the spend landed on the
Agent SDK credit (account → credits), not platform.claude.com pay-as-you-go,
before running the rest.

    python spikes/s1_claude_economics.py            # dry: prints the plan
    python spikes/s1_claude_economics.py --go        # actually runs (bounded)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from nightsweeper.env import ApiKeyPresentError, assert_no_api_key, scrubbed_env

PROMPTS = [
    "In one short paragraph, summarize what a capacity-aware scheduler is.",
    "Write a Python one-liner that reverses a string. Output only the code.",
    "List three pitfalls of unattended overnight coding agents.",
]


def run_once(prompt: str, model: str) -> dict:
    out = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--model", model, prompt],
        capture_output=True, text=True, env=scrubbed_env(), timeout=600,
    )
    if out.returncode != 0:
        raise RuntimeError(f"claude exit {out.returncode}: {out.stderr.strip()[:300]}")
    return json.loads(out.stdout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="actually run (spends real credit)")
    ap.add_argument("--ceiling", type=float, default=2.0, help="stop after this much $ spent")
    ap.add_argument("--tasks", type=int, default=3)
    ap.add_argument("--model", default="claude-sonnet-4-6")
    a = ap.parse_args()

    try:
        assert_no_api_key()
    except ApiKeyPresentError as e:
        print(f"ABORT: {e}", file=sys.stderr)
        return 2

    if not a.go:
        print(__doc__)
        print(f"DRY RUN. Would run up to {a.tasks} `claude -p` tasks on {a.model}, "
              f"stopping at ${a.ceiling:.2f}. Re-run with --go to execute.")
        print("ANTHROPIC_API_KEY is unset ✓ (would run under credit-pool routing).")
        return 0

    spent = 0.0
    for i, prompt in enumerate(PROMPTS[: a.tasks], 1):
        if spent >= a.ceiling:
            print(f"Spend ceiling ${a.ceiling:.2f} reached — stopping.")
            break
        payload = run_once(prompt, a.model)
        cost = float(payload.get("total_cost_usd", 0.0))
        spent += cost
        print(f"task {i}: ${cost:.4f}  (cumulative ${spent:.4f})")
        if i == 1:
            print("\n>>> STOP and verify routing now: confirm this spend appears against your "
                  "Agent SDK monthly credit, NOT platform.claude.com pay-as-you-go (#43333). "
                  "Re-run to continue once verified.\n")
            break
    print(f"\nMeasured per-task cost ~${(spent / max(1, min(a.tasks, 1))):.4f}. "
          "Extrapolate vs your monthly credit ($20 Pro / $100 Max5x / $200 Max20x) to set "
          "nightly_budget + per_task_floor, and record in docs/research/2026-06-15-grounding.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
