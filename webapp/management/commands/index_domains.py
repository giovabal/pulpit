"""Rebuild the outbound-link domain index behind Manage → Domains (``network.links.index_domains``)."""

from django.core.management.base import BaseCommand

from network.links import index_domains


class Command(BaseCommand):
    help = (
        "Count, per linked web site, the in-target channels' alive in-period messages linking to it (text URLs, "
        "hidden links, buttons and previews; t.me excluded). New sites are added uncategorised (or under their "
        "hosting platform's category); categories and notes are kept."
    )

    def handle(self, *args, **options) -> None:
        counts = index_domains(progress=lambda line: (self.stdout.write(line), self.stdout.flush()))
        self.stdout.write(
            self.style.SUCCESS(
                f"Indexed {counts['domains']} sites over {counts['messages']} messages ({counts['new']} new)."
            )
        )
