"""Run control for the commands the Operations panel launches: a cooperative pause and a clean abort.

**Pause.** The panel asks a running command to pause by creating its *request* file
(``runner.tasks.request_pause``). The command honours it at its next ``PauseGate.checkpoint()``,
a point it placed between two channels or two phases, where it holds no transaction and no
open cursor: it runs the release hooks it registered (the crawl disconnects from Telegram,
which also closes Telethon's session file), closes every database connection, writes the
*paused* file and waits. Deleting the request (``runner.tasks.cancel_pause``) resumes it: the
hooks reconnect, the paused file goes, and the run carries on where it stopped with its
in-memory state intact (the channel list read at the start, the per-run caches, the progress
counter). A request deleted before the command reached a checkpoint never takes effect. The
two paths come from the environment, set by ``runner.tasks.launch``; a command started from a
shell has neither, and every checkpoint is a no-op.

**Abort.** ``sigterm_exits`` turns the panel's SIGTERM into ``SystemExit``, so ``finally``
blocks and context managers run: the crawl's temporary download directory is removed, the
Telegram client disconnects, an open transaction rolls back and an interrupted message walk
records the days it finished. A second SIGTERM kills outright.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import signal
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from django.db import connections

logger = logging.getLogger(__name__)

PAUSE_REQUEST_ENV = "PULPIT_PAUSE_REQUEST_FILE"
PAUSED_ENV = "PULPIT_PAUSED_FILE"
# How often a paused command looks for the request file to be gone.
PAUSE_POLL_SECONDS = 1.0


@dataclass(frozen=True)
class _Hold:
    """A resource the command keeps open across checkpoints and gives up while paused."""

    release: Callable[[], Any]
    restore: Callable[[], Any]
    label: str


def _duration(seconds: float) -> str:
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min {secs} s"
    return f"{secs} s"


class PauseGate:
    """The command side of the pause protocol (see the module docstring)."""

    def __init__(
        self,
        request_path: Path | None = None,
        paused_path: Path | None = None,
        *,
        stdout: Any = None,
        style: Any = None,
        poll_seconds: float = PAUSE_POLL_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.request_path = request_path
        self.paused_path = paused_path
        self.stdout = stdout
        self.style = style
        self.poll_seconds = poll_seconds
        self._sleep = sleep
        self._holds: list[_Hold] = []

    @classmethod
    def from_env(cls, *, stdout: Any = None, style: Any = None) -> PauseGate:
        """The gate of a panel-launched run; a disabled one when the paths are not in the environment."""
        request = os.environ.get(PAUSE_REQUEST_ENV)
        paused = os.environ.get(PAUSED_ENV)
        if not (request and paused):
            return cls(stdout=stdout, style=style)
        return cls(Path(request), Path(paused), stdout=stdout, style=style)

    @property
    def enabled(self) -> bool:
        return self.request_path is not None and self.paused_path is not None

    @contextlib.contextmanager
    def holding(self, release: Callable[[], Any], restore: Callable[[], Any], *, label: str) -> Iterator[None]:
        """Within the block, a pause calls ``release`` before waiting and ``restore`` before going on."""
        if not self.enabled:
            yield
            return
        hold = _Hold(release, restore, label)
        self._holds.append(hold)
        try:
            yield
        finally:
            self._holds.remove(hold)

    def checkpoint(self) -> bool:
        """Pause here when a pause was requested; True when the run paused (and has resumed since).

        Call it only where the command streams no queryset: closing the connection would break
        an open cursor. Inside a transaction it does nothing: closing would roll the transaction
        back, so the pause waits for the next checkpoint.
        """
        if not self.enabled or not self.request_path.exists():
            return False
        if any(conn.in_atomic_block for conn in connections.all(initialized_only=True)):
            return False
        for hold in reversed(self._holds):
            try:
                hold.release()
            except Exception as exc:  # noqa: BLE001 - the database is still released, which is the point
                logger.warning("Could not release %s while pausing: %s", hold.label, exc)
        connections.close_all()
        started = time.monotonic()
        self.paused_path.write_text(
            json.dumps({"pid": os.getpid(), "paused_at": datetime.now(timezone.utc).isoformat()})
        )
        released = " and ".join(["the database", *(hold.label for hold in self._holds)])
        self._say(f"Paused: released {released}. Click Resume in the Operations panel to continue.", "WARNING")
        try:
            while True:
                while self.request_path.exists():
                    self._sleep(self.poll_seconds)
                try:
                    self._restore()
                except Exception as exc:  # noqa: BLE001 - stay paused and let the analyst retry
                    self._say(f"Could not resume ({exc}): still paused. Click Resume to try again.", "ERROR")
                    self.request_path.touch()
                    continue
                break
        finally:
            # Also on an abort while paused, so the panel never shows a finished run as paused.
            self.paused_path.unlink(missing_ok=True)
        self._say(f"Resumed after {_duration(time.monotonic() - started)}.", "SUCCESS")
        return True

    def _restore(self) -> None:
        restored: list[_Hold] = []
        try:
            for hold in self._holds:
                hold.restore()
                restored.append(hold)
        except BaseException:
            for hold in reversed(restored):
                with contextlib.suppress(Exception):
                    hold.release()
            raise

    def _say(self, text: str, level: str) -> None:
        if self.stdout is None:
            return
        styler = getattr(self.style, level, None) if self.style is not None else None
        self.stdout.write(styler(text) if styler else text)
        self.stdout.flush()


@contextlib.contextmanager
def sigterm_exits() -> Iterator[None]:
    """Within the block, the first SIGTERM raises ``SystemExit(143)``; a second one kills outright.

    Python's default SIGTERM disposition ends the process on the spot, skipping every
    ``finally``. A no-op outside the main thread, where signal handlers cannot be installed.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def _exit(signum: int, _frame: Any) -> None:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        raise SystemExit(128 + signum)

    previous = signal.signal(signal.SIGTERM, _exit)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)
