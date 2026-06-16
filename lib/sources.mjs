// Backlog sources (Node port) — pull REAL chores, never fabricate (R1/R25).
// github_issues (gh), apple_notes (osascript + heading scoping), linear (GraphQL).
// tasklist lives in tasks.mjs. Each source: { name, fetch() -> [task] }.
import { spawnSync } from 'node:child_process';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';

const VALIDATORS = new Set(['test', 'typecheck', 'build', 'none', 'custom-cmd']);
const VALUES = new Set(['high', 'med', 'low']);
const hashId = (p, s) => p + createHash('sha1').update(s).digest('hex').slice(0, 12);

function complexityFromBody(b) { const n = (b || '').length; return n < 400 ? 'low' : n < 1600 ? 'medium' : 'high'; }
function coerce(validator, value, dv, dvalue) {
  return [VALIDATORS.has(validator) ? validator : dv, VALUES.has(value) ? value : dvalue];
}

// ---------- GitHub issues ----------
function githubSource(o) {
  const repos = o.repos ?? [];
  const valueMap = o.value_label_map ?? {};
  const dvalue = o.default_value ?? 'med', dval = o.default_validator ?? 'test';
  const vprefix = o.validator_label_prefix ?? 'validator:';
  return {
    name: 'github_issues',
    _list(repo) {   // injectable seam: returns parsed `gh issue list` JSON for unit tests
      const r = spawnSync('gh', ['issue', 'list', '-R', repo, '--state', 'open', '--json', 'number,title,body,labels', '--limit', '200'], { encoding: 'utf8', timeout: 60000 });
      if (r.status !== 0) throw new Error(`github_issues: gh failed for ${repo}: ${r.stderr?.trim().slice(0, 200)}`);
      return JSON.parse(r.stdout || '[]');
    },
    fetch() {
      const tasks = [];
      for (const repo of repos) {
        for (const iss of this._list(repo)) {
          const labels = (iss.labels ?? []).map((l) => l.name);
          let value = dvalue;
          for (const [lbl, v] of Object.entries(valueMap)) if (labels.includes(lbl)) { value = v; break; }
          let validator = dval;
          for (const n of labels) if (n.startsWith(vprefix)) { validator = n.slice(vprefix.length); break; }
          [validator, value] = coerce(validator, value, dval, dvalue);
          const body = iss.body ?? '';
          tasks.push({ id: `gh:${repo}#${iss.number}`, source: 'github_issues', title: iss.title ?? '', body, est_complexity: complexityFromBody(body), validator, value, validator_cmd: null });
        }
      }
      return tasks;
    },
  };
}

// ---------- Apple Notes (with heading scoping) ----------
const stripTags = (s) => s.replace(/<[^>]+>/g, '');
const unescape = (s) => s.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
  .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&nbsp;/g, ' ');
const DONE_PREFIX = /^\s*(?:\[x\]|✓|✔)\s*/i;
const HEADING = /<h[1-6][ >]|<b>|<strong>|font-weight:\s*(?:bold|[6-9]00)/i;
const STRIKE = /<s>|<strike>|line-through/i;
const INLINE = /\[([^\]]*)\]\s*$/;

export function parseNotesLines(body) {
  const s = body.replace(/<\/(div|p|li|h[1-6])>/gi, '\n').replace(/<br ?\/?>/gi, '\n');
  const out = [];
  for (const raw of s.split('\n')) {
    let done = STRIKE.test(raw);
    const isHeading = HEADING.test(raw);
    let text = unescape(stripTags(raw)).trim();
    if (!text) continue;
    if (DONE_PREFIX.test(text)) { done = true; text = text.replace(DONE_PREFIX, ''); }
    out.push({ text, done, isHeading });
  }
  return out;
}

function appleNotesSource(o) {
  const dvalue = o.default_value ?? 'med', dval = o.default_validator ?? 'test';
  const toTask = (text) => {
    let validator = dval, value = dvalue, title = text;
    const m = text.match(INLINE);
    if (m) {
      for (const part of m[1].split(/\s+/)) {
        const [k, v] = part.split('=');
        if (k === 'validator' && VALIDATORS.has(v)) validator = v;
        else if (k === 'value' && VALUES.has(v)) value = v;
      }
      title = text.slice(0, m.index).trim();
    }
    return { id: hashId('note:', title), source: 'apple_notes', title, body: title, est_complexity: 'low', validator, value, validator_cmd: null };
  };
  return {
    name: 'apple_notes',
    _fetchBody() {
      if (!o.note) throw new Error("apple_notes: 'note' (title) is required");
      const target = o.folder ? `note "${o.note}" of folder "${o.folder}"` : `note "${o.note}"`;
      const r = spawnSync('osascript', ['-e', `tell application "Notes" to get body of ${target}`], { encoding: 'utf8', timeout: 30000 });
      if (r.status !== 0) throw new Error(`apple_notes: osascript failed: ${(r.stderr ?? '').slice(0, 200)}`);
      return r.stdout;
    },
    fetch() {
      const lines = parseNotesLines(this._fetchBody());
      let items;
      if (o.heading) {
        const t = o.heading.trim().toLowerCase();
        items = []; let collecting = false;
        for (const ln of lines) {
          if (ln.isHeading) { if (ln.text.trim().toLowerCase().startsWith(t)) collecting = true; else if (collecting) break; continue; }
          if (collecting) items.push(ln);
        }
      } else {
        items = (o.skip_title === false ? lines : lines.slice(1)).filter((l) => !l.isHeading);
      }
      return items.filter((l) => !(l.done && !o.include_done)).map((l) => toTask(l.text));
    },
  };
}

