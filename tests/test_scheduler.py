"""The worker container's timetable (deploy/scheduler.py)."""
import datetime as dt
import importlib.util
import tarfile
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("scheduler", ROOT / "deploy" / "scheduler.py")
sched = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sched)
IST = ZoneInfo("Asia/Kolkata")


def at(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=IST)


def test_timetable():
    assert sched.due(at(2026, 11, 27, 18, 30)) == [("daily",)]            # Friday evening build
    assert sched.due(at(2026, 11, 27, 19, 30)) == [("--if-stale",)]       # retry
    assert sched.due(at(2026, 11, 27, 20, 0)) == [("--if-stale",)]        # hourly FII/DII catch-up
    assert sched.due(at(2026, 11, 27, 20, 5)) == []
    assert sched.due(at(2026, 11, 28, 18, 30)) == []                       # Saturday: no session
    assert sched.due(at(2026, 11, 28, 2, 15)) == [("backup",)]            # backups every day
    assert sched.due(at(2026, 11, 26, 2, 15)) == [("backup",)]


def test_backup_keeps_the_newest(tmp_path, monkeypatch):
    data, cache = tmp_path / "data", tmp_path / "cache"
    data.mkdir()
    cache.mkdir()
    (data / "rs_data.json").write_text("{}")
    (data / "users.json").write_text("{}")
    (cache / ".nse_archive.json").write_text("{}")
    monkeypatch.setattr(sched, "DATA", str(data))
    monkeypatch.setattr(sched, "CACHE", str(cache))
    monkeypatch.setattr(sched, "KEEP_BACKUPS", 2)
    for day in (1, 2, 3):
        sched.backup(at(2026, 11, day, 2, 15))
    kept = sorted((data / "backups").iterdir())
    assert [p.name for p in kept] == ["nse-rs-20261102-0215.tar.gz", "nse-rs-20261103-0215.tar.gz"]
    names = tarfile.open(kept[-1]).getnames()
    assert "data/rs_data.json" in names and "cache/.nse_archive.json" in names
    assert not any("backups" in n for n in names)
