// The deterministic dispatcher — the core IP (Node port of the Python engine).
// Value order; cheapest eligible agent (capability gate + live availability); local-first;
// escalate ONCE then park; hard caps; ledger dedupe. No ML.
import { allows } from './agents.mjs';

const VALUE = { high: 0, med: 1, low: 2 };
const nowIso = () => new Date().toISOString();

export class Dispatcher {
  constructor(agents, isolation, validator, ledger, config) {
    this.agents = [...agents].sort((a, b) => a.costRank - b.costRank);
    this.iso = isolation; this.validator = validator; this.ledger = ledger;
    this.caps = config.caps;
    // Preflight gate (V2, opt-in): only enforces a per-task $ cap when explicitly turned on.
    this.preflightGate = config.preflight?.mode === 'gate';
    this.perTaskCap = config.caps?.per_task_cap ?? null;
    this.totalSpend = 0; this.dispatched = 0; this.passed = 0; this.parked = 0;
  }

  async _eligible(task, exclude = new Set()) {
    const out = [];
    for (const a of this.agents) {
      if (exclude.has(a.name)) continue;
      if (!allows(a.capability, task.validator, task.est_complexity ?? 'low')) continue;
      if (!(await a.probe()).available) continue;
      out.push(a);
    }
    return out;
  }

  _record(task, agent, result, passed, escalated, branch, reason, consumed, predicted = null) {
    this.ledger.record({
      task_id: task.id, source: task.source ?? 'tasklist', backend: agent,
      consumed, validation_result: result, passed, escalated, branch,
      predicted_lo: predicted?.lo ?? null, predicted_hi: predicted?.hi ?? null,
      ts: nowIso(), park_reason: reason ?? null,
    });
    if (passed) this.passed++; else if (reason) this.parked++;
  }

  async _process(task) {
    // Preflight gate (opt-in): if the cheapest eligible agent's low estimate already
    // blows the per-task cap, park it for review rather than spend over budget.
    if (this.preflightGate && this.perTaskCap != null) {
      const elig0 = await this._eligible(task);
      const est0 = elig0[0]?.estimate?.(task) ?? null;
      if (est0 && est0.lo > this.perTaskCap) {
        this._record(task, elig0[0].name, 'parked', false, false, null,
          `over-per-task-cap ($${est0.lo.toFixed(2)} > $${this.perTaskCap.toFixed(2)})`, 0, est0);
        return;
      }
    }
    this.dispatched++;
    const tried = new Set();
    let escalated = false;
    while (true) {
      const elig = await this._eligible(task, tried);
      if (!elig.length) {
        this._record(task, '(none)', 'failed', false, escalated, null,
          escalated ? 'escalation-exhausted' : 'no-escalation-lane', 0);
        return;
      }
      const agent = elig[0];
      const predicted = agent.estimate?.(task) ?? null;
      let wdir, result, validation;
      try {
        wdir = this.iso.create(task);
        result = agent.dispatch(task, wdir, task.context);
        this.totalSpend += result.consumedUsd ?? 0;
        validation = result.ok ? this.validator.validate(task, wdir) : { result: 'failed', detail: result.error };
      } catch (e) {
        try { this.iso.cleanup(task, true); } catch {}
        this._record(task, '(none)', 'failed', false, escalated, null, `dispatch-error: ${String(e.message).slice(0, 80)}`, 0);
        return;
      }
      if (validation.result === 'passed') {
        const h = this.iso.handoff(task, wdir);
        this.iso.cleanup(task, false);
        this._record(task, agent.name, 'passed', true, escalated, h.branch, null, result.consumedUsd ?? 0, predicted);
        return;
      }
      tried.add(agent.name);
      const vres = validation.failedGate ? `failed:gate:${validation.failedGate}` : 'failed';
      const next = escalated ? [] : await this._eligible(task, tried);
      if (next.length) {
        this._record(task, agent.name, vres, false, escalated, null, null, result.consumedUsd ?? 0, predicted);
        this.iso.cleanup(task, false);
        escalated = true;
        continue;
      }
      this.iso.cleanup(task, true);
      this._record(task, agent.name, vres, false, escalated, null,
        escalated ? 'escalation-exhausted' : 'no-escalation-lane', result.consumedUsd ?? 0, predicted);
      return;
    }
  }

  async _processable(task) {
    return task.validator === 'none' || (await this._eligible(task)).length > 0;
  }

  async run(tasks) {
    const ordered = [...tasks].sort((a, b) => VALUE[a.value] - VALUE[b.value]);
    let i = 0, stop = 'backlog-drained';
    while (i < ordered.length) {
      if (this.dispatched >= this.caps.nightly_task_cap) { stop = 'nightly-task-cap'; break; }
      if (this.totalSpend >= this.caps.nightly_dollar_cap) { stop = 'nightly-dollar-cap'; break; }
      let any = false;
      for (const t of ordered.slice(i)) if (await this._processable(t)) { any = true; break; }
      if (!any) { stop = 'no-processable-task-remaining'; break; }
      const task = ordered[i++];
      if (task.validator === 'none') { this._record(task, '(none)', 'parked', false, false, null, 'validator-none', 0); continue; }
      if (!(await this._eligible(task)).length) { this._record(task, '(none)', 'parked', false, false, null, 'no-eligible-agent', 0); continue; }
      await this._process(task);
    }
    return { stop_reason: stop, tasks_total: ordered.length, dispatched: this.dispatched, passed: this.passed, parked: this.parked, backlog_remaining: ordered.length - i };
  }
}
