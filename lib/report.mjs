// The morning report (Node port). Honest by construction: always shows per-agent
// consumption + utilization for every paid agent, recommends a downgrade when an
// agent is paid-for-but-underused, flags adjudication-gate rejections; never inflates.
import { writeFileSync } from 'node:fs';

// name -> nightly budget (usd) for agents that actually cost money.
function paidAgents(config) {
  const out = {};
  for (const a of config.agents) {
    const b = a.options?.nightly_budget;
    if (b) out[a.name] = Number(b);
  }
  return out;
}

function windowStart(nightStart, nights) {
  const d = new Date(nightStart);
  if (Number.isNaN(d.getTime())) return nightStart;
  d.setUTCDate(d.getUTCDate() - nights);
  return d.toISOString();
}

// [(agent, evidence)] for paid agents that should be downgraded: too few passes AND
// (under-used OR paying-for-failure). Pass-per-dollar is first-class (R18). An unused
// young agent is never nagged — no attempts means no evidence.
export function downgradeCandidates(config, ledger, nightStart) {
  const dg = config.report.downgrade;
  const hist = ledger.laneSummary(windowStart(nightStart, dg.window_nights));
  const out = [];
  for (const [agent, budget] of Object.entries(paidAgents(config))) {
    const s = hist[agent] ?? { consumed: 0, passes: 0, attempts: 0 };
    if (s.attempts === 0) continue;
    const budgetWindow = budget * dg.window_nights;
    const util = budgetWindow > 0 ? s.consumed / budgetWindow : 0;
    const lowPass = s.passes < dg.min_passes;
    const underused = util < dg.spend_pct_threshold;
    if (lowPass && (underused || s.consumed > 0)) {
      out.push([agent, {
        window_nights: dg.window_nights, spend: s.consumed,
        budget_window: budgetWindow, utilization_pct: Math.round(util * 1000) / 10, passes: s.passes,
      }]);
    }
  }
  return out;
}

export function generateReport(config, ledger, summary, nightStart) {
  const paid = paidAgents(config);
  const L = [`# Nightsweeper morning report — ${nightStart.slice(0, 10)}`, ''];
  if (summary.tasks_total === 0) {
    L.push('**No backlog, no run.** No chores were ready. Nightsweeper never invents work.');
    const t = L.join('\n') + '\n';
    try { writeFileSync(config.report.path, t); } catch {}
    return t;
  }
  const tonight = ledger.laneSummary(nightStart);
  const rows = ledger.since(nightStart);
  L.push('## Summary',
    `- Chores seen: **${summary.tasks_total}**`,
    `- Done: **${summary.passed}** · Set aside (parked): **${summary.parked}** · Dispatched: **${summary.dispatched}**`,
    `- Stop reason: \`${summary.stop_reason}\``, '',
    '## Per-agent work tonight', '| Agent | Attempts | Done | $ spent | Utilization |', '|---|---:|---:|---:|---|');
  for (const a of [...config.agents].sort((x, y) => x.cost_rank - y.cost_rank)) {
    const s = tonight[a.name] ?? { attempts: 0, passes: 0, consumed: 0 };
    let util, spend;
    if (paid[a.name]) {
      const budget = paid[a.name];
      const ppd = s.consumed > 0 ? (s.passes / s.consumed).toFixed(2) : '0.00';
      util = `${Math.round((1000 * s.consumed) / budget) / 10}% of $${budget.toFixed(2)} · ${ppd} passes/$`;
      spend = `$${s.consumed.toFixed(2)}`;
    } else {
      util = 'free ($0)'; spend = '$0.00';
    }
    L.push(`| ${a.name} | ${s.attempts} | ${s.passes} | ${spend} | ${util} |`);
  }

  // Plan utilization & recommendations — always reported, recommendation or not (R20/R27).
  L.push('', '## Plan utilization & recommendations');
  if (!Object.keys(paid).length) L.push('- No paid agents configured — every agent is free.');
  for (const [agent, budget] of Object.entries(paid)) {
    const s = tonight[agent] ?? { consumed: 0 };
    L.push(`- \`${agent}\`: spent $${s.consumed.toFixed(2)} of $${budget.toFixed(2)} tonight (utilization always reported).`);
  }
  for (const [agent, ev] of downgradeCandidates(config, ledger, nightStart)) {
    L.push(`- **Recommend downgrading \`${agent}\`.** Over the last ${ev.window_nights} nights it used `
      + `$${ev.spend.toFixed(2)} of $${ev.budget_window.toFixed(2)} (${ev.utilization_pct}%) and cleared `
      + `${ev.passes} chore(s). Honesty over engagement — you are paying for capacity you are not using.`);
  }

  const gateFails = {};
  for (const r of rows) if (String(r.validation_result).startsWith('failed:gate:')) {
    const g = r.validation_result.slice('failed:gate:'.length);
    gateFails[g] = (gateFails[g] ?? 0) + 1;
  }
  if (Object.keys(gateFails).length) {
    L.push('', '## Adjudication gates');
    for (const [g, c] of Object.entries(gateFails))
      L.push(`- **${g}** rejected ${c} change(s) that passed their tests — kept out of a passing branch.`);
  }
  const parked = rows.filter((r) => r.park_reason);
  if (parked.length) {
    L.push('', '## Set aside for you');
    for (const r of parked) L.push(`  - \`${r.task_id}\` (${r.backend}) — ${r.park_reason}`);
  }

  // Preflight accuracy (V2): only renders once an agent's cost_model populates predictions.
  const pred = rows.filter((r) => r.predicted_lo != null && ['passed', 'failed'].includes(r.validation_result));
  if (pred.length) {
    const bracketed = pred.filter((r) => r.predicted_lo <= (r.consumed ?? 0) && (r.consumed ?? 0) <= r.predicted_hi).length;
    const pct = Math.round((1000 * bracketed) / pred.length) / 10;
    L.push('', '## Preflight accuracy (V2)',
      `- [predicted_lo, predicted_hi] bracketed actual cost in **${bracketed}/${pred.length} (${pct}%)** `
      + 'of predicted dispatches (≥70% supports promoting preflight from advisory to gate).');
  }
  const t = L.join('\n') + '\n';
  try { writeFileSync(config.report.path, t); } catch {}
  return t;
}
