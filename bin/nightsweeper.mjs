#!/usr/bin/env node
// nightsweeper — your overnight AI agent crew. Run with no args for the interactive hub.
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { checkbox } from '@inquirer/prompts';
import { hub } from '../lib/hub.mjs';
import { runSetup } from '../lib/setup.mjs';
import { loadConfig } from '../lib/config.mjs';
import { loadTasks, checkReadiness } from '../lib/tasks.mjs';
import { Ledger } from '../lib/ledger.mjs';
import { buildAgents, runNight, gitRoot } from '../lib/run.mjs';
import { installScheduler } from '../lib/scheduler.mjs';

const argv = process.argv.slice(2);
const cmd = argv[0];
const flag = (n) => argv.includes(n);
const opt = (n) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : null; };
const configPath = opt('--config') ?? 'nightsweeper.config.yaml';
const nightStart = () => { const d = new Date(); d.setUTCHours(0, 0, 0, 0); return d.toISOString(); };

const HELP = `nightsweeper — overnight AI agent crew

  nightsweeper                 open the interactive hub (recommended)
  nightsweeper setup           onboarding wizard (pick agents, write config)
  nightsweeper run [--lanes a,b] [--choose-lanes] [--print]
  nightsweeper agents          show your agents + how much energy each has left
  nightsweeper readiness       which chores are ready vs need enrichment
  nightsweeper report          print the latest morning report
  nightsweeper install-scheduler   run every night automatically
  --config <path>              use a specific config (default nightsweeper.config.yaml)`;

async function main() {
  if (!cmd) return hub();
  if (cmd === 'setup') return runSetup();
  if (cmd === 'help' || cmd === '-h' || cmd === '--help') return console.log(HELP);

  if (cmd === 'run') {
    let only = opt('--lanes')?.split(',').map((s) => s.trim());
    if (flag('--choose-lanes') || flag('--choose-agents')) {
      const config = loadConfig(configPath);
      const ledger = new Ledger(path.join(gitRoot(), '.nightsweeper', 'ledger.jsonl'));
      const agents = (await buildAgents(config, ledger, nightStart())).sort((a, b) => a.costRank - b.costRank);
      only = await checkbox({
        message: 'Which agents tonight? (space to toggle)',
        choices: await Promise.all(agents.map(async (a) => ({ name: `${a.name} — ${(await a.probe()).usage}`, value: a.name, checked: true }))),
      });
    }
    const { summary, report } = await runNight({ configPath, only });
    if (flag('--print')) console.log(report);
    else console.log(`nightsweeper: ${summary.dispatched} dispatched, ${summary.passed} done, ${summary.parked} set aside; stop=${summary.stop_reason}`);
    return;
  }
  if (cmd === 'agents' || cmd === 'probe') {
    const config = loadConfig(configPath);
    const ledger = new Ledger(path.join(gitRoot(), '.nightsweeper', 'ledger.jsonl'));
    const agents = await buildAgents(config, ledger, nightStart());
    console.log('Your agents & energy:');
    for (const a of agents.sort((x, y) => x.costRank - y.costRank)) {
      const p = await a.probe();
      console.log(`  ${p.available ? '🟢' : '🔴'} ${a.name.padEnd(8)} ${p.usage}`);
    }
    return;
  }
  if (cmd === 'readiness' || cmd === 'tasks') {
    const config = loadConfig(configPath);
    const { ready, needsEnrichment } = checkReadiness(loadTasks(config.tasksFile), config.validators);
    console.log(`✅ ${ready.length} ready · ⚠️  ${needsEnrichment.length} need enrichment`);
    for (const { task, why } of needsEnrichment) console.log(`  ⚠️  ${task.title}\n      → ${why}`);
    return;
  }
  if (cmd === 'report') {
    const config = loadConfig(configPath);
    console.log(existsSync(config.report.path) ? readFileSync(config.report.path, 'utf8') : 'No report yet — run a night first.');
    return;
  }
  if (cmd === 'install-scheduler') return installScheduler(loadConfig(configPath), configPath);

  console.error(`unknown command: ${cmd}\n\n${HELP}`);
  process.exit(1);
}

main().catch((e) => { console.error('nightsweeper:', e.message); process.exit(1); });
