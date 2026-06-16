// The Agents — your overnight crew. Each agent is a harness over a model:
//   kind 'aider'  → local Ollama model via Aider (free)
//   kind 'codex'  → `codex exec` on your ChatGPT plan quota ($0 marginal)
//   kind 'claude' → headless `claude -p` on the Agent SDK credit (metered)
// Every agent: probe() -> {available, usage}, dispatch(task, workdir, ctx) -> {ok, consumedUsd, error}.
// Ported from the Python reference (reference parity bar = its 127 tests).

import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { globSync } from 'node:fs';
import path from 'node:path';

const COMPLEXITY = { low: 0, medium: 1, high: 2 };

export function allows(capability, validator, complexity) {
  const vals = capability?.validators ?? ['test', 'typecheck', 'build', 'none', 'custom-cmd'];
  const max = capability?.max_complexity ?? 'high';
  return vals.includes(validator) && COMPLEXITY[complexity] <= COMPLEXITY[max];
}

function scrubbedEnv() {
  const e = { ...process.env };
  delete e.ANTHROPIC_API_KEY;
  return e;
}

async function ollamaUp(host) {
  try {
    const r = await fetch(host.replace(/\/$/, '') + '/api/tags', { signal: AbortSignal.timeout(3000) });
    return r.ok;
  } catch {
    return false;
  }
}

function newestCodexRateLimits(sessionsDir) {
  try {
    const files = globSync(path.join(sessionsDir.replace('~', homedir()), '**/rollout-*.jsonl')).sort();
    if (!files.length) return null;
    let rl = null;
    for (const line of readFileSync(files[files.length - 1], 'utf8').split('\n')) {
      if (!line.includes('"rate_limits"')) continue;
      try {
        const d = JSON.parse(line);
        const p = d.payload ?? d;
        if (p.type === 'token_count' && p.rate_limits) rl = p.rate_limits;
      } catch {}
    }
    return rl;
  } catch {
    return null;
  }
}

export function makeAgent(cfg, { ledger, nightStart } = {}) {
  const o = cfg.options ?? cfg;
  const base = { name: cfg.name, kind: cfg.kind, costRank: cfg.cost_rank ?? 0, capability: cfg.capability };

  if (cfg.kind === 'aider' || cfg.kind === 'ollama') {
    const model = o.model ?? 'qwen2.5-coder:7b';
    const host = o.ollama_host ?? 'http://localhost:11434';
    return {
      ...base,
      async probe() {
        const up = await ollamaUp(host);
        return { available: up, usage: up ? `local ${model} · free ($0)` : `local ${model} · Ollama unreachable` };
      },
      estimateUsd: () => 0,
      dispatch(task, workdir) {
        const prompt = `${task.title}\n\n${task.body ?? ''}`;
        const bin = o.aider_bin ?? 'aider';
        const args = ['--model', `ollama_chat/${model}`, '--edit-format', o.edit_format ?? 'whole',
          '--yes-always', '--no-auto-commits', '--no-stream', '--no-check-update',
          ...(o.extra_args ?? []), '--message', prompt];
        const env = { ...scrubbedEnv(), OLLAMA_API_BASE: host };
        const r = spawnSync(bin, args, { cwd: workdir, env, encoding: 'utf8', timeout: (o.timeout_sec ?? 1800) * 1000 });
        if (r.error?.code === 'ENOENT') return { ok: false, consumedUsd: 0, error: 'aider not found' };
        return { ok: r.status === 0, consumedUsd: 0, error: r.status === 0 ? null : `aider exit ${r.status}` };
      },
    };
  }

  if (cfg.kind === 'codex') {
    const sessionsDir = o.sessions_dir ?? '~/.codex/sessions';
    const maxUsed = o.max_used_percent ?? 95;
    return {
      ...base,
      async probe() {
        const rl = newestCodexRateLimits(sessionsDir);
        if (!rl) return { available: true, usage: 'ChatGPT quota · $0 · windows unread (optimistic)' };
        const p = rl.primary?.used_percent ?? 0, s = rl.secondary?.used_percent ?? 0;
        const available = Math.max(p, s) < maxUsed;
        return { available, usage: `ChatGPT quota · $0 · 5h ${p}% used · weekly ${s}% used${available ? '' : '  ⚠ EXHAUSTED'}` };
      },
      estimateUsd: () => 0,
      dispatch(task, workdir) {
        const prompt = `${task.title}\n\n${task.body ?? ''}`;
        const args = ['exec', '--json', '--skip-git-repo-check', '--sandbox', o.sandbox_mode ?? 'workspace-write'];
        if (o.model) args.push('--model', o.model);
        args.push(prompt);
        const r = spawnSync('codex', args, { cwd: workdir, env: scrubbedEnv(), encoding: 'utf8', timeout: (o.timeout_sec ?? 1800) * 1000 });
        if (r.error?.code === 'ENOENT') return { ok: false, consumedUsd: 0, error: 'codex not found' };
        if (/rate limit/i.test(r.stderr ?? '')) return { ok: false, consumedUsd: 0, error: 'codex rate-limited' };
        return { ok: r.status === 0, consumedUsd: 0, error: r.status === 0 ? null : `codex exit ${r.status}` };
      },
    };
  }

  // claude (metered Agent SDK credit; budget-gated, fail-closed)
  const model = o.model ?? 'claude-sonnet-4-6';
  const budget = Number(o.nightly_budget ?? 0), floor = Number(o.per_task_floor ?? 0);
  const remaining = () => budget - (ledger?.spendSince?.(cfg.name, nightStart) ?? 0);
  return {
    ...base,
    async probe() {
      const r = remaining();
      const available = r > 0 && r >= floor;
      return { available, usage: `Agent SDK credit · $${r.toFixed(2)} of $${budget.toFixed(2)} left tonight${available ? '' : '  ⚠ exhausted'}` };
    },
    estimateUsd: () => 0,
    dispatch(task, workdir) {
      if (process.env.ANTHROPIC_API_KEY) return { ok: false, consumedUsd: 0, error: 'ANTHROPIC_API_KEY set (uncapped-bill guard)' };
      if (remaining() < floor) return { ok: false, consumedUsd: 0, error: 'below per-task budget floor' };
      const prompt = `${task.title}\n\n${task.body ?? ''}`;
      const args = ['-p', '--output-format', 'json', '--dangerously-skip-permissions', '--model', model, prompt];
      const r = spawnSync('claude', args, { cwd: workdir, env: scrubbedEnv(), encoding: 'utf8', timeout: (o.timeout_sec ?? 1800) * 1000 });
      if (r.error?.code === 'ENOENT') return { ok: false, consumedUsd: 0, error: 'claude not found' };
      if (r.status !== 0) return { ok: false, consumedUsd: 0, error: `claude exit ${r.status}` };
      try {
        const payload = JSON.parse(r.stdout);
        return { ok: true, consumedUsd: Number(payload.total_cost_usd ?? 0), error: null };
      } catch (e) {
        return { ok: false, consumedUsd: 0, error: `unparseable claude JSON: ${e.message}` };
      }
    },
  };
}
