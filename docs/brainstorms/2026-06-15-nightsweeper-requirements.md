---
date: 2026-06-15
topic: nightsweeper
---

# Nightsweeper — Requirements

## Summary

Nightsweeper is a local-first, capacity-aware overnight scheduler. It pulls a real backlog, probes which already-paid-for agent backend has idle headroom tonight, dispatches each task to the cheapest lane that can plausibly clear its validator, validates every result in an isolated git worktree, and writes a morning report. V1 proves the loop with two lanes (local + Claude headless) and two sources (GitHub issues + a TODO/FIXME scan). V2 extends it with a Codex lane, Linear/Gbrain sources, and preflight cost prediction — through new adapters and one dispatch hook, not an architectural rewrite.

---

## Problem Frame

Flat-rate coding subscriptions (Claude Max, ChatGPT Pro) plus an always-on local machine are idle capacity at zero or pre-paid marginal cost overnight. Existing tools either measure usage after the fact (ccusage) or do FinOps reporting; none match a real backlog to idle owned capacity and execute it while the operator sleeps. The scarce resource is idle agent capacity on infrastructure already paid for — not the subscription's headline number. The pain is concrete: a backlog of small, validatable tasks sits untouched while pre-paid capacity expires unused every night.

---

## Key Decisions

- **Local-first lanes.** The only truly-free lane is local (OpenClaw/Ollama, $0). Cloud lanes are headroom-gated and treated as not-free. The dispatcher prefers the cheapest lane with idle headroom and escalates off local only on validation failure.
- **Value over tokens.** Tasks are ranked by `value` (high/med/low), never by tokens consumed. Token/credit usage is recorded for economics and honesty, never used to prioritize or to look busy.
- **Honesty over engagement.** The morning report must be willing to recommend downgrading a chronically underused subscription. Reporting optimizes for the operator's interest, not for making the tool look productive.
- **Two adapter seams from day one.** Backends and backlog sources sit behind two interfaces — the only API-wrapper-shaped parts of the system — so V2 slots in as new adapters. `BackendAdapter`: `probe_headroom() -> Capacity` and `dispatch(task) -> Result`. `BacklogSource`: `fetch() -> [Task]`, each Task normalized to `{id, source, title, body, est_complexity, est_context_tokens, validator, value}`.
- **Deterministic dispatch only.** Backend selection is rule-based — no ML routing, no learned policy. Rules: in `value` order, pick the cheapest lane that has idle headroom and can plausibly clear the task's validator.
- **Escalation discipline.** At most one escalation per task (local → a cloud lane) on validation failure; if it still fails, the task is parked for human review, not retried in a loop.
- **Hard stop conditions.** A night ends on headroom exhaustion across eligible lanes, or on reaching a configured nightly task cap or spend cap — whichever comes first.
- **Stable ledger from V1.** The SQLite `runs` schema includes `predicted_lo` / `predicted_hi` columns from V1 (nullable until V2's preflight populates them), so V2 adds rows of meaning, not a migration.
- **Budget fallback when headroom is opaque.** When a lane's remaining headroom cannot be read programmatically, the lane falls back to a configured per-night budget rather than being disabled.
- **Stack: Python 3.12 + standard library.** `subprocess` orchestrates the headless agent CLIs; `sqlite3` is the ledger; one small dependency (PyYAML) reads config. Chosen for subprocess-orchestration fit, spike velocity, and operator toolchain match.
- **Completed-task output: labeled branch, PR opt-in.** A passing task lands on its own labeled branch; opening a PR is a per-source config toggle, default off. Low overnight GitHub noise; the operator reviews branches from the report.

---

## Actors

- A1. **Operator** — the single human. Configures sources, lanes, and caps; reviews the morning report and the resulting branches. No multi-tenant, no auth.
- A2. **Backlog source** — an adapter that fetches real tasks and normalizes them (V1: GitHub issues, TODO/FIXME scan).
- A3. **Backend lane** — an adapter that reports idle headroom and dispatches a task (V1: local, Claude headless).
- A4. **Dispatcher** — the deterministic core that orders tasks by value and matches each to a lane.
- A5. **Validator** — runs the task's configured check inside an isolated worktree and gates on the outcome.

---

## Key Flows

- F1. **Nightly run.** Ingest real tasks from all configured sources → probe headroom on all eligible lanes → for each task in value order, dispatch to the cheapest eligible lane in an isolated worktree → validate → on pass, keep the branch; on fail, escalate once or park → repeat until a stop condition → write the morning report.
- F2. **Escalation.** **Trigger:** a task fails its validator on the local lane. The dispatcher escalates to the cheapest cloud lane with headroom that can plausibly clear the validator, once. **Covers R10, R11.** If that also fails validation, the task is parked for human review.
- F3. **Stop conditions.** **Trigger:** headroom exhausted across eligible lanes, OR the nightly task cap reached, OR the nightly spend cap reached. The run stops cleanly, leaving the backlog remainder for the next night and recording why it stopped.
- F4. **Morning report.** After the run, summarize what ran, what passed, per-lane consumption, backlog remaining, and a downgrade recommendation when a paid lane was chronically underused. **Covers R16–R20.**

---

## Requirements

**Backlog ingest**

- R1. Pull tasks only from real configured sources via `BacklogSource.fetch()`; never synthesize a task. No backlog item → no run.
- R2. Normalize every task to `{id, source, title, body, est_complexity, est_context_tokens, validator, value}`. `validator` is one of `test | typecheck | build | none | custom-cmd`; `value` is one of `high | med | low`.
- R3. V1 sources are GitHub issues and a repo TODO/FIXME scan. Source `value`/priority is derived from the source's own signals (e.g., issue labels) with a configured default when absent.

**Capacity probing**

- R4. Probe headroom per lane via `BackendAdapter.probe_headroom()` before dispatch: local is always available at $0; Claude reports remaining headless headroom.
- R5. When a lane's headroom cannot be read programmatically, fall back to a configured per-night budget for that lane (R8 still applies).
- R6. Treat cloud lanes as headroom-gated and not-free; only the local lane is free.

**Dispatch (core IP)**

- R7. Process tasks in `value` order (high → med → low).
- R8. For each task, pick the cheapest lane that (a) has idle headroom and (b) can plausibly clear the task's validator. Local-first.
- R9. Selection uses deterministic rules only — no ML routing, no learned policy.
- R10. Escalate off the local lane to a cloud lane only after a validation failure, and at most once per task.
- R11. After a single failed escalation, park the task for human review; do not retry further.

**Validation & isolation**

- R12. Run each task's configured validator; keep only results that pass.
- R13. Execute each task in its own git worktree/branch so concurrent and sequential tasks do not collide.
- R14. On pass, leave a labeled branch; opening a PR is a config toggle, default off.
- R15. On fail-then-park, preserve the branch/worktree state needed for human review and record the parked status.

**Ledger & report**

- R16. Record every attempt in a SQLite `runs` table: `task_id, source, backend, predicted_lo, predicted_hi, consumed, validation_result, passed, escalated, branch, ts`. `predicted_lo`/`predicted_hi` are nullable in V1.
- R17. The morning report states what ran, what passed, per-lane consumption, and backlog remaining.
- R18. The report recommends downgrading a subscription when its lane was chronically underused, with the underuse evidence.
- R19. The report is a markdown artifact the operator reads after the run.
- R20. Consumption is reported for economics and honesty, never used to rank or to inflate apparent productivity.

**Config & runtime**

- R21. A single `nightsweeper.config.yaml` defines backlog sources, backends + caps, the nightly task/$ cap, the per-task cap, and validators.
- R22. Run as a local cron/launchd job — no hosted dependency, no telemetry.
- R23. Use a local SQLite store; nothing leaves the machine except calls the chosen lanes already make.
- R24. Respect the nightly task cap and nightly spend cap as hard stop conditions; respect a per-task cap where applicable.

**Guardrails (first-class)**

- R25. Never invent work (restates R1 as an inviolable principle).
- R26. Rank by value, never by tokens consumed (restates R7/R20 as an inviolable principle).
- R27. The report must be willing to recommend a downgrade — honesty over engagement (restates R18 as an inviolable principle).
- R28. Local is the only free lane; cloud lanes are headroom-gated (restates R6 as an inviolable principle).

---

## Acceptance Examples

- AE1. **Covers R1, R25.** No tasks returned by any source → the night does not run; the report records "no backlog, no run."
- AE2. **Covers R8, R10.** Local has headroom and clears the task's validator → the task passes on local with no escalation; only local consumption is recorded.
- AE3. **Covers R10, R11.** Local fails the validator → one escalation to the cheapest cloud lane with headroom → if it passes, keep the branch; if it fails again, park for human review (no further retries).
- AE4. **Covers F3, R24.** Headroom is exhausted across eligible lanes mid-run → the run stops, the remaining backlog is left intact, and the report records the stop reason.
- AE5. **Covers R5.** A lane's headroom cannot be read programmatically → that lane runs against its configured per-night budget instead of being disabled.
- AE6. **Covers R18, R27.** A paid lane was available all week but cleared almost nothing → the report recommends downgrading that plan and shows the underuse evidence.
- AE7. **Covers R24.** The nightly task cap or spend cap is reached → the run stops cleanly even if backlog and headroom remain.

---

## Scope Boundaries

**Deferred for later (V2, same architecture)**

- Codex backend lane (`codex exec` against ChatGPT Plus/Pro quota), added as a new `BackendAdapter`.
- Linear and Gbrain backlog sources, added as new `BacklogSource` adapters. Gbrain is a source only if its MCP exposes a usable backlog with value/priority signals; otherwise it stays a read-only context enricher.
- Preflight cost prediction: `estimate(task, backend) -> (cost_lo, cost_hi)` recorded before dispatch, predicted-vs-actual logging, and a per-task cost cap that may skip over-budget tasks.

**Outside this product's identity (non-goals, both phases)**

- No generic model router / gateway — that is commodity (OpenRouter/Portkey own it).
- No request-level optimization for interactive sessions.
- No hosted dashboard, no auth, no multi-tenant. Single operator only.
- No ML routing.
- No context-packer; shell out to repomix if context packing is ever needed.

---

## Dependencies / Assumptions

- **Claude headless economics (V1, riskiest).** The operating assumption, per the brief, is that as of 2026-06-15 headless `claude -p` / Agent SDK usage bills against a separate, capped credit pool — so the Claude lane is headroom-gated, not free overnight. The system is designed around this regardless; a spike confirms the economics on the operator's account before relying on the lane.
- **Headroom readability (V1, riskiest).** Whether remaining headroom can be read programmatically for local and Claude is unverified; if not, R5's budget fallback is the path. A spike determines which.
- **Local task-clearing rate (V1, riskiest).** Whether the local lane clears enough real tasks to be worth running (vs. everything escalating) is unverified. A 10-task spike reports the pass rate.
- **Codex headroom readability (V2).** Whether Codex 5h/weekly headroom is machine-readable or only inferable from failures is unverified; a spike decides before the V2 lane relies on it.
- **Gbrain MCP surface (V2).** Whether Gbrain's MCP exposes a backlog with value/priority signals (vs. memory retrieval only) is unverified; a spike decides whether it is a source or only an enricher.
- **Preflight accuracy (V2).** Whether `[predicted_lo, predicted_hi]` brackets actual cost ≥70% of the time on a 20-task replay is unverified; below that bar, preflight ships advisory-only, not as a gate.

---

## Outstanding Questions

**Resolve Before Planning** — none; product decisions are settled above.

**Deferred to Planning**

- The validator-plausibility model: how the dispatcher deterministically decides a lane "can plausibly clear" a task's validator (e.g., a config capability matrix by validator type and complexity tier, with validation+escalation as the safety net).
- The exact per-lane headroom-probe mechanics (what is read, and the budget-fallback trigger).
- The worktree lifecycle and cleanup policy (success vs. parked vs. failed).

---

## Success Criteria

- On a real backlog, real passing tasks land as labeled branches overnight with no invented work.
- The local lane clears a meaningful fraction of tasks on its own — measured as the pass rate of the 10-task local spike, which the plan reports before the lane is trusted as the default.
- The morning report is honest: it surfaces per-lane consumption and recommends a downgrade when the evidence warrants, even though that makes the tool look less busy.
- V2 lands as new adapters plus the preflight hook, with no change to the V1 dispatcher core, ledger schema, or isolation model.
