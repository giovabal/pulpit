"""Mirror the legacy Organization model into the new Label system.

Creates one primary, partition LabelGroup named "Organization", one Label per
Organization (copying name, colour, is_in_target), and one ChannelLabel per
ChannelAttribution (mapping organization → label, preserving start/end). This
is the additive half of the Organization → Label migration; a later migration
drops Organization and ChannelAttribution once all code reads labels.

Idempotent (get_or_create + flag re-sync) so it is safe to re-run.
"""

from django.db import migrations

ORG_GROUP_NAME = "Organization"


def seed_labels(apps, schema_editor):
    Organization = apps.get_model("webapp", "Organization")
    ChannelAttribution = apps.get_model("webapp", "ChannelAttribution")
    LabelGroup = apps.get_model("webapp", "LabelGroup")
    Label = apps.get_model("webapp", "Label")
    ChannelLabel = apps.get_model("webapp", "ChannelLabel")

    group, _ = LabelGroup.objects.get_or_create(
        name=ORG_GROUP_NAME,
        defaults={
            "description": "Migrated from the legacy Organization model.",
            "is_partition": True,
            "is_primary": True,
        },
    )
    # Re-sync the defining flags in case a prior partial run left them off.
    LabelGroup.objects.filter(pk=group.pk).update(is_partition=True, is_primary=True)

    org_to_label: dict[int, int] = {}
    for org in Organization.objects.all():
        label, _ = Label.objects.get_or_create(group=group, name=org.name)
        Label.objects.filter(pk=label.pk).update(color=org.color, is_in_target=org.is_in_target)
        org_to_label[org.id] = label.id

    existing = set(ChannelLabel.objects.values_list("channel_id", "label_id", "start", "end"))
    rows = []
    for cid, org_id, start, end in ChannelAttribution.objects.values_list(
        "channel_id", "organization_id", "start", "end"
    ).iterator(chunk_size=1000):
        label_id = org_to_label.get(org_id)
        if label_id is None or (cid, label_id, start, end) in existing:
            continue
        rows.append(ChannelLabel(channel_id=cid, label_id=label_id, start=start, end=end))
        if len(rows) >= 1000:
            ChannelLabel.objects.bulk_create(rows)
            rows = []
    if rows:
        ChannelLabel.objects.bulk_create(rows)


def unseed_labels(apps, schema_editor):
    """Drop everything seeded here. Organization / ChannelAttribution are untouched."""
    ChannelLabel = apps.get_model("webapp", "ChannelLabel")
    Label = apps.get_model("webapp", "Label")
    LabelGroup = apps.get_model("webapp", "LabelGroup")
    ChannelLabel.objects.all().delete()
    Label.objects.all().delete()
    LabelGroup.objects.filter(name=ORG_GROUP_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0054_labelgroup_label_channellabel"),
    ]

    operations = [
        migrations.RunPython(seed_labels, unseed_labels),
    ]
