import { test } from 'node:test';
import assert from 'node:assert';
import { Validator } from '../lib/validator.mjs';

// Drive the validator with a scripted _run so no real commands execute.
function withRuns(v, script) {
  const calls = [];
  v._run = (cmd) => { calls.push(cmd); return script(cmd, calls.length - 1); };
  return calls;
}
const task = (o) => ({ id: 't', validator: 'test', validator_cmd: null, ...o });

test('validator:none parks for a human, never runs anything', () => {
  const v = new Validator({ test: 'npm test' });
  const calls = withRuns(v, () => ({ status: 0 }));
  const r = v.validate(task({ validator: 'none' }), '/wd');
  assert.equal(r.result, 'parked');
  assert.equal(calls.length, 0);
});

test('passing functional check with no gates → passed', () => {
  const v = new Validator({ test: 'npm test' });
  withRuns(v, () => ({ status: 0 }));
  assert.equal(v.validate(task({}), '/wd').result, 'passed');
});

test('failing functional check → failed, gates never consulted', () => {
  const v = new Validator({ test: 'npm test' }, [{ name: 'depthfinder', cmd: 'df', required: true }]);
  const calls = withRuns(v, () => ({ status: 1 }));
  const r = v.validate(task({}), '/wd');
  assert.equal(r.result, 'failed');
  assert.equal(calls.length, 1);   // stopped at the functional check
});

test('custom-cmd overrides the global validators map', () => {
  const v = new Validator({ test: 'npm test' });
  const calls = withRuns(v, () => ({ status: 0 }));
  v.validate(task({ validator: 'custom-cmd', validator_cmd: './check.sh' }), '/wd');
  assert.equal(calls[0], './check.sh');
});

test('adjudication gate rejects a change that passed its tests', () => {
  const v = new Validator({ test: 'npm test' }, [{ name: 'depthfinder', cmd: 'df --strict', required: true }]);
  // functional passes (call 0), gate rejects (call 1)
  withRuns(v, (cmd, i) => ({ status: i === 0 ? 0 : 1 }));
  const r = v.validate(task({}), '/wd');
  assert.equal(r.result, 'failed');
  assert.equal(r.failedGate, 'depthfinder');
});

test('an absent optional gate (exit 127) is skipped, not a failure', () => {
  const v = new Validator({ test: 'npm test' }, [{ name: 'optional', cmd: 'missingtool', required: false }]);
  withRuns(v, (cmd, i) => ({ status: i === 0 ? 0 : 127 }));
  assert.equal(v.validate(task({}), '/wd').result, 'passed');
});
