import asyncio
import glob
import inspect
import logging
import os
import shutil
from typing import Any

from django.conf import settings

from crawler.client import TelegramAPIClient
from webapp.models import (
    Channel,
    Message,
    MessageAudio,
    MessageOtherMedia,
    MessagePicture,
    MessageSticker,
    MessageVideo,
    ProfilePicture,
)

from telethon import errors
from telethon.tl.types import (
    DocumentAttributeAnimated,
    DocumentAttributeAudio,
    DocumentAttributeSticker,
    DocumentAttributeVideo,
)

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT_SECONDS = 120


def _doc_attributes(document: Any) -> list[Any]:
    return getattr(document, "attributes", None) or []


def _is_sticker(document: Any) -> bool:
    return any(isinstance(a, DocumentAttributeSticker) for a in _doc_attributes(document))


def _is_audio(document: Any) -> bool:
    if any(isinstance(a, DocumentAttributeAudio) for a in _doc_attributes(document)):
        return True
    mime = getattr(document, "mime_type", "") or ""
    return mime.startswith("audio/")


def _is_voice(document: Any) -> bool:
    for a in _doc_attributes(document):
        if isinstance(a, DocumentAttributeAudio):
            return bool(getattr(a, "voice", False))
    return False


def _is_animated(document: Any) -> bool:
    return any(isinstance(a, DocumentAttributeAnimated) for a in _doc_attributes(document))


def _is_round_video(document: Any) -> bool:
    for a in _doc_attributes(document):
        if isinstance(a, DocumentAttributeVideo):
            return bool(getattr(a, "round_message", False))
    return False


