import os

from conftest import make_config

from nightsweeper.scheduling.install import install


def test_install_renders_valid_plist_and_wrapper(tmp_path):
    cfg = make_config()
    cfg.schedule.hour = 3
    cfg.schedule.minute = 0
    agents = tmp_path / "agents"
    repo = tmp_path / "repo"
    repo.mkdir()
    rc = install(cfg, agents_dir=str(agents), repo=str(repo), python="/usr/bin/python3")
    assert rc == 0

    plist = agents / "com.nightsweeper.run.plist"
    text = plist.read_text()
    assert "StartCalendarInterval" in text
    assert "<integer>3</integer>" in text          # the configured hour
    assert "<false/>" in text                        # RunAtLoad false

    run_sh = repo / ".nightsweeper" / "run.sh"
    assert run_sh.exists() and os.access(run_sh, os.X_OK)
    assert "caffeinate -is" in run_sh.read_text()    # cannot idle-sleep mid-run
    assert "run --if-missed" in run_sh.read_text()   # self-heal flag
