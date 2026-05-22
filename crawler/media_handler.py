import asyncio
import glob
import inspect
import logging
import mimetypes
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

    def _download_media(self, telegram_object: Any, thumb: Any = None) -> str | None:
        kwargs: dict[str, Any] = {"file": self.download_temp_dir} if self.download_temp_dir else {}
        if thumb is not None:
            # Telethon's ``thumb`` param picks a specific size from ``photo.sizes``
            # (ignoring ``video_sizes``), forcing a static frame for video media.
            # ``thumb=-1`` picks the largest static variant.
            kwargs["thumb"] = thumb
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
        # A row is considered fully captured only when:
        #   - the main picture file is on disk
        #   - mime_type is recorded (lets the template choose <img> vs <video>)
        #   - for video avatars, the static thumbnail is also on disk
        # Anything weaker forces a re-download so the missing piece can be filled.
        fresh_picture_ids: set[int] = set()
        for pp in ProfilePicture.objects.filter(channel=channel):
            if not pp.picture or not os.path.exists(pp.picture.path):
                continue
            if not pp.mime_type:
                continue
            if pp.mime_type.startswith("video/"):
                if not pp.thumbnail or not os.path.exists(pp.thumbnail.path):
                    continue
            fresh_picture_ids.add(pp.telegram_id)
        for telegram_picture in self.api_client.client.get_profile_photos(telegram_channel):
            if telegram_picture.id in fresh_picture_ids:
                continue
            # Photos are iterated newest-first, so wrap each one independently;
            # a recoverable error on the current avatar must not abort the loop
            # and leave older pictures unchecked.
            try:
                picture_filename = self._download_media(telegram_picture)
                if not picture_filename:
                    # Skip empty downloads outright — creating a ProfilePicture
                    # row with an empty FieldFile would mask the failure as a
                    # "broken" record on every subsequent --get-channels-info run.
                    logger.warning(
                        "Profile picture %s for channel %s: download returned no file",
                        telegram_picture.id,
                        telegram_channel.id,
                    )
                    continue
                mime_type, _ = mimetypes.guess_type(picture_filename)
                mime_type = mime_type or ""
                thumbnail_filename: str | None = None
                if mime_type.startswith("video/"):
                    # Telegram video avatars: pull the largest static frame so
                    # template contexts that can't render <video> (small list
                    # rows, posters) still have something to show.
                    try:
                        thumbnail_filename = self._download_media(telegram_picture, thumb=-1)
                    except (
                        errors.rpcerrorlist.FileMigrateError,
                        errors.rpcerrorlist.FileReferenceExpiredError,
                        errors.rpcerrorlist.FileReferenceInvalidError,
                        ValueError,
                    ) as thumb_err:
                        logger.warning(
                            "Failed to download static thumbnail for profile picture %s of channel %s: %s",
                            telegram_picture.id,
                            telegram_channel.id,
                            thumb_err,
                        )
                ProfilePicture.from_telegram_object(
                    telegram_picture,
                    force_update=True,
                    defaults={
                        "channel": channel,
                        "picture": picture_filename,
                        "mime_type": mime_type,
                        "thumbnail": thumbnail_filename,
                    },
                )
                self._cleanup_downloaded_file(picture_filename)
                if thumbnail_filename:
                    self._cleanup_downloaded_file(thumbnail_filename)
                pictures_downloaded += 1
            except (
                errors.rpcerrorlist.FileMigrateError,
                errors.rpcerrorlist.FileReferenceExpiredError,
                errors.rpcerrorlist.FileReferenceInvalidError,
                ValueError,
            ) as e:
                logger.warning(
                    "Error downloading profile picture %s for channel %s: %s",
                    telegram_picture.id,
                    telegram_channel.id,
                    e,
                )
        return pictures_downloaded

    def download_message_picture(self, telegram_message: Any) -> int:
        if not self.download_images:
            return 0
        if not hasattr(telegram_message.media, "photo"):
            return 0
        try:
            picture_filename = self._download_media(telegram_message)
            if not picture_filename:
                # _download_media returned None (timeout) or an empty path. Without this
                # guard, MessagePicture.from_telegram_object would still create a row
                # with picture=NULL — a "zombie" that messagepicture__isnull=True can no
                # longer recover via --fix-missing-media.
                logger.warning(
                    "Empty download for message picture (msg_id=%s) — likely timeout or stripped media; skipping save",
                    telegram_message.id,
                )
                return 0
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

    def download_message_video(self, telegram_message: Any) -> int:
        """Download video documents — including GIFs/animations and round videos.

        Webm video stickers (mime ``video/*`` + sticker attribute) are deferred to
        download_message_sticker so the two categories stay disjoint.
        """
        if not self.download_video:
            return 0
        document = getattr(telegram_message, "document", None)
        if not document and telegram_message.media:
            document = getattr(telegram_message.media, "document", None)
        if not document:
            return 0
        mime_type = getattr(document, "mime_type", "") or ""
        if not mime_type.startswith("video/"):
            return 0
        if _is_sticker(document):
            return 0
        try:
            video_filename = self._download_media(telegram_message)
            if not video_filename:
                logger.warning(
                    "Empty download for message video (msg_id=%s) — likely timeout or stripped media; skipping save",
                    telegram_message.id,
                )
                return 0
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
            return 1
        except (
            errors.rpcerrorlist.FileMigrateError,
            errors.rpcerrorlist.FileReferenceExpiredError,
            errors.rpcerrorlist.FileReferenceInvalidError,
            ValueError,
            Message.DoesNotExist,
        ) as e:
            logger.warning("Error downloading message video (msg_id=%s): %s", telegram_message.id, e)
        return 0

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
        # Telethon's default profile-photo download filename is ``photo_<digits>.jpg``
        # in the working directory (which is BASE_DIR when invoked via manage.py).
        # Match the digit-suffix pattern strictly so unrelated ``photo_*.jpg`` files
        # a developer might keep in the project root aren't swept by the cleanup.
        for file_path in glob.glob(f"{settings.BASE_DIR}/photo_[0-9]*.jpg"):
            if not os.path.isfile(file_path) or os.path.islink(file_path):
                continue
            try:
                os.remove(file_path)
            except OSError as error:
                logger.warning("Unable to remove leftover file '%s': %s", file_path, error)
        if self.download_temp_dir and os.path.isdir(self.download_temp_dir):
            try:
                shutil.rmtree(self.download_temp_dir)
            except OSError as error:
                logger.warning("Unable to remove temporary download directory '%s': %s", self.download_temp_dir, error)
