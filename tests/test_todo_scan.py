from nightsweeper.config import SourceConfig
from nightsweeper.sources.todo_scan import TodoScanSource


def _write(p, text):
    p.write_text(text, encoding="utf-8")


def test_only_enrolled_markers_dispatch_bare_are_inventory(tmp_path):
    _write(tmp_path / "a.py", "# TODO(nightsweeper: validator=test value=med) wire it up\n")
    _write(tmp_path / "b.py", "# TODO just a private note\n# FIXME another bare one\n")
    s = TodoScanSource(SourceConfig(name="todo_scan", options={"paths": [str(tmp_path)]}))
    tasks = s.fetch()
    assert len(tasks) == 1                       # only the enrolled marker
    t = tasks[0]
    assert t.validator == "test" and t.value == "med" and t.source == "todo_scan"
    assert s.inventory()["bare_todo_count"] == 2  # both bare markers counted, not dispatched


def test_stable_ids_and_dedupe_within_scan(tmp_path):
    _write(tmp_path / "a.py", "# TODO(nightsweeper: validator=test) one\n")
    s = TodoScanSource(SourceConfig(name="todo_scan", options={"paths": [str(tmp_path)]}))
    id1 = s.fetch()[0].id
    id2 = s.fetch()[0].id
    assert id1 == id2 and id1.startswith("td:")


def test_unknown_tag_values_fall_back(tmp_path):
    _write(tmp_path / "a.py", "# TODO(nightsweeper: validator=bogus value=nope) x\n")
    s = TodoScanSource(SourceConfig(name="todo_scan", options={"paths": [str(tmp_path)], "default_value": "low"}))
    t = s.fetch()[0]
    assert t.validator == "none" and t.value == "low"  # bad values fall back safely
