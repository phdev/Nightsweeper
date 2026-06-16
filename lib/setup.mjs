// Onboarding wizard — `nightsweeper setup` (or auto-runs when no config exists).
import { checkbox, input } from '@inquirer/prompts';
import { existsSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { homedir } from 'node:os';
import path from 'node:path';
import YAML from 'yaml';

const have = (cmd) => spawnSync('command', ['-v', cmd], { shell: true, encoding: 'utf8' }).status === 0;

export async function runSetup() {
  console.log('\n🌙  Nightsweeper setup — let\'s pick your agents and write a config.\n');
  const aiderBin = existsSync(path.join(homedir(), '.aider-venv/bin/aider'))
    ? path.join(homedir(), '.aider-venv/bin/aider') : 'aider';
  const detected = {
    qwen: have('ollama') && (have('aider') || existsSync(aiderBin)),
    codex: have('codex'),
    claude: have('claude'),
  };
  console.log('Detected agents on this machine:');
  console.log(`   qwen  (local, free)        : ${detected.qwen ? '🟢 ready' : '🔴 needs Ollama + Aider'}`);
  console.log(`   codex (ChatGPT quota, $0)  : ${detected.codex ? '🟢 ready' : '🔴 not found'}`);
  console.log(`   claude (Agent SDK credit)  : ${detected.claude ? '🟢 ready' : '🔴 not found'}\n`);

  const chosen = await checkbox({
    message: 'Which agents should Nightsweeper use? (space to toggle)',
    choices: [
      { name: 'qwen — local, free', value: 'qwen', checked: detected.qwen },
      { name: 'codex — ChatGPT plan quota, $0 marginal', value: 'codex', checked: detected.codex },
      { name: 'claude — Agent SDK credit (metered, pre-paid)', value: 'claude', checked: detected.claude },
    ],
  });

  const agents = [];
  let rank = 0;
  if (chosen.includes('qwen')) agents.push({ name: 'qwen', kind: 'aider', cost_rank: rank++, model: 'qwen2.5-coder:7b', ollama_host: 'http://localhost:11434', aider_bin: aiderBin, edit_format: 'whole', extra_args: ['--analytics-disable'], capability: { validators: ['test', 'custom-cmd'], max_complexity: 'medium' } });
  if (chosen.includes('codex')) agents.push({ name: 'codex', kind: 'codex', cost_rank: rank++, sandbox_mode: 'workspace-write', capability: { validators: ['test', 'custom-cmd', 'none'], max_complexity: 'high' } });
  if (chosen.includes('claude')) agents.push({ name: 'claude', kind: 'claude', cost_rank: rank++, model: 'claude-sonnet-4-6', nightly_budget: 3, per_task_floor: 0.5, capability: { validators: ['test', 'custom-cmd', 'none'], max_complexity: 'high' } });

  const testCmd = await input({ message: 'How are your tests run (the "did it work?" check)?', default: 'npm test' });
  const hour = Number(await input({ message: 'What hour (0-23) should it run each night?', default: '3' }));

  const config = {
    schedule: { hour: Number.isFinite(hour) ? hour : 3, minute: 0 },
    caps: { nightly_task_cap: 10, nightly_dollar_cap: 3 },
    tasks_file: 'nightsweeper.tasks.yaml',
    agents,
    validators: { test: testCmd },
    isolation: { pr_opt_in: false },
    report: { path: 'nightsweeper-report.md' },
  };
  writeFileSync('nightsweeper.config.yaml', YAML.stringify(config));
  if (!existsSync('nightsweeper.tasks.yaml')) {
    writeFileSync('nightsweeper.tasks.yaml', YAML.stringify([
      { id: 'example', title: 'Example chore — replace me', body: 'Describe exactly what to change, concretely.', validator: 'test', value: 'med' },
    ]));
  }
  console.log('\n✅  Wrote nightsweeper.config.yaml + a starter nightsweeper.tasks.yaml.');
  console.log('    Next: run `nightsweeper` for the hub, or `nightsweeper run` to go tonight.\n');
}
