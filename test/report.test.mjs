import { test } from 'node:test';
import assert from 'node:assert';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { generateReport, downgradeCandidates } from '../lib/report.mjs';

function cfg(reportPath) {
  return {
    agents: [
      { name: 'qwen', cost_rank: 0, options: {} },
      { name: 'claude', cost_rank: 1, options: { nightly_budget: 5 } },
    ],
    report: { path: reportPath, downgrade: { window_nights: 7, spend_pct_threshold: 0.25, min_passes: 3 } },
  };
}

// A ledger double over an in-memory rows array (same shape as lib/ledger.mjs).
function ledgerOf(rows) {
  return {
    since: (ts) => rows.filter((r) => r.ts >= ts),
    laneSummary(ts) {
      const out = {};
      for (const r of rows.filter((x) => x.ts >= ts)) {
        const a = (out[r.backend] ??= { consumed: 0, passes: 0, attempts: 0 });
        a.consumed += r.consumed ?? 0; a.passes += r.passed ? 1 : 0; a.attempts += 1;
      }
      return out;
    },
  };
}

test('no backlog → honest "no run" report, no invented work', () => {
  const p = path.join(mkdtempSync(path.join(tmpdir(), 'ns-')), 'r.md');
  const txt = generateReport(cfg(p), ledgerOf([]), { tasks_total: 0 }, '2026-06-16T00:00:00.000Z');
  assert.match(txt, /No backlog, no run/);
});

test('paid-but-underused agent triggers a downgrade recommendation', () => {
  // claude attempted 2 chores over the window, passed 1, spent $0.40 of a $35 window budget.
  const rows = [
    { ts: '2026-06-12T00:00:00.000Z', backend: 'claude', consumed: 0.2, passed: true, task_id: 'a', validation_result: 'passed' },
    { ts: '2026-06-13T00:00:00.000Z', backend: 'claude', consumed: 0.2, passed: false, task_id: 'b', validation_result: 'failed', park_reason: 'failed twice' },
    { ts: '2026-06-16T00:00:00.000Z', backend: 'qwen', consumed: 0, passed: true, task_id: 'c', validation_result: 'passed' },
  ];
  const cands = downgradeCandidates(cfg('/dev/null'), ledgerOf(rows), '2026-06-16T00:00:00.000Z');
  assert.equal(cands.length, 1);
  assert.equal(cands[0][0], 'claude');
  const p = path.join(mkdtempSync(path.join(tmpdir(), 'ns-')), 'r.md');
  const txt = generateReport(cfg(p), ledgerOf(rows), { tasks_total: 3, dispatched: 3, passed: 2, parked: 1, stop_reason: 'backlog_empty' }, '2026-06-16T00:00:00.000Z');
  assert.match(txt, /Recommend downgrading `claude`/);
  assert.match(txt, /passes\/\$/);            // utilization column rendered
});

test('an unused (zero-attempt) paid agent is never nagged', () => {
  const cands = downgradeCandidates(cfg('/dev/null'), ledgerOf([]), '2026-06-16T00:00:00.000Z');
  assert.equal(cands.length, 0);
});
