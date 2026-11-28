import contextlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.conf import settings

from runner.control import CLEANUP_ENV, PAUSE_REQUEST_ENV, PAUSED_ENV

logger = logging.getLogger(__name__)

TASK_NAMES = ("crawl_channels", "search_channels", "structural_analysis", "compare_analysis")
# The commands that honour a pause request (runner.control.PauseGate checkpoints).
PAUSABLE_TASKS = frozenset({"crawl_channels", "search_channels"})

_MANAGE_PY = str(settings.BASE_DIR / "manage.py")
_TMP_DIR = settings.BASE_DIR / "tmp"
_LAUNCH_LOCKS: dict[str, threading.Lock] = {name: threading.Lock() for name in TASK_NAMES}

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mK]")
_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")
_WARNING_RE = re.compile(r"^/.+\.py:\d+: \w+Warning:")

# Django's color_style() palette under DJANGO_COLORS=dark (pinned in launch()):
# ERROR → 31 (red, bold), WARNING → 33 (yellow, bold), SUCCESS → 32 (green,
# bold). Checked in this order so a line mixing styles keeps the most severe
# colour. launch() passes --force-color so the styles survive the pipe.
_SGR_CLASSES = (("31", "line-error"), ("33", "line-warning"), ("32", "line-success"))
_PROGRESS_PREFIX_RE = re.compile(r"^\[\d+/\d+\] ")


def _keyword_scope(text: str) -> str:
    """The part of *text* the keyword fallback is allowed to read.

    Per-channel progress lines are ``[i/N] [id=X] <title> | <status>`` (see
    ``ProgressPrinter`` in crawl_channels). The title is free text chosen by
    the channel's owner — it may read "COMEDY OF ERRORS | fans" — so only the
    status after the last separator says anything about the run. Titles may
    themselves contain " | "; statuses never do.
    """
    if _PROGRESS_PREFIX_RE.match(text) and " | " in text:
        return text.rsplit(" | ", 1)[1]
    return text


def _classify_line(raw: str, text: str) -> str:
    """CSS class for one log line.

    The authoritative signal is the ANSI SGR colour the command itself put on
    the line (self.style.ERROR/WARNING/SUCCESS, the styled WARNING+ log
    handler). Lines with no colour — plain progress writes, tracebacks,
    third-party output — fall back to keyword heuristics.
    """
    codes: set[str] = set()
    for match in _SGR_RE.finditer(raw):
        codes.update(c for c in match.group(1).split(";") if c)
    for code, cls in _SGR_CLASSES:
        if code in codes:
            return cls

    lowered = _keyword_scope(text).lower()
    if "error" in lowered or lowered.startswith("traceback") or lowered.startswith("exception"):
        return "line-error"
    if "warning" in lowered or "skipping" in lowered:
        return "line-warning"
    if "complete" in lowered or "done" in lowered or "success" in lowered:
        return "line-success"
    return ""


def _tmp(task: str, suffix: str) -> Path:
    _TMP_DIR.mkdir(exist_ok=True)
    return _TMP_DIR / f"runner_{task}{suffix}"


def _meta_path(task: str) -> Path:
    return _tmp(task, ".meta.json")


def _log_path(task: str) -> Path:
    return _tmp(task, ".log")


def _pause_request_path(task: str) -> Path:
    """Exists while a pause is requested; the panel creates it, deleting it resumes the run."""
    return _tmp(task, ".pause")


def _paused_path(task: str) -> Path:
    """Exists while the command is paused; written and removed by the command itself."""
    return _tmp(task, ".paused")


def _cleanup_note_path(task: str) -> Path:
    """What the command asks the wrapper to delete should it be killed (``runner.control.removed_if_killed``)."""
    return _tmp(task, ".cleanup.json")


def _clear_pause_files(task: str) -> None:
    _pause_request_path(task).unlink(missing_ok=True)
    _paused_path(task).unlink(missing_ok=True)


def _pause_state(task: str) -> str:
    """``none``, ``requested`` (not reached a checkpoint yet), ``paused``, or ``resuming`` (reconnecting)."""
    requested = _pause_request_path(task).exists()
    paused = _paused_path(task).exists()
    if paused:
        return "paused" if requested else "resuming"
    return "requested" if requested else "none"


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it (e.g. PID recycled by a privileged process).
        # Treat as running to avoid falsely reporting "failed".
        return True


