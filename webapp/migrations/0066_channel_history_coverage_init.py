"""Initialise ``Channel.history_coverage`` for channels crawled before it existed.

The coverage lists the days whose required messages are all stored; the crawler walks
only the required days missing from it. A channel holding messages gets
``[[<local date of its oldest stored message>, null]]``: everything from there on was
walked by the earlier crawls (each resumed from the newest stored message), while the
days before it are left missing — so the next crawl walks below the oldest stored
message down to the channel's required start once (a single request when nothing is
missing), which also repairs channels whose older history was never fetched. A channel
with no stored message keeps ``[]``: its first crawl walks everything required anyway.
"""

from django.db import migrations
from django.db.models import Min
from django.utils import timezone

_BATCH = 500


def init_history_coverage(apps, schema_editor):
    Channel = apps.get_model("webapp", "Channel")
    Message = apps.get_model("webapp", "Message")
    # One row per channel holding a dated message — small enough to hold, and fully read
    # before the first write.
    oldest = list(
        Message.objects.filter(date__isnull=False)
        .order_by()
        .values("channel_id")
        .annotate(first=Min("date"))
        .values_list("channel_id", "first")
    )
    channels = [
        Channel(pk=channel_id, history_coverage=[[timezone.localdate(first).isoformat(), None]])
        for channel_id, first in oldest
    ]
    Channel.objects.bulk_update(channels, ["history_coverage"], batch_size=_BATCH)


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0065_repair_reference_users_and_environment_stamps"),
    ]

    operations = [
        migrations.RunPython(init_history_coverage, migrations.RunPython.noop),
    ]
