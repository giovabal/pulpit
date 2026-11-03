"""Image fingerprints (crawler.image_hash, hash_media, purge_orphan_media) and link capture (Message.link_urls)."""

import datetime
import io
import os
import shutil
import tempfile
import types
from typing import Any
from unittest.mock import MagicMock

from django.core.management import call_command
from django.test import TestCase, override_settings

from crawler.channel_crawler import ChannelCrawler, _link_urls
from crawler.image_hash import fingerprint, hamming, hash_stored_pictures
from webapp.management.commands.purge_orphan_media import purge_orphan_fingerprints
from webapp.models import Domain, ImageFingerprint, Message, MessagePicture
from webapp.test_helpers import make_channel, make_label

import numpy as np
from PIL import Image
from telethon.tl.types import (
    InlineButtonTypeCallback,
    InlineButtonTypeUrl,
    KeyboardInlineButton,
    KeyboardInlineButtonRow,
    MessageEntityBold,
    MessageEntityTextUrl,
    MessageEntityUrl,
    ReplyInlineMarkup,
)


def _texture(seed: int, size: int = 256) -> Image.Image:
    """A smooth random grayscale texture (blurred noise): real structure at low frequencies, like a photo."""
    rng = np.random.default_rng(seed)
    noise = rng.random((16, 16)) * 255
    return Image.fromarray(noise.astype(np.uint8), "L").resize((size, size), Image.Resampling.BICUBIC).convert("RGB")


