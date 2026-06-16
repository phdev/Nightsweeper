import { test } from 'node:test';
import assert from 'node:assert';
import { allows, makeAgent } from '../lib/agents.mjs';

const FULL = { validators: ['test', 'typecheck', 'build', 'none', 'custom-cmd'], max_complexity: 'high' };

test('allows: capability gates on both validator and complexity', () => {
  assert.equal(allows(FULL, 'test', 'high'), true);
  assert.equal(allows({ validators: ['test'], max_complexity: 'low' }, 'test', 'low'), true);
  assert.equal(allows({ validators: ['test'], max_complexity: 'low' }, 'test', 'high'), false); // too complex
  assert.equal(allows({ validators: ['test'], max_complexity: 'high' }, 'build', 'low'), false); // validator not allowed
});

test('allows: permissive defaults when capability is omitted', () => {
  assert.equal(allows(undefined, 'custom-cmd', 'high'), true);
});

test('every agent kind exposes probe/dispatch/estimate', () => {
  for (const kind of ['aider', 'codex', 'claude']) {
    const a = makeAgent({ name: kind, kind, cost_rank: 0, capability: FULL }, {});
    assert.equal(typeof a.probe, 'function');
    assert.equal(typeof a.dispatch, 'function');
    assert.equal(typeof a.estimate, 'function');
  }
});

test('estimate is dormant without a cost_model, active with one', () => {
  const free = makeAgent({ name: 'qwen', kind: 'aider', cost_rank: 0, capability: FULL }, {});
  assert.equal(free.estimate({ est_context_tokens: 50000 }), null);
  const paid = makeAgent({ name: 'claude', kind: 'claude', cost_rank: 2, capability: FULL, options: { cost_model: { input_per_mtok: 3, output_per_mtok: 15 } } }, {});
  const est = paid.estimate({ est_context_tokens: 1_000_000 });
  assert.ok(est && est.lo > 0 && est.hi > est.lo);
});

test('claude dispatch hard-refuses when ANTHROPIC_API_KEY is set (uncapped-bill guard)', () => {
  const saved = process.env.ANTHROPIC_API_KEY;
  process.env.ANTHROPIC_API_KEY = 'sk-test';
  try {
    const a = makeAgent({ name: 'claude', kind: 'claude', cost_rank: 2, capability: FULL, options: { nightly_budget: 5, per_task_floor: 0 } },
      { ledger: { spendSince: () => 0 }, nightStart: 'x' });
    const r = a.dispatch({ title: 't', body: 'b' }, '/wd');
    assert.equal(r.ok, false);
    assert.match(r.error, /ANTHROPIC_API_KEY/);
  } finally {
    if (saved === undefined) delete process.env.ANTHROPIC_API_KEY; else process.env.ANTHROPIC_API_KEY = saved;
  }
});

test('claude dispatch refuses below the per-task budget floor (no spend)', () => {
  const saved = process.env.ANTHROPIC_API_KEY;
  delete process.env.ANTHROPIC_API_KEY;
  try {
    const a = makeAgent({ name: 'claude', kind: 'claude', cost_rank: 2, capability: FULL, options: { nightly_budget: 1, per_task_floor: 0.5 } },
      { ledger: { spendSince: () => 0.8 }, nightStart: 'x' });   // remaining 0.2 < floor 0.5
    const r = a.dispatch({ title: 't', body: 'b' }, '/wd');
    assert.equal(r.ok, false);
    assert.match(r.error, /floor/);
  } finally {
    if (saved !== undefined) process.env.ANTHROPIC_API_KEY = saved;
  }
});

test('claude probe reports exhaustion when the nightly budget is spent', async () => {
  const a = makeAgent({ name: 'claude', kind: 'claude', cost_rank: 2, capability: FULL, options: { nightly_budget: 3, per_task_floor: 0.5 } },
    { ledger: { spendSince: () => 3 }, nightStart: 'x' });   // 0 remaining
  const p = await a.probe();
  assert.equal(p.available, false);
  assert.match(p.usage, /exhausted/);
});
