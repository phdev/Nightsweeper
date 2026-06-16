// The morning report (Node port). Honest by construction: always shows per-agent
// consumption; flags an adjudication-gate rejection; never inflates.
import { writeFileSync } from 'node:fs';

export function generateReport(config, ledger, summary, nightStart) {
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
    '## Per-agent work tonight', '| Agent | Attempts | Done | $ spent |', '|---|---:|---:|---:|');
  for (const a of [...config.agents].sort((x, y) => x.cost_rank - y.cost_rank)) {
    const s = tonight[a.name] ?? { attempts: 0, passes: 0, consumed: 0 };
    L.push(`| ${a.name} | ${s.attempts} | ${s.passes} | $${s.consumed.toFixed(2)} |`);
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
  const t = L.join('\n') + '\n';
  try { writeFileSync(config.report.path, t); } catch {}
  return t;
}
