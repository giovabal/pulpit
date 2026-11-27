"""The project's ``tmp/`` folder: what writes there, whether it is in use, and emptying it.

Three things write there:

* the Operations panel's task files, ``runner_<task>.*`` (``runner.tasks``): the log, the
  status, the pause files. A task writes its log for as long as it runs, so any running task
  makes the folder busy;
* every ``crawl_channels`` run's download folder, ``crawl_channels_<random>/``, launched from the
  panel or from a terminal. The run holds an advisory lock on ``crawl_channels_<random>.lock``
  next to it for as long as it lives (``crawl_download_dir``); the lock dies with the process,
  even a killed one, so an unlocked folder is the leftover of a run that is gone;
* Django's file cache (``CACHES["default"]``, ``tmp/django-cache/``), written by the web server
  and the crawler at any time. It is emptied through the cache API, never deleted, so a write in
  flight still finds its folder; it never makes the folder busy.

``scan`` reports each group's size and what keeps the folder busy; ``clear`` empties it when
nothing does, holding every task's launch lock so no Operations task starts meanwhile.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from django.conf import settings
from django.core.cache import caches

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt

CRAWL_DIR_PREFIX = "crawl_channels_"
LOCK_SUFFIX = ".lock"
TASK_FILE_PREFIX = "runner_"
# A crawl folder or lock this young is left alone even when unlocked: the run that made it may
# not have taken its lock yet.
FRESH_SECONDS = 60

GROUP_LABELS = {
    "crawl": "Download folders of crawls that ended without cleaning up",
    "crawl_active": "Download folders of running crawls",
    "tasks": "Operations panel logs of the last runs",
    "cache": "Page cache",
    "other": "Other files",
}


def tmp_root() -> Path:
    """The folder itself; read at call time so tests redirecting ``runner.tasks._TMP_DIR`` apply."""
    from runner import tasks

    return Path(tasks._TMP_DIR)


# ── Locks ────────────────────────────────────────────────────────────────────


def _try_lock(handle: IO[bytes]) -> bool:
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return False
    return True


def _unlock(handle: IO[bytes]) -> None:
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    else:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


@contextlib.contextmanager
def held_lock(path: Path) -> Iterator[None]:
    """Hold an exclusive advisory lock on ``path`` (created if missing) for the block; then remove it."""
    handle = open(path, "a+b")  # noqa: SIM115 - stays open for as long as the lock is held
    try:
        if not _try_lock(handle):
            raise RuntimeError(f"{path} is locked by another process")
        try:
            yield
        finally:
            _unlock(handle)
    finally:
        handle.close()
        path.unlink(missing_ok=True)


def is_locked(path: Path) -> bool:
    """True while a live process holds ``path``'s lock (``held_lock``); False for a missing file."""
    try:
        handle = open(path, "r+b")  # noqa: SIM115 - closed below
    except FileNotFoundError:
        return False
    except OSError:
        return True  # cannot even be opened (a Windows sharing violation): count it as in use
    with handle:
        if _try_lock(handle):
            _unlock(handle)
            return False
        return True


@contextlib.contextmanager
def crawl_download_dir() -> Iterator[str]:
    """A fresh ``tmp/crawl_channels_<random>/`` for one crawl, locked as in use until the block ends."""
    root = tmp_root()
    root.mkdir(exist_ok=True)
    path = tempfile.mkdtemp(prefix=CRAWL_DIR_PREFIX, dir=root)
    with held_lock(Path(path + LOCK_SUFFIX)):
        try:
            yield path
        finally:
            shutil.rmtree(path, ignore_errors=True)


# ── Scan and clear ───────────────────────────────────────────────────────────


def _cache_dir(root: Path) -> Path | None:
    """The default cache's folder when it is a file cache inside ``root``."""
    conf = settings.CACHES.get("default", {})
    if not conf.get("BACKEND", "").endswith("FileBasedCache") or not conf.get("LOCATION"):
        return None
    location = Path(conf["LOCATION"]).resolve()
    return location if location.parent == root.resolve() else None


def _size(path: Path) -> int:
    """Bytes under ``path``, symlinks counted as links and never followed."""
    try:
        if path.is_symlink() or not path.is_dir():
            return path.lstat().st_size
    except OSError:
        return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            with contextlib.suppress(OSError):
                total += os.lstat(os.path.join(dirpath, name)).st_size
    return total


