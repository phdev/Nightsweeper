// Load the chores list + the readiness check: which chores can a robot actually
// PROVE it finished? (the golden rule). Ported + extended for the onboarding UX.
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import YAML from 'yaml';
import { createHash } from 'node:crypto';

const VALIDATORS = new Set(['test', 'typecheck', 'build', 'none', 'custom-cmd']);
const VALUES = new Set(['high', 'med', 'low']);

export function loadTasks(file) {
  if (!existsSync(file)) return [];
  const data = YAML.parse(readFileSync(file, 'utf8')) ?? [];
  const list = Array.isArray(data) ? data : data.tasks ?? [];
  return list.filter((e) => e && (e.title || e.id)).map((e) => {
    let validator = VALIDATORS.has(e.validator) ? e.validator : 'test';
    if (e.validator_cmd) validator = 'custom-cmd';
    const title = e.title ?? e.id ?? '';
    return {
      id: String(e.id ?? 'task:' + createHash('sha1').update(title).digest('hex').slice(0, 12)),
      source: 'tasklist', title, body: e.body ?? '',
      est_complexity: ['low', 'medium', 'high'].includes(e.est_complexity) ? e.est_complexity : 'low',
      validator, validator_cmd: e.validator_cmd ?? null,
      value: VALUES.has(e.value) ? e.value : 'med',
    };
  });
}

export function saveTasks(file, tasks) {
  writeFileSync(file, YAML.stringify(tasks.map((t) => ({
    id: t.id, title: t.title, body: t.body, validator: t.validator,
    ...(t.validator_cmd ? { validator_cmd: t.validator_cmd } : {}), value: t.value,
  }))));
}

// Returns { ready, needsEnrichment: [{task, why}] }.
export function checkReadiness(tasks, validators = {}) {
  const ready = [], needsEnrichment = [];
  for (const t of tasks) {
    let why = null;
    if (t.validator === 'none') why = "no proof — needs a validator (how would a robot prove it's done?)";
    else if (t.validator === 'custom-cmd' && !t.validator_cmd) why = "custom-cmd has no command — add a `validator_cmd` that exits 0 when done";
    else if (!t.validator_cmd && !validators[t.validator]) why = `validator '${t.validator}' has no command configured`;
    else if (!t.body || t.body.length < 12) why = "too vague — add concrete instructions in `body`";
    if (why) needsEnrichment.push({ task: t, why }); else ready.push(t);
  }
  return { ready, needsEnrichment };
}
