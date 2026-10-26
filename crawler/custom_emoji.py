"""Custom emoji: record the ones stored messages name, then resolve their documents and packs.

Telegram puts a custom emoji in a post as a ``MessageEntityCustomEmoji`` — a UTF-16
``offset`` / ``length`` span over a plain Unicode fallback, plus the ``document_id`` of the
sticker document drawn in its place — and a custom-emoji reaction as a
``ReactionCustomEmoji(document_id)``. Storing a message records the spans
(``save_message_custom_emoji``; ``channel_crawler._save_reactions`` the per-emoji reaction
counts), each pointing at a ``CustomEmoji`` row keyed on the document id that starts as a
placeholder — no network call while a message is stored.

``resolve_custom_emoji`` then fills the placeholders in batches of ``CUSTOM_EMOJI_BATCH``
ids (``messages.getCustomEmojiDocuments``, callable without Premium): fallback character,
format, the free / text-colour flags, and the pack (``DocumentAttributeCustomEmoji.stickerset``),
which ``messages.getStickerSet`` then titles. With sticker downloads on, the same documents —
fresh file references included — are downloaded, one file per document id
(``MediaHandler.download_custom_emoji``). The crawl runs it after every channel and once at
the end of the messages loop, so whatever an interrupted pass left is picked up next time.
"""

import logging
import os
from collections.abc import Callable, Iterable
from itertools import batched
from time import sleep
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from crawler.client import TelegramAPIClient
from webapp.models import CustomEmoji, CustomEmojiPack, MessageCustomEmoji

from telethon import errors
from telethon.tl.functions.messages import GetCustomEmojiDocumentsRequest, GetStickerSetRequest
from telethon.tl.types import DocumentAttributeCustomEmoji, InputStickerSetID, MessageEntityCustomEmoji

logger = logging.getLogger(__name__)

#: Document ids per ``messages.getCustomEmojiDocuments`` call — Telegram's limit.
CUSTOM_EMOJI_BATCH = 200

#: Primary keys per ``IN`` lookup, under SQLite's bound-variable limit.
_PK_CHUNK = 500

# Document ids already asked for in this process — a lookup that failed or a file that would
# not download is not re-requested after every channel of the run; the next run retries it.
# Same run-scoped give-up as media_handler._TIMED_OUT_THIS_RUN.
_ATTEMPTED_THIS_RUN: set[int] = set()
# Pack ids whose lookup failed with an unexpected error in this process, likewise.
_PACKS_ATTEMPTED_THIS_RUN: set[int] = set()


def custom_emoji_spans(telegram_message: Any) -> list[tuple[int, int, int]]:
    """``(document_id, offset, length)`` of every custom emoji in *telegram_message*'s text."""
    entities = getattr(telegram_message, "entities", None)
    if not isinstance(entities, (list, tuple)):
        return []
    return [
        (entity.document_id, entity.offset, entity.length)
        for entity in entities
        if isinstance(entity, MessageEntityCustomEmoji)
    ]


def custom_emoji_pks(document_ids: Iterable[int]) -> dict[int, int]:
    """Map each document id to its ``CustomEmoji`` pk, creating the placeholders still missing."""
    ids = sorted(set(document_ids))
    if not ids:
        return {}
    pks: dict[int, int] = {}
    for chunk in batched(ids, _PK_CHUNK):
        pks.update(CustomEmoji.objects.filter(telegram_id__in=chunk).values_list("telegram_id", "pk"))
    missing = [doc_id for doc_id in ids if doc_id not in pks]
    if missing:
        CustomEmoji.objects.bulk_create([CustomEmoji(telegram_id=doc_id) for doc_id in missing], ignore_conflicts=True)
        for chunk in batched(missing, _PK_CHUNK):
            pks.update(CustomEmoji.objects.filter(telegram_id__in=chunk).values_list("telegram_id", "pk"))
    return pks


def save_message_custom_emoji(message_pk: int, telegram_message: Any) -> None:
    """Replace the custom-emoji spans stored for *message_pk* with those *telegram_message* carries.

    A message without custom emoji and without stored spans writes nothing, so storing an
    ordinary message costs one read and never takes SQLite's write lock.
    """
    spans = custom_emoji_spans(telegram_message)
    if not spans and not MessageCustomEmoji.objects.filter(message_id=message_pk).exists():
        return
    pks = custom_emoji_pks(doc_id for doc_id, _, _ in spans)
    rows = {
        offset: MessageCustomEmoji(message_id=message_pk, emoji_id=pks[doc_id], offset=offset, length=length)
        for doc_id, offset, length in spans
    }
    with transaction.atomic():
        MessageCustomEmoji.objects.filter(message_id=message_pk).delete()
        MessageCustomEmoji.objects.bulk_create(list(rows.values()))


