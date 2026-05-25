"""Backfill ChannelAttribution from the legacy Channel.organization + out_of_target_after.

Each channel that had an organization becomes one attribution period
``(start=None, end=out_of_target_after)`` — i.e. in-target from creation up to
the old cutoff (or open-ended when no cutoff was set). Channels with no
organization get no attribution; an orphan ``out_of_target_after`` with no
organization is discarded (it was meaningless without an org).
"""

from django.db import migrations


def backfill_attributions(apps, schema_editor):
    Channel = apps.get_model("webapp", "Channel")
    ChannelAttribution = apps.get_model("webapp", "ChannelAttribution")
    rows = []
    qs = Channel.objects.filter(organization__isnull=False).values_list("id", "organization_id", "out_of_target_after")
    for channel_id, organization_id, out_of_target_after in qs.iterator(chunk_size=1000):
        rows.append(
            ChannelAttribution(
                channel_id=channel_id,
                organization_id=organization_id,
                start=None,
                end=out_of_target_after,
            )
        )
        if len(rows) >= 1000:
            ChannelAttribution.objects.bulk_create(rows)
            rows = []
    if rows:
        ChannelAttribution.objects.bulk_create(rows)


def reverse_backfill(apps, schema_editor):
    """Restore each channel's FK + cutoff from its earliest attribution, then drop the rows.

    Runs after 0049's reverse has re-added the columns. Periods are non-overlapping,
    so the earliest period (start ASC, NULL first) is the natural single value to
    restore onto the legacy single-org/single-cutoff fields.
    """
    Channel = apps.get_model("webapp", "Channel")
    ChannelAttribution = apps.get_model("webapp", "ChannelAttribution")
    seen: set[int] = set()
    for channel_id, organization_id, end in ChannelAttribution.objects.order_by("channel_id", "start").values_list(
        "channel_id", "organization_id", "end"
    ):
        if channel_id in seen:
            continue
        seen.add(channel_id)
        Channel.objects.filter(pk=channel_id).update(organization_id=organization_id, out_of_target_after=end)
    ChannelAttribution.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0047_channelattribution"),
    ]

    operations = [
        migrations.RunPython(backfill_attributions, reverse_backfill),
    ]
