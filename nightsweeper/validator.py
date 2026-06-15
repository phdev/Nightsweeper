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

PASSED, FAILED, PARKED = "passed", "failed", "parked"


@dataclass
class ValidationResult:
    result: str  # PASSED | FAILED | PARKED
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.result == PASSED


class Validator:
    def __init__(self, validators_cfg: dict, timeout_sec: int = 1800):
        self.validators = validators_cfg
        self.timeout_sec = timeout_sec

    # injectable for tests
    def _run(self, command: str, workdir: str):
        return subprocess.run(
            command, shell=True, capture_output=True, text=True,
            cwd=workdir, timeout=self.timeout_sec,
        )

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
        if out.returncode == 0:
            return ValidationResult(PASSED, f"`{command}` exited 0")
        return ValidationResult(FAILED, f"`{command}` exited {out.returncode}")