class FingerprintTests(TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def _save(self, image: Image.Image, name: str, **kwargs: Any) -> str:
        path = os.path.join(self.dir, name)
        image.save(path, **kwargs)
        return path

    def test_reencoding_and_resizing_stay_within_the_default_distance(self) -> None:
        original = _texture(1)
        base = fingerprint(self._save(original, "a.png"))
        recoded = fingerprint(self._save(original, "b.jpg", quality=40))
        smaller = fingerprint(self._save(original.resize((128, 128)), "c.jpg", quality=80))
        self.assertEqual(base[2:], (256, 256))
        self.assertEqual(fingerprint(self._save(original, "a2.png"))[0], base[0])
        self.assertLessEqual(hamming(base[0], recoded[0]), 6)
        self.assertLessEqual(hamming(base[0], smaller[0]), 6)

    def test_a_different_image_is_far(self) -> None:
        a = fingerprint(self._save(_texture(1), "a.png"))
        b = fingerprint(self._save(_texture(2), "b.png"))
        self.assertGreater(hamming(a[0], b[0]), 20)

    def test_uniform_and_unreadable_images_have_no_fingerprint(self) -> None:
        self.assertIsNone(fingerprint(self._save(Image.new("RGB", (64, 64), "#ff0000"), "flat.png")))
        broken = os.path.join(self.dir, "broken.jpg")
        with open(broken, "wb") as fh:
            fh.write(b"not an image")
        self.assertIsNone(fingerprint(broken))


class HashStoredPicturesTests(TestCase):
    def setUp(self) -> None:
        self.media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        os.makedirs(os.path.join(self.media_root, "photos"))
        channel = make_channel(telegram_id=1, label=make_label("Org"))
        for tid in (1, 2):
            _texture(tid).save(os.path.join(self.media_root, "photos", f"{tid}.jpg"))
            message = Message.objects.create(telegram_id=tid, channel=channel)
            MessagePicture.objects.create(message=message, telegram_id=tid, picture=f"photos/{tid}.jpg")
        # A forward of photo 1: same file, hashed once.
        forward = Message.objects.create(telegram_id=3, channel=channel)
        MessagePicture.objects.create(message=forward, telegram_id=1, picture="photos/1.jpg")

    def test_incremental_hashing(self) -> None:
        self.assertEqual(hash_stored_pictures(limit=1), {"hashed": 1, "skipped": 0, "unchanged": 1})
        self.assertEqual(hash_stored_pictures(), {"hashed": 1, "skipped": 0, "unchanged": 1})
        self.assertEqual(hash_stored_pictures(), {"hashed": 0, "skipped": 0, "unchanged": 2})
        self.assertEqual(hash_stored_pictures(rehash=True)["hashed"], 2)
        self.assertEqual(ImageFingerprint.objects.count(), 2)

    def test_hash_media_command_and_crawl_option(self) -> None:
        out = io.StringIO()
        call_command("hash_media", stdout=out)
        self.assertIn("2 file(s) fingerprinted", out.getvalue())
        out = io.StringIO()
        call_command("crawl_channels", "--hash-images", "--index-domains", stdout=out, stderr=io.StringIO())
        self.assertIn("Images: 0 fingerprinted", out.getvalue())
        self.assertIn("Domains:", out.getvalue())

    def test_orphan_fingerprints_are_purged(self) -> None:
        hash_stored_pictures()
        MessagePicture.objects.filter(telegram_id=2).delete()
        self.assertEqual(purge_orphan_fingerprints(), 1)
        self.assertEqual(list(ImageFingerprint.objects.values_list("telegram_id", flat=True)), [1])


def _tg(text: str, entities: list | None = None, markup: Any = None) -> Any:
    return types.SimpleNamespace(message=text, entities=entities or [], reply_markup=markup)


class LinkUrlCaptureTests(TestCase):
    def test_entities_and_buttons(self) -> None:
        text = "🔥 Read shopw2r.com and the post"
        offset = len("🔥 Read ".encode("utf-16-le")) // 2  # the emoji is two UTF-16 code units
        message = _tg(
            text,
            [
                MessageEntityBold(offset=0, length=2),
                MessageEntityUrl(offset=offset, length=len("shopw2r.com")),
                MessageEntityTextUrl(offset=offset + 16, length=4, url="https://gab.com/hidden"),
                MessageEntityTextUrl(offset=0, length=2, url="https://gab.com/hidden"),
            ],
            ReplyInlineMarkup(
                rows=[
                    KeyboardInlineButtonRow(
                        buttons=[
                            KeyboardInlineButton(
                                text="Donate", type=InlineButtonTypeUrl(url="https://givesendgo.com/x")
                            ),
                            KeyboardInlineButton(text="Vote", type=InlineButtonTypeCallback(data=b"1")),
                            # An older-layer button carrying its URL itself.
                            types.SimpleNamespace(text="Shop", url="https://shopw2r.com/"),
                        ]
                    )
                ]
            ),
        )
        self.assertEqual(
            _link_urls(message),
            ["shopw2r.com", "https://gab.com/hidden", "https://givesendgo.com/x", "https://shopw2r.com/"],
        )
        self.assertEqual(_link_urls(types.SimpleNamespace()), [])


class LinkUrlsCrawlTests(TestCase):
    def setUp(self) -> None:
        self.channel = make_channel(telegram_id=1, label=make_label("Org"))
        self.api_client = MagicMock()
        self.api_client.wait_time = 0
        self.crawler = ChannelCrawler(self.api_client, MagicMock(), MagicMock())

    def _tg_message(self, text: str) -> Any:
        return types.SimpleNamespace(
            id=6,
            peer_id=types.SimpleNamespace(channel_id=1),
            date=datetime.datetime(2024, 2, 1, tzinfo=datetime.UTC),
            message=text,
            entities=[MessageEntityTextUrl(offset=0, length=4, url="https://odysee.com/@x")],
            reply_markup=None,
            fwd_from=None,
            media=None,
            pinned=False,
            edit_date=None,
            views=5,
            forwards=0,
            replies=None,
            reply_to=None,
            factcheck=None,
            reactions=None,
        )

    def test_get_message_stores_the_links(self) -> None:
        self.crawler.reference_resolver.resolve_message_references.return_value = []
        self.crawler.get_message(self.channel, self._tg_message("Watch"))
        self.assertEqual(Message.objects.get().link_urls, ["https://odysee.com/@x"])

    def _refresh(self, stored_text: str, telegram_text: str) -> Message:
        Message.objects.create(
            channel=self.channel,
            telegram_id=6,
            date=datetime.datetime(2024, 2, 1, tzinfo=datetime.UTC),
            message=stored_text,
        )
        self.api_client.client.iter_messages.return_value = iter([self._tg_message(telegram_text)])
        self.crawler.refresh_message_stats(self.channel, MagicMock())
        return Message.objects.get()

    def test_refresh_backfills_while_the_text_is_unchanged(self) -> None:
        self.assertEqual(self._refresh("Watch", "Watch").link_urls, ["https://odysee.com/@x"])

    def test_refresh_never_takes_links_from_a_replaced_text(self) -> None:
        self.assertIsNone(self._refresh("Watch", "This channel can't be displayed").link_urls)


class ContactInfoViewTests(TestCase):
    def test_sites_once_per_message_and_emails(self) -> None:
        channel = make_channel(telegram_id=1, label=make_label("Org"))
        Message.objects.create(
            telegram_id=1,
            channel=channel,
            message="https://www.gab.com/a https://gab.com/b write@club.org",
            link_urls=["https://givesendgo.com/x"],
        )
        Message.objects.create(
            telegram_id=2, channel=channel, message="https://t.me/x", webpage_url="https://gab.com/c"
        )
        data = self.client.get(f"/stats/data/channel/{channel.pk}/contact_info/").json()
        self.assertEqual({d["domain"]: d["count"] for d in data["domains"]}, {"gab.com": 2, "givesendgo.com": 1})
        self.assertEqual(data["emails"], [{"email": "write@club.org", "count": 1}])
        self.assertFalse(Domain.objects.filter(posts__gt=0).exists())
