# CLAUDE.md — Nightsweeper repo notes for coding agents

Local-first, capacity-aware overnight scheduler. **Python 3.10+ stdlib + PyYAML.**
Read `docs/plans/2026-06-15-001-feat-nightsweeper-overnight-scheduler-plan.md` (the
build plan, V1 detail + V2 roadmap) and `docs/brainstorms/2026-06-15-nightsweeper-requirements.md`
(the requirements) before changing behavior.

## Architecture map

```
nightsweeper/
  models.py        Task (8 fields; est_context_tokens dormant), Capacity, Result, CostRange, RunRow
  config.py        load/validate nightsweeper.config.yaml (caps, capability matrix, …)
  env.py           assert_no_api_key / scrubbed_env  (Claude lane safety)
  ledger.py        SQLite `runs` (stable schema; predicted_lo/hi nullable)
  registry.py      config-driven name → adapter class maps (the seam)
  adapters/
    backend.py     BackendAdapter ABC: probe_headroom / dispatch(…, context=None) / estimate→None / bind_runtime
    backlog.py     BacklogSource ABC: fetch / inventory
  preflight.py     V2 cost model → CostRange (estimate); advisory by default
  backends/        aider.py (Aider→Ollama, proven), local.py (OpenClaw), claude_headless.py, codex.py [V2]
  sources/         github_issues.py, todo_scan.py (enrolled), tasklist.py (YAML/JSON list),
                   apple_notes.py (osascript), linear.py [V2]
  enrichers/       gbrain.py [V2] read-only context (no-op without MCP) + CompositeEnricher
  isolation.py     git worktree per task; push-then-optional-PR; cleanup+prune
  validator.py     run the configured validator in the worktree (executable; none→park)
  dispatcher.py    THE CORE IP — value order, capability gate, cost_rank select,
                   escalate-once-then-park, hard stops + early-stop
  report.py        morning report; always-on utilization + defined downgrade metric
  cli.py           run | probe | report | install-scheduler  (fcntl lock + sentinel)
  scheduling/      launchd plist + caffeinate run.sh + install.py
spikes/            S1/S2/S3 ready-to-run (safe by default; --go to execute)
```

## The two seams (how to extend — this is the V2 path)

Add a lane: subclass `BackendAdapter`, decorate with `@register_backend("name")`,
implement `probe_headroom`/`dispatch`; add a config entry with `cost_rank` + a
`capability` row. Add a source: subclass `BacklogSource`, `@register_source("name")`,
implement `fetch`. **The dispatcher never changes.** The dormant `estimate()` and
`dispatch(…, context=)` hooks + the `predicted_lo/hi` columns absorb V2 (Codex,
Linear, Gbrain, preflight) with no signature or schema change.

## Hard rules (do not regress)

- **Never invent work.** No backlog → no run. Bare TODOs are report-only inventory.
- **Value, never tokens.** `value` orders tasks; cost (`cost_rank`) only gates/selects
  among already-eligible lanes; `est_complexity`/`est_context_tokens` only gate
  eligibility — never ordering or selection.
- **Claude lane is budget-gated + fail-closed.** Never set `ANTHROPIC_API_KEY`
  (`dispatch` hard-refuses if present; grounding §1). No pre-dispatch estimate in V1;
  the $ cap is enforced post-run (overshoot bounded by one task's full escalation
  chain — up to two lane runs in V1).
- **Deterministic dispatch only** — no ML routing.
- **Report stays honest** — always print per-lane utilization, recommend downgrade
  when the metric fires.

## Environment realities (this machine)

- `python3` is 3.10 (not 3.12) → keep code 3.10+-compatible.
- `openclaw` and `flock` are **absent**. The local lane + spike S3 need OpenClaw +
  an Ollama model pulled; single-instance uses `fcntl` (in `cli.py`), not `flock`.
- Spike **S1 spends real Claude credit** and **S3 needs OpenClaw + a ~18GB model** —
  both are `--go`-gated; do not run them without an explicit decision.

## Testing

`.venv/bin/python -m pytest -q` (104 tests). Aider lane proven end-to-end on a real
worktree (tasklist → Aider+Qwen → validated branch). Adapters take injectable subprocess
seams (`_gh`, `_run_agent`, `_run_claude`, `_git`, `_run`) so logic is unit-tested
without live CLIs. `tests/conftest.py` holds the dispatcher/report test doubles;
`tests/test_end_to_end.py` runs the real loop with a real validator.

## Grounding

`docs/research/2026-06-15-grounding.md` — current facts behind the design (Claude
June-15 billing, headroom opacity, local-model capability, Codex quota, worktrees,
launchd). Update it with spike results.
