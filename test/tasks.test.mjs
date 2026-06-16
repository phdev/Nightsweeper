import { test } from 'node:test';
import assert from 'node:assert';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { loadTasks, checkReadiness } from '../lib/tasks.mjs';

test('tasklist loads; validator_cmd implies custom-cmd; bad values coerced', () => {
  const f = path.join(mkdtempSync(path.join(tmpdir(), 'ns-')), 't.yaml');
  writeFileSync(f, '- id: a\n  title: x\n  validator: test\n  value: high\n'
    + '- id: b\n  title: y\n  validator_cmd: "true"\n'
    + '- id: c\n  title: z\n  validator: bogus\n  value: nope\n');
  const tasks = loadTasks(f);
  assert.equal(tasks.length, 3);
  assert.equal(tasks[1].validator, 'custom-cmd');
  assert.equal(tasks[1].validator_cmd, 'true');
  assert.equal(tasks[2].validator, 'test');   // coerced
  assert.equal(tasks[2].value, 'med');         // coerced
});

test('readiness flags chores with no way to prove they are done', () => {
  const tasks = [
    { id: 'a', title: 'A', body: 'do a real concrete thing', validator: 'test', validator_cmd: null },
    { id: 'b', title: 'B', body: 'x', validator: 'none', validator_cmd: null },
    { id: 'c', title: 'C', body: 'no command given', validator: 'custom-cmd', validator_cmd: null },
  ];
  const { ready, needsEnrichment } = checkReadiness(tasks, { test: 'npm test' });
  assert.equal(ready.length, 1);
  assert.equal(needsEnrichment.length, 2);
  assert.match(needsEnrichment[0].why, /validator/);
});
