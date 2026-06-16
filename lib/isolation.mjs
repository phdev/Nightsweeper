// One git worktree/branch per task (Node port). -B reuses the branch on re-create.
import { spawnSync } from 'node:child_process';
import path from 'node:path';

const safe = (id) => id.replace(/[^A-Za-z0-9._/-]/g, '-');

export class Isolation {
  constructor(repoRoot, cfg, repoSlug) {
    this.repoRoot = repoRoot; this.cfg = cfg; this.repoSlug = repoSlug;
  }
  _git(args, cwd) {
    return spawnSync('git', args, { cwd: cwd ?? this.repoRoot, encoding: 'utf8', timeout: 120000 });
  }
  branchFor(id) { return this.cfg.branch_prefix + safe(id); }
  workdirFor(id) { return path.join(this.repoRoot, this.cfg.worktree_dir, safe(id)); }

  create(task) {
    const branch = this.branchFor(task.id), wdir = this.workdirFor(task.id);
    let base = this.cfg.base_ref ?? 'origin/HEAD';
    if (this._git(['rev-parse', '--verify', '--quiet', base]).status !== 0) base = 'HEAD';
    const r = this._git(['worktree', 'add', wdir, '-B', branch, base]);
    if (r.status !== 0) throw new Error(`worktree add failed: ${r.stderr?.trim()}`);
    return wdir;
  }
  handoff(task, wdir) {
    const branch = this.branchFor(task.id);
    this._git(['add', '-A'], wdir);
    this._git(['commit', '-m', `nightsweeper: ${(task.title ?? '').slice(0, 60)}`], wdir);
    const push = this._git(['push', '-u', 'origin', 'HEAD'], wdir);
    return { branch, pushed: push.status === 0 };
  }
  cleanup(task, keep) {
    if (keep) return;
    this._git(['worktree', 'remove', '--force', this.workdirFor(task.id)]);
    this._git(['worktree', 'prune']);
    this._git(['config', '--unset', 'extensions.worktreeConfig']);
  }
}
