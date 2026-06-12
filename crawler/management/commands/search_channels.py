import logging
import re
from time import sleep
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import F, Q
from django.utils import timezone

from crawler.channel_crawler import ChannelCrawler
from crawler.client import TelegramAPIClient
from crawler.media_handler import MediaHandler
from crawler.reference_resolver import ReferenceResolver
from webapp.models import Channel, SearchTerm
from webapp_engine.command_logging import styled_warning_logs

from telethon import errors
from telethon.sync import TelegramClient

logger = logging.getLogger(__name__)

# t.me/<path> in any of its spellings: scheme and www. optional, telegram.me alias.
_TME_LINK_RE = re.compile(r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(?P<path>.+)$", re.IGNORECASE)


def parse_channel_identifier(raw: str) -> int | str:
    """Normalise one identifier line into a resolution seed.

    Accepts a t.me / telegram.me link (channel page, /s/ web preview, message
    or /c/ internal link), an @username, a bare username, or a numeric ID
    (bare or -100-prefixed Bot-API form). Returns the bare numeric telegram_id
    (int) or the username (str). Raises ValueError for forms that cannot name
    a channel (invite links, empty lines).
    """
    text = raw.strip()
    match = _TME_LINK_RE.match(text)
    if match:
        path = match.group("path").split("?", 1)[0].split("#", 1)[0]
        segments = [s for s in path.split("/") if s]
        if not segments:
            raise ValueError("link has no channel name")
        first = segments[0]
        if first.lower() == "s" and len(segments) > 1:  # t.me/s/<username> web preview
            first = segments[1]
        if first.lower() == "c":  # t.me/c/<id>/<msg> internal link: <id> is the bare channel id
            if len(segments) > 1 and segments[1].isdigit():
                return int(segments[1])
            raise ValueError("t.me/c/ link without a numeric channel id")
        if first.lower() == "joinchat" or first.startswith("+"):
            raise ValueError("invite links cannot be resolved to a channel")
        text = first
    if text.startswith("@"):
        text = text[1:]
    if not text:
        raise ValueError("empty identifier")
    if "/" in text:
        # Anything URL-shaped was handled above, so a leftover slash means a
        # non-Telegram link or a malformed paste — clearer to refuse here than
        # to let get_entity fail on it.
        raise ValueError("not a t.me link, @username, username, or numeric ID")
    if re.fullmatch(r"-?\d+", text):
        # Bot-API marked forms: -100<id> for channels/supergroups, plain negative for
        # basic groups. Channel.telegram_id stores the bare positive id.
        if text.startswith("-100") and len(text) > 4:
            return int(text[4:])
        return abs(int(text))
    return text


class Command(BaseCommand):
    args = ""
    help = "crawling Telegram groups"

    def add_arguments(self, parser):
        parser.add_argument(
            "--amount",
            type=int,
            default=None,
            help="Number of database search terms to process (default: all; 0 = none, only --extra-term).",
        )
        parser.add_argument(
            "--extra-term",
            dest="extra_terms",
            action="append",
            default=[],
            metavar="TERM",
            help=(
                "Additional search term to process alongside database terms. "
                "Can be repeated. Terms are not persisted unless the Operations "
                "panel 'Save to database' checkbox was checked before launching."
            ),
        )
        parser.add_argument(
            "--add-channel",
            dest="add_channels",
            action="append",
            default=[],
            metavar="IDENTIFIER",
            help=(
                "Resolve a specific channel and add it to the database: a t.me link, "
                "an @username, a bare username, or a numeric Telegram ID. Can be repeated. "
                "Identifiers that cannot be resolved are reported as warnings."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Route logger.warning/error lines (own modules, telethon) through
        # self.style so they carry severity colour in the Operations panel.
        with styled_warning_logs(self.style):
            self._handle(*args, **options)

    def _handle(self, *args: Any, **options: Any) -> None:
        qs = SearchTerm.objects.all().order_by(F("last_check").asc(nulls_first=True))
        if options["amount"] is not None:
            qs = qs[: options["amount"]]
        extra_terms = [t for t in (options.get("extra_terms") or []) if t]
        identifiers = [i.strip() for i in (options.get("add_channels") or []) if i.strip()]
        total_found = 0
        total_new = 0
        with TelegramClient(
            settings.TELEGRAM_SESSION_NAME,
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
            connection_retries=settings.TELEGRAM_CONNECTION_RETRIES,
            retry_delay=settings.TELEGRAM_RETRY_DELAY,
            flood_sleep_threshold=settings.TELEGRAM_FLOOD_SLEEP_THRESHOLD,
        ).start(phone=settings.TELEGRAM_PHONE_NUMBER) as client:
            api_client = TelegramAPIClient(client)
            media_handler = MediaHandler(api_client)
            reference_resolver = ReferenceResolver(api_client)
            crawler = ChannelCrawler(api_client, media_handler, reference_resolver)
            # Direct adds run first: each is a single cheap get_entity call, so a long
            # term-search phase (or a flood wait it triggers) cannot starve them.
            if identifiers:
                add_counts = {"added": 0, "present": 0, "failed": 0}
                for raw in identifiers:
                    add_counts[self._add_one_channel(crawler, raw)] += 1
                summary = (
                    f"Channel add complete. {add_counts['added']} added, "
                    f"{add_counts['present']} already in database, {add_counts['failed']} not added."
                )
                style = self.style.WARNING if add_counts["failed"] else self.style.SUCCESS
                self.stdout.write(style(summary))
            searched_words: set[str] = set()
            for term in qs:
                result = self._run_search(crawler, term.word, "Searching: ")
                searched_words.add(term.word)  # term.word is already normalised by SearchTerm.save()
                if result is None:
                    continue  # leave last_check untouched so a failed term is retried first next run
                found, new = result
                total_found += found
                total_new += new
                term.last_check = timezone.now()
                term.save(update_fields=["last_check"])
            for word in extra_terms:
                # A term saved to the database before launch (Operations panel "Save to
                # database") is also passed as --extra-term; skip it here so it is not
                # searched twice in the same run. Normalise to match SearchTerm.save().
                if " ".join(word.split()).lower() in searched_words:
                    continue
                result = self._run_search(crawler, word, "Searching (extra): ")
                if result is None:
                    continue
                found, new = result
                total_found += found
                total_new += new
        self.stdout.write(self.style.SUCCESS(f"\nSearch complete. {total_found} channels found, {total_new} new."))

    def _run_search(self, crawler: ChannelCrawler, word: str, label: str) -> tuple[int, int] | None:
        """Run one search term; return (found, new), or None if it failed so the run can continue.

        A single bad term (RPCError, above-threshold flood wait, network error) must not abort the
        whole command — log it and move on, mirroring the per-channel resilience of crawl_channels.
        """
        self.stdout.write(f'{label}"{word}" … ', ending="")
        self.stdout.flush()
        try:
            found, new = crawler.search_channel(word)
        except errors.FloodWaitError as exc:
            self.stdout.write(self.style.WARNING(f"flood wait, skipping: {exc}"))
            if not settings.IGNORE_FLOODWAIT:
                sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)
            return None
        except Exception as exc:  # noqa: BLE001 - one bad term must not abort the whole run
            logger.warning("Search failed for term %r: %s", word, exc)
            self.stdout.write(self.style.WARNING(f"failed: {exc}"))
            return None
        self.stdout.write(f"{found} found, {new} new")
        return found, new

    def _add_one_channel(self, crawler: ChannelCrawler, raw: str) -> str:
        """Resolve one --add-channel identifier; returns "added", "present", or "failed".

        Mirrors _run_search's resilience: one bad identifier must not abort the run.
        Every non-resolvable identifier is reported as a warning line.
        """
        self.stdout.write(f'Adding: "{raw}" … ', ending="")
        self.stdout.flush()
        try:
            seed = parse_channel_identifier(raw)
        except ValueError as exc:
            self.stdout.write(self.style.WARNING(f"not added ({exc})"))
            return "failed"
        # Same DB-first shortcut as ReferenceResolver._resolve_one, on either identity
        # axis; prefer the live owner of a recycled handle over a lost row.
        seed_q = Q(telegram_id=seed) if isinstance(seed, int) else Q(username__iexact=seed)
        existing = Channel.objects.filter(seed_q).order_by("is_lost", "pk").first()
        if existing:
            self.stdout.write(f"already in database: {existing} [id={existing.pk}]")
            return "present"
        pre_count = Channel.objects.count()
        try:
            channel, _telegram_channel, status = crawler.resolve_channel_or_classify(seed)
        except errors.FloodWaitError as exc:
            self.stdout.write(self.style.WARNING(f"flood wait, skipping: {exc}"))
            if not settings.IGNORE_FLOODWAIT:
                sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)
            return "failed"
        except Exception as exc:  # noqa: BLE001 - one bad identifier must not abort the whole run
            logger.warning("Could not add channel %r: %s", raw, exc)
            self.stdout.write(self.style.WARNING(f"failed: {exc}"))
            return "failed"
        if status == "ok":
            if Channel.objects.count() > pre_count:
                self.stdout.write(self.style.SUCCESS(f"added: {channel} [id={channel.pk}]"))
                return "added"
            # Resolution found a telegram_id already stored under another (since-changed)
            # username; from_telegram_object refreshed that row rather than creating one.
            self.stdout.write(f"already in database: {channel} [id={channel.pk}] (metadata refreshed)")
            return "present"
        reasons = {
            "private": "channel is private",
            "lost": "not found on Telegram",
            "user_account": "resolves to a user account, not a channel",
        }
        self.stdout.write(self.style.WARNING(f"not added ({reasons.get(status, status)})"))
        return "failed"
