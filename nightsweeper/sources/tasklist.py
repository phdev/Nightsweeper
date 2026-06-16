"""Task-list file backlog source.

Ingest a literal list of tasks the operator authored — a YAML or JSON file
(YAML is a JSON superset, so both parse). Still a *real* source (R1/R25): it
reads your file, never fabricates. Missing/empty file → zero tasks. Each entry::

    - id: add-fn                 # optional; derived from title if omitted
      title: "Implement add()"
      body: "Write add(a, b) in solution.py returning their sum."
      validator: custom-cmd      # test|typecheck|build|none|custom-cmd (coerced)
      value: high                # high|med|low (coerced)
      est_complexity: low        # optional; low|medium|high
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from ..adapters.backlog import BacklogSource
from ..models import COMPLEXITIES, VALIDATORS, VALUES, Task
from ..registry import register_source


@register_source("tasklist")
class TaskListSource(BacklogSource):
    def __init__(self, cfg):
        o = cfg.options
        self.path = o.get("path", "nightsweeper.tasks.yaml")
        self.default_value = o.get("default_value", "med")
        self.default_validator = o.get("default_validator", "test")

    # injectable for tests
    def _load(self) -> list:
        p = Path(self.path)
        if not p.exists():
            return []
        data = yaml.safe_load(p.read_text()) or []
        if not isinstance(data, list):
            raise ValueError(f"tasklist: {self.path} must be a YAML/JSON list of tasks")
        return data

    def _to_task(self, entry: dict) -> Task:
        title = entry.get("title") or entry.get("id") or ""
        body = entry.get("body", "")
        tid = entry.get("id") or "task:" + hashlib.sha1(title.encode()).hexdigest()[:12]
        validator = entry.get("validator", self.default_validator)
        if validator not in VALIDATORS:
            validator = self.default_validator
        value = entry.get("value", self.default_value)
        if value not in VALUES:
            value = self.default_value
        complexity = entry.get("est_complexity", "low")
        if complexity not in COMPLEXITIES:
            complexity = "low"
        validator_cmd = entry.get("validator_cmd")
        if validator_cmd:
            validator = "custom-cmd"  # a per-task command implies a custom-cmd validator
        return Task(
            id=str(tid), source="tasklist", title=title, body=body,
            est_complexity=complexity,
            est_context_tokens=entry.get("est_context_tokens") or max(1, len(body) // 4),
            validator=validator, value=value, validator_cmd=validator_cmd,
        )

    def fetch(self) -> list:
        return [self._to_task(e) for e in self._load() if (e.get("title") or e.get("id"))]
