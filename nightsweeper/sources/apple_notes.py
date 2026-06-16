"""Apple Notes backlog source (macOS).

Reads a named note via ``osascript`` (AppleScript) and turns its lines into tasks
— a real source (R1/R25): it reads *your* note, never fabricates. One line = one
task. Done items (strikethrough, or a leading ``[x]`` / ``✓``) are skipped unless
``include_done``. The first line (the note's title) is skipped by default. An
optional trailing inline tag sets per-task fields::

    Fix the flaky retry  [validator=test value=high]

Caveat: a headless cron/launchd job needs macOS Automation (TCC) permission to
control Notes — grant it once when prompted (or in System Settings → Privacy &
Security → Automation).
"""

from __future__ import annotations

import hashlib
import html
import re
import subprocess

from ..adapters.backlog import BacklogSource
from ..models import VALIDATORS, VALUES, Task
from ..registry import register_source

_TAG = re.compile(r"<[^>]+>")
_DONE_PREFIX = re.compile(r"^\s*(?:\[x\]|✓|✔)\s*", re.IGNORECASE)
_STRIKE = re.compile(r"(?i)<s>|<strike>|line-through")
_INLINE = re.compile(r"\[([^\]]*)\]\s*$")
# Notes renders Title/Heading/Subheading as <h1>-<h6> or bold standalone lines.
_HEADING = re.compile(r"(?i)<h[1-6][ >]|<b>|<strong>|font-weight:\s*(?:bold|[6-9]00)")


class SourceFetchError(RuntimeError):
    pass


@register_source("apple_notes")
class AppleNotesSource(BacklogSource):
    def __init__(self, cfg):
        o = cfg.options
        self.note = o.get("note")
        self.folder = o.get("folder")
        self.heading = o.get("heading")  # scope to items under this heading only
        self.default_value = o.get("default_value", "med")
        self.default_validator = o.get("default_validator", "test")
        self.include_done = o.get("include_done", False)
        self.skip_title = o.get("skip_title", True)

    # injectable for tests
    def _fetch_body(self) -> str:
        if not self.note:
            raise SourceFetchError("apple_notes: 'note' (note title) is required")
        target = f'note "{self.note}"'
        if self.folder:
            target += f' of folder "{self.folder}"'
        script = f"tell application \"Notes\" to get body of {target}"
        out = subprocess.run(["osascript", "-e", script],
                             capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            raise SourceFetchError(f"apple_notes: osascript failed: {out.stderr.strip()[:200]}")
        return out.stdout

    def _lines(self, body: str) -> list:
        s = re.sub(r"(?i)</(div|p|li|h[1-6])>", "\n", body)
        s = re.sub(r"(?i)<br ?/?>", "\n", s)
        out = []
        for raw in s.split("\n"):
            done = bool(_STRIKE.search(raw))
            is_heading = bool(_HEADING.search(raw))
            text = html.unescape(_TAG.sub("", raw)).strip()
            if not text:
                continue
            if _DONE_PREFIX.match(text):
                done = True
                text = _DONE_PREFIX.sub("", text)
            out.append((text, done, is_heading))
        return out

    def _to_task(self, text: str) -> Task:
        validator, value = self.default_validator, self.default_value
        title = text
        m = _INLINE.search(text)
        if m:
            for part in m.group(1).split():
                if "=" in part:
                    k, v = part.split("=", 1)
                    if k == "validator" and v in VALIDATORS:
                        validator = v
                    elif k == "value" and v in VALUES:
                        value = v
            title = text[:m.start()].strip()
        tid = "note:" + hashlib.sha1(title.encode()).hexdigest()[:12]
        return Task(id=tid, source="apple_notes", title=title, body=title,
                    est_complexity="low", est_context_tokens=max(1, len(title) // 4),
                    validator=validator, value=value)

    def fetch(self) -> list:
        lines = self._lines(self._fetch_body())
        if self.heading:
            # collect only the items under the matching heading, until the next heading
            target = self.heading.strip().lower()
            items, collecting = [], False
            for text, done, is_heading in lines:
                if is_heading:
                    if text.strip().lower().startswith(target):
                        collecting = True
                    elif collecting:
                        break  # the next heading ends the section
                    continue
                if collecting:
                    items.append((text, done))
        else:
            if self.skip_title and lines:
                lines = lines[1:]  # first line is the note title
            items = [(t, d) for t, d, _ in lines]
        return [self._to_task(text) for text, done in items
                if not (done and not self.include_done)]