def _idle_status() -> dict:
    return {
        "status": "idle",
        "start_time": None,
        "end_time": None,
        "args": [],
        "exit_code": None,
        "pid": None,
        "pause": "none",
    }


def get_status(task: str) -> dict:
    """Return the current status dict for a task."""
    meta_path = _meta_path(task)
    if not meta_path.exists():
        return _idle_status()

    try:
        meta = json.loads(meta_path.read_text())
    except (ValueError, OSError) as e:
        logger.warning("Cannot read task meta for %s: %s", task, e)
        return _idle_status()

    pid = meta.get("pid")
    exit_code = meta.get("exit_code")

    if exit_code is not None:
        status = "done" if exit_code == 0 else "failed"
    elif pid and _is_running(pid):
        status = "running"
    elif meta.get("launching"):
        # launch() writes the meta before Popen and the pid after it: in that window
        # there is neither pid nor exit code, and without this marker a concurrent
        # poll would paint the task "failed" (stopping the UI polling) and another
        # worker's launch() would see not-running and double-start the command. The
        # staleness bound keeps a launcher that died mid-spawn from wedging the task
        # as forever-"running".
        started = meta.get("start_time")
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(started)
        except (TypeError, ValueError):
            age = timedelta.max
        status = "running" if age < timedelta(seconds=60) else "failed"
    else:
        # Process ended without writing an exit code (e.g. SIGKILL).
        status = "failed"

    return {
        "status": status,
        "start_time": meta.get("start_time"),
        "end_time": meta.get("end_time"),
        "args": meta.get("args", []),
        "exit_code": exit_code,
        "pid": pid,
        # Pause files left by a run that ended (or a request sent as it ended) mean nothing.
        "pause": _pause_state(task) if status == "running" and task in PAUSABLE_TASKS else "none",
    }


def get_log_lines(task: str, offset: int = 0, since: str | None = None) -> tuple[list[dict[str, str]], int]:
    """Return (new_lines, new_offset) for the log since *offset* bytes.

    Each line is a ``{"text": <ANSI-stripped text>, "cls": <css class or "">}``
    dict — severity is classified server-side (from the line's ANSI colour,
    with keyword fallback) so the panel JS just applies the class.

    *since* is the run's ``start_time`` the caller's *offset* was taken against;
    when it differs from the current run's start_time a new run has begun, so the
    offset is stale and reset to 0 (otherwise a secondary observer whose offset
    predates the new run would seek past the start of the new log and silently
    skip its opening output).
    """
    log_path = _log_path(task)
    if not log_path.exists():
        return [], 0

    # A new run (different start_time) makes any prior offset meaningless, even when the
    # new log has already grown past it — reset on run identity, not just on size.
    if since is not None:
        try:
            current_start = json.loads(_meta_path(task).read_text()).get("start_time")
        except (ValueError, OSError):
            current_start = None
        if current_start is not None and since != current_start:
            offset = 0

    # `launch` truncates the log via open("wb"), so an offset from a previous
    # run can land past the current EOF. Detect that and reset (backstop for the
    # case where the caller did not pass *since*).
    if offset > log_path.stat().st_size:
        offset = 0

    with open(log_path, "rb") as f:
        f.seek(offset)
        data = f.read()

    if not data:
        return [], offset

    # Only process bytes up to and including the last newline.  Any trailing
    # bytes without a newline are left behind the offset so they are re-read on
    # the next poll — once the newline arrives the full line is emitted in one
    # piece (e.g. "  [3] Some Channel … done" rather than two separate lines when
    # polling catches a partial write).
    last_nl = data.rfind(b"\n")
    if last_nl == -1:
        return [], offset

    complete_data = data[: last_nl + 1]
    new_offset = offset + last_nl + 1

    text = complete_data.decode("utf-8", errors="replace")

    # Simulate terminal CR behaviour: split on \n, within each segment the last
    # \r-separated piece is what would be visible on screen. Classify severity
    # from that visible segment's ANSI codes before stripping them for display.
    # Also drop Python warning lines (header + indented code snippet).
    lines = []
    skip_next = False
    for raw_line in text.split("\n"):
        segments = raw_line.split("\r")
        raw_final = segments[-1]
        final = _ANSI_RE.sub("", raw_final).rstrip()
        if _WARNING_RE.match(final):
            skip_next = True
            continue
        if skip_next:
            skip_next = False
            continue
        if final:
            lines.append({"text": final, "cls": _classify_line(raw_final, final)})

    return lines, new_offset


