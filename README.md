# Nightsweeper

A local-first, capacity-aware overnight scheduler that dispatches a **real** backlog
of tasks to whichever agent backend has idle, already-paid-for capacity tonight —
local (OpenClaw/Ollama), Claude headless, and (V2) Codex headless — validates each
result in an isolated git worktree, and produces an honest morning report.

**Thesis:** Flat-rate coding subscriptions plus an always-on local machine are idle
capacity at zero or pre-paid marginal cost. The scarce resource is idle agent capacity
on infrastructure you already pay for — not the subscription number. Nightsweeper
matches a real backlog to that idle capacity and executes it overnight.

## Hard guardrails (first-class principles)

1. **Never invent work.** No backlog item → no run. Bare `TODO`/`FIXME` notes are
   report-only inventory; only enrolled `TODO(nightsweeper: …)` markers dispatch.
2. **Rank by value, never by tokens consumed.** Cost only ever gates eligibility,
   never ordering or selection.
3. **Honesty over engagement.** The report always prints per-lane utilization and
   recommends downgrading a chronically underused plan.
4. **Local-first.** Local (Ollama) is the only truly-free lane; cloud lanes are
   headroom/budget-gated and fail-closed.

## How it works (the nightly loop)

`ingest` → `probe capacity` → `dispatch` (value order, cheapest eligible lane,
local-first, **escalate once then park**, deterministic rules only) → `validate`
(executable) in a per-task git worktree → labeled branch per pass → `SQLite ledger`
→ `markdown report`. See `docs/plans/2026-06-15-001-feat-nightsweeper-overnight-scheduler-plan.md`.

## Install

```bash
python3 -m venv .venv && .venv/bin/pip install -e .   # Python 3.10+
cp nightsweeper.config.example.yaml nightsweeper.config.yaml   # then edit
```

Optional backends/tools: `gh` (GitHub issues), `ollama` + `openclaw` (local lane),
`claude` (Claude lane). Each adapter degrades to "contributes nothing / lane
unavailable" rather than crashing the night.

## Commands

```bash
nightsweeper run                 # the nightly loop (writes the morning report)
nightsweeper run --print         # ... and print the report to stdout
nightsweeper run --if-missed     # only if today's run hasn't happened (scheduler self-heal)
nightsweeper probe               # preview per-lane headroom (no dispatch, no spend)
nightsweeper report              # print the latest morning report
nightsweeper install-scheduler   # render the launchd LaunchAgent + caffeinate wrapper
```

## Configuration

A single `nightsweeper.config.yaml` (gitignored) defines backlog sources, backend
lanes + caps, the nightly task/$ caps, the per-task cap, validators, the lane
**capability matrix**, isolation, and report thresholds. See the annotated
`nightsweeper.config.example.yaml`.

The **capability matrix** is how the dispatcher decides a lane "can plausibly clear"
a validator — deterministically, no ML: each lane lists the validator types it may
attempt and a max task-complexity tier it is trusted for.

## Scheduling

`nightsweeper install-scheduler` renders a per-user launchd LaunchAgent
(`StartCalendarInterval`) that runs the job under `caffeinate -is`. Single-instance
and missed-run self-heal are handled in the CLI (an `fcntl` lock + a sentinel), so it
is portable (macOS has no `flock`). It prints the `launchctl load` and
`sudo pmset repeat wakeorpoweron …` commands to run yourself (guarantee the Mac is
awake for the run).

## The riskiest-assumption spikes

V1 ships three decision-gating spikes under `spikes/` (safe by default — `--go` to
execute). Run these before trusting a lane:

- `spikes/s1_claude_economics.py` — Claude lane economics + billing-routing check.
- `spikes/s2_headroom.py` — is Claude headroom readable, or is budget-fallback the path?
- `spikes/s3_local_passrate.py` — local 10-task pass rate, bucketed by complexity.

## V1 vs V2

V1: GitHub issues + enrolled-TODO sources; local + Claude lanes; configurable test
command validator; one worktree/task; SQLite ledger; markdown report.

V2 (built — new adapters only, no dispatcher rewrite):

- **Codex lane** (`codex exec`, ChatGPT-plan quota, $0 marginal) — `probe_headroom`
  scrapes the newest `~/.codex/sessions/**/rollout-*.jsonl` for live rate-limit
  windows (spike S4).
- **Linear source** (Linear GraphQL, `$LINEAR_API_KEY`).
- **Gbrain enricher** — read-only context threaded through `dispatch(…, context=)`;
  *not* a source (no confirmed backlog MCP — spike S5). Graceful no-op without an MCP.
- **Preflight cost prediction** — a `cost_model` per cloud lane fills `predicted_lo/hi`;
  the report shows bracket accuracy. The per-task-cap **gate** is opt-in
  (`preflight.mode: gate`); it ships `advisory` until your replay clears ≥70% (S6).

These attach at the seams V1 built (the two adapter interfaces, the `estimate()` and
`dispatch(…, context=)` hooks, the `predicted_lo/hi` columns) — no rewrite.

## Development

```bash
.venv/bin/python -m pytest -q     # 114 tests
```

See `CLAUDE.md` for the architecture map and how to add a lane/source.
