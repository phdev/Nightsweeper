"""TODO/FIXME scan backlog source (U8) — enrolled markers only.

Honors "never invent work" (R1/R25): a bare ``TODO``/``FIXME`` is a private note,
not a committed backlog item, so it is NEVER dispatched — it is surfaced only as
a report-only inventory count via ``inventory()``. Only markers carrying an
explicit enrollment tag become dispatchable tasks::

    TODO(nightsweeper: validator=test value=med)

Task ids are stable (hash of file:line:text). Ledger-based dedupe (so a parked
task is not re-queued nightly) is applied by the night runner, not here.
"""

from __future__ import annotations

import hashlib
import os
import re

from ..adapters.backlog import BacklogSource
from ..models import VALIDATORS, VALUES, Task
from ..registry import register_source

_ENROLLED = re.compile(r"\b(?:TODO|FIXME)\(nightsweeper:\s*(?P<args>[^)]*)\)", re.IGNORECASE)
_BARE = re.compile(r"\b(?:TODO|FIXME)\b")
_TEXT_EXT = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".rb", ".java", ".c", ".h",
    ".cpp", ".cc", ".sh", ".yaml", ".yml", ".toml", ".md", ".txt", ".cfg", ".ini",
}


def _parse_args(arg_str: str) -> dict:
    out = {}
    for part in arg_str.split():
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


@register_source("todo_scan")
class TodoScanSource(BacklogSource):
    def __init__(self, cfg):
        o = cfg.options
        self.paths = o.get("paths", ["."])
        self.default_value = o.get("default_value", "low")
        self._bare_count = 0

    # injectable for tests
    def _iter_files(self):
        skip = {".git", "node_modules", ".venv", "venv", "__pycache__", ".nightsweeper"}
        for root in self.paths:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in skip]
                for fn in filenames:
                    if os.path.splitext(fn)[1] in _TEXT_EXT:
                        yield os.path.join(dirpath, fn)

    def fetch(self) -> list:
        self._bare_count = 0
        tasks, seen = [], set()
        for path in self._iter_files():
            try:
                lines = open(path, encoding="utf-8", errors="ignore").read().splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                m = _ENROLLED.search(line)
                if m:
                    args = _parse_args(m.group("args"))
                    validator = args.get("validator", "none")
                    if validator not in VALIDATORS:
                        validator = "none"
                    value = args.get("value", self.default_value)
                    if value not in VALUES:
                        value = self.default_value
                    tid = "td:" + hashlib.sha1(
                        f"{path}:{i}:{line.strip()}".encode()
                    ).hexdigest()[:12]
                    if tid in seen:
                        continue
                    seen.add(tid)
                    tasks.append(Task(
                        id=tid, source="todo_scan", title=line.strip()[:120], body=line.strip(),
                        est_complexity="low", est_context_tokens=max(1, len(line) // 4),
                        validator=validator, value=value,
                    ))
                elif _BARE.search(line):
                    self._bare_count += 1
        return tasks

    def inventory(self) -> dict:
        # bare (un-enrolled) markers surfaced as a report-only count, never dispatched
        return {"bare_todo_count": self._bare_count}
