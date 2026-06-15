from types import SimpleNamespace

from nightsweeper.config import Isolation
from nightsweeper.isolation import WorktreeManager
from nightsweeper.models import Task


class FakeRun:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def _mgr(pr_opt_in=False, gh_rc=0):
    cfg = Isolation(worktree_dir=".nightsweeper/worktrees", pr_opt_in=pr_opt_in)
    m = WorktreeManager("/repo", cfg, repo_slug="phdev/Nightsweeper")
    m.calls = []

    def fake_git(args, cwd=None):
        m.calls.append(("git", tuple(args)))
        return FakeRun(0, "", "")

    def fake_gh(args, cwd=None):
        m.calls.append(("gh", tuple(args)))
        return FakeRun(gh_rc, "https://github.com/phdev/Nightsweeper/pull/1", "" if gh_rc == 0 else "boom")

    m._git, m._gh = fake_git, fake_gh
    return m


def _task():
    return Task(id="gh:phdev/Nightsweeper#7", source="github_issues", title="Fix it",
                body="b", est_complexity="low", est_context_tokens=10, validator="test", value="high")


def test_branch_and_workdir_naming():
    m = _mgr()
    assert m.branch_for("gh:x#1") == "nightsweeper/gh-x-1"
    assert m.workdir_for("gh:x#1").endswith(".nightsweeper/worktrees/gh-x-1")


def test_create_adds_worktree_from_origin_head():
    m = _mgr()
    m.create(_task())
    add = [c for c in m.calls if c[1][0] == "worktree" and c[1][1] == "add"]
    assert add and add[0][1][-1] == "origin/HEAD"


def test_handoff_branch_only_when_pr_off():
    m = _mgr(pr_opt_in=False)
    h = m.handoff(_task(), "/repo/.nightsweeper/worktrees/x")
    assert h.pushed is True and h.pr_url is None
    assert not any(c[0] == "gh" for c in m.calls)  # no PR opened


def test_handoff_opens_draft_pr_when_opted_in():
    m = _mgr(pr_opt_in=True)
    h = m.handoff(_task(), "/repo/.nightsweeper/worktrees/x")
    gh = [c for c in m.calls if c[0] == "gh"][0][1]
    assert "--draft" in gh and h.pr_url.endswith("/pull/1")


def test_cleanup_keeps_parked_worktree():
    m = _mgr()
    m.cleanup(_task(), keep=True)
    assert m.calls == []  # parked → nothing removed


def test_cleanup_removes_and_prunes_on_pass():
    m = _mgr()
    m.cleanup(_task(), keep=False)
    verbs = [c[1][1] for c in m.calls if c[1][0] == "worktree"]
    assert "remove" in verbs and "prune" in verbs
