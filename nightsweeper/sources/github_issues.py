"""GitHub issues backlog source (U7).

Fetches real open issues via the ``gh`` CLI and normalizes each to a Task.
Never fabricates work (R1/R25): an empty issue list yields zero tasks. A ``gh``
failure raises ``SourceFetchError``; the night runner catches it per-source so
one broken source does not crash the night.
"""

from __future__ import annotations

import json
import subprocess

from ..adapters.backlog import BacklogSource
from ..models import VALIDATORS, VALUES, Task
from ..registry import register_source


class SourceFetchError(RuntimeError):
    pass


def _complexity_from_body(body: str) -> str:
    n = len(body or "")
    if n < 400:
        return "low"
    if n < 1600:
        return "medium"
    return "high"


@register_source("github_issues")
class GithubIssuesSource(BacklogSource):
    def __init__(self, cfg):
        o = cfg.options
        self.repos = o.get("repos", [])
        self.labels = o.get("labels", [])
        self.value_label_map = o.get("value_label_map", {})
        self.default_value = o.get("default_value", "med")
        self.validator_label_prefix = o.get("validator_label_prefix", "validator:")
        self.default_validator = o.get("default_validator", "test")

    # injectable for tests
    def _fetch_raw_issues(self, repo: str) -> list:
        cmd = ["gh", "issue", "list", "-R", repo, "--state", "open",
               "--json", "number,title,body,labels,url", "--limit", "200"]
        for lbl in self.labels:
            cmd += ["--label", lbl]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            raise SourceFetchError(f"github_issues: `gh` invocation failed for {repo}: {e}") from e
        if out.returncode != 0:
            raise SourceFetchError(
                f"github_issues: `gh issue list` failed for {repo} "
                f"(exit {out.returncode}): {out.stderr.strip()}"
            )
        return json.loads(out.stdout or "[]")

    def _to_task(self, repo: str, issue: dict) -> Task:
        label_names = [l["name"] for l in issue.get("labels", [])]
        value = self.default_value
        for lbl, val in self.value_label_map.items():
            if lbl in label_names:
                value = val
                break
        validator = self.default_validator
        for name in label_names:
            if name.startswith(self.validator_label_prefix):
                validator = name[len(self.validator_label_prefix):]
                break
        # coerce typo'd labels to defaults — one bad issue must not drop the source
        if validator not in VALIDATORS:
            validator = self.default_validator
        if value not in VALUES:
            value = self.default_value
        body = issue.get("body") or ""
        return Task(
            id=f"gh:{repo}#{issue['number']}",
            source="github_issues",
            title=issue.get("title", ""),
            body=body,
            est_complexity=_complexity_from_body(body),
            est_context_tokens=max(1, (len(body) + len(issue.get("title", ""))) // 4),
            validator=validator,
            value=value,
        )

    def fetch(self) -> list:
        tasks = []
        for repo in self.repos:
            for issue in self._fetch_raw_issues(repo):
                tasks.append(self._to_task(repo, issue))
        return tasks
