"""The channel columns the web app's per-channel CSVs open with (emoji usage, Audience sections).

``channel_id`` is the row's own key (callers write it first); :func:`channel_csv_cells` gives the rest.
The label is the channel's *current* one (:attr:`Channel.current_label`), as the pages show it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from webapp.models import Channel

CHANNEL_CSV_COLUMNS = ("channel_id", "channel_telegram_id", "channel_username", "channel_title", "label")


def channel_csv_cells(channel: Channel | None) -> list[Any]:
    """The cells after ``channel_id``: Telegram id, username, title, current label ("" for no channel)."""
    if channel is None:
        return ["", "", "", ""]
    label = channel.current_label
    return [channel.telegram_id, channel.username, channel.title, label.name if label else ""]
