import datetime
import itertools
from collections.abc import Callable, Iterator
from typing import Any

from django.db.models import Max

from webapp.models import Channel

_HOLE_FETCH_BATCH_SIZE: int = 100


def iter_hole_ranges(
    channel: Channel, min_telegram_id: int | None = None
) -> Iterator[tuple[int, int, "datetime.datetime | None", "datetime.datetime | None"]]:
    """Yield ``(start, end, prev_date, current_date)`` for each block of missing message IDs.

    ``prev_date`` / ``current_date`` are the dates of the stored messages bounding the gap (either
    may be ``None``). Telegram IDs are monotonic in time, so these bound the gap's date range and
    let callers tell whether the gap could contain in-target messages.
    """
    qs = channel.message_set.order_by("telegram_id")
    if min_telegram_id is not None:
        qs = qs.filter(telegram_id__gte=min_telegram_id)
    prev_id: int | None = None
    prev_date: datetime.datetime | None = None
    for current_id, current_date in qs.values_list("telegram_id", "date").iterator():
        if prev_id is not None and current_id - prev_id > 1:
            yield (prev_id + 1, current_id - 1, prev_date, current_date)
        prev_id, prev_date = current_id, current_date


def _gap_could_be_in_target(
    prev_date: datetime.datetime | None,
    current_date: datetime.datetime | None,
    intervals: list[tuple[Any, Any]],
) -> bool:
    """Whether a gap bounded by these dates could contain an in-target message.

    Conservative: a gap with an unknown bounding date is always fetched.
    """
    if prev_date is None or current_date is None:
        return True
    lo = min(prev_date, current_date).date()
    hi = max(prev_date, current_date).date()
    return any((s is None or s <= hi) and (e is None or e >= lo) for s, e in intervals)


def fix_message_holes(
    channel: Channel,
    telegram_channel: Any,
    api_client: Any,
    get_message_fn: Callable[[Channel, Any], tuple[bool, int]],
    update_status: Callable[[str], None],
    channel_label: str,
    current_message_count: int,
) -> tuple[int, int]:
    """Fetch and store messages that fill detected gaps in the channel's message sequence.

    Returns ``(messages_processed, images_downloaded)``.
    Progress checkpoints are saved after each batch so an interrupted run can resume.
    """
    baseline_min_id = channel.last_hole_check_max_telegram_id

    # Non-to_inspect channels only store in-target-period messages, so a gap whose bounding dates
    # fall entirely outside those periods is intentional — skip it instead of re-fetching it forever.
    to_inspect = channel.to_inspect
    intervals = [] if to_inspect else list(channel.in_target_periods.values_list("start", "end"))

    # Build a lazy stream of every missing ID — never materialised in full.
    id_stream = (
        mid
        for start, end, prev_date, current_date in iter_hole_ranges(channel, min_telegram_id=baseline_min_id)
        if to_inspect or _gap_could_be_in_target(prev_date, current_date, intervals)
        for mid in range(start, end + 1)
    )

    # Peek: if the stream is empty there are no holes.
    first = next(id_stream, None)
    if first is None:
        channel.last_hole_check_max_telegram_id = channel.message_set.aggregate(Max("telegram_id"))["telegram_id__max"]
        channel.save(update_fields=["last_hole_check_max_telegram_id"])
        update_status(f"{channel_label} | no message holes found")
        return 0, 0

    # Put the peeked item back at the front.
    id_stream = itertools.chain([first], id_stream)

    update_status(f"{channel_label} | fixing message holes")

    processed_messages = 0
    downloaded_images = 0

    def flush(batch: list[int]) -> None:
        nonlocal processed_messages, downloaded_images
        api_client.wait()
        messages = api_client.client.get_messages(telegram_channel, ids=batch)
        if not isinstance(messages, list):
            messages = [messages]
        for telegram_message in messages:
            if telegram_message is None or not hasattr(telegram_message, "peer_id"):
                continue
            stored, imgs = get_message_fn(channel, telegram_message)
            downloaded_images += imgs
            if stored:
                processed_messages += 1
            update_status(f"{channel_label} | messages processed: {current_message_count + processed_messages}")
        # Save progress after each batch so an interrupted run resumes from here.
        channel.last_hole_check_max_telegram_id = batch[-1]
        channel.save(update_fields=["last_hole_check_max_telegram_id"])

    batch: list[int] = []
    for mid in id_stream:
        batch.append(mid)
        if len(batch) >= _HOLE_FETCH_BATCH_SIZE:
            flush(batch)
            batch = []
    if batch:
        flush(batch)

    channel.last_hole_check_max_telegram_id = channel.message_set.aggregate(Max("telegram_id"))["telegram_id__max"]
    channel.save(update_fields=["last_hole_check_max_telegram_id"])
    return processed_messages, downloaded_images
