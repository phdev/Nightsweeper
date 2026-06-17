import { test } from 'node:test';
import assert from 'node:assert';
import { Dispatcher } from '../lib/dispatcher.mjs';

function fakeLedger() {
  return { rows: [], record(r) { this.rows.push(r); }, hasRun() { return false; }, spendSince() { return 0; } };
}
const fakeIso = { create: () => '/wd', handoff: () => ({ branch: 'b', pushed: true }), cleanup: () => {} };
const cap = { validators: ['test'], max_complexity: 'high' };
const task = (id, value = 'high') => ({ id, source: 'tasklist', title: id, body: 'b', validator: 'test', value, est_complexity: 'low' });

test('cheapest available agent does the chore; pass recorded', async () => {
  const ledger = fakeLedger();
  const agent = { name: 'qwen', costRank: 0, capability: cap, probe: async () => ({ available: true }), dispatch: () => ({ ok: true, consumedUsd: 0 }) };
  const validator = { validate: () => ({ result: 'passed' }) };
  const d = new Dispatcher([agent], fakeIso, validator, ledger, { caps: { nightly_task_cap: 5, nightly_dollar_cap: 5 } });
  const s = await d.run([task('t1')]);
  assert.equal(s.passed, 1);
  assert.equal(ledger.rows[0].backend, 'qwen');
});

test('local fails → escalates once → claude passes', async () => {
  const ledger = fakeLedger();
  const local = { name: 'qwen', costRank: 0, capability: cap, probe: async () => ({ available: true }), dispatch: () => ({ ok: true, consumedUsd: 0 }) };
  const claude = { name: 'claude', costRank: 1, capability: cap, probe: async () => ({ available: true }), dispatch: () => ({ ok: true, consumedUsd: 0.1 }) };
  let calls = 0;
  const validator = { validate: () => ({ result: calls++ === 0 ? 'failed' : 'passed' }) };
  const d = new Dispatcher([local, claude], fakeIso, validator, ledger, { caps: { nightly_task_cap: 5, nightly_dollar_cap: 5 } });
  const s = await d.run([task('t1')]);
  assert.equal(s.passed, 1);
  assert.equal(ledger.rows.map((r) => r.backend).join(','), 'qwen,claude');
  assert.equal(ledger.rows[1].escalated, true);
});

test('escalation feeds the failure forward (deterministic ladder, not a blind re-run)', async () => {
  const ledger = fakeLedger();
  let ctxSeen = null;
  const local = { name: 'qwen', costRank: 0, capability: cap, probe: async () => ({ available: true }), dispatch: () => ({ ok: true, consumedUsd: 0 }) };
  const claude = { name: 'claude', costRank: 1, capability: cap, probe: async () => ({ available: true }),
    dispatch: (t, wd, ctx) => { ctxSeen = ctx; return { ok: true, consumedUsd: 0.1 }; } };
  let calls = 0;
  const validator = { validate: () => (calls++ === 0 ? { result: 'failed', detail: '`grep hello x` exited 1' } : { result: 'passed' }) };
  const d = new Dispatcher([local, claude], fakeIso, validator, ledger, { caps: { nightly_task_cap: 5, nightly_dollar_cap: 5 } });
  await d.run([task('t1')]);
  assert.ok(ctxSeen?.priorFailure, 'the escalated agent receives the prior failure detail');
  assert.equal(ctxSeen.priorFailure.agent, 'qwen');
  assert.match(ctxSeen.priorFailure.detail, /grep hello/);
});

test('zero chores → no run', async () => {
  const d = new Dispatcher([], fakeIso, { validate: () => {} }, fakeLedger(), { caps: { nightly_task_cap: 5, nightly_dollar_cap: 5 } });
  const s = await d.run([]);
  assert.equal(s.tasks_total, 0);
  assert.equal(s.dispatched, 0);
});

test('value orders the backlog — high before low, regardless of arrival order', async () => {
  const ledger = fakeLedger();
  const agent = { name: 'qwen', costRank: 0, capability: cap, probe: async () => ({ available: true }), dispatch: () => ({ ok: true, consumedUsd: 0 }) };
  const d = new Dispatcher([agent], fakeIso, { validate: () => ({ result: 'passed' }) }, ledger, { caps: { nightly_task_cap: 5, nightly_dollar_cap: 5 } });
  await d.run([task('lo', 'low'), task('hi', 'high'), task('mid', 'med')]);
  assert.deepEqual(ledger.rows.map((r) => r.task_id), ['hi', 'mid', 'lo']);
});