def _custom_emoji_attribute(document: Any) -> Any:
    for attribute in getattr(document, "attributes", None) or []:
        if isinstance(attribute, DocumentAttributeCustomEmoji):
            return attribute
    return None


def _pack_for(attribute: Any) -> CustomEmojiPack | None:
    """The ``CustomEmojiPack`` an emoji's ``stickerset`` names, created (untitled) on first sight."""
    stickerset = getattr(attribute, "stickerset", None)
    pack_id = getattr(stickerset, "id", None)
    if not isinstance(pack_id, int):
        return None
    access_hash = getattr(stickerset, "access_hash", None)
    pack, created = CustomEmojiPack.objects.get_or_create(
        telegram_id=pack_id, defaults={"access_hash": access_hash if isinstance(access_hash, int) else None}
    )
    if not created and isinstance(access_hash, int) and pack.access_hash != access_hash:
        pack.access_hash = access_hash
        pack.save(update_fields=["access_hash", "_updated"])
    return pack


def _fill_pack(pack: CustomEmojiPack, sticker_set: Any) -> None:
    """Write a Telegram ``StickerSet``'s title, short name, size and access hash onto *pack*, and save it."""
    access_hash = getattr(sticker_set, "access_hash", None)
    if isinstance(access_hash, int):
        pack.access_hash = access_hash
    pack.title = (getattr(sticker_set, "title", "") or "")[:255]
    pack.short_name = (getattr(sticker_set, "short_name", "") or "")[:255]
    count = getattr(sticker_set, "count", None)
    pack.emoji_count = count if isinstance(count, int) else None
    pack.fetched_at = timezone.now()
    pack.is_unavailable = False
    pack.save()


def pack_from_sticker_set(sticker_set: Any) -> CustomEmojiPack | None:
    """The ``CustomEmojiPack`` for a full Telegram ``StickerSet`` — a supergroup's ``ChannelFull.emojiset`` —
    created or refreshed from it (it carries the title, so no ``messages.getStickerSet`` lookup is due)."""
    pack_id = getattr(sticker_set, "id", None)
    if not isinstance(pack_id, int):
        return None
    pack, _ = CustomEmojiPack.objects.get_or_create(telegram_id=pack_id)
    _fill_pack(pack, sticker_set)
    return pack


def _needs_file(emoji: CustomEmoji, check_files: bool) -> bool:
    if not emoji.file:
        return True
    return check_files and not os.path.exists(os.path.join(settings.MEDIA_ROOT, emoji.file.name))


def _pending_ids(download: bool, check_files: bool) -> list[int]:
    """Document ids to ask Telegram for: unresolved placeholders, plus missing files when downloading."""
    ids = set(CustomEmoji.objects.filter(fetched_at__isnull=True).values_list("telegram_id", flat=True))
    if download:
        resolved = CustomEmoji.objects.filter(fetched_at__isnull=False, is_unavailable=False)
        if not check_files:
            resolved = resolved.filter(file="")
        ids.update(
            emoji.telegram_id for emoji in resolved.only("telegram_id", "file") if _needs_file(emoji, check_files)
        )
    return sorted(ids - _ATTEMPTED_THIS_RUN)


def _flood_wait(error: errors.FloodWaitError, what: str) -> None:
    logger.warning("Flood wait while %s; the rest is retried later: %s", what, error)
    if not settings.IGNORE_FLOODWAIT:
        sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)


def _apply_document(emoji: CustomEmoji, document: Any, media_handler: Any, check_files: bool) -> bool:
    """Write *document*'s metadata onto *emoji*, download its file when due; True if a file was saved."""
    attribute = _custom_emoji_attribute(document)
    emoji.mime_type = (getattr(document, "mime_type", "") or "")[:100]
    emoji.is_unavailable = False
    emoji.fetched_at = timezone.now()
    if attribute is not None:
        emoji.alt = (getattr(attribute, "alt", "") or "")[:32]
        emoji.is_free = bool(getattr(attribute, "free", False))
        emoji.text_color = bool(getattr(attribute, "text_color", False))
        emoji.pack = _pack_for(attribute)
    downloaded = False
    if media_handler is not None and media_handler.download_stickers and _needs_file(emoji, check_files):
        downloaded = media_handler.download_custom_emoji(document, emoji)
    emoji.save()
    return downloaded


