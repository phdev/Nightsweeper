"""Claude headless lane (U10) — budget-gated, fail-closed.

Grounding §1–2: headless ``claude -p`` bills a separate, capped monthly credit,
and live remaining headroom is not programmatically readable on a subscription
machine. So this lane is BUDGET-gated: ``probe_headroom`` returns
``nightly_budget − spent_tonight`` (read from the ledger), and the night's $ cap
is enforced by the dispatcher's post-run re-probe (bounded single-task overshoot,
no pre-dispatch estimate in V1). A static ``per_task_floor`` is the minimum
remaining budget required to attempt a task — when remaining drops below it the
lane is unavailable (fail-closed). ``ANTHROPIC_API_KEY`` is hard-refused: a set
key bills uncapped API spend (grounding §1).
"""

from __future__ import annotations

import json
import subprocess

from ..adapters.backend import BackendAdapter
from ..env import ApiKeyPresentError, assert_no_api_key, scrubbed_env
from ..models import Capacity, Result
from ..preflight import estimate_usd, parse_cost_model
from ..registry import register_backend


@register_backend("claude")
class ClaudeBackend(BackendAdapter):
    def __init__(self, cfg):
        o = cfg.options
        self.cost_rank = cfg.cost_rank
        self.model = o.get("model", "claude-sonnet-4-6")
        self.nightly_budget = float(o.get("nightly_budget", 0.0))
        self.per_task_floor = float(o.get("per_task_floor", 0.0))
        self.timeout_sec = int(o.get("timeout_sec", 1800))
        self.cost_model = parse_cost_model(o)  # preflight (V2); None → estimate() returns None
        self._ledger = None
        self._night_start = None

    def estimate(self, task):
        return estimate_usd(task.est_context_tokens, self.cost_model)

    def bind_runtime(self, ledger, night_start_ts: str) -> None:
        self._ledger = ledger
        self._night_start = night_start_ts

    def _remaining(self) -> float:
        spent = 0.0
        if self._ledger is not None and self._night_start is not None:
            spent = self._ledger.spend_since("claude", self._night_start)
        return self.nightly_budget - spent

    def probe_headroom(self) -> Capacity:
        remaining = self._remaining()
        # fail-closed: need at least a per-task floor's worth of budget to attempt
        available = remaining > 0 and remaining >= self.per_task_floor
        return Capacity(available=available, dollars_remaining=remaining, unit="usd")

    # injectable for tests
    def _run_claude(self, task, workdir: str):
        """Return (returncode, stdout, stderr). Real impl shells claude -p."""
        cmd = ["claude", "-p", "--output-format", "json", "--model", self.model,
               f"{task.title}\n\n{task.body}"]
        out = subprocess.run(
            cmd, capture_output=True, text=True, cwd=workdir,
            timeout=self.timeout_sec, env=scrubbed_env(),
        )
        return out.returncode, out.stdout, out.stderr

    def dispatch(self, task, workdir, context=None) -> Result:
        try:
            assert_no_api_key()
        except ApiKeyPresentError as e:
            return Result(ok=False, error=str(e))
        r = self._remaining()  # mirror probe_headroom exactly (fail-closed at 0/floor)
        if not (r > 0 and r >= self.per_task_floor):
            return Result(ok=False, error="below per-task budget floor (fail-closed)")
        try:
            rc, stdout, stderr = self._run_claude(task, workdir)
        except FileNotFoundError:
            return Result(ok=False, error="claude CLI not found")
        except subprocess.TimeoutExpired:
            return Result(ok=False, error="claude dispatch timed out")
        if rc != 0:
            return Result(ok=False, error=f"claude exit {rc}: {stderr.strip()[:300]}", raw=stdout)
        try:
            payload = json.loads(stdout)
            # None-safe: a present-but-null total_cost_usd/usage must not crash the
            # night AFTER the credit was spent (`float(None)` / `None + n` raise).
            cost = float(payload.get("total_cost_usd") or 0.0)
            usage = payload.get("usage") or {}
            tokens = (int(usage.get("input_tokens") or 0)
                      + int(usage.get("output_tokens") or 0)) or None
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            return Result(ok=False, error=f"unparseable claude JSON/cost: {e}", raw=stdout)
        return Result(ok=True, consumed_usd=cost, tokens=tokens, raw=stdout)
