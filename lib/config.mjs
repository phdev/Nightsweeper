// Load and lightly validate nightsweeper.config.yaml (Node port).
import { existsSync, readFileSync } from 'node:fs';
import YAML from 'yaml';

const VALIDATORS = new Set(['test', 'typecheck', 'build', 'none', 'custom-cmd']);

export function loadConfig(path = 'nightsweeper.config.yaml') {
  if (!existsSync(path)) {
    const e = new Error(`config not found: ${path} (run \`nightsweeper setup\` or \`nightsweeper\`)`);
    e.code = 'ENOCONFIG';
    throw e;
  }
  const raw = YAML.parse(readFileSync(path, 'utf8')) ?? {};
  const caps = raw.caps ?? {};
  if (caps.nightly_task_cap == null || caps.nightly_dollar_cap == null) {
    throw new Error('caps.nightly_task_cap and caps.nightly_dollar_cap are required (never default to unlimited)');
  }
  const preflight = { mode: 'advisory', ...(raw.preflight ?? {}) };
  if (!['advisory', 'gate'].includes(preflight.mode)) {
    throw new Error(`preflight.mode '${preflight.mode}' not in ('advisory', 'gate')`);
  }
  const agents = (raw.agents ?? []).map((a) => ({
    name: a.name, kind: a.kind ?? 'aider', cost_rank: a.cost_rank ?? 0,
    capability: a.capability ?? { validators: [...VALIDATORS], max_complexity: 'high' },
    options: a,
  }));
  if (!agents.length) throw new Error('config: at least one agent is required');
  return {
    schedule: { hour: 3, minute: 0, ...(raw.schedule ?? {}) },
    caps,
    tasksFile: raw.tasks_file ?? 'nightsweeper.tasks.yaml',
    sources: raw.sources ?? [],
    agents,
    validators: raw.validators ?? {},
    gates: raw.gates ?? [],
    isolation: { worktree_dir: '.nightsweeper/worktrees', pr_opt_in: false, branch_prefix: 'nightsweeper/', base_ref: 'origin/HEAD', ...(raw.isolation ?? {}) },
    report: {
      path: 'nightsweeper-report.md',
      ...(raw.report ?? {}),
      downgrade: { window_nights: 7, spend_pct_threshold: 0.25, min_passes: 3, ...(raw.report?.downgrade ?? {}) },
    },
    preflight,
    _path: path,
  };
}