def _resolve_documents(
    api_client: TelegramAPIClient,
    media_handler: Any,
    check_files: bool,
    update_status: Callable[[str], None],
) -> tuple[int, int, bool]:
    """Ask Telegram for the pending documents; ``(emoji resolved, files downloaded, flood-waited)``."""
    download = media_handler is not None and media_handler.download_stickers
    pending = _pending_ids(download, check_files)
    resolved = downloaded = 0
    for batch in batched(pending, CUSTOM_EMOJI_BATCH):
        update_status(f"resolving custom emoji … {resolved}/{len(pending)}")
        api_client.wait()
        try:
            documents = api_client.client(GetCustomEmojiDocumentsRequest(document_id=list(batch)))
        except errors.FloodWaitError as error:
            _flood_wait(error, "resolving custom emoji")
            return resolved, downloaded, True
        except Exception as error:  # noqa: BLE001 - an unresolvable batch must not abort the crawl
            _ATTEMPTED_THIS_RUN.update(batch)
            logger.warning("Could not resolve %d custom emoji (%s); retrying next run", len(batch), error)
            continue
        _ATTEMPTED_THIS_RUN.update(batch)
        by_id = {getattr(document, "id", None): document for document in documents or []}
        for emoji in CustomEmoji.objects.filter(telegram_id__in=batch).select_related("pack"):
            document = by_id.get(emoji.telegram_id)
            if document is None:
                # Not (or no longer) a custom emoji Telegram serves: stop asking for it.
                emoji.fetched_at = emoji.fetched_at or timezone.now()
                emoji.is_unavailable = True
                emoji.save(update_fields=["fetched_at", "is_unavailable", "_updated"])
                continue
            downloaded += _apply_document(emoji, document, media_handler, check_files)
            resolved += 1
    return resolved, downloaded, False


def _resolve_packs(api_client: TelegramAPIClient, update_status: Callable[[str], None]) -> int:
    """Title the packs not looked up yet (``messages.getStickerSet``); the number titled."""
    titled = 0
    packs = [
        pack
        for pack in CustomEmojiPack.objects.filter(fetched_at__isnull=True, access_hash__isnull=False)
        if pack.telegram_id not in _PACKS_ATTEMPTED_THIS_RUN
    ]
    for index, pack in enumerate(packs, 1):
        update_status(f"resolving custom emoji packs … {index}/{len(packs)}")
        api_client.wait()
        try:
            result = api_client.client(
                GetStickerSetRequest(
                    stickerset=InputStickerSetID(id=pack.telegram_id, access_hash=pack.access_hash), hash=0
                )
            )
        except errors.StickersetInvalidError:
            pack.fetched_at = timezone.now()
            pack.is_unavailable = True
            pack.save(update_fields=["fetched_at", "is_unavailable", "_updated"])
            continue
        except errors.FloodWaitError as error:
            _flood_wait(error, "resolving custom emoji packs")
            break
        except Exception as error:  # noqa: BLE001 - one pack must not abort the crawl
            _PACKS_ATTEMPTED_THIS_RUN.add(pack.telegram_id)
            logger.warning("Could not look up custom emoji pack %s (%s); retrying next run", pack.telegram_id, error)
            continue
        sticker_set = getattr(result, "set", None)
        if sticker_set is None:
            continue
        _fill_pack(pack, sticker_set)
        titled += 1
    return titled


def resolve_custom_emoji(
    api_client: TelegramAPIClient,
    media_handler: Any = None,
    status_callback: Callable[[str], None] | None = None,
    check_files: bool = False,
) -> tuple[int, int]:
    """Resolve pending custom emoji and title their packs; ``(emoji resolved, files downloaded)``.

    *media_handler* gates the downloads (``download_stickers``); ``None`` resolves metadata
    only. ``check_files`` also re-fetches emoji whose stored file is missing from disk — the
    ``--fix-missing-media`` pass. Never raises for a Telegram error: whatever is left pending
    is retried by the next call of a later run.
    """

    def update_status(message: str) -> None:
        if status_callback:
            status_callback(message)

    resolved, downloaded, flooded = _resolve_documents(api_client, media_handler, check_files, update_status)
    if not flooded:
        _resolve_packs(api_client, update_status)
    return resolved, downloaded
