"""Record the @handles of posts stored before the crawler read them (crawler/mention_backfill.py).

The default run uses the database alone: handles of stored channels become mentions, unknown ones are queued
like any unresolved reference. ``--resolve`` also asks Telegram about the unknown ones; it stops at a long
flood wait, and the next run carries on.
"""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from crawler.client import TelegramAPIClient
from crawler.mention_backfill import FOUND, BackfillPlan, apply_plan, look_up_handles, plan_backfill
from crawler.reference_resolver import ReferenceResolver
from webapp.cache import invalidate_home_summary_cache
from webapp.models import Channel
from webapp_engine.command_logging import styled_warning_logs

from telethon.sync import TelegramClient

#: Unknown handles listed by --dry-run.
DRY_RUN_HANDLES = 25


class Command(BaseCommand):
    help = "Record the @handles of stored in-target posts as mentions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Count what would be recorded; no Telegram call, no database write."
        )
        parser.add_argument(
            "--resolve",
            action="store_true",
            help="Also look up the handles of no stored channel on Telegram, the most used first.",
        )
        parser.add_argument(
            "--limit", type=int, default=None, metavar="N", help="With --resolve, look up at most N handles."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be at least 1.")
        with styled_warning_logs(self.style):
            self._handle(**options)

    def _handle(self, **options: Any) -> None:
        plan = plan_backfill()
        self._summarise(plan)
        if options["dry_run"]:
            for handle, message_pks in plan.unknown_by_use()[:DRY_RUN_HANDLES]:
                self.stdout.write(f"  {len(message_pks):>6}  @{handle}")
            self.stdout.write("Dry run: nothing written.")
            return
        apply_plan(plan)
        added = len(plan.references)
        self.stdout.write(self.style.SUCCESS(f"{added:,} mentions recorded."))
        if options["resolve"] and plan.unknown:
            added += self._look_up(plan, options["limit"])
        if added:
            invalidate_home_summary_cache()
            self.stdout.write("Run Refresh degrees (crawl_channels --in-degrees --out-degrees) to count them there.")

    def _summarise(self, plan: BackfillPlan) -> None:
        unknown_uses = sum(len(pks) for pks in plan.unknown.values())
        skipped = ", ".join(f"{n:,} {reason}" for reason, n in plan.skipped.most_common() if n) or "none"
        self.stdout.write(
            f"{plan.posts:,} in-target posts carry an @handle: {len(plan.references):,} mentions to record, "
            f"{len(plan.unknown):,} unknown handles ({unknown_uses:,} mentions). Left out: {skipped}."
        )

    def _look_up(self, plan: BackfillPlan, limit: int | None) -> int:
        with TelegramClient(
            settings.TELEGRAM_SESSION_NAME,
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
            connection_retries=settings.TELEGRAM_CONNECTION_RETRIES,
            retry_delay=settings.TELEGRAM_RETRY_DELAY,
            flood_sleep_threshold=settings.TELEGRAM_FLOOD_SLEEP_THRESHOLD,
        ).start(phone=settings.TELEGRAM_PHONE_NUMBER) as client:
            resolver = ReferenceResolver(TelegramAPIClient(client))
            counts = look_up_handles(resolver, plan, limit=limit, report=self._report)
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{counts['found']:,} handles found, {counts['dropped']:,} dropped (nothing there, or a person), "
                f"{counts['left']:,} left for a later run; {counts['references']:,} more mentions recorded."
            )
        )
        return counts["references"]

    def _report(self, handle: str, uses: int, channel: Channel | None, outcome: str) -> None:
        if outcome == FOUND:
            kind = "bot" if channel.is_user_account else "channel"
            self.stdout.write(self.style.SUCCESS(f"@{handle} ({uses:,}×) {kind}: {channel} [id={channel.pk}]"))
        else:
            self.stdout.write(f"@{handle} ({uses:,}×) dropped")
