"""Telegram custom emoji: the packs they come from, their files, and where they are used.

A custom emoji is a sticker document (``DocumentAttributeCustomEmoji``) that a post draws in
place of a span of its text — a plain Unicode fallback, which is all the stored text holds —
or that a reader reacts with. ``CustomEmoji`` holds one row per Telegram document id, created
as a placeholder the moment a stored message names it and filled in by the crawler's
resolution pass (``crawler.custom_emoji``): fallback character, format, pack and — when
sticker downloads are on — the file, stored once per document under ``stickers/emoji/``.
``CustomEmojiPack`` is the sticker set an emoji belongs to (its ``t.me/addemoji/`` link).
``MessageCustomEmoji`` records each use in a post's text as the UTF-16 span Telegram reports;
``MessageCustomReaction`` breaks down ``MessageReaction``'s aggregated ``"custom"`` bucket
per emoji.
"""

import os

from django.db import models

from webapp.models.base import BaseModel, OverwriteStorage, _telegram_picture_upload_to_function
from webapp.models.telegram_models import Message

#: The three formats Telegram serves custom emoji in, by MIME type → stored file extension.
CUSTOM_EMOJI_EXTENSIONS: dict[str, str] = {
    "image/webp": "webp",
    "application/x-tgsticker": "tgs",  # gzipped Lottie JSON
    "video/webm": "webm",
}


class CustomEmojiPack(BaseModel):
    """A custom emoji pack (a Telegram sticker set of custom emoji), titled by ``messages.getStickerSet``.

    ``is_in_target`` and ``note`` are the analyst's: a pack the study is about — an organisation's
    own pack, say — is marked in target in Manage → Emoji. Packs start out of target; the
    flag classifies, it never removes a pack's uses from any count.
    """

    telegram_id = models.BigIntegerField(unique=True)
    access_hash = models.BigIntegerField(null=True)
    short_name = models.CharField(max_length=255, blank=True)
    title = models.CharField(max_length=255, blank=True)
    emoji_count = models.PositiveIntegerField(null=True)
    # Set once the pack's title has been asked for; is_unavailable when Telegram no longer has it.
    fetched_at = models.DateTimeField(null=True)
    is_unavailable = models.BooleanField(default=False)
    is_in_target = models.BooleanField(default=False, db_index=True)
    note = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.display_title

    @property
    def display_title(self) -> str:
        return self.title or self.short_name or f"Pack {self.telegram_id}"

    @property
    def telegram_url(self) -> str:
        return f"https://t.me/addemoji/{self.short_name}" if self.short_name else ""


class CustomEmoji(BaseModel):
    """One custom emoji document; a placeholder (``fetched_at`` NULL) until the crawler resolves it."""

    telegram_id = models.BigIntegerField(unique=True)
    pack = models.ForeignKey(CustomEmojiPack, on_delete=models.SET_NULL, null=True, related_name="emoji")
    # The Unicode emoji the custom one stands for (DocumentAttributeCustomEmoji.alt).
    alt = models.CharField(max_length=32, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
    # Usable without Telegram Premium (DocumentAttributeCustomEmoji.free).
    is_free = models.BooleanField(null=True)
    # Drawn in the surrounding text colour, like a glyph (DocumentAttributeCustomEmoji.text_color).
    text_color = models.BooleanField(default=False)
    file = models.FileField(
        upload_to=_telegram_picture_upload_to_function, storage=OverwriteStorage(), max_length=255, blank=True
    )
    fetched_at = models.DateTimeField(null=True)
    # Telegram returned no document for the id (deleted, or never a custom emoji).
    is_unavailable = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "custom emoji"

    def __str__(self) -> str:
        return f"{self.alt or '?'} custom emoji {self.telegram_id}"

    def get_media_path(self, filename: str) -> str:
        # Keyed on the document id, like every message medium: one file however many posts use it.
        extension = CUSTOM_EMOJI_EXTENSIONS.get(self.mime_type) or filename.rsplit(".", 1)[-1]
        return os.path.join("stickers", "emoji", f"{self.telegram_id}.{extension}")

    @property
    def kind(self) -> str:
        """``"lottie"`` (TGS), ``"video"`` (webm) or ``"image"`` (webp) — how a page draws it."""
        if self.mime_type == "application/x-tgsticker":
            return "lottie"
        if self.mime_type.startswith("video/"):
            return "video"
        return "image"


class MessageCustomEmoji(models.Model):
    """A custom emoji drawn over a span of a post's text — Telegram's UTF-16 ``offset`` / ``length``."""

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="custom_emoji_spans")
    emoji = models.ForeignKey(CustomEmoji, on_delete=models.CASCADE, related_name="uses")
    offset = models.PositiveIntegerField()
    length = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["message", "offset"], name="msgcustomemoji_msg_offset_uniq")]
        ordering = ["offset"]

    def __str__(self) -> str:
        return f"custom emoji {self.emoji_id} at {self.offset} in message {self.message_id}"


class MessageCustomReaction(models.Model):
    """How many readers reacted to a message with one custom emoji (part of its ``"custom"`` bucket)."""

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="custom_reactions")
    emoji = models.ForeignKey(CustomEmoji, on_delete=models.CASCADE, related_name="reactions")
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["message", "emoji"], name="msgcustomreaction_msg_emoji_uniq")]
        ordering = ["-count"]

    def __str__(self) -> str:
        return f"custom emoji {self.emoji_id} ×{self.count} on message {self.message_id}"
