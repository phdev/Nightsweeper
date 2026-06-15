import pytest

from nightsweeper.config import SourceConfig
from nightsweeper.sources.github_issues import GithubIssuesSource, SourceFetchError


def _src():
    return GithubIssuesSource(SourceConfig(name="github_issues", options={
        "repos": ["phdev/Nightsweeper"],
        "value_label_map": {"priority:high": "high"},
        "default_value": "med",
        "validator_label_prefix": "validator:",
        "default_validator": "test",
    }))


def test_normalizes_issue_to_task_with_all_fields(monkeypatch):
    s = _src()
    monkeypatch.setattr(s, "_fetch_raw_issues", lambda repo: [
        {"number": 7, "title": "Fix the thing", "body": "x" * 500,
         "labels": [{"name": "priority:high"}, {"name": "validator:build"}]},
    ])
    tasks = s.fetch()
    t = tasks[0]
    assert t.id == "gh:phdev/Nightsweeper#7"
    assert t.value == "high" and t.validator == "build"
    assert t.est_complexity == "medium" and t.est_context_tokens > 0
    assert t.source == "github_issues"


def test_defaults_when_no_labels(monkeypatch):
    s = _src()
    monkeypatch.setattr(s, "_fetch_raw_issues", lambda repo: [
        {"number": 1, "title": "t", "body": "", "labels": []},
    ])
    t = s.fetch()[0]
    assert t.value == "med" and t.validator == "test" and t.est_complexity == "low"


def test_empty_issue_list_yields_no_tasks(monkeypatch):
    s = _src()
    monkeypatch.setattr(s, "_fetch_raw_issues", lambda repo: [])
    assert s.fetch() == []  # never fabricates work (R1)


def test_gh_failure_raises_clear_error(monkeypatch):
    s = _src()

    def boom(repo):
        raise SourceFetchError("github_issues: `gh issue list` failed (exit 1): not authenticated")

    monkeypatch.setattr(s, "_fetch_raw_issues", boom)
    with pytest.raises(SourceFetchError, match="gh issue list"):
        s.fetch()
