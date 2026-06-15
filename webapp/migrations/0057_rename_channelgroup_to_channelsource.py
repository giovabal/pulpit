from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0056_drop_legacy_organization_models"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="ChannelGroup",
            new_name="ChannelSource",
        ),
        migrations.AlterField(
            model_name="channelsource",
            name="channels",
            field=models.ManyToManyField(blank=True, related_name="sources", to="webapp.channel"),
        ),
    ]
