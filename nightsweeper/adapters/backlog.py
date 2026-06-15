"""``BacklogSource`` — the backlog seam (origin core interface).

V1 sources: github_issues, todo_scan. V2 sources: linear, gbrain.
``fetch()`` returns only real tasks — never fabricated (origin R1/R25).
"""

from __future__ import annotations

import abc

from ..models import Task


class BacklogSource(abc.ABC):
    name: str

    @abc.abstractmethod
    def fetch(self) -> list:
        """Return a list of normalized ``Task`` objects from a real source."""

    def inventory(self) -> dict:
        """Optional report-only signals not dispatched as tasks.

        Used by ``todo_scan`` to surface a count of bare (un-enrolled) TODO/FIXME
        markers in the morning report without dispatching them (honors R1/R25).
        Returns an empty mapping by default.
        """
        return {}
