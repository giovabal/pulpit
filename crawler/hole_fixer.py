import itertools
from collections.abc import Callable, Iterator
from typing import Any

from django.db.models import Max

from webapp.models import Channel

_HOLE_FETCH_BATCH_SIZE: int = 100


def iter_hole_ranges(channel: Channel, min_telegram_id: int | None = None) -> Iterator[tuple[int, int]]:
    """Yield ``(start, end)`` pairs for each contiguous block of missing message IDs."""
    qs = channel.message_set.order_by("telegram_id")
    if min_telegram_id is not None:
        qs = qs.filter(telegram_id__gte=min_telegram_id)
    prev_id: int | None = None
    for (current_id,) in qs.values_list("telegram_id").iterator():
        if prev_id is not None and current_id - prev_id > 1:
            yield (prev_id + 1, current_id - 1)
        prev_id = current_id


def find_missing_message_ids(channel: Channel, min_telegram_id: int | None = None) -> list[int]:
    """Return the list of telegram_ids that are absent from channel's stored messages."""
    return [mid for start, end in iter_hole_ranges(channel, min_telegram_id) for mid in range(start, end + 1)]


def fix_message_holes(
    channel: Channel,
    telegram_channel: Any,
    api_client: Any,
    get_message_fn: Callable[[Channel, Any], tuple[bool, int]],
    remaining_limit: int | None,
    update_status: Callable[[str], None],
    channel_label: str,
    current_message_count: int,
) -> tuple[int, int]:
    """Fetch and store messages that fill detected gaps in the channel's message sequence.

    Returns ``(messages_processed, images_downloaded)``.
    Progress checkpoints are saved after each batch so an interrupted run can resume.
    """
    baseline_min_id = channel.last_hole_check_max_telegram_id

    # Build a lazy stream of every missing ID — never materialised in full.
    id_stream = (
        mid
        for start, end in iter_hole_ranges(channel, min_telegram_id=baseline_min_id)
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

    # Honour the optional budget — but keep id_stream as the shared ref so we
    # can probe it after islice is exhausted to detect truncation.
    consume_stream = itertools.islice(id_stream, remaining_limit) if remaining_limit is not None else id_stream

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
    for mid in consume_stream:
        batch.append(mid)
        if len(batch) >= _HOLE_FETCH_BATCH_SIZE:
            flush(batch)
            batch = []
    if batch:
        flush(batch)

    # If remaining_limit was set and the underlying stream still has items,
    # we were truncated — checkpoint is already at the last processed ID.
    if remaining_limit is not None and next(id_stream, None) is not None:
        update_status(f"{channel_label} | hole-fix limit reached, checkpoint saved")
        return processed_messages, downloaded_images

    channel.last_hole_check_max_telegram_id = channel.message_set.aggregate(Max("telegram_id"))["telegram_id__max"]
    channel.save(update_fields=["last_hole_check_max_telegram_id"])
    return processed_messages, downloaded_images
