"""Local lane — OpenClaw over Ollama (U9). The only truly-free lane ($0).

Default model Qwen3-Coder-30B (NOT gemma — grounding §3: gemma is not a coding
specialist). The model is config-driven. Every result is gated downstream on
EXECUTABLE validation, never self-report. Tool-call loops / malformed tool calls
surface as a dispatch failure so the dispatcher escalates rather than hanging.
"""

from __future__ import annotations

import subprocess
import urllib.error
import urllib.request

from ..adapters.backend import BackendAdapter
from ..models import Capacity, Result
from ..registry import register_backend


@register_backend("local")
class LocalBackend(BackendAdapter):
    def __init__(self, cfg):
        o = cfg.options
        self.cost_rank = cfg.cost_rank
        self.model = o.get("model", "qwen3-coder:30b")
        self.ollama_host = o.get("ollama_host", "http://localhost:11434")
        self.timeout_sec = int(o.get("timeout_sec", 1800))

    # injectable for tests
    def _ollama_up(self) -> bool:
        try:
            with urllib.request.urlopen(self.ollama_host + "/api/tags", timeout=3) as r:
                return r.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def probe_headroom(self) -> Capacity:
        # Always free; capacity is bounded only by the machine + Ollama being up.
        return Capacity(available=self._ollama_up(), dollars_remaining=None, unit="unbounded")

    # injectable for tests
    def _run_agent(self, task, workdir: str):
        """Return (ok, raw, error). Real impl shells OpenClaw headless in workdir."""
        cmd = [
            "openclaw", "infer", "model", "run",
            "--model", f"ollama/{self.model}",
            "--prompt", f"{task.title}\n\n{task.body}",
            "--json",
        ]
        try:
            out = subprocess.run(
                cmd, capture_output=True, text=True, cwd=workdir, timeout=self.timeout_sec
            )
        except FileNotFoundError:
            return False, None, "openclaw not installed (local lane unavailable)"
        except subprocess.TimeoutExpired:
            return False, None, "local dispatch timed out"
        if out.returncode != 0:
            return False, out.stdout, f"openclaw exit {out.returncode}: {out.stderr.strip()[:300]}"
        return True, out.stdout, None

    def dispatch(self, task, workdir, context=None) -> Result:
        ok, raw, err = self._run_agent(task, workdir)
        return Result(ok=ok, consumed_usd=0.0, tokens=None, raw=raw, error=err)