_WRAPPER_SCRIPT = """\
import json, os, shutil, signal, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

meta_path = Path(sys.argv[1])
cmd = sys.argv[2:]
cleanup_note = os.environ.get("PULPIT_CLEANUP_FILE")


def _clean_up_after_kill():
    # The command leaves a cleanup note only if it died without unwinding (runner.control.removed_if_killed):
    # aborted (SIGTERM, which it does not catch so that it stops at once) or killed.
    if not cleanup_note:
        return
    note = Path(cleanup_note)
    try:
        spec = json.loads(note.read_text())
    except FileNotFoundError:
        return
    except Exception as e:
        print(f"\\x1b[31;1mrunner wrapper: unreadable cleanup note: {e}\\x1b[0m", file=sys.stderr)
        note.unlink(missing_ok=True)
        return
    try:
        import fcntl
    except ImportError:
        fcntl = None
    lock = Path(spec["lock"])
    handle = open(lock, "a+b")
    try:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return  # a run that started since holds it: the folders are its own now
        for path in map(Path, spec["remove"]):
            if path.exists():
                print(f"Removing {path.parent.name}/{path.name}/, which the stopped run left unfinished ...", flush=True)
                shutil.rmtree(path, ignore_errors=True)
        lock.unlink(missing_ok=True)  # while still locked: see runner.tmp_dir.held_lock
    finally:
        handle.close()
        note.unlink(missing_ok=True)


# Install SIGTERM handler before Popen: if a signal arrives in the gap
# between Popen returning and the handler being installed, the default
# disposition exits the wrapper and orphans the child management command,
# making it unreachable from the abort button.
_proc = None
_pending_sigterm = False
def _handle(_sig, _frame):
    global _pending_sigterm
    if _proc is None:
        _pending_sigterm = True
    else:
        _proc.send_signal(signal.SIGTERM)
signal.signal(signal.SIGTERM, _handle)

_proc = subprocess.Popen(cmd)
if _pending_sigterm:
    _proc.send_signal(signal.SIGTERM)
exit_code = _proc.wait()
# Before the exit code is recorded: until then the task reads as running, so neither a new launch
# nor Maintenance -> Temporary files acts on the folders being deleted.
try:
    _clean_up_after_kill()
except Exception as e:
    print(f"\\x1b[31;1mrunner wrapper: cleanup failed: {e}\\x1b[0m", file=sys.stderr)
try:
    m = json.loads(meta_path.read_text())
    m["exit_code"] = exit_code
    m["end_time"] = datetime.now(timezone.utc).isoformat()
    meta_path.write_text(json.dumps(m))
except Exception as e:
    # Hardcoded red SGR: output goes to the task log, where the panel maps
    # ANSI colour to line severity (runner.tasks._classify_line).
    print(f"\\x1b[31;1mrunner wrapper: failed to write metadata: {e}\\x1b[0m", file=sys.stderr)
sys.exit(exit_code)
"""


@contextlib.contextmanager
def launches_held() -> Iterator[None]:
    """Hold every task's launch lock: no task starts from this process inside the block (tmp/ being emptied)."""
    with contextlib.ExitStack() as stack:
        for name in TASK_NAMES:
            stack.enter_context(_LAUNCH_LOCKS[name])
        yield