// ---------- Linear (GraphQL) ----------
const LINEAR_PRIORITY = { 1: 'high', 2: 'high', 3: 'med', 4: 'low', 0: 'low' };
function linearSource(o) {
  const keyEnv = o.api_key_env ?? 'LINEAR_API_KEY';
  const dvalue = o.default_value ?? 'med', dval = o.default_validator ?? 'test';
  return {
    name: 'linear',
    async fetch() {
      const key = process.env[keyEnv];
      if (!key) throw new Error(`linear: $${keyEnv} not set`);
      const filter = { state: { type: { neq: 'completed' } } };
      if (o.team) filter.team = { key: { eq: o.team } };
      const query = 'query($filter: IssueFilter){ issues(filter:$filter, first:200){ nodes{ identifier title description priority labels{ nodes{ name } } } } }';
      const res = await fetch(o.endpoint ?? 'https://api.linear.app/graphql', {
        method: 'POST', headers: { Authorization: key, 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, variables: { filter } }), signal: AbortSignal.timeout(60000),
      });
      const data = await res.json();
      if (data.errors) throw new Error(`linear: ${JSON.stringify(data.errors).slice(0, 200)}`);
      return data.data.issues.nodes.map((iss) => {
        const [validator, value] = coerce(dval, LINEAR_PRIORITY[iss.priority] ?? dvalue, dval, dvalue);
        const body = iss.description ?? '';
        return { id: `linear:${iss.identifier}`, source: 'linear', title: iss.title ?? '', body, est_complexity: body.length >= 600 ? 'medium' : 'low', validator, value, validator_cmd: null };
      });
    },
  };
}

// ---------- TODO scan (enrolled source-code markers) ----------
// Only markers a human deliberately enrolled — TODO(nightsweeper: ...) — become
// chores. Bare TODO/FIXME are left alone (R1: never invent work).
const ENROLLED = /TODO\(nightsweeper:?\s*([^)]*)\)\s*:?\s*(.*)$/i;
const SKIP_DIRS = new Set(['node_modules', '.git', 'dist', 'build', '.next', 'out', 'coverage', 'vendor', '__pycache__', '.venv', 'target']);
const DEFAULT_EXTS = ['.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.py', '.go', '.rs', '.java', '.rb', '.c', '.h', '.cc', '.cpp', '.swift', '.kt'];

function parseMarkerArgs(s) {
  const out = {};
  for (const part of (s || '').trim().split(/\s+/)) {
    const i = part.indexOf('=');
    if (i > 0) out[part.slice(0, i)] = part.slice(i + 1);
  }
  return out;
}

function* walk(dir, exts, depth = 0) {
  if (depth > 12) return;
  let entries;
  try { entries = readdirSync(dir, { withFileTypes: true }); } catch { return; }
  for (const e of entries) {
    if (SKIP_DIRS.has(e.name)) continue;
    const full = path.join(dir, e.name);
    if (e.isDirectory()) yield* walk(full, exts, depth + 1);
    else if (e.isFile() && (exts.length === 0 || exts.includes(path.extname(e.name)))) yield full;
  }
}

function todoScanSource(o) {
  const root = o.root ?? '.';
  const exts = o.extensions ?? DEFAULT_EXTS;
  const dvalue = o.default_value ?? 'med', dval = o.default_validator ?? 'test';
  const maxBytes = o.max_file_bytes ?? 512 * 1024;
  return {
    name: 'todo_scan',
    _read(file) { return readFileSync(file, 'utf8'); },
    _files() { return [...walk(root, exts)]; },
    _size(file) { try { return statSync(file).size; } catch { return 0; } },
    fetch() {
      const tasks = [];
      for (const file of this._files()) {
        if (this._size(file) > maxBytes) continue;
        let text; try { text = this._read(file); } catch { continue; }
        if (!text.includes('TODO(nightsweeper')) continue;
        const rel = path.relative(root, file) || path.basename(file);
        text.split('\n').forEach((line, i) => {
          const m = line.match(ENROLLED);
          if (!m) return;
          const args = parseMarkerArgs(m[1]);
          let desc = (m[2] || '').replace(/(\*\/|-->|"""|#)\s*$/, '').trim();
          if (!desc) desc = `Resolve enrolled TODO at ${rel}:${i + 1}`;
          const [validator, value] = coerce(args.validator, args.value, dval, dvalue);
          tasks.push({
            id: hashId('todo:', `${rel}:${i + 1}:${desc}`),
            source: 'todo_scan',
            title: desc,
            body: `${desc}\n\n(enrolled TODO at ${rel}:${i + 1})`,
            est_complexity: 'low',
            validator, value, validator_cmd: null,
          });
        });
      }
      return tasks;
    },
  };
}

const KINDS = { github_issues: githubSource, apple_notes: appleNotesSource, linear: linearSource, todo_scan: todoScanSource };
export function makeSource(cfg) {
  const fn = KINDS[cfg.name];
  if (!fn) throw new Error(`unknown source '${cfg.name}' (have ${Object.keys(KINDS).join(', ')}, plus tasklist)`);
  return fn(cfg);
}
export { appleNotesSource, todoScanSource, githubSource };
