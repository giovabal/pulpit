"""Styled console routing for WARNING+ log records in management commands.

Without a handler, ``logger.warning()`` / ``logger.error()`` calls from
first-party modules and third-party libraries reach stderr through Python's
last-resort handler as bare, style-less text. In a terminal that loses the
severity colour; in the Operations panel — which derives each log line's
colour from the ANSI SGR codes the line carries (``runner.tasks``) — it
loses the colour entirely. Commands wrap their work in
``styled_warning_logs(self.style)`` so every WARNING+ record is printed
through the command's own style: yellow for WARNING, red for ERROR+.
"""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

# Plain-language rewrites for the low-level Telethon warnings that routinely
# surface during a long crawl. They report transient, auto-recovered network
# events, but the raw text ("Server closed the connection: [Errno 104]
# Connection reset by peer") reads as alarming to a non-technical operator, so
# the log shows the friendly equivalent instead. Telethon warnings that match
# nothing here are shown unchanged.
_TELETHON_FRIENDLY_WARNINGS: tuple[tuple[str, str], ...] = (
    ("closed the connection", "Lost contact with Telegram for a moment — reconnecting automatically."),
    ("connection reset", "Lost contact with Telegram for a moment — reconnecting automatically."),
)


def _friendly_telethon_warning(message: str) -> str | None:
    """Return a plain-language rewrite for a known transient Telethon warning, or
    ``None`` when the message has no friendly equivalent and should be shown as-is."""
    lowered = message.lower()
    for needle, friendly in _TELETHON_FRIENDLY_WARNINGS:
        if needle in lowered:
            return friendly
    return None


class StyledWarningLogHandler(logging.Handler):
    """Route WARNING+ log records to the terminal as coloured, newline-separated messages."""

    def __init__(self, style: Any, ensure_newline: Callable[[], None] | None = None) -> None:
        super().__init__(logging.WARNING)
        self._style = style
        self._ensure_newline = ensure_newline

    def emit(self, record: logging.LogRecord) -> None:
        if self._ensure_newline is not None:
            self._ensure_newline()
        msg = self.format(record)
        # Telethon's own low-level warnings (logger namespace "telethon.*") are
        # rewritten into operator-friendly language where we have an equivalent;
        # first-party warnings are already phrased for the operator.
        if record.name.startswith("telethon"):
            friendly = _friendly_telethon_warning(record.getMessage())
            if friendly is not None:
                msg = friendly
        print(self._style.WARNING(msg) if record.levelno < logging.ERROR else self._style.ERROR(msg))


@contextmanager
def styled_warning_logs(style: Any, ensure_newline: Callable[[], None] | None = None) -> Iterator[None]:
    """Attach a :class:`StyledWarningLogHandler` to the root logger for the duration."""
    handler = StyledWarningLogHandler(style, ensure_newline)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield
    finally:
        root.removeHandler(handler)
