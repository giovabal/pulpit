import glob
import os
from datetime import timedelta
from time import sleep

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .models import Channel, Message, MessagePicture, ProfilePicture

from telethon import errors, functions
from telethon.tl.functions.channels import GetFullChannelRequest


class TelegramCrawler:
    client = None
    last_call = None
    wait_time = 1  # in seconds
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
        if channel.telegram_location is None and location:
            channel.telegram_location = location

    def get_basic_channel(self, seed):
        self.wait()
        telegram_channel = None

        try:
            telegram_channel = self.client.get_entity(seed)
            return (Channel.from_telegram_object(telegram_channel, force_update=True), telegram_channel) if telegram_channel else (None, None)
        except errors.rpcerrorlist.ChannelPrivateError:
            print("Seed non disponibile: ", seed)
            return None, None


    def get_channel(self, seed):
        channel, telegram_channel = self.get_basic_channel(seed)
        if channel is None:
            Channel.objects.filter(Q(telegram_id=seed) | Q(username=seed)).update(is_lost=True)
            return

        print(f"[{channel.id}]", channel)

        self.get_profile_picture(telegram_channel)

        self.set_more_channel_details(channel, telegram_channel)

        last_message = channel.message_set.order_by("telegram_id").last()
        min_id = last_message.telegram_id if last_message is not None else 0
        message_count = 0
        c = 0
        for i, telegram_message in enumerate(
            self.client.iter_messages(telegram_channel, min_id=min_id, wait_time=self.wait_time), start=1
        ):
            c = i
            self.get_message(channel, telegram_message)

        message_count += c
        max_id = None
        if not channel.are_messages_crawled:
            first_message = channel.message_set.order_by("telegram_id").first()
            max_id = first_message.telegram_id if first_message else None

        c = 0
        if max_id is not None:
            for i, telegram_message in enumerate(
                self.client.iter_messages(telegram_channel, max_id=max_id, wait_time=self.wait_time), start=1
            ):
                c = i
                self.get_message(channel, telegram_message)

        message_count += c
        channel.are_messages_crawled = True
        channel.save()
        print(f"  * {message_count} messaggi")

    def get_profile_picture(self, telegram_channel):
        for telegram_picture in self.client.get_profile_photos(telegram_channel):
            picture_filename = self.client.download_media(telegram_picture)
            ProfilePicture.from_telegram_object(
                telegram_picture,
                force_update=True,
                defaults={"channel": Channel.objects.get(telegram_id=telegram_channel.id), "picture": picture_filename},
            )

    def get_message_picture(self, telegram_message):
        if not hasattr(telegram_message.media, "photo"):
            return

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
        except (errors.rpcerrorlist.FileMigrateError, ValueError) as e:
            print(e)
            print(telegram_message.__dict__)

    def get_message(self, channel, telegram_message):
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
                except Exception:
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
                    except Exception:
                        missing_references.append(reference)

        if telegram_message.media:
            self.get_message_picture(telegram_message)
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

    def search_channel(self, q, limit=1000):
        self.wait()

        def _do(q, limit):
            results_count = 0
            result = self.client(functions.contacts.SearchRequest(q=q, limit=limit))
            for channel in result.chats:
                if hasattr(channel, "id"):
                    results_count += 1
                    already_exists = Channel.objects.filter(telegram_id=channel.id).exists()
                    if not already_exists:
                        Channel.from_telegram_object(channel, force_update=True)
            return results_count

        self.client.loop.run_until_complete(_do(q, limit))

    def clean_leftovers(self):
        for file_path in glob.glob(f"{settings.BASE_DIR}/photo_*.jpg"):
            try:
                os.remove(file_path)
            except Exception:
                pass

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
                    except Exception:
                        pass
                if channel:
                    message.references.add(channel)
            if not flood_error:
                message.missing_references = ""
                message.save()
