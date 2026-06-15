"""Worktree isolation + handoff (U11).

One git worktree/branch per task under a gitignored dir; on pass, push a labeled
branch (and optionally open a draft PR — config toggle, default off); on park,
preserve the worktree for human review. Cleanup removes + prunes the worktree and
resets any stray ``extensions.worktreeConfig`` (grounding §5). Git/gh calls go
through injectable runners so the logic is unit-testable without a live repo.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from typing import Optional


class IsolationError(RuntimeError):
    pass


def _safe_ref(task_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._/-]", "-", task_id)


@dataclass
class Handoff:
    branch: str
    pushed: bool
    pr_url: Optional[str] = None
    error: Optional[str] = None


class WorktreeManager:
    def __init__(self, repo_root: str, isolation_cfg, repo_slug: Optional[str] = None):
        self.repo_root = repo_root
        self.cfg = isolation_cfg
        self.repo_slug = repo_slug

    # injectable for tests
    def _git(self, args: list, cwd: Optional[str] = None):
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, cwd=cwd or self.repo_root
        )

    def _gh(self, args: list, cwd: Optional[str] = None):
        return subprocess.run(
            ["gh", *args], capture_output=True, text=True, cwd=cwd or self.repo_root
        )

    def branch_for(self, task_id: str) -> str:
        return self.cfg.branch_prefix + _safe_ref(task_id)

    def workdir_for(self, task_id: str) -> str:
        return os.path.join(self.repo_root, self.cfg.worktree_dir, _safe_ref(task_id))

    def create(self, task) -> str:
        branch, wdir = self.branch_for(task.id), self.workdir_for(task.id)
        r = self._git(["worktree", "add", wdir, "-b", branch, "origin/HEAD"])
        if r.returncode != 0:
            raise IsolationError(f"worktree add failed for {task.id}: {r.stderr.strip()}")
        return wdir

    def handoff(self, task, wdir: str) -> Handoff:
        branch = self.branch_for(task.id)
        label = self.cfg.label_prefix + _safe_ref(task.id)
        self._git(["add", "-A"], cwd=wdir)
        self._git(["commit", "-m", f"nightsweeper: {task.title[:60]}"], cwd=wdir)
        push = self._git(["push", "-u", "origin", "HEAD"], cwd=wdir)
        if push.returncode != 0:
            return Handoff(branch=branch, pushed=False, error=push.stderr.strip())
        pr_url = None
        if self.cfg.pr_opt_in and self.repo_slug:
            gh = self._gh([
                "pr", "create", "-R", self.repo_slug, "--head", branch,
                "--title", f"nightsweeper: {task.title[:60]}",
                "--body", f"Automated by Nightsweeper for task `{task.id}`.",
                "--draft", "--label", label,
            ], cwd=wdir)
            if gh.returncode == 0:
                pr_url = gh.stdout.strip()
            else:
                # branch is pushed; PR failure is non-fatal — surface and continue
                return Handoff(branch=branch, pushed=True, error=f"gh pr create: {gh.stderr.strip()}")
        return Handoff(branch=branch, pushed=True, pr_url=pr_url)

    def cleanup(self, task, keep: bool) -> None:
        if keep:
            return  # parked: preserve the worktree for human review
        wdir = self.workdir_for(task.id)
        self._git(["worktree", "remove", "--force", wdir])
        self._git(["worktree", "prune"])
        # undo the known stray worktreeConfig leftover (grounding §5)
        self._git(["config", "--unset", "extensions.worktreeConfig"])
