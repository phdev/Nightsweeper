"""Validator (U12) — run the task's configured check inside the worktree.

Keep only passes (R12). ``validator: none`` cannot be auto-passed, so it always
parks (R15). ``test``/``typecheck``/``build``/``custom-cmd`` resolve to commands
from the config's ``validators`` map and pass iff the command exits 0. The
command runs inside the task's worktree with a timeout. The subprocess call is
injectable so the routing logic is unit-testable.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional

PASSED, FAILED, PARKED = "passed", "failed", "parked"


@dataclass
class ValidationResult:
    result: str  # PASSED | FAILED | PARKED
    detail: str = ""
    failed_gate: Optional[str] = None  # set when a functional pass was rejected by a gate

    @property
    def passed(self) -> bool:
        return self.result == PASSED


class Validator:
    def __init__(self, validators_cfg: dict, gates: Optional[list] = None, timeout_sec: int = 1800):
        self.validators = validators_cfg
        self.gates = gates or []  # adjudication gates (e.g. Depthfinder); all must hold
        self.timeout_sec = timeout_sec

    # injectable for tests
    def _run(self, command: str, workdir: str):
        return subprocess.run(
            command, shell=True, capture_output=True, text=True,
            cwd=workdir, timeout=self.timeout_sec,
        )

    def _run_gates(self, workdir: str):
        """Run every adjudication gate. Return (failed_gate_name, detail) or (None, '')."""
        for gate in self.gates:
            try:
                out = self._run(gate.cmd, workdir)
            except subprocess.TimeoutExpired:
                return gate.name, f"gate '{gate.name}' timed out"
            if out.returncode == 127 and not gate.required:
                continue  # optional gate whose command isn't installed → skip
            if out.returncode != 0:
                return gate.name, f"gate '{gate.name}' rejected: `{gate.cmd}` exited {out.returncode}"
        return None, ""

    def validate(self, task, workdir: str) -> ValidationResult:
        if task.validator == "none":
            return ValidationResult(PARKED, "validator:none — no automated pass signal; parked")
        command = self.validators.get(task.validator)
        if not command:
            return ValidationResult(FAILED, f"no command configured for validator '{task.validator}'")
        try:
            out = self._run(command, workdir)
        except subprocess.TimeoutExpired:
            return ValidationResult(FAILED, "validator timed out")
        except OSError as e:
            return ValidationResult(FAILED, f"validator could not run: {e}")
        if out.returncode != 0:
            return ValidationResult(FAILED, f"`{command}` exited {out.returncode}")
        # functional check passed → run adjudication gates
        gate_name, detail = self._run_gates(workdir)
        if gate_name:
            return ValidationResult(FAILED, detail, failed_gate=gate_name)
        held = f"; {len(self.gates)} gate(s) held" if self.gates else ""
        return ValidationResult(PASSED, f"`{command}` exited 0{held}")