test('nightly task cap stops the night', async () => {
  const ledger = fakeLedger();
  const agent = { name: 'qwen', costRank: 0, capability: cap, probe: async () => ({ available: true }), dispatch: () => ({ ok: true, consumedUsd: 0 }) };
  const d = new Dispatcher([agent], fakeIso, { validate: () => ({ result: 'passed' }) }, ledger, { caps: { nightly_task_cap: 2, nightly_dollar_cap: 5 } });
  const s = await d.run([task('a'), task('b'), task('c'), task('d')]);
  assert.equal(s.stop_reason, 'nightly-task-cap');
  assert.equal(s.dispatched, 2);
});

test('nightly dollar cap stops the night', async () => {
  const ledger = fakeLedger();
  const agent = { name: 'claude', costRank: 0, capability: cap, probe: async () => ({ available: true }), dispatch: () => ({ ok: true, consumedUsd: 1 }) };
  const d = new Dispatcher([agent], fakeIso, { validate: () => ({ result: 'passed' }) }, ledger, { caps: { nightly_task_cap: 10, nightly_dollar_cap: 2 } });
  const s = await d.run([task('a'), task('b'), task('c'), task('d')]);
  assert.equal(s.stop_reason, 'nightly-dollar-cap');
  assert.ok(s.dispatched <= 3);   // stops once cumulative spend reaches the cap
});

test('preflight gate (opt-in) parks a chore whose estimate blows the per-task cap', async () => {
  const ledger = fakeLedger();
  const pricey = { name: 'claude', costRank: 0, capability: cap, probe: async () => ({ available: true }),
    estimate: () => ({ lo: 0.5, hi: 1.2 }), dispatch: () => ({ ok: true, consumedUsd: 0.5 }) };
  const d = new Dispatcher([pricey], fakeIso, { validate: () => ({ result: 'passed' }) }, ledger,
    { caps: { nightly_task_cap: 5, nightly_dollar_cap: 5, per_task_cap: 0.1 }, preflight: { mode: 'gate' } });
  const s = await d.run([task('t1')]);
  assert.equal(s.dispatched, 0);
  assert.match(ledger.rows[0].park_reason, /over-per-task-cap/);
  assert.equal(ledger.rows[0].predicted_lo, 0.5);
});

test('advisory mode (default) never gates — it only records predictions', async () => {
  const ledger = fakeLedger();
  const pricey = { name: 'claude', costRank: 0, capability: cap, probe: async () => ({ available: true }),
    estimate: () => ({ lo: 0.5, hi: 1.2 }), dispatch: () => ({ ok: true, consumedUsd: 0.5 }) };
  const d = new Dispatcher([pricey], fakeIso, { validate: () => ({ result: 'passed' }) }, ledger,
    { caps: { nightly_task_cap: 5, nightly_dollar_cap: 5, per_task_cap: 0.1 } });   // no preflight block → advisory
  const s = await d.run([task('t1')]);
  assert.equal(s.passed, 1);
  assert.equal(ledger.rows[0].predicted_lo, 0.5);
  assert.equal(ledger.rows[0].predicted_hi, 1.2);
});

test('a chore no agent can handle is parked, not dropped', async () => {
  const ledger = fakeLedger();
  const weak = { name: 'qwen', costRank: 0, capability: { validators: ['test'], max_complexity: 'low' }, probe: async () => ({ available: true }), dispatch: () => ({ ok: true, consumedUsd: 0 }) };
  const d = new Dispatcher([weak], fakeIso, { validate: () => ({ result: 'passed' }) }, ledger, { caps: { nightly_task_cap: 5, nightly_dollar_cap: 5 } });
  // 'big' is too complex for the only agent; 'small' is fine. big sorts first (high value).
  const big = { ...task('big', 'high'), est_complexity: 'high' };
  const small = task('small', 'low');
  await d.run([big, small]);
  const bigRow = ledger.rows.find((r) => r.task_id === 'big');
  assert.equal(bigRow.park_reason, 'no-eligible-agent');
  assert.equal(ledger.rows.find((r) => r.task_id === 'small').passed, true);
});
