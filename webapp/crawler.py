import glob
import logging
import os
from datetime import timedelta
from time import sleep

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .models import Channel, Message, MessagePicture, MessageVideo, ProfilePicture

from telethon import errors, functions
from telethon.tl.functions.channels import GetFullChannelRequest

logger = logging.getLogger(__name__)


class TelegramCrawler:
    client = None
    last_call = None
    wait_time = settings.TELEGRAM_CRAWLER_GRACE_TIME  # in seconds
    messages_limit_per_channel = settings.TELEGRAM_CRAWLER_MESSAGES_LIMIT_PER_CHANNEL
    skippable_references = ["joinchat"]

    def __init__(self, client):
        self.client = client
        self.last_call = timezone.now() - timedelta(seconds=self.wait_time)

    def wait(self):
        w = self.wait_time - (timezone.now() - self.last_call).seconds
        if w > 0:
            sleep(w)
        self.last_call = timezone.now()

    def set_more_channel_details(self, channel, telegram_channel):
        channel_full_info = self.client(GetFullChannelRequest(channel=telegram_channel))
        channel.participants_count = channel_full_info.full_chat.participants_count
        channel.about = channel_full_info.full_chat.about
        location = channel_full_info.full_chat.location
        if not channel.telegram_location and location:
            channel.telegram_location = location

    def get_basic_channel(self, seed):
        self.wait()
        telegram_channel = None

        try:
            telegram_channel = self.client.get_entity(seed)
            return (
                (Channel.from_telegram_object(telegram_channel, force_update=True), telegram_channel)
                if telegram_channel
                else (None, None)
            )
        except errors.rpcerrorlist.ChannelPrivateError:
            print("Not available seed: ", seed)
            return None, None

    def get_channel(self, seed, status_callback=None):
        def update_status(message):
            if status_callback:
                status_callback(message)

        channel, telegram_channel = self.get_basic_channel(seed)
        if channel is None:
            Channel.objects.filter(Q(telegram_id=seed) | Q(username=seed)).update(is_lost=True)
            return

        channel_label = f"[{channel.id}] {channel}"
        update_status(f"{channel_label} | fetching profile pictures")

        image_count = self.get_profile_picture(telegram_channel)

        update_status(f"{channel_label} | fetching channel details")

        self.set_more_channel_details(channel, telegram_channel)

        last_message = channel.message_set.order_by("telegram_id").last()
        min_id = last_message.telegram_id if last_message is not None else 0
        message_count = 0
        c = 0
        if self.messages_limit_per_channel is None or self.messages_limit_per_channel <= 0:
            remaining_limit = None
        else:
            remaining_limit = self.messages_limit_per_channel
        update_status(f"{channel_label} | downloading recent messages")
        for i, telegram_message in enumerate(
            self.client.iter_messages(telegram_channel, min_id=min_id, wait_time=self.wait_time, limit=remaining_limit),
            start=1,
        ):
            c = i
            image_count += self.get_message(channel, telegram_message)
            update_status(f"{channel_label} | messages processed: {message_count + c}")

        message_count += c
        if remaining_limit is not None:
            remaining_limit -= c
            if remaining_limit <= 0:
                channel.are_messages_crawled = True
                channel.save()
                update_status(
                    f"{channel_label} | completed ({message_count} new messages, {image_count} downloaded images)"
                )
                return
        max_id = None
        if not channel.are_messages_crawled:
            first_message = channel.message_set.order_by("telegram_id").first()
            max_id = first_message.telegram_id if first_message else None

        c = 0
        if max_id is not None:
            update_status(f"{channel_label} | downloading history")
            for i, telegram_message in enumerate(
                self.client.iter_messages(
                    telegram_channel, max_id=max_id, wait_time=self.wait_time, limit=remaining_limit
                ),
                start=1,
            ):
                c = i
                image_count += self.get_message(channel, telegram_message)
                update_status(f"{channel_label} | messages processed: {message_count + c}")

        message_count += c
        channel.are_messages_crawled = True
        channel.save()
        update_status(f"{channel_label} | completed ({message_count} new messages, {image_count} downloaded images)")

    def get_profile_picture(self, telegram_channel):
        pictures_downloaded = 0
        for telegram_picture in self.client.get_profile_photos(telegram_channel):
            picture_filename = self.client.download_media(telegram_picture)
            ProfilePicture.from_telegram_object(
                telegram_picture,
                force_update=True,
                defaults={"channel": Channel.objects.get(telegram_id=telegram_channel.id), "picture": picture_filename},
            )
            self._cleanup_downloaded_file(picture_filename)
            pictures_downloaded += 1

        return pictures_downloaded

    def get_message_picture(self, telegram_message):
        if not settings.TELEGRAM_CRAWLER_DOWNLOAD_IMAGES:
            return 0

        if not hasattr(telegram_message.media, "photo"):
            return 0

        try:
            picture_filename = self.client.download_media(telegram_message)
            MessagePicture.from_telegram_object(
                telegram_message.media.photo,
                force_update=True,
                defaults={
                    "message": Message.objects.get(
                        channel__telegram_id=telegram_message.peer_id.channel_id, telegram_id=telegram_message.id
                    ),
                    "picture": picture_filename,
                },
            )
            self._cleanup_downloaded_file(picture_filename)
            return 1
        except (errors.rpcerrorlist.FileMigrateError, ValueError) as e:
            print(e)
            print(telegram_message.__dict__)

        return 0

    def get_message_video(self, telegram_message):
        if not settings.TELEGRAM_CRAWLER_DOWNLOAD_VIDEO:
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
            video_filename = self.client.download_media(telegram_message)
            MessageVideo.from_telegram_object(
                document,
                force_update=True,
                defaults={
                    "message": Message.objects.get(
                        channel__telegram_id=telegram_message.peer_id.channel_id, telegram_id=telegram_message.id
                    ),
                    "video": video_filename,
                },
            )
            self._cleanup_downloaded_file(video_filename)
        except (errors.rpcerrorlist.FileMigrateError, ValueError) as e:
            print(e)
            print(telegram_message.__dict__)

    def _cleanup_downloaded_file(self, filename):
        if filename and os.path.exists(filename):
            os.remove(filename)

    def get_message(self, channel, telegram_message):
        downloaded_images = 0
        message = Message.from_telegram_object(telegram_message, force_update=True, defaults={"channel": channel})
        missing_references = []
        if (
            telegram_message.fwd_from
            and telegram_message.fwd_from.from_id
            and hasattr(telegram_message.fwd_from.from_id, "channel_id")
        ):
            if Channel.objects.filter(telegram_id=telegram_message.fwd_from.from_id.channel_id).exists():
                message.forwarded_from = Channel.objects.get(telegram_id=telegram_message.fwd_from.from_id.channel_id)
            else:
                try:
                    self.wait()
                    new_telegram_channel = self.client.get_entity(telegram_message.fwd_from.from_id.channel_id)
                    message.forwarded_from = Channel.from_telegram_object(new_telegram_channel, force_update=True)
                except errors.rpcerrorlist.ChannelPrivateError:
                    message.forwarded_from_private = telegram_message.fwd_from.from_id.channel_id
                except AttributeError:
                    message.forwarded_from_private = 0

        for reference in message.get_telegram_references():
            reference = reference.strip().lower()
            if reference in self.skippable_references:
                continue
            if Channel.objects.filter(username=reference).exists():
                message.references.add(Channel.objects.filter(username=reference).first())
            else:
                try:
                    self.wait()
                    new_telegram_channel = self.client.get_entity(reference)
                    message.references.add(Channel.from_telegram_object(new_telegram_channel, force_update=True))
                except (ValueError, errors.rpcerrorlist.UsernameInvalidError):
                    pass
                except errors.rpcerrorlist.FloodWaitError as error:
                    logger.warning("Unable to resolve message reference '%s': %s", reference, error)
                    raise
                except errors.RPCError as error:
                    logger.warning("Unable to resolve message reference '%s': %s", reference, error)
                    missing_references.append(reference)

        if telegram_message.entities:
            for entity in telegram_message.entities:
                tme = "https://t.me/"
                if hasattr(entity, "url") and entity.url.startswith(tme):
                    reference = entity.url[len(tme) :].split("/")[0].strip().lower()
                else:
                    continue
                if reference in self.skippable_references:
                    continue
                if Channel.objects.filter(username=reference).exists():
                    message.references.add(Channel.objects.filter(username=reference).first())
                else:
                    try:
                        self.wait()
                        new_telegram_channel = self.client.get_entity(reference)
                        message.references.add(Channel.from_telegram_object(new_telegram_channel, force_update=True))
                    except (ValueError, errors.rpcerrorlist.UsernameInvalidError):
                        pass
                    except errors.rpcerrorlist.FloodWaitError as error:
                        logger.warning("Unable to resolve URL reference '%s': %s", reference, error)
                        raise
                    except errors.RPCError as error:
                        logger.warning("Unable to resolve URL reference '%s': %s", reference, error)
                        missing_references.append(reference)

        if telegram_message.media:
            downloaded_images += self.get_message_picture(telegram_message)
            self.get_message_video(telegram_message)
            if hasattr(telegram_message.media, "webpage"):
                message.webpage_url = (
                    telegram_message.media.webpage.url if hasattr(telegram_message.media.webpage, "url") else ""
                )
                message.webpage_type = (
                    telegram_message.media.webpage.type if hasattr(telegram_message.media.webpage, "type") else ""
                )

        if missing_references:
            message.missing_references = "|" + "|".join(missing_references)

        message.save()
        return downloaded_images

    def search_channel(self, q, limit=1000):
        self.wait()
        results_count = 0
        result = self.client(functions.contacts.SearchRequest(q=q, limit=limit))
        for channel in result.chats:
            if hasattr(channel, "id"):
                results_count += 1
                already_exists = Channel.objects.filter(telegram_id=channel.id).exists()
                if not already_exists:
                    Channel.from_telegram_object(channel, force_update=True)
        return results_count

    def clean_leftovers(self):
        for file_path in glob.glob(f"{settings.BASE_DIR}/photo_*.jpg"):
            try:
                os.remove(file_path)
            except OSError as error:
                logger.warning("Unable to remove leftover file '%s': %s", file_path, error)

    def get_missing_references(self):
        for message in Message.objects.exclude(missing_references=""):
            flood_error = False
            for reference in message.missing_references[1:].split("|"):
                if reference in self.skippable_references:
                    continue
                channel = Channel.objects.filter(username=reference).first()
                if not channel:
                    try:
                        channel, telegram_channel = self.get_basic_channel(reference)
                    except errors.rpcerrorlist.FloodWaitError:
                        flood_error = True
                    except (ValueError, errors.RPCError) as error:
                        logger.warning("Unable to fetch missing reference '%s': %s", reference, error)
                if channel:
                    message.references.add(channel)
            if not flood_error:
                message.missing_references = ""
                message.save()
