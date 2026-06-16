import { test } from 'node:test';
import assert from 'node:assert';
import { mkdtempSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { Ledger } from '../lib/ledger.mjs';

function tmpLedger() {
  return new Ledger(path.join(mkdtempSync(path.join(tmpdir(), 'ns-')), 'nested', 'ledger.jsonl'));
}
const row = (o) => ({ task_id: 'a', backend: 'qwen', consumed: 0, passed: false, ts: '2026-06-16T01:00:00.000Z', ...o });

test('record persists to JSONL and reloads on reopen', () => {
  const l = tmpLedger();
  l.record(row({ task_id: 'x' }));
  assert.ok(existsSync(l.file));
  const reopened = new Ledger(l.file);
  assert.equal(reopened.hasRun('x'), true);
});

test('hasRun dedupes already-attempted chores', () => {
  const l = tmpLedger();
  assert.equal(l.hasRun('a'), false);
  l.record(row({ task_id: 'a' }));
  assert.equal(l.hasRun('a'), true);
  assert.equal(l.hasRun('b'), false);
});

test('spendSince sums only the named agent after the cutoff', () => {
  const l = tmpLedger();
  l.record(row({ backend: 'claude', consumed: 0.3, ts: '2026-06-16T02:00:00.000Z' }));
  l.record(row({ backend: 'claude', consumed: 0.2, ts: '2026-06-16T03:00:00.000Z' }));
  l.record(row({ backend: 'qwen', consumed: 9, ts: '2026-06-16T03:00:00.000Z' }));
  l.record(row({ backend: 'claude', consumed: 5, ts: '2026-06-15T00:00:00.000Z' })); // before cutoff
  assert.equal(l.spendSince('claude', '2026-06-16T00:00:00.000Z'), 0.5);
});

test('laneSummary aggregates attempts/passes/consumed per agent', () => {
  const l = tmpLedger();
  l.record(row({ backend: 'claude', passed: true, consumed: 0.2 }));
  l.record(row({ backend: 'claude', passed: false, consumed: 0.1 }));
  l.record(row({ backend: 'qwen', passed: true, consumed: 0 }));
  const s = l.laneSummary('2026-06-16T00:00:00.000Z');
  assert.ok(Math.abs(s.claude.consumed - 0.3) < 1e-9);
  assert.equal(s.claude.passes, 1);
  assert.equal(s.claude.attempts, 2);
  assert.equal(s.qwen.passes, 1);
});
