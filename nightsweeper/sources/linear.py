"""Linear backlog source (V2). Fetches real issues via the Linear GraphQL API.

Maps Linear priority → Nightsweeper value; coerces unknown validator/value labels
to defaults (never raises out of fetch). Needs a Linear API key in the env
(default ``LINEAR_API_KEY``). Registers as a new adapter — no dispatcher change.
"""

from __future__ import annotations

import json
import os
import urllib.request

from ..adapters.backlog import BacklogSource
from ..models import VALIDATORS, VALUES, Task
from ..registry import register_source

# Linear priority: 0 none, 1 urgent, 2 high, 3 medium, 4 low
_PRIORITY_VALUE = {1: "high", 2: "high", 3: "med", 4: "low", 0: "low"}

_QUERY = """query($filter: IssueFilter) {
  issues(filter: $filter, first: 200) {
    nodes { identifier title description priority
            labels { nodes { name } } }
  }
}"""


class LinearFetchError(RuntimeError):
    pass


@register_source("linear")
class LinearSource(BacklogSource):
    def __init__(self, cfg):
        o = cfg.options
        self.api_key_env = o.get("api_key_env", "LINEAR_API_KEY")
        self.team_key = o.get("team")
        self.default_value = o.get("default_value", "med")
        self.default_validator = o.get("default_validator", "test")
        self.validator_label_prefix = o.get("validator_label_prefix", "validator:")
        self.endpoint = o.get("endpoint", "https://api.linear.app/graphql")

    # injectable for tests
    def _fetch_raw_issues(self) -> list:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise LinearFetchError(f"linear: ${self.api_key_env} not set")
        filt = {"state": {"type": {"neq": "completed"}}}
        if self.team_key:
            filt["team"] = {"key": {"eq": self.team_key}}
        body = json.dumps({"query": _QUERY, "variables": {"filter": filt}}).encode()
        req = urllib.request.Request(
            self.endpoint, data=body,
            headers={"Authorization": key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read())
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            raise LinearFetchError(f"linear: API request failed: {e}") from e
        if "errors" in data:
            raise LinearFetchError(f"linear: GraphQL errors: {data['errors']}")
        return data["data"]["issues"]["nodes"]

    def _to_task(self, issue: dict) -> Task:
        labels = [n["name"] for n in (issue.get("labels") or {}).get("nodes", [])]
        value = _PRIORITY_VALUE.get(issue.get("priority", 0), self.default_value)
        validator = self.default_validator
        for name in labels:
            if name.startswith(self.validator_label_prefix):
                validator = name[len(self.validator_label_prefix):]
                break
        if validator not in VALIDATORS:
            validator = self.default_validator
        if value not in VALUES:
            value = self.default_value
        desc = issue.get("description") or ""
        return Task(
            id=f"linear:{issue['identifier']}",
            source="linear",
            title=issue.get("title", ""),
            body=desc,
            est_complexity="medium" if len(desc) >= 600 else "low",
            est_context_tokens=max(1, (len(desc) + len(issue.get("title", ""))) // 4),
            validator=validator,
            value=value,
        )

    def fetch(self) -> list:
        return [self._to_task(i) for i in self._fetch_raw_issues()]
