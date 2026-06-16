"""Apple Notes source — parsing tests (osascript mocked)."""

from nightsweeper.config import SourceConfig
from nightsweeper.sources.apple_notes import AppleNotesSource

# Approximates the HTML `body of note` returns: title first, then lines; one item
# struck through (done), one with an inline tag.
SAMPLE = (
    "<div><h1>Project X Tasks</h1></div>"
    "<div>Fix the flaky retry [validator=test value=high]</div>"
    "<div>Add a --json flag</div>"
    "<div><s>Old done thing</s></div>"
)


def _src(**opts):
    return AppleNotesSource(SourceConfig(name="apple_notes", options={"note": "Project X Tasks", **opts}))


def test_parses_lines_skips_title_and_done(monkeypatch):
    s = _src()
    monkeypatch.setattr(s, "_fetch_body", lambda: SAMPLE)
    tasks = s.fetch()
    titles = [t.title for t in tasks]
    assert "Project X Tasks" not in titles      # title skipped
    assert "Old done thing" not in titles        # struck-through = done, skipped
    assert titles == ["Fix the flaky retry", "Add a --json flag"]


def test_inline_tag_sets_validator_and_value(monkeypatch):
    s = _src()
    monkeypatch.setattr(s, "_fetch_body", lambda: SAMPLE)
    fix = s.fetch()[0]
    assert fix.validator == "test" and fix.value == "high"  # from [validator=test value=high]
    assert fix.source == "apple_notes" and fix.id.startswith("note:")


def test_defaults_when_no_tag(monkeypatch):
    s = _src(default_value="low", default_validator="none")
    monkeypatch.setattr(s, "_fetch_body", lambda: SAMPLE)
    add_flag = s.fetch()[1]
    assert add_flag.validator == "none" and add_flag.value == "low"


def test_include_done(monkeypatch):
    s = _src(include_done=True)
    monkeypatch.setattr(s, "_fetch_body", lambda: SAMPLE)
    assert any(t.title == "Old done thing" for t in s.fetch())


def test_leading_checkbox_marker_is_done(monkeypatch):
    s = _src()
    monkeypatch.setattr(s, "_fetch_body",
                        lambda: "<div>Title</div><div>[x] already done</div><div>real task</div>")
    assert [t.title for t in s.fetch()] == ["real task"]


NOTE_WITH_HEADINGS = (
    "<div><h1>AI learning path</h1></div>"
    "<div><h2>Reading</h2></div>"
    "<div>Read paper A</div>"
    "<div><h2>Depthfinder</h2></div>"
    "<div>Add coherence dimension [validator=test value=high]</div>"
    "<div><s>old depthfinder task</s></div>"
    "<div>Wire warn-below gate</div>"
    "<div><h2>Other</h2></div>"
    "<div>Not this one</div>"
)


def test_scopes_to_a_heading(monkeypatch):
    s = AppleNotesSource(SourceConfig(name="apple_notes",
                                      options={"note": "AI learning path", "heading": "Depthfinder"}))
    monkeypatch.setattr(s, "_fetch_body", lambda: NOTE_WITH_HEADINGS)
    tasks = s.fetch()
    titles = [t.title for t in tasks]
    assert titles == ["Add coherence dimension", "Wire warn-below gate"]  # only under Depthfinder
    assert "Read paper A" not in titles and "Not this one" not in titles
    assert "old depthfinder task" not in titles                          # done, skipped
    assert tasks[0].validator == "test" and tasks[0].value == "high"     # inline tag honored
