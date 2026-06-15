# Nightsweeper

A local-first, capacity-aware overnight scheduler that dispatches a **real** backlog
of tasks to whichever agent backend has idle, already-paid-for capacity tonight —
local (OpenClaw/Ollama), Claude headless, and (V2) Codex headless — validates each
result, and produces a morning report.

**Thesis:** Flat-rate coding subscriptions plus an always-on local machine are idle
capacity at zero or pre-paid marginal cost. The scarce resource is idle agent capacity
on infrastructure you already pay for — not the subscription number. Nightsweeper matches
a real backlog to that idle capacity and executes it overnight.

## Status

Pre-implementation. Planning artifacts live under `docs/`:

- `docs/brainstorms/` — requirements (the **what**), produced by `/ce-brainstorm`.
- `docs/plans/` — implementation plan (the **how**), produced by `/ce-plan`.

V1 is built only after the plan is approved.

## Hard guardrails (first-class principles)

1. **Never invent work.** No backlog item → no run. Pull only from real sources.
2. **Rank by value, never by tokens consumed.** Token usage is a vanity metric.
3. **Honesty over engagement.** The morning report must be willing to recommend
   downgrading a chronically underused plan.
4. **Local-first.** The only truly-free lane is local; cloud lanes are headroom-gated.
