// Functional validator + adjudication gates (Node port). The validator is the gate —
// keep only passes. A per-task validator_cmd overrides the global validators map.
import { spawnSync } from 'node:child_process';

export class Validator {
  constructor(validators, gates = [], timeoutSec = 1800) {
    this.validators = validators; this.gates = gates; this.timeoutSec = timeoutSec;
  }
  _run(cmd, wd) {
    return spawnSync(cmd, { cwd: wd, shell: true, encoding: 'utf8', timeout: this.timeoutSec * 1000 });
  }
  validate(task, wdir) {
    if (task.validator === 'none') return { result: 'parked', detail: 'validator:none — needs human' };
    const command = (task.validator === 'custom-cmd' && task.validator_cmd) || this.validators[task.validator];
    if (!command) return { result: 'failed', detail: `no command for validator '${task.validator}'` };
    const out = this._run(command, wdir);
    if (out.status !== 0) return { result: 'failed', detail: `\`${command}\` exited ${out.status}` };
    for (const gate of this.gates) {
      const g = this._run(gate.cmd, wdir);
      if (g.status === 127 && !gate.required) continue;
      if (g.status !== 0) return { result: 'failed', detail: `gate '${gate.name}' rejected (exit ${g.status})`, failedGate: gate.name };
    }
    return { result: 'passed', detail: `passed${this.gates.length ? ` · ${this.gates.length} gate(s) held` : ''}` };
  }
}
