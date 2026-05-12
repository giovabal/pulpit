from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0032_channelgroup_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="channel",
            name="interesting_override",
            field=models.BooleanField(blank=True, default=None, null=True),
        ),
    ]
