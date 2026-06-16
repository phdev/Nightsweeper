// The interactive `nightsweeper` hub — your control room. Just run `nightsweeper`.
import { select, checkbox, confirm, input } from '@inquirer/prompts';
import { existsSync, readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { loadConfig } from './config.mjs';
import { loadTasks, checkReadiness, saveTasks } from './tasks.mjs';
import { Ledger } from './ledger.mjs';
import { buildAgents, runNight, gitRoot } from './run.mjs';
import { runSetup } from './setup.mjs';

const HOW = `
🌙  How Nightsweeper works (the 30-second version)

  You keep a list of CHORES. While you sleep, Nightsweeper hands each chore to the
  cheapest AGENT that's free right now — a local one (Qwen, free), or a cloud one you
  already pay for (Codex on your ChatGPT plan = $0, or Claude). It CHECKS the agent
  actually did it (runs your tests / a "did it work?" command), and only keeps the
  good work — each finished chore lands on its own git branch for you to review.

  The golden rule:  every chore needs a "did it work?" check.
  If you can't say how an agent would PROVE it finished, it's a wish, not a chore —
  Nightsweeper sets it aside instead of guessing. (Run "Check chore readiness".)

  In the morning: a report of what got done, what was set aside, and what each agent cost.
`;

async function ensureConfig() {
  try { return loadConfig(); }
  catch (e) {
    if (e.code !== 'ENOCONFIG') throw e;
    console.log("\nNo config yet — let's set one up.\n");
    await runSetup();
    return loadConfig();
  }
}

async function showAgents(config) {
  const root = gitRoot();
  const ledger = new Ledger(path.join(root, '.nightsweeper', 'ledger.jsonl'));
  const ns = (() => { const d = new Date(); d.setUTCHours(0, 0, 0, 0); return d.toISOString(); })();
  const agents = await buildAgents(config, ledger, ns);
  console.log('\n🤖  Your agents & energy:\n');
  for (const a of agents.sort((x, y) => x.costRank - y.costRank)) {
    const p = await a.probe();
    console.log(`   ${p.available ? '🟢' : '🔴'} ${a.name.padEnd(8)} ${p.usage}`);
  }
  console.log('');
}

async function showReadiness(config) {
  const { ready, needsEnrichment } = checkReadiness(loadTasks(config.tasksFile), config.validators);
  console.log(`\n✅  ${ready.length} chore(s) ready · ⚠️  ${needsEnrichment.length} need enrichment\n`);
  for (const { task, why } of needsEnrichment) console.log(`   ⚠️  ${task.title}\n       → ${why}`);
  if (ready.length) console.log(`\n   Ready: ${ready.map((t) => t.title).join(', ')}`);
  console.log('');
}

async function editChores(config) {
  const what = await select({
    message: 'Edit chores', choices: [
      { name: 'Add a chore (guided)', value: 'add' },
      { name: `Open ${config.tasksFile} in your editor`, value: 'editor' },
      { name: 'Back', value: 'back' }],
  });
  if (what === 'editor') {
    spawnSync(process.env.EDITOR ?? 'nano', [config.tasksFile], { stdio: 'inherit' });
  } else if (what === 'add') {
    const title = await input({ message: 'Chore title:' });
    const body = await input({ message: 'Concrete instructions (what to change):' });
    const validator = await select({
      message: 'How do we prove it\'s done?', choices: [
        { name: 'Run the tests (test)', value: 'test' },
        { name: 'A custom command I\'ll provide', value: 'custom-cmd' },
        { name: "No check — set aside for me (none)", value: 'none' }],
    });
    let validator_cmd = null;
    if (validator === 'custom-cmd') validator_cmd = await input({ message: 'Shell command that exits 0 when done:' });
    const value = await select({ message: 'Priority?', choices: [{ name: 'high', value: 'high' }, { name: 'med', value: 'med' }, { name: 'low', value: 'low' }] });
    const tasks = loadTasks(config.tasksFile);
    tasks.push({ id: title.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40), title, body, validator, validator_cmd, value });
    saveTasks(config.tasksFile, tasks);
    console.log(`\n   Added. ${config.tasksFile} now has ${tasks.length} chore(s).\n`);
  }
}

function showSchedule(config) {
  const plist = path.join(process.env.HOME, 'Library', 'LaunchAgents', 'com.nightsweeper.run.plist');
  const installed = existsSync(plist);
  const { hour, minute } = config.schedule;
  console.log(`\n⏰  Scheduling`);
  console.log(`   Configured run time: ${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')} nightly`);
  console.log(`   LaunchAgent installed: ${installed ? '✅ yes' : '❌ no — run `nightsweeper install-scheduler`'}`);
  console.log(`   Reports land at: ${config.report.path} (read it with "Morning report" or \`nightsweeper report\`)\n`);
}

function showReport(config) {
  if (!existsSync(config.report.path)) { console.log('\n   No report yet — run a night first.\n'); return; }
  console.log('\n' + readFileSync(config.report.path, 'utf8'));
}

async function runFromHub(config) {
  const root = gitRoot();
  const ledger = new Ledger(path.join(root, '.nightsweeper', 'ledger.jsonl'));
  const ns = (() => { const d = new Date(); d.setUTCHours(0, 0, 0, 0); return d.toISOString(); })();
  const agents = await buildAgents(config, ledger, ns);
  const picks = await checkbox({
    message: 'Which agents tonight? (space to toggle)',
    choices: await Promise.all(agents.map(async (a) => ({ name: `${a.name} — ${(await a.probe()).usage}`, value: a.name, checked: true }))),
  });
  if (!(await confirm({ message: `Run now with [${picks.join(', ')}]?`, default: true }))) return;
  console.log('\n   Running… (live inference; this can take a few minutes)\n');
  const { report } = await runNight({ configPath: config._path, only: picks });
  console.log(report);
}

export async function hub() {
  const config = await ensureConfig();
  console.log('\n🌙  Welcome to Nightsweeper.');
  for (;;) {
    const action = await select({
      message: 'What do you want to do?',
      choices: [
        { name: '📖  How it works', value: 'how' },
        { name: '🤖  Your agents & energy', value: 'agents' },
        { name: '✅  Check chore readiness (what needs enrichment)', value: 'readiness' },
        { name: '✏️   Edit chores', value: 'edit' },
        { name: '⏰  Scheduling', value: 'schedule' },
        { name: '🌅  Morning report', value: 'report' },
        { name: '▶️   Run now', value: 'run' },
        { name: '🚪  Quit', value: 'quit' },
      ],
    });
    try {
      if (action === 'how') console.log(HOW);
      else if (action === 'agents') await showAgents(config);
      else if (action === 'readiness') await showReadiness(config);
      else if (action === 'edit') await editChores(config);
      else if (action === 'schedule') showSchedule(config);
      else if (action === 'report') showReport(config);
      else if (action === 'run') await runFromHub(config);
      else break;
    } catch (e) {
      if (e?.name === 'ExitPromptError') break;
      console.log(`\n   ⚠️  ${e.message}\n`);
    }
  }
  console.log('\n   Good night. 🌙\n');
}
