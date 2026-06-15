"""Nightsweeper — local-first, capacity-aware overnight scheduler.

Pulls a real backlog, probes idle paid-for capacity, dispatches each task in
value order to the cheapest lane that can plausibly clear its validator
(local-first, deterministic, escalate-once-then-park), validates in an isolated
git worktree, and writes an honest morning report.

V1 builds the two adapter seams (BackendAdapter, BacklogSource) plus two dormant
V2 hooks (a preflight ``estimate()`` and a ``dispatch(..., context=)`` param) and
the nullable ``predicted_lo/hi`` ledger columns, so V2 needs no rewrite.
"""

__version__ = "0.1.0"
