"""Aider local lane — drives a local Ollama model through Aider's edit loop.

A drop-in alternative to the OpenClaw `local` lane: Aider is a mature, headless
terminal coder with native Ollama support and a stable CLI. Runs co-located with
the worktree it edits; points at Ollama via ``OLLAMA_API_BASE`` (local or LAN).
``$0`` marginal; gated downstream on EXECUTABLE validation (Aider's exit code is
not a success signal — the validator decides pass/fail).
"""

from __future__ import annotations

import subprocess
import urllib.error
import urllib.request

from ..adapters.backend import BackendAdapter
from ..env import scrubbed_env
from ..models import Capacity, CostRange, Result
from ..registry import register_backend


@register_backend("aider")
class AiderBackend(BackendAdapter):
    def __init__(self, cfg):
        o = cfg.options
        self.cost_rank = cfg.cost_rank
        self.model = o.get("model", "qwen2.5-coder:7b")
        self.ollama_host = o.get("ollama_host", "http://localhost:11434")
        self.aider_bin = o.get("aider_bin", "aider")
        self.edit_format = o.get("edit_format", "whole")  # robust for small models
        self.timeout_sec = int(o.get("timeout_sec", 1800))
        self.extra_args = list(o.get("extra_args", []))

    def _ollama_up(self) -> bool:
        try:
            with urllib.request.urlopen(self.ollama_host + "/api/tags", timeout=3) as r:
                return r.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def probe_headroom(self) -> Capacity:
        return Capacity(available=self._ollama_up(), dollars_remaining=None, unit="unbounded")

    # injectable for tests
    def _run_aider(self, task, workdir: str, message: str):
        cmd = [
            self.aider_bin,
            "--model", f"ollama_chat/{self.model}",
            "--edit-format", self.edit_format,
            "--yes-always", "--no-auto-commits", "--no-stream",
            "--no-check-update", "--no-show-model-warnings",
            "--message", message,
        ] + self.extra_args
        env = scrubbed_env()
        env["OLLAMA_API_BASE"] = self.ollama_host  # point Aider at the (remote) Ollama
        out = subprocess.run(cmd, capture_output=True, text=True, cwd=workdir,
                             timeout=self.timeout_sec, env=env)
        return out.returncode, out.stdout, out.stderr

    def dispatch(self, task, workdir, context=None) -> Result:
        message = f"{task.title}\n\n{task.body}"
        if context:
            message += f"\n\nRelevant context:\n{context}"
        try:
            rc, stdout, stderr = self._run_aider(task, workdir, message)
        except FileNotFoundError:
            return Result(ok=False, error=f"aider not found ('{self.aider_bin}')")
        except subprocess.TimeoutExpired:
            return Result(ok=False, error="aider timed out")
        # Aider's exit code is not a reliable success signal; the validator is the gate.
        ok = rc == 0
        return Result(ok=ok, consumed_usd=0.0, raw=stdout,
                      error=None if ok else f"aider exit {rc}: {stderr.strip()[:300]}")

    def estimate(self, task) -> CostRange:
        return CostRange(lo=0.0, hi=0.0)  # local is free

    def usage_summary(self) -> str:
        up = self._ollama_up()
        return f"local {self.model} (aider) · free ($0)" if up else f"local {self.model} · Ollama unreachable"
