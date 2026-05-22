"""Recompute per-channel z-scores and the composite ``interest_score`` for
every alive Message (or a single channel).

Companion to ``webapp.scoring``: usually fires automatically at the end of
each per-channel crawl; this command is the manual / batch path.

Usage:
    python manage.py compute_message_scores                     # all channels
    python manage.py compute_message_scores --channel-id 42     # one channel
    python manage.py compute_message_scores --recency-days 90
    python manage.py compute_message_scores --weights reactions=0.6,forwards=0.3,views=0.1
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand, CommandError

from webapp.scoring import DEFAULT_WEIGHTS, MIN_SAMPLE, recompute_all_channels, recompute_channel


def _parse_weights(value: str | None) -> dict[str, float]:
    if not value:
        return DEFAULT_WEIGHTS
    parsed: dict[str, float] = {}
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise CommandError(f"Invalid --weights chunk {chunk!r}; expected 'facet=number'.")
        name, raw = chunk.split("=", 1)
        name = name.strip().lower()
        if name not in DEFAULT_WEIGHTS:
            raise CommandError(f"Unknown facet {name!r} in --weights; choose from {sorted(DEFAULT_WEIGHTS)}.")
        try:
            parsed[name] = float(raw.strip())
        except ValueError as err:
            raise CommandError(f"Invalid weight value {raw!r} for {name!r}.") from err
    # Fill missing facets with defaults so a partial override still scores.
    return {**DEFAULT_WEIGHTS, **parsed}


class Command(BaseCommand):
    help = (
        "Recompute z-scores (views, forwards, reactions) and the composite interest_score "
        "for every alive Message, or a single channel with --channel-id."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--channel-id",
            type=int,
            default=None,
            metavar="N",
            help="Recompute scores for a single channel (DB primary key). Default: every channel.",
        )
        parser.add_argument(
            "--min-sample",
            type=int,
            default=MIN_SAMPLE,
            metavar="N",
            help=f"Skip channels with fewer than N alive messages. Default: {MIN_SAMPLE}.",
        )
        parser.add_argument(
            "--recency-days",
            type=int,
            default=None,
            metavar="N",
            help=(
                "Use only messages from the last N days for the per-channel baseline. "
                "Omit to use the full message history."
            ),
        )
        parser.add_argument(
            "--weights",
            default=None,
            metavar="facet=w,facet=w",
            help=(
                "Composite weight overrides. Facets: reactions, forwards, views. "
                f"Defaults to {','.join(f'{k}={v}' for k, v in DEFAULT_WEIGHTS.items())}. "
                "Weights are renormalised to sum to 1."
            ),
        )

    def handle(self, *args, **options) -> None:
        weights = _parse_weights(options["weights"])
        min_sample = options["min_sample"]
        recency_days = options["recency_days"]
        channel_id: int | None = options["channel_id"]

        started = time.monotonic()
        if channel_id is not None:
            n = recompute_channel(channel_id, weights=weights, min_sample=min_sample, recency_days=recency_days)
            elapsed = time.monotonic() - started
            self.stdout.write(
                self.style.SUCCESS(f"Recomputed scores for channel {channel_id}: {n:,} messages in {elapsed:.2f}s.")
            )
            return

        last_report = [time.monotonic()]

        def _progress(ix: int, total: int, _msg_count: int) -> None:
            # Throttle stdout to one line per second on large catalogues so the
            # terminal doesn't spend more time scrolling than scoring.
            now = time.monotonic()
            if ix == total or (now - last_report[0]) > 1.0:
                self.stdout.write(f"  [{ix}/{total}] channels scored", ending="\r")
                self.stdout.flush()
                last_report[0] = now

        channels, messages = recompute_all_channels(
            weights=weights,
            min_sample=min_sample,
            recency_days=recency_days,
            on_progress=_progress,
        )
        elapsed = time.monotonic() - started
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(f"Processed {channels:,} channels, {messages:,} messages in {elapsed:.2f}s.")
        )
