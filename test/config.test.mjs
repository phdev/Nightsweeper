import { test } from 'node:test';
import assert from 'node:assert';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { loadConfig } from '../lib/config.mjs';

function write(yaml) {
  const f = path.join(mkdtempSync(path.join(tmpdir(), 'ns-')), 'c.yaml');
  writeFileSync(f, yaml);
  return f;
}
const BASE = 'caps:\n  nightly_task_cap: 5\n  nightly_dollar_cap: 2\nagents:\n  - name: qwen\n    kind: aider\n    cost_rank: 0\n';

test('missing config throws ENOCONFIG (never silently defaults)', () => {
  try { loadConfig('/no/such/config.yaml'); assert.fail('should throw'); }
  catch (e) { assert.equal(e.code, 'ENOCONFIG'); }
});

test('caps are required — never default to unlimited', () => {
  assert.throws(() => loadConfig(write('agents:\n  - name: qwen\n')), /nightly_task_cap/);
});

test('at least one agent is required', () => {
  assert.throws(() => loadConfig(write('caps:\n  nightly_task_cap: 5\n  nightly_dollar_cap: 2\n')), /at least one agent/);
});

test('valid config loads with sane defaults + downgrade policy', () => {
  const c = loadConfig(write(BASE));
  assert.equal(c.caps.nightly_task_cap, 5);
  assert.equal(c.agents.length, 1);
  assert.equal(c.agents[0].kind, 'aider');
  assert.equal(c.tasksFile, 'nightsweeper.tasks.yaml');
  assert.equal(c.report.path, 'nightsweeper-report.md');
  assert.equal(c.report.downgrade.window_nights, 7);
  assert.equal(c.report.downgrade.min_passes, 3);
  assert.equal(c.isolation.pr_opt_in, false);
  assert.deepEqual(c.sources, []);
});

test('user report settings merge without clobbering downgrade defaults', () => {
  const c = loadConfig(write(BASE + 'report:\n  path: out.md\n  downgrade:\n    min_passes: 1\n'));
  assert.equal(c.report.path, 'out.md');
  assert.equal(c.report.downgrade.min_passes, 1);       // overridden
  assert.equal(c.report.downgrade.window_nights, 7);    // default preserved
});