def launch(task: str, args: list[str]) -> None:
    """Launch a management command as a subprocess, streaming output to a log file.

    The command is wrapped in a small self-contained Python script that is spawned
    as an independent process.  That wrapper process is not a daemon thread — it
    survives Django dev-server auto-reloads — so the exit code is always recorded
    in the meta file once the command finishes.
    """
    if task not in TASK_NAMES:
        raise ValueError(f"Unknown task: {task!r}")

    with _LAUNCH_LOCKS[task]:
        current = get_status(task)
        if current["status"] == "running":
            raise RuntimeError(f"Task {task!r} is already running (PID {current['pid']}).")

        _TMP_DIR.mkdir(exist_ok=True)
        log_path = _log_path(task)
        meta_path = _meta_path(task)
        # A request sent as the previous run ended would pause this one at its first checkpoint.
        _clear_pause_files(task)
        # A note left by a run whose wrapper died too (a reboot): Maintenance → Temporary files
        # deletes what it named.
        _cleanup_note_path(task).unlink(missing_ok=True)

        meta: dict = {
            "start_time": datetime.now(timezone.utc).isoformat(),
            "end_time": None,
            "args": args,
            "pid": None,
            "exit_code": None,
            # Tells get_status() the pid is intentionally absent for a moment;
            # cleared right after Popen below.
            "launching": True,
        }
        meta_path.write_text(json.dumps(meta))

        env = {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "PYTHONWARNINGS": "ignore::DeprecationWarning",
            "MPLBACKEND": "Agg",
            # Pin Django's palette so the SGR→severity mapping in
            # _classify_line is stable regardless of the server's environment.
            "DJANGO_COLORS": "dark",
        }
        if task in PAUSABLE_TASKS:
            env[PAUSE_REQUEST_ENV] = str(_pause_request_path(task))
            env[PAUSED_ENV] = str(_paused_path(task))
        env[CLEANUP_ENV] = str(_cleanup_note_path(task))
        # --force-color: stdout is a pipe, so Django would otherwise emit the
        # self.style.* markup as plain text and get_log_lines() could not
        # classify line severity from the ANSI codes.
        cmd = [sys.executable, _MANAGE_PY, task, "--force-color", *args]
        # Open log file, pass the fd to the subprocess, then close our copy immediately
        # (the subprocess keeps the fd alive via inheritance).
        with open(log_path, "wb") as log_file:
            proc = subprocess.Popen(
                [sys.executable, "-c", _WRAPPER_SCRIPT, str(meta_path), *cmd],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
            )

        # Re-read the on-disk meta before writing the pid: if the wrapper
        # finished between Popen returning and this line (a fast-failing
        # task — bad path, import error, argparse error) it has already
        # written end_time/exit_code, and a blind overwrite with our local
        # dict would wipe that out and leave get_status() reporting "failed"
        # via the pid-not-running branch.
        try:
            persisted = json.loads(meta_path.read_text())
        except (ValueError, OSError):
            persisted = meta
        persisted["pid"] = proc.pid
        persisted.pop("launching", None)
        meta_path.write_text(json.dumps(persisted))


def abort(task: str) -> bool:
    """Send SIGTERM to a running task. Returns True if the signal was delivered."""
    if task not in TASK_NAMES:
        return False
    current = get_status(task)
    if current["status"] != "running" or not current["pid"]:
        return False
    # Second _is_running() check immediately before the kill shrinks (but does
    # not close) the PID-recycle race window: between get_status() and the
    # kill, the wrapper could exit and the kernel could recycle the PID for an
    # unrelated process. Closing the window completely would need holding the
    # Popen handle across requests.
    if not _is_running(current["pid"]):
        return False
    try:
        os.kill(current["pid"], signal.SIGTERM)
        return True
    except (ProcessLookupError, PermissionError):
        # ProcessLookupError: the PID exited between the check and the kill.
        # PermissionError: the PID was recycled onto a process we cannot signal — the
        # same case _is_running() deliberately treats as "running". Either way the
        # signal was not delivered to our task, so report failure instead of 500ing.
        return False


def request_pause(task: str) -> bool:
    """Ask a running pausable task to pause at its next checkpoint. Returns True if the request was filed."""
    if task not in PAUSABLE_TASKS or get_status(task)["status"] != "running":
        return False
    _pause_request_path(task).touch()
    return True


def cancel_pause(task: str) -> bool:
    """Withdraw a pause request: a run still on its way to a checkpoint never pauses, a paused one resumes.

    Returns True if there was a request to withdraw.
    """
    if task not in PAUSABLE_TASKS:
        return False
    request = _pause_request_path(task)
    if not request.exists():
        return False
    request.unlink(missing_ok=True)
    return True


def reset(task: str) -> bool:
    """Delete the meta file so the task status returns to idle. Returns True if reset."""
    if task not in TASK_NAMES:
        return False
    if get_status(task)["status"] == "running":
        return False
    meta = _meta_path(task)
    if meta.exists():
        meta.unlink()
    _clear_pause_files(task)
    return True
