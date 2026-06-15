"""Codex headless lane (V2, U-codex). ChatGPT-plan quota; $0 marginal cost.

Grounding §4 / spike S4: headroom is read by SCRAPING the newest Codex session
rollout (`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`) for the latest
`payload.type == "token_count"` event's `rate_limits` (primary ~5h + secondary
~weekly windows, `used_percent`). `codex exec --json` itself emits null
rate_limits, so the side-channel scrape is the probe; if no populated rollout
exists, fall back to infer-from-errors (optimistic available, rate-limit errors
surface at dispatch). Registers as a new adapter — no dispatcher change (V2 seam).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

from ..adapters.backend import BackendAdapter
from ..env import scrubbed_env
from ..models import Capacity, CostRange, Result
from ..registry import register_backend


@register_backend("codex")
class CodexBackend(BackendAdapter):
    def __init__(self, cfg):
        o = cfg.options
        self.cost_rank = cfg.cost_rank
        self.max_used_percent = float(o.get("max_used_percent", 95.0))
        self.sessions_dir = os.path.expanduser(o.get("sessions_dir", "~/.codex/sessions"))
        self.timeout_sec = int(o.get("timeout_sec", 1800))
        self.model = o.get("model")

    # injectable for tests
    def _read_rate_limits(self) -> Optional[dict]:
        base = Path(self.sessions_dir)
        if not base.exists():
            return None
        files = sorted(base.glob("**/rollout-*.jsonl"))
        if not files:
            return None
        rl = None
        for line in files[-1].read_text(errors="ignore").splitlines():
            if '"rate_limits"' not in line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = d.get("payload", d)
            if payload.get("type") == "token_count" and payload.get("rate_limits"):
                rl = payload["rate_limits"]  # keep the latest one in the file
        return rl

    def probe_headroom(self) -> Capacity:
        rl = self._read_rate_limits()
        if rl is None:
            # no populated rollout → optimistic; rate-limit errors handled at dispatch
            return Capacity(available=True, unit="unbounded")
        used = max((rl.get("primary") or {}).get("used_percent", 0.0),
                   (rl.get("secondary") or {}).get("used_percent", 0.0))
        return Capacity(available=used < self.max_used_percent, unit="unbounded")

    # injectable for tests
    def _run_codex(self, task, workdir: str):
        cmd = ["codex", "exec", "--json"]
        if self.model:
            cmd += ["--model", self.model]
        cmd.append(f"{task.title}\n\n{task.body}")
        out = subprocess.run(cmd, capture_output=True, text=True, cwd=workdir,
                             timeout=self.timeout_sec, env=scrubbed_env())
        return out.returncode, out.stdout, out.stderr

    def dispatch(self, task, workdir, context=None) -> Result:
        try:
            rc, stdout, stderr = self._run_codex(task, workdir)
        except FileNotFoundError:
            return Result(ok=False, error="codex CLI not found")
        except subprocess.TimeoutExpired:
            return Result(ok=False, error="codex dispatch timed out")
        if "rate limit" in (stderr or "").lower():
            return Result(ok=False, error="codex rate-limited (inferred from error)", raw=stdout)
        if rc != 0:
            return Result(ok=False, error=f"codex exit {rc}: {stderr.strip()[:200]}", raw=stdout)
        return Result(ok=True, consumed_usd=0.0, raw=stdout)  # $0 marginal on a plan

    def estimate(self, task) -> CostRange:
        return CostRange(lo=0.0, hi=0.0)  # quota-gated, no $ cost