def _crawl_lock_of(entry: Path) -> Path | None:
    """The lock guarding a crawl folder or the lock file itself; None for any other entry."""
    if not entry.name.startswith(CRAWL_DIR_PREFIX):
        return None
    if entry.name.endswith(LOCK_SUFFIX):
        return entry
    return entry.with_name(entry.name + LOCK_SUFFIX)


def _crawl_entry_active(entry: Path, lock: Path, now: float) -> bool:
    if is_locked(lock):
        return True
    with contextlib.suppress(OSError):
        if now - entry.lstat().st_mtime < FRESH_SECONDS:
            return True
    return False


def _classify(entry: Path, root: Path, now: float) -> str:
    cache = _cache_dir(root)
    if cache is not None and entry.resolve() == cache:
        return "cache"
    if entry.name.startswith(TASK_FILE_PREFIX):
        return "tasks"
    lock = _crawl_lock_of(entry)
    if lock is not None:
        return "crawl_active" if _crawl_entry_active(entry, lock, now) else "crawl"
    return "other"


def _blockers(root: Path, active_crawl_entries: list[str]) -> list[str]:
    from runner import tasks
    from runner.views import TASK_DEFINITIONS

    blockers = [
        f"{TASK_DEFINITIONS[name]['title']} is running in the Operations panel."
        for name in tasks.TASK_NAMES
        if tasks.get_status(name)["status"] == "running"
    ]
    panel_crawl = tasks.get_status("crawl_channels")["status"] == "running"
    if active_crawl_entries and not panel_crawl:
        folders = sorted({name.removesuffix(LOCK_SUFFIX) for name in active_crawl_entries})
        blockers.append(f"A crawl started from a terminal is downloading into {root.name}/{folders[0]}/.")
    return blockers


def scan(root: Path | None = None) -> dict[str, Any]:
    """Each group's entries and bytes, the total, and why the folder cannot be emptied (if so)."""
    root = root or tmp_root()
    now = time.time()
    groups = {key: {"entries": 0, "bytes": 0} for key in GROUP_LABELS}
    active_crawl: list[str] = []
    if root.is_dir():
        for entry in root.iterdir():
            group = _classify(entry, root, now)
            groups[group]["entries"] += 1
            groups[group]["bytes"] += _size(entry)
            if group == "crawl_active":
                active_crawl.append(entry.name)
    blockers = _blockers(root, active_crawl) if root.is_dir() else []
    total = sum(g["bytes"] for g in groups.values())
    entries = sum(g["entries"] for g in groups.values())
    return {
        "path": root.name,
        "exists": root.is_dir(),
        "total_bytes": total,
        "groups": [{"key": key, "label": GROUP_LABELS[key], **groups[key]} for key in GROUP_LABELS],
        "blockers": blockers,
        "clearable": not blockers and entries > 0,
    }


class TmpInUseError(RuntimeError):
    def __init__(self, blockers: list[str]) -> None:
        super().__init__(" ".join(blockers))
        self.blockers = blockers


@dataclass
class ClearReport:
    removed_entries: int = 0
    freed_bytes: int = 0
    cache_cleared: bool = False
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _remove(entry: Path) -> None:
    if entry.is_symlink() or not entry.is_dir():
        entry.unlink()
    else:
        shutil.rmtree(entry)


def clear(root: Path | None = None) -> ClearReport:
    """Empty the folder, keeping it; raise ``TmpInUseError`` while anything writes in it.

    Every task's launch lock is held throughout, so no Operations task starts (from this web
    process) into a folder being emptied, and each crawl folder's lock is checked again just
    before it goes.
    """
    from runner import tasks

    root = root or tmp_root()
    report = ClearReport()
    if not root.is_dir():
        return report
    with tasks.launches_held():
        state = scan(root)
        if state["blockers"]:
            raise TmpInUseError(state["blockers"])
        now = time.time()
        for entry in sorted(root.iterdir()):
            group = _classify(entry, root, now)
            size = _size(entry)
            if group == "cache":
                caches["default"].clear()
                report.cache_cleared = True
                report.freed_bytes += max(0, size - _size(entry))
                continue
            if group == "crawl_active":
                report.skipped.append(entry.name)
                continue
            try:
                _remove(entry)
            except OSError as exc:
                report.errors.append(f"{entry.name}: {exc}")
                report.freed_bytes += max(0, size - _size(entry))
                continue
            report.removed_entries += 1
            report.freed_bytes += size
    return report
