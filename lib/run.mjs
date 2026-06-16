// Orchestrate one night: config → agents → chores → dispatcher → report.
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { loadConfig } from './config.mjs';
import { makeAgent } from './agents.mjs';
import { loadTasks } from './tasks.mjs';
import { Ledger } from './ledger.mjs';
import { Isolation } from './isolation.mjs';
import { Validator } from './validator.mjs';
import { Dispatcher } from './dispatcher.mjs';
import { generateReport } from './report.mjs';

export function gitRoot() {
  const r = spawnSync('git', ['rev-parse', '--show-toplevel'], { encoding: 'utf8' });
  if (r.status !== 0) throw new Error('not inside a git repository');
  return r.stdout.trim();
}
function repoSlug() {
  const r = spawnSync('gh', ['repo', 'view', '--json', 'nameWithOwner', '-q', '.nameWithOwner'], { encoding: 'utf8' });
  return r.status === 0 ? r.stdout.trim() || null : null;
}
function nightStartIso() {
  const d = new Date(); d.setUTCHours(0, 0, 0, 0); return d.toISOString();
}

export async function buildAgents(config, ledger, nightStart, only) {
  let agents = config.agents.map((a) => makeAgent(a, { ledger, nightStart }));
  if (only?.length) agents = agents.filter((a) => only.includes(a.name));
  return agents;
}

export async function runNight({ configPath = 'nightsweeper.config.yaml', only } = {}) {
  const config = loadConfig(configPath);
  const root = gitRoot();
  const ledger = new Ledger(path.join(root, '.nightsweeper', 'ledger.jsonl'));
  const nightStart = nightStartIso();
  const agents = await buildAgents(config, ledger, nightStart, only);
  if (!agents.length) return { summary: { tasks_total: 0 }, report: 'No agents selected — nothing to run.\n' };
  const tasks = loadTasks(config.tasksFile).filter((t) => !ledger.hasRun(t.id));
  const iso = new Isolation(root, config.isolation, repoSlug());
  const validator = new Validator(config.validators, config.gates);
  const disp = new Dispatcher(agents, iso, validator, ledger, config);
  const summary = await disp.run(tasks);
  const report = generateReport(config, ledger, summary, nightStart);
  return { summary, report, config };
}
