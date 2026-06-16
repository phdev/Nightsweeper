// Append-only JSONL ledger (Node port — replaces the Python SQLite store; same data).
import { appendFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs';
import path from 'node:path';

export class Ledger {
  constructor(file) {
    this.file = file;
    mkdirSync(path.dirname(file), { recursive: true });
    this._rows = existsSync(file)
      ? readFileSync(file, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l))
      : [];
  }
  record(row) {
    this._rows.push(row);
    appendFileSync(this.file, JSON.stringify(row) + '\n');
  }
  hasRun(taskId) { return this._rows.some((r) => r.task_id === taskId); }
  since(ts) { return this._rows.filter((r) => r.ts >= ts); }
  spendSince(agent, ts) {
    return this._rows.filter((r) => r.backend === agent && r.ts >= ts).reduce((s, r) => s + (r.consumed ?? 0), 0);
  }
  laneSummary(ts) {
    const out = {};
    for (const r of this.since(ts)) {
      const a = (out[r.backend] ??= { consumed: 0, passes: 0, attempts: 0 });
      a.consumed += r.consumed ?? 0; a.passes += r.passed ? 1 : 0; a.attempts += 1;
    }
    return out;
  }
}
