import json
import os
import re
import signal
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

TASK_NAMES = ("get_channels", "search_channels", "structural_analysis", "compare_analysis")

_MANAGE_PY = str(settings.BASE_DIR / "manage.py")
_TMP_DIR = settings.BASE_DIR / "tmp"
_LAUNCH_LOCKS: dict[str, threading.Lock] = {name: threading.Lock() for name in TASK_NAMES}

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mK]")
_WARNING_RE = re.compile(r"^/.+\.py:\d+: \w+Warning:")


def _tmp(task: str, suffix: str) -> Path:
    _TMP_DIR.mkdir(exist_ok=True)
    return _TMP_DIR / f"runner_{task}{suffix}"


def _meta_path(task: str) -> Path:
    return _tmp(task, ".meta.json")


def _log_path(task: str) -> Path:
    return _tmp(task, ".log")


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


def get_status(task: str) -> dict:
    """Return the current status dict for a task."""
    meta_path = _meta_path(task)
    if not meta_path.exists():
        return {"status": "idle", "start_time": None, "end_time": None, "args": [], "exit_code": None, "pid": None}

    try:
        meta = json.loads(meta_path.read_text())
    except (ValueError, OSError):
        return {"status": "idle", "start_time": None, "end_time": None, "args": [], "exit_code": None, "pid": None}

    pid = meta.get("pid")
    exit_code = meta.get("exit_code")

    if exit_code is not None:
        status = "done" if exit_code == 0 else "failed"
    elif pid and _is_running(pid):
        status = "running"
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
    }


def get_log_lines(task: str, offset: int = 0) -> tuple[list[str], int]:
    """Return (new_lines, new_offset) for the log since *offset* bytes."""
    log_path = _log_path(task)
    if not log_path.exists():
        return [], 0

    with open(log_path, "rb") as f:
        f.seek(offset)
        data = f.read()
        new_offset = offset + len(data)

    if not data:
        return [], new_offset

    text = data.decode("utf-8", errors="replace")
    text = _ANSI_RE.sub("", text)

    # Simulate terminal CR behaviour: split on \n, within each segment the last
    # \r-separated piece is what would be visible on screen.
    # Also drop Python warning lines (header + indented code snippet).
    lines = []
    skip_next = False
    for raw_line in text.split("\n"):
        segments = raw_line.split("\r")
        final = segments[-1].rstrip()
        if _WARNING_RE.match(final):
            skip_next = True
            continue
        if skip_next:
            skip_next = False
            continue
        if final:
            lines.append(final)

    return lines, new_offset


_WRAPPER_SCRIPT = """\
import json, signal, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

meta_path = Path(sys.argv[1])
cmd = sys.argv[2:]
proc = subprocess.Popen(cmd)
signal.signal(signal.SIGTERM, lambda _sig, _frame: proc.send_signal(signal.SIGTERM))
exit_code = proc.wait()
try:
    m = json.loads(meta_path.read_text())
    m["exit_code"] = exit_code
    m["end_time"] = datetime.now(timezone.utc).isoformat()
    meta_path.write_text(json.dumps(m))
except Exception:
    pass
sys.exit(exit_code)
"""


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

        meta: dict = {
            "start_time": datetime.now(timezone.utc).isoformat(),
            "end_time": None,
            "args": args,
            "pid": None,
            "exit_code": None,
        }
        meta_path.write_text(json.dumps(meta))

        env = {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "PYTHONWARNINGS": "ignore::DeprecationWarning",
            "MPLBACKEND": "Agg",
        }
        cmd = [sys.executable, _MANAGE_PY, task, *args]
        log_file = open(log_path, "wb")  # subprocess inherits the fd; we close our copy after Popen
        try:
            proc = subprocess.Popen(
                [sys.executable, "-c", _WRAPPER_SCRIPT, str(meta_path), *cmd],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
            )
        finally:
            log_file.close()

        meta["pid"] = proc.pid
        meta_path.write_text(json.dumps(meta))


def abort(task: str) -> bool:
    """Send SIGTERM to a running task. Returns True if the signal was delivered."""
    if task not in TASK_NAMES:
        return False
    current = get_status(task)
    if current["status"] != "running" or not current["pid"]:
        return False
    try:
        os.kill(current["pid"], signal.SIGTERM)
        return True
    except ProcessLookupError:
        return False
