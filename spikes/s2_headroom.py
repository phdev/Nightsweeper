#!/usr/bin/env python3
"""Spike S2 — Claude headroom readability (plan U2).

Resolves: can remaining Claude credit/headroom be read programmatically, or is
the budget-fallback the path? Grounding §2: there is no supported scriptable read
of live remaining subscription headroom; the only live signal is the
`anthropic-ratelimit-unified-*` response headers, which Claude Code does not
expose to hooks/CLI. This spike probes whether `claude --debug api` surfaces
those headers locally (a supported capture path) — if not, the architecture's
budget-fallback (KTD2) stands as the primary mechanism.

SAFE BY DEFAULT: prints the plan and exits. Pass --go to issue one tiny probe.

    python spikes/s2_headroom.py            # dry
    python spikes/s2_headroom.py --go        # one tiny --debug api probe
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

from nightsweeper.env import ApiKeyPresentError, assert_no_api_key, scrubbed_env

HDR = re.compile(r"anthropic-ratelimit-unified-[\w-]+", re.IGNORECASE)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true")
    a = ap.parse_args()

    try:
        assert_no_api_key()
    except ApiKeyPresentError as e:
        print(f"ABORT: {e}", file=sys.stderr)
        return 2

    if not a.go:
        print(__doc__)
        print("DRY RUN. Would run `claude --debug api -p 'hi'` and grep stderr for "
              "anthropic-ratelimit-unified-* headers. Re-run with --go.")
        return 0

    out = subprocess.run(
        ["claude", "--debug", "api", "-p", "hi"],
        capture_output=True, text=True, env=scrubbed_env(), timeout=120,
    )
    blob = (out.stdout or "") + (out.stderr or "")
    found = sorted(set(HDR.findall(blob)))
    if found:
        print("Found unified rate-limit headers (a live-read path may be viable):")
        for h in found:
            print("  -", h)
        print("\nDecision: consider a header-capture probe; otherwise keep budget-fallback.")
    else:
        print("No unified rate-limit headers surfaced by `claude --debug api`.")
        print("Decision: budget-fallback (KTD2) stands as the Claude lane's probe mechanism.")
    print("Record the outcome in docs/research/2026-06-15-grounding.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
