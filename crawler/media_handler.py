import asyncio
import glob
import inspect
import logging
import os
import shutil
from typing import Any

from django.conf import settings

from crawler.client import TelegramAPIClient
from webapp.models import Channel, Message, MessagePicture, MessageVideo, ProfilePicture

from telethon import errors

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT_SECONDS = 120


class MediaHandler:
    def __init__(
        self,
        api_client: TelegramAPIClient,
        download_temp_dir: str | None = None,
        download_images: bool = False,
        download_video: bool = False,
    ) -> None:
        self.api_client = api_client
        self.download_temp_dir = download_temp_dir
        self.download_images = download_images
        self.download_video = download_video

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
        existing_picture_ids = set(ProfilePicture.objects.filter(channel=channel).values_list("telegram_id", flat=True))
        for telegram_picture in self.api_client.client.get_profile_photos(telegram_channel):
            if telegram_picture.id in existing_picture_ids:
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
