# Nightsweeper 🌙

**Your overnight AI agent crew.** You keep a list of chores. While you sleep,
Nightsweeper hands each one to the cheapest **agent** that's free right now — a local
one (Qwen, free), or a cloud one you already pay for (Codex on your ChatGPT plan = $0,
or Claude) — **checks the agent actually did it** (runs your tests), and keeps only
the good work. Each finished chore lands on its own git branch for you to review, with
a morning report waiting.

It never invents work, ranks by value (not tokens), runs local-first, and is honest
about what your paid plans are actually earning you.

## Install

```bash
# from npm (once published):
npm install -g nightsweeper      # or: npx nightsweeper

# from source (today):
git clone https://github.com/phdev/Nightsweeper.git && cd Nightsweeper
npm install
node bin/nightsweeper.mjs        # opens the hub
```

You also need at least one **agent**. The free local one is Ollama + a model + Aider:
```bash
brew install ollama && ollama pull qwen2.5-coder:7b
python3 -m venv ~/.aider-venv && ~/.aider-venv/bin/pip install aider-chat
```
(Or use the `codex` / `claude` CLIs you already have — the setup wizard detects them.)

## Quick start

```bash
nightsweeper setup     # pick your agents, write a config (guided)
nightsweeper           # open the interactive hub
```

The hub (`nightsweeper` with no args) is your control room:

```
🌙  What do you want to do?
  📖  How it works
  🤖  Your agents & energy        ← who's on the crew + how much energy each has left
  ✅  Check chore readiness        ← which chores need enrichment to be provable
  ✏️   Edit chores
  ⏰  Scheduling                   ← confirm when it runs each night
  🌅  Morning report               ← what got done last night
  ▶️   Run now
```

## How it works

```
your chores  →  pick the cheapest FREE agent that can do it
             →  it edits the code in an isolated git worktree
             →  CHECK it: run your tests + any quality gates
             →  passed → keep the branch · failed → escalate once → else set aside
             →  morning report: what's done, what's set aside, what each agent cost
```

**The golden rule:** every chore needs a *"did it work?"* check. If you can't say how an
agent would **prove** it finished (a test, a build, a command that exits 0), it's a wish,
not a chore — Nightsweeper sets it aside instead of guessing. Run **Check chore readiness**
and it tells you exactly which chores need enrichment and why.

A chore is just YAML:
```yaml
- id: fix-add
  title: "Implement add(a, b)"
  body: "Write add(a, b) in solution.py returning their sum."
  validator: test            # how we prove it: run the tests
  value: high
# or give a chore its own proof command:
- id: write-docs
  title: "Write QA-PLAN.md with CLI + Dashboard sections"
  body: "Create QA-PLAN.md covering each surface."
  validator_cmd: "test -f QA-PLAN.md && grep -qi '## CLI' QA-PLAN.md"
  value: med
```

## The agents

| Agent | Marginal cost | Runs on |
|---|---|---|
| **qwen** (local, via Aider/OpenClaw + Ollama) | **$0** | your machine |
| **codex** (`codex exec`) | **$0** | your ChatGPT Plus/Pro quota |
| **claude** (`claude -p`) | metered (pre-paid Agent SDK credit) | your Claude Max/Pro credit |

Before any run you can pick which agents to use and see each one's live energy:
```
🟢 qwen     local qwen2.5-coder:7b · free ($0)
🟢 codex    ChatGPT quota · $0 · 5h 1% used · weekly 21% used
🟢 claude   Agent SDK credit · $2.00 of $3.00 left tonight
```

## Commands

```bash
nightsweeper                 the interactive hub
nightsweeper setup           onboarding wizard
nightsweeper run [--lanes qwen,codex] [--print]
nightsweeper agents          your agents + energy
nightsweeper readiness       which chores are ready vs need enrichment
nightsweeper report          the latest morning report
nightsweeper install-scheduler   run every night automatically (launchd)
```

## Run it every night

```bash
nightsweeper install-scheduler   # then run the launchctl + pmset lines it prints
```
Runs under `caffeinate` so the Mac stays awake; reports land in your repo each morning.

## Status

**Node rewrite — feature-complete, pending first publish.** Native Node (no Python at
runtime): the interactive hub, onboarding wizard, agents + energy, chore-readiness, and
the dispatcher / validator / adjudication-gates / git-isolation / report engine. Backlog
sources: an authored `tasks_file`, GitHub issues, Apple Notes (heading-scoped), Linear,
and `todo_scan` (enrolled `TODO(nightsweeper: …)` markers only — bare TODOs are left
alone). The morning report always prints per-agent utilization and recommends downgrading
a paid-but-underused agent. Preflight cost prediction is wired (advisory by default; an
opt-in `preflight.mode: gate` parks chores over `per_task_cap`). **46 tests** —
`npm test`. Publishing is set up via OIDC Trusted Publishing (no stored npm token) —
see [`RELEASING.md`](RELEASING.md) for the one-time bootstrap + the tokenless release flow.

The original Python implementation (127 tests, V1 + V2) remains under `nightsweeper/` as
the reference spec and will be archived once the Node version is published.

See `CLAUDE.md` for the architecture.
