"""The temporary files: the project's ``tmp/`` folder and what stopped analyses leave in ``exports/``.

Three things write in ``tmp/``:

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

In ``exports/``, ``structural_analysis`` stages its output in ``<name>.tmp/`` and, while it
publishes, moves the previous export aside to ``<name>.old/`` (``_atomic_publish``). A run that is
killed or aborted leaves them behind, and only a later run with the same name cleaned them up. Each
run now holds ``exports/<name>.lock`` from its start to its end (``export_in_progress``), so the
staging and backup of a live run are told apart from leftovers. A leftover backup whose export is
missing (the run stopped between the two renames) is put back, as the next run would do.

``scan`` reports each group's size and what keeps the folder busy; ``clear`` empties it when
nothing does, holding every task's launch lock so no Operations task starts meanwhile.
"""

from __future__ import annotations

import contextlib
import os
import re
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
# structural_analysis' staging and backup folders next to exports/<name>/ (export names hold no dot).
STAGING_SUFFIX = ".tmp"
BACKUP_SUFFIX = ".old"
_EXPORT_NAME = re.compile(r"[\w\-]+")
# A crawl folder, export leftover or lock this young is left alone even when unlocked: the run
# that made it may not have taken its lock yet.
FRESH_SECONDS = 60
# How long a run waits for a lock someone else holds: ``is_locked`` takes it for an instant to probe it.
LOCK_WAIT_SECONDS = 2.0

GROUP_LABELS = {
    "crawl": "Download folders of crawls that ended without cleaning up",
    "crawl_active": "Download folders of running crawls (kept)",
    "exports": "Unfinished exports in exports/, from analyses that stopped before publishing",
    "exports_restore": "Exports in exports/ an analysis stopped while replacing (put back, not deleted)",
    "exports_active": "Exports being written by a running analysis (kept)",
    "tasks": "Operations panel logs of the last runs",
    "cache": "Page cache",
    "other": "Other files",
}
# Kept by ``clear``: in use.
ACTIVE_GROUPS = frozenset({"crawl_active", "exports_active"})


def tmp_root() -> Path:
    """The folder itself; read at call time so tests redirecting ``runner.tasks._TMP_DIR`` apply."""
    from runner import tasks

    return Path(tasks._TMP_DIR)


def exports_root() -> Path:
    """``exports/``; read at call time so tests overriding ``BASE_DIR`` apply."""
    return Path(settings.BASE_DIR) / "exports"


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


class LockHeldError(RuntimeError):
    """The lock is held by another process."""


def _is_same_file(handle: IO[bytes], path: Path) -> bool:
    try:
        return os.path.samestat(os.fstat(handle.fileno()), os.stat(path))
    except OSError:
        return False


def _acquire(path: Path, wait: float) -> IO[bytes]:
    deadline = time.monotonic() + wait
    while True:
        handle = open(path, "a+b")  # noqa: SIM115 - stays open for as long as the lock is held
        if _try_lock(handle):
            if _is_same_file(handle, path):
                return handle
            # The holder removed the file as it let go: this lock guards nothing any more.
            _unlock(handle)
            handle.close()
            continue
        handle.close()
        if time.monotonic() >= deadline:
            raise LockHeldError(f"{path} is locked by another process")
        time.sleep(0.05)


@contextlib.contextmanager
def held_lock(path: Path, wait: float | None = None) -> Iterator[None]:
    """Hold an exclusive advisory lock on ``path`` (created if missing) for the block; then remove it.

    A lock someone else holds is retried for ``wait`` seconds (``LOCK_WAIT_SECONDS`` by default),
    then ``LockHeldError``. The file is removed while still locked (POSIX), so a process that
    opened it meanwhile and gets the lock next sees it is gone and starts over on a new file,
    rather than holding a lock nobody can see.
    """
    handle = _acquire(path, LOCK_WAIT_SECONDS if wait is None else wait)
    try:
        yield
    finally:
        if fcntl is not None:
            path.unlink(missing_ok=True)
            handle.close()  # releases the lock
        else:  # Windows cannot remove a file that is open
            _unlock(handle)
            handle.close()
            with contextlib.suppress(OSError):
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


@contextlib.contextmanager
def export_in_progress(name: str) -> Iterator[None]:
    """Mark ``exports/<name>.tmp/`` and ``<name>.old/`` as this run's for the block (``exports/<name>.lock``).

    ``LockHeldError`` when another run of the same name holds it. The staging folder goes when the
    block ends: a published run has renamed it already, and any other way out (an error, Ctrl-C)
    leaves nothing worth keeping. Killed by the Operations panel's Abort, which unwinds nothing,
    the run leaves it to the panel's wrapper (``removed_if_killed``). ``<name>.old/`` is never
    deleted here: it may be the only published copy (the command's crash recovery).
    """
    from runner.control import removed_if_killed

    root = exports_root()
    root.mkdir(parents=True, exist_ok=True)
    lock = root / f"{name}{LOCK_SUFFIX}"
    staging = root / f"{name}{STAGING_SUFFIX}"
    with held_lock(lock), removed_if_killed(lock, [staging]):
        try:
            yield
        finally:
            shutil.rmtree(staging, ignore_errors=True)


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


