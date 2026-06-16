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

test('zero chores → no run', async () => {
  const d = new Dispatcher([], fakeIso, { validate: () => {} }, fakeLedger(), { caps: { nightly_task_cap: 5, nightly_dollar_cap: 5 } });
  const s = await d.run([]);
  assert.equal(s.tasks_total, 0);
  assert.equal(s.dispatched, 0);
});