class MediaHandler:
    def __init__(
        self,
        api_client: TelegramAPIClient,
        download_temp_dir: str | None = None,
        download_images: bool = False,
        download_video: bool = False,
        download_audio: bool = False,
        download_stickers: bool = False,
        download_other_media: bool = False,
    ) -> None:
        self.api_client = api_client
        self.download_temp_dir = download_temp_dir
        self.download_images = download_images
        self.download_video = download_video
        self.download_audio = download_audio
        self.download_stickers = download_stickers
        self.download_other_media = download_other_media

    def _download_media(self, telegram_object: Any) -> str | None:
        kwargs = {"file": self.download_temp_dir} if self.download_temp_dir else {}
        client = self.api_client.client
        # Unwrap the sync shim added by telethon.sync to get the raw async coroutine function.
        # Falls back to a direct synchronous call when the client does not expose the shim
        # (e.g. in tests using plain MagicMock).
        try:
            async_download = inspect.unwrap(type(client).download_media)
        except AttributeError:
            return client.download_media(telegram_object, **kwargs)

        async def _run() -> str | None:
            try:
                return await asyncio.wait_for(
                    async_download(client, telegram_object, **kwargs), DOWNLOAD_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                logger.warning("Media download timed out after %ss; skipping file", DOWNLOAD_TIMEOUT_SECONDS)
                return None

        return client.loop.run_until_complete(_run())

    def _cleanup_downloaded_file(self, filename: str | None) -> None:
        if filename and os.path.exists(filename):
            os.remove(filename)

    def download_profile_picture(self, telegram_channel: Any) -> int:
        pictures_downloaded = 0
        channel = Channel.objects.filter(telegram_id=telegram_channel.id).first()
        if channel is None:
            logger.warning("Channel not found for telegram_id=%s", telegram_channel.id)
            return 0
        # A record is considered up-to-date only when its file is on disk; records
        # with an empty picture field or a missing file get re-downloaded.
        on_disk_picture_ids: set[int] = set()
        for pp in ProfilePicture.objects.filter(channel=channel):
            if pp.picture and os.path.exists(pp.picture.path):
                on_disk_picture_ids.add(pp.telegram_id)
        for telegram_picture in self.api_client.client.get_profile_photos(telegram_channel):
            if telegram_picture.id in on_disk_picture_ids:
                continue
            picture_filename = self._download_media(telegram_picture)
            ProfilePicture.from_telegram_object(
                telegram_picture,
                force_update=True,
                defaults={"channel": channel, "picture": picture_filename},
            )
            self._cleanup_downloaded_file(picture_filename)
            pictures_downloaded += 1
        return pictures_downloaded

    def download_message_picture(self, telegram_message: Any) -> int:
        if not self.download_images:
            return 0
        if not hasattr(telegram_message.media, "photo"):
            return 0
        try:
            picture_filename = self._download_media(telegram_message)
            MessagePicture.from_telegram_object(
                telegram_message.media.photo,
                force_update=True,
                defaults={
                    "message": Message.objects.get(
                        channel__telegram_id=telegram_message.peer_id.channel_id,
                        telegram_id=telegram_message.id,
                    ),
                    "picture": picture_filename,
                },
            )
            self._cleanup_downloaded_file(picture_filename)
            return 1
        except (
            errors.rpcerrorlist.FileMigrateError,
            errors.rpcerrorlist.FileReferenceExpiredError,
            errors.rpcerrorlist.FileReferenceInvalidError,
            ValueError,
            Message.DoesNotExist,
        ) as e:
            logger.warning("Error downloading message picture (msg_id=%s): %s", telegram_message.id, e)
        return 0

    def download_message_video(self, telegram_message: Any) -> None:
        """Download video documents — including GIFs/animations and round videos.

        Webm video stickers (mime ``video/*`` + sticker attribute) are deferred to
        download_message_sticker so the two categories stay disjoint.
        """
        if not self.download_video:
            return
        document = getattr(telegram_message, "document", None)
        if not document and telegram_message.media:
            document = getattr(telegram_message.media, "document", None)
        if not document:
            return
        mime_type = getattr(document, "mime_type", "") or ""
        if not mime_type.startswith("video/"):
            return
        if _is_sticker(document):
            return
        try:
            video_filename = self._download_media(telegram_message)
            MessageVideo.from_telegram_object(
                document,
                force_update=True,
                defaults={
                    "message": Message.objects.get(
                        channel__telegram_id=telegram_message.peer_id.channel_id,
                        telegram_id=telegram_message.id,
                    ),
                    "video": video_filename,
                    "is_animated": _is_animated(document),
                    "is_round": _is_round_video(document),
                },
            )
            self._cleanup_downloaded_file(video_filename)
        except (
            errors.rpcerrorlist.FileMigrateError,
            errors.rpcerrorlist.FileReferenceExpiredError,
            errors.rpcerrorlist.FileReferenceInvalidError,
            ValueError,
            Message.DoesNotExist,
        ) as e:
            logger.warning("Error downloading message video (msg_id=%s): %s", telegram_message.id, e)

    def download_message_audio(self, telegram_message: Any) -> int:
        """Download audio documents — both voice notes and uploaded audio files.

        Voice vs audio is recorded on the saved row via ``is_voice``.
        Sticker documents (which can have audio mime in rare cases) are skipped.
        """
        if not self.download_audio:
            return 0
        document = getattr(telegram_message, "document", None)
        if not document and telegram_message.media:
            document = getattr(telegram_message.media, "document", None)
        if not document:
            return 0
        if _is_sticker(document):
            return 0
        if not _is_audio(document):
            return 0
        mime_type = getattr(document, "mime_type", "") or ""
        try:
            audio_filename = self._download_media(telegram_message)
            if not audio_filename:
                return 0
            MessageAudio.from_telegram_object(
                document,
                force_update=True,
                defaults={
                    "message": Message.objects.get(
                        channel__telegram_id=telegram_message.peer_id.channel_id,
                        telegram_id=telegram_message.id,
                    ),
                    "audio": audio_filename,
                    "mime_type": mime_type,
                    "is_voice": _is_voice(document),
                },
            )
            self._cleanup_downloaded_file(audio_filename)
            return 1
        except (
            errors.rpcerrorlist.FileMigrateError,
            errors.rpcerrorlist.FileReferenceExpiredError,
            errors.rpcerrorlist.FileReferenceInvalidError,
            ValueError,
            Message.DoesNotExist,
        ) as e:
            logger.warning("Error downloading message audio (msg_id=%s): %s", telegram_message.id, e)
        return 0

    def download_message_sticker(self, telegram_message: Any) -> int:
        """Download stickers — static webp, animated TGS, and video webm stickers."""
        if not self.download_stickers:
            return 0
        document = getattr(telegram_message, "document", None)
        if not document and telegram_message.media:
            document = getattr(telegram_message.media, "document", None)
        if not document:
            return 0
        if not _is_sticker(document):
            return 0
        mime_type = getattr(document, "mime_type", "") or ""
        try:
            sticker_filename = self._download_media(telegram_message)
            if not sticker_filename:
                return 0
            MessageSticker.from_telegram_object(
                document,
                force_update=True,
                defaults={
                    "message": Message.objects.get(
                        channel__telegram_id=telegram_message.peer_id.channel_id,
                        telegram_id=telegram_message.id,
                    ),
                    "sticker": sticker_filename,
                    "mime_type": mime_type,
                    "is_animated": _is_animated(document) or mime_type == "application/x-tgsticker",
                },
            )
            self._cleanup_downloaded_file(sticker_filename)
            return 1
        except (
            errors.rpcerrorlist.FileMigrateError,
            errors.rpcerrorlist.FileReferenceExpiredError,
            errors.rpcerrorlist.FileReferenceInvalidError,
            ValueError,
            Message.DoesNotExist,
        ) as e:
            logger.warning("Error downloading message sticker (msg_id=%s): %s", telegram_message.id, e)
        return 0

    def download_message_other_media(self, telegram_message: Any) -> int:
        """Download documents that aren't video, audio, or stickers.

        Photo posts arrive as MessageMediaPhoto and are handled by download_message_picture;
        bot-posted ``image/*`` documents do *not* reach the photo branch, so we accept them
        here.
        """
        if not self.download_other_media:
            return 0
        document = getattr(telegram_message, "document", None)
        if not document and telegram_message.media:
            document = getattr(telegram_message.media, "document", None)
        if not document:
            return 0
        mime_type = getattr(document, "mime_type", "") or ""
        if mime_type.startswith("video/"):
            return 0
        if _is_sticker(document):
            return 0
        if _is_audio(document):
            return 0
        try:
            other_filename = self._download_media(telegram_message)
            if not other_filename:
                return 0
            MessageOtherMedia.from_telegram_object(
                document,
                force_update=True,
                defaults={
                    "message": Message.objects.get(
                        channel__telegram_id=telegram_message.peer_id.channel_id,
                        telegram_id=telegram_message.id,
                    ),
                    "media_file": other_filename,
                    "mime_type": mime_type,
                },
            )
            self._cleanup_downloaded_file(other_filename)
            return 1
        except (
            errors.rpcerrorlist.FileMigrateError,
            errors.rpcerrorlist.FileReferenceExpiredError,
            errors.rpcerrorlist.FileReferenceInvalidError,
            ValueError,
            Message.DoesNotExist,
        ) as e:
            logger.warning("Error downloading message other-media (msg_id=%s): %s", telegram_message.id, e)
        return 0

    def clean_leftovers(self) -> None:
        for file_path in glob.glob(f"{settings.BASE_DIR}/photo_*.jpg"):
            try:
                os.remove(file_path)
            except OSError as error:
                logger.warning("Unable to remove leftover file '%s': %s", file_path, error)
        if self.download_temp_dir and os.path.isdir(self.download_temp_dir):
            try:
                shutil.rmtree(self.download_temp_dir)
            except OSError as error:
                logger.warning("Unable to remove temporary download directory '%s': %s", self.download_temp_dir, error)
