from collections.abc import Callable
from typing import Any

from django.db.models import Max

from webapp.models import Channel

_HOLE_FETCH_BATCH_SIZE: int = 100


def find_missing_message_ids(channel: Channel, min_telegram_id: int | None = None) -> list[int]:
    """Return the list of telegram_ids that are absent from channel's stored messages."""
    messages = channel.message_set.order_by("telegram_id")
    if min_telegram_id is not None:
        messages = messages.filter(telegram_id__gte=min_telegram_id)
    holes: list[int] = []
    prev_id: int | None = None
    for (current_id,) in messages.values_list("telegram_id").iterator():
        if prev_id is not None and current_id - prev_id > 1:
            holes.extend(range(prev_id + 1, current_id))
        prev_id = current_id
    return holes


def fix_message_holes(
    channel: Channel,
    telegram_channel: Any,
    api_client: Any,
    get_message_fn: Callable[[Channel, Any], int],
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
    missing_ids = find_missing_message_ids(channel, min_telegram_id=baseline_min_id)
    if not missing_ids:
        channel.last_hole_check_max_telegram_id = channel.message_set.aggregate(Max("telegram_id"))["telegram_id__max"]
        channel.save(update_fields=["last_hole_check_max_telegram_id"])
        update_status(f"{channel_label} | no message holes found")
        return 0, 0

    processed_messages = 0
    downloaded_images = 0
    was_limited = False
    if remaining_limit is not None and remaining_limit > 0:
        was_limited = len(missing_ids) > remaining_limit
        missing_ids = missing_ids[:remaining_limit]

    update_status(f"{channel_label} | fixing {len(missing_ids)} missing message ids")

    for offset in range(0, len(missing_ids), _HOLE_FETCH_BATCH_SIZE):
        batch = missing_ids[offset : offset + _HOLE_FETCH_BATCH_SIZE]
        api_client.wait()
        messages = api_client.client.get_messages(telegram_channel, ids=batch)
        if not isinstance(messages, list):
            messages = [messages]
        for telegram_message in messages:
            if telegram_message is None or not hasattr(telegram_message, "peer_id"):
                continue
            downloaded_images += get_message_fn(channel, telegram_message)
            processed_messages += 1
            update_status(f"{channel_label} | messages processed: {current_message_count + processed_messages}")
        # Save progress after each batch so an interrupted run resumes from here
        channel.last_hole_check_max_telegram_id = batch[-1]
        channel.save(update_fields=["last_hole_check_max_telegram_id"])

    if was_limited:
        update_status(f"{channel_label} | hole-fix limit reached, checkpoint saved")
        return processed_messages, downloaded_images

    channel.last_hole_check_max_telegram_id = channel.message_set.aggregate(Max("telegram_id"))["telegram_id__max"]
    channel.save(update_fields=["last_hole_check_max_telegram_id"])
    return processed_messages, downloaded_images
