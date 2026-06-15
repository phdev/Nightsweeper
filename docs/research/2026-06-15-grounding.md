# Nightsweeper grounding research — 2026-06-15

Condensed findings behind the plan's spikes and risk treatment. Each topic was
researched against current (mid-2026) web sources; the Claude billing claim was
adversarially re-verified.

## 1. Claude headless billing — CORROBORATED (high)

As of **2026-06-15**, `claude -p` (non-interactive) and the Claude Agent SDK no
longer count toward the interactive Pro/Max usage limits. They draw from a
**separate, dollar-denominated monthly credit** billed at standard API rates:
**$20 Pro / $100 Max 5x / $200 Max 20x** (Team $20/$100; Enterprise $20/$200).
Credit resets each cycle, **no rollover**, must be claimed once, and is **per-seat
(not pooled)**.

- When the credit is exhausted: requests **stop** unless "usage credits" overflow
  is enabled, in which case they bill **uncapped** at API rates.
- $200 Max-20x credit ≈ ~13.3M Opus / ~22M Sonnet / ~67M Haiku tokens/month
  (2–3× with prompt caching). A sustained nightly Opus loop exhausts it in days.
- `ANTHROPIC_API_KEY` set in the environment overrides credit routing and bills
  uncapped pay-as-you-go (issue #37686: ~$1,800 in 2 days). A reported bug
  (#43333, v2.1.91) mis-routed `claude -p` to the API dashboard even under pure
  OAuth — fix status unconfirmed.
- Interactive Claude Code (TTY/IDE) and Claude.ai chat are unchanged (5h rolling
  window + weekly cap), but are not designed/sanctioned for unattended scheduling.

**Design guidance:** treat the Claude lane as metered API spend; **fail-closed**
by default; run with `env -u ANTHROPIC_API_KEY`; verify spend lands on the Agent
SDK credit; per-night $ cap; prefer Sonnet/Haiku + caching, reserve Opus.

Sources: support.claude.com/en/articles/15036540, thenewstack.io/anthropic-agent-sdk-credits,
github.com/anthropics/claude-code/issues/37686, .../issues/43333.

## 2. Reading Claude headroom programmatically — (high)

There is **no supported, scriptable call that returns live remaining subscription
or credit headroom** on a subscription (Max/Pro, claude.ai OAuth) machine.

- Only live signal: `anthropic-ratelimit-unified-5h-utilization` / `-7d-utilization`
  / `-reset` / `-status` HTTP headers on Claude Code's own traffic — **not exposed**
  to hooks/statusline/CLI; must be captured from live traffic (proxy, or possibly
  `claude --debug api`). Each capture costs a little quota.
- ccusage, Claude Code OTEL metrics, `~/.claude/stats-cache.json`, and the local
  `~/.claude/projects/**/*.jsonl` logs are **consumption counters** reconstructed
  after-the-fact — no `remaining`/`limit`/`reset` field.
- `claude -p --output-format json` returns per-run `total_cost_usd` + token usage.
- A `429` + `retry-after` / `unified-status==rate_limited` is the only other live
  signal.

**Design guidance:** the **budget-fallback is the primary path** for the Claude
lane (configured per-night $ cap), with consumption read from each run's JSON
output and reconciled against local logs for the report — not a live-headroom gate.

## 3. Local agent capability — (medium)

A free local lane is real but **narrow**, and best used as a **first-pass filter**
with executable verification + cloud escalation.

- Best locally-runnable coding models: **Qwen3-Coder-30B-A3B** (~18GB Q4, agentic
  tool-loops, ~52% SWE-bench-Verified), Qwen2.5-Coder-32B (codegen), Devstral-Small
  (tool-calling robust). **Gemma is not a coding specialist** — keep it as a cheap
  generalist for non-agentic subtasks only.
- Benchmark-vs-reality gap is large: grep-scored "passes" collapse under real test
  execution — **gate every local task on executable validation**, never self-report.
- **OpenClaw** is a real open-source, self-hosted Claude-Code-like agent (formerly
  Clawdbot) that drives local Ollama models via `/api/chat`; headless invocation
  e.g. `openclaw infer model run --model ollama/<m> --prompt ... --json`. Broad
  shell/file/browser permissions ⇒ sandbox for unattended runs.
- Realistic routing: ~60–80% of routine tasks clear locally; hard multi-file
  refactors/debugging should escalate.

## 4. Codex exec quota (V2) — (high)

`codex exec --json` emits `rate_limits: null` (fix WONTFIX). No official
`codex status --json`. Read headroom by **scraping the newest
`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`** for the latest
`token_count.rate_limits` ({primary, secondary}: used_percent, window_minutes,
resets_in_seconds) — populated by interactive/app-server sessions, possibly not
by exec-only. Undocumented internal `GET /api/codex/usage` is the alternative.
Fallback: infer exhaustion from rate-limit errors. Windows: ~5h primary + ~weekly
secondary, token-denominated.

## 5. Worktree isolation — (high)

`git worktree add <path> -b <branch> origin/HEAD`; keep worktrees under a
gitignored dir; copy needed gitignored config in (`.worktreeinclude`); worktrees
isolate **files only** (ports/DB/caches still shared). Handoff: `git push -u
origin HEAD` first (no gh flag auto-pushes), then `gh pr create -R <owner/repo>
--base <default> --head <branch> --title ... --body ... [--draft] [--label]`.
Cleanup: `git worktree remove [--force]` + `git worktree prune`; watch the Claude
Code `extensions.worktreeConfig` leftover bug. Recommended handoff = **labeled
branch always, draft PR optionally** — exactly the chosen default. Cap ~5–7
concurrent.

## 6. Local scheduling — (high)

macOS: a per-user **LaunchAgent** with `StartCalendarInterval` (cron is deprecated
+ TCC friction). launchd gives **single-instance for free** (won't overlap).
Biggest risk: a sleeping/off Mac may not fire — **guarantee wake** with `pmset
repeat wakeorpoweron` and run under `caffeinate -is`; a missed-while-off run is
**not** caught up, so add a sentinel-file **self-heal** check on next launch. Add
`flock` for scheduler-agnostic single-instance. Linux equivalent: systemd timer
with `Persistent=true`.

## Spike results — run 2026-06-15

### S1 — Claude economics (1 bounded real call) — DECISION: keep the lane on

A single small Sonnet (`claude-sonnet-4-6`) task via
`env -u ANTHROPIC_API_KEY claude -p --output-format json` cost **$0.0553**
(`total_cost_usd` parsed cleanly). Extrapolation at ~$0.05/small task: a $3/night
cap ≈ 3–15 real tasks/night and ~$90/month — within a Max-5x $100 monthly Agent
SDK credit. Real repo-context agentic tasks cost more, so the conservative default
holds: **`nightly_budget: 3.00`, `per_task_floor: 0.50`, default model Sonnet**.
**Open item (operator-only):** verify the spend landed on the Agent SDK *credit*,
not pay-as-you-go API (bug #43333) — check your account → credits once.

### S2 — Claude headroom readability — DECISION: budget-fallback confirmed

`claude --debug api -p 'hi'` surfaced **no** `anthropic-ratelimit-unified-*`
headers locally. There is no supported scriptable live-remaining read on this
subscription machine. **The Claude lane's `probe_headroom` stays budget-gated
(KTD2)** — `nightly_budget − spent_tonight` from the ledger — as designed.

### S3 — local pass rate — DECISION: local-first holds; local owns ≤ medium

OpenClaw is not installable on this machine and the planned Qwen3-Coder-30B was
not pulled, so S3 ran via the **Ollama-direct fallback** (`spikes/s3_ollama_direct.py`)
on **`qwen2.5-coder:7b`** — single-shot codegen + real `pytest` validation, a
**conservative floor** (an agentic OpenClaw loop and a 30B model would do better).
Result on 4 real tasks:

| Tier | Pass rate |
|---|---|
| low | **2/2 = 100%** |
| medium | **1/2 = 50%** |
| aggregate | **3/4 = 75%** |

The one medium miss (`merge_intervals`) is exactly the case the dispatcher
**escalates** to the Claude lane on validation failure — the designed behavior.
**Decisions:** (1) local-first is justified — even a single-shot 7B clears all easy
tasks for free; (2) set local `capability.max_complexity: medium` (50% floor at
medium, escalation covers the misses) — the conservative operator may pin `low`
(100% measured); (3) on this machine the validated runnable model is
`qwen2.5-coder:7b` (Qwen3-Coder-30B remains the recommended agentic upgrade once
pulled). The example config's `max_complexity: medium` is supported by this data.
