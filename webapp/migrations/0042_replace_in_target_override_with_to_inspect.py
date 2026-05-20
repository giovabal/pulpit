from django.db import migrations, models


def copy_override_to_inspect(apps, schema_editor):
    Channel = apps.get_model("webapp", "Channel")
    Channel.objects.filter(in_target_override=True).update(to_inspect=True)


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0041_message_composite_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="channel",
            name="to_inspect",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(copy_override_to_inspect, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="channel",
            name="in_target_override",
        ),
    ]
