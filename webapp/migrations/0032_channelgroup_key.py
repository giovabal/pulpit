from django.db import migrations, models
from django.utils.text import slugify


def populate_keys(apps, schema_editor):
    ChannelGroup = apps.get_model("webapp", "ChannelGroup")
    used: set[str] = set()
    for group in ChannelGroup.objects.order_by("id"):
        base = slugify(group.name) or str(group.pk)
        key = base
        n = 1
        while key in used:
            key = f"{base}-{n}"
            n += 1
        used.add(key)
        group.key = key
        group.save(update_fields=["key"])


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0031_message_fwd_from_date"),
    ]

    operations = [
        migrations.AddField(
            model_name="channelgroup",
            name="key",
            field=models.SlugField(max_length=100, default=""),
            preserve_default=False,
        ),
        migrations.RunPython(populate_keys, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="channelgroup",
            name="key",
            field=models.SlugField(max_length=100, unique=True),
        ),
    ]
