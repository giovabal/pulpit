from django.db import migrations, models


def backfill_stats_refreshed_at(apps, schema_editor):
    Message = apps.get_model("webapp", "Message")
    Message.objects.update(stats_refreshed_at=models.F("_updated"))


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0029_add_replies_fetched_to_message"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="stats_refreshed_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.RunPython(backfill_stats_refreshed_at, migrations.RunPython.noop),
    ]
