"""Fingerprint the stored message pictures for the image near-copy analysis.

Each stored picture file (one per Telegram photo id) gets a 64-bit perceptual hash (pHash) and a
difference hash (dHash) in ``ImageFingerprint`` — see :mod:`crawler.image_hash`. Incremental: a file
already fingerprinted is skipped unless it was re-downloaded or ``--rehash`` is given, so the command
can run after every crawl (``crawl_channels --hash-images`` does it for you).

Usage:
    python manage.py hash_media             # new files only
    python manage.py hash_media --limit 500 # at most 500 files
    python manage.py hash_media --rehash    # every stored file again
"""

from typing import Any

from django.core.management.base import BaseCommand

from crawler.image_hash import hash_stored_pictures


class Command(BaseCommand):
    help = "Fingerprint stored message pictures (perceptual hashes for image near-copy detection)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--limit", type=int, default=None, help="Hash at most this many files.")
        parser.add_argument("--rehash", action="store_true", help="Recompute every stored file's fingerprint.")

    def handle(self, *args: Any, **options: Any) -> None:
        def _progress(line: str) -> None:
            self.stdout.write(line)
            self.stdout.flush()

        counts = hash_stored_pictures(limit=options["limit"], rehash=options["rehash"], progress=_progress)
        self.stdout.write(
            self.style.SUCCESS(
                f"{counts['hashed']} file(s) fingerprinted, {counts['skipped']} skipped (unreadable or uniform), "
                f"{counts['unchanged']} already up to date."
            )
        )