def _entry_active(entry: Path, lock: Path, now: float) -> bool:
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
        return "crawl_active" if _entry_active(entry, lock, now) else "crawl"
    return "other"


def _export_leftover(entry: Path) -> tuple[str, str] | None:
    """``(export name, suffix)`` of an analysis' staging, backup or lock in ``exports/``; None otherwise."""
    name, dot, suffix = entry.name.rpartition(".")
    suffix = dot + suffix
    if not dot or suffix not in (STAGING_SUFFIX, BACKUP_SUFFIX, LOCK_SUFFIX) or not _EXPORT_NAME.fullmatch(name):
        return None
    return name, suffix


def _classify_export(entry: Path, root: Path, now: float) -> str | None:
    """The group of an ``exports/`` entry; None for an export, or anything that is not an analysis' leftover."""
    parsed = _export_leftover(entry)
    if parsed is None:
        return None
    name, suffix = parsed
    if _entry_active(entry, root / f"{name}{LOCK_SUFFIX}", now):
        return "exports_active"
    if suffix == BACKUP_SUFFIX and not (root / name).is_dir():
        return "exports_restore"
    return "exports"


def _entries(root: Path, exports: Path, now: float) -> Iterator[tuple[Path, str]]:
    """Every entry of ``tmp/`` and every analysis leftover in ``exports/``, with its group."""
    if root.is_dir():
        for entry in sorted(root.iterdir()):
            yield entry, _classify(entry, root, now)
    if exports.is_dir():
        for entry in sorted(exports.iterdir()):
            group = _classify_export(entry, exports, now)
            if group is not None:
                yield entry, group


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


def scan(root: Path | None = None, exports: Path | None = None) -> dict[str, Any]:
    """Each group's entries and bytes, the total, and why the files cannot be deleted (if so).

    An analysis writing its export does not block: its folders are kept, the rest goes.
    """
    root = root or tmp_root()
    exports = exports or exports_root()
    groups = {key: {"entries": 0, "bytes": 0} for key in GROUP_LABELS}
    active_crawl: list[str] = []
    for entry, group in _entries(root, exports, time.time()):
        groups[group]["entries"] += 1
        groups[group]["bytes"] += _size(entry)
        if group == "crawl_active":
            active_crawl.append(entry.name)
    blockers = _blockers(root, active_crawl) if root.is_dir() else []
    total = sum(g["bytes"] for g in groups.values())
    deletable = sum(g["entries"] for key, g in groups.items() if key not in ACTIVE_GROUPS)
    return {
        "path": root.name,
        "exists": root.is_dir(),
        "total_bytes": total,
        "groups": [{"key": key, "label": GROUP_LABELS[key], **groups[key]} for key in GROUP_LABELS],
        "blockers": blockers,
        "clearable": not blockers and deletable > 0,
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
    # Exports put back from the backup an analysis left (``exports_restore``).
    restored: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _remove_lock(path: Path) -> bool:
    """Remove a lock file nobody holds, taking the lock first; False when someone holds it.

    Taking it first means a run that opened the file meanwhile is never left holding a lock that
    nobody can see (``held_lock``).
    """
    try:
        with held_lock(path, wait=0):
            pass
    except LockHeldError:
        return False
    return True


def _remove(entry: Path) -> bool:
    """Delete an entry, symlinks unlinked and never followed; False for a lock someone holds."""
    if entry.is_symlink():
        entry.unlink()
    elif entry.is_dir():
        shutil.rmtree(entry)
    elif entry.name.endswith(LOCK_SUFFIX):
        return _remove_lock(entry)
    else:
        entry.unlink()
    return True


def _shown(entry: Path) -> str:
    return f"{entry.parent.name}/{entry.name}"


def clear(root: Path | None = None, exports: Path | None = None) -> ClearReport:
    """Empty ``tmp/``, keeping it, and remove the analyses' leftovers in ``exports/``.

    Raise ``TmpInUseError`` while anything writes in ``tmp/``. Every task's launch lock is held
    throughout, so no Operations task starts (from this web process) meanwhile, and each entry's
    lock is checked again just before it goes: a crawl or analysis that started in between keeps
    its folders.
    """
    from runner import tasks

    root = root or tmp_root()
    exports = exports or exports_root()
    report = ClearReport()
    with tasks.launches_held():
        state = scan(root, exports)
        if state["blockers"]:
            raise TmpInUseError(state["blockers"])
        for entry, group in _entries(root, exports, time.time()):
            size = _size(entry)
            if group == "cache":
                caches["default"].clear()
                report.cache_cleared = True
                report.freed_bytes += max(0, size - _size(entry))
                continue
            if group in ACTIVE_GROUPS:
                report.skipped.append(_shown(entry))
                continue
            try:
                if group == "exports_restore":
                    entry.rename(entry.with_suffix(""))
                    report.restored.append(entry.stem)
                    continue
                if not _remove(entry):
                    report.skipped.append(_shown(entry))
                    continue
            except OSError as exc:
                report.errors.append(f"{_shown(entry)}: {exc}")
                report.freed_bytes += max(0, size - _size(entry))
                continue
            report.removed_entries += 1
            report.freed_bytes += size
    return report
