from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0033_channel_interesting_override"),
    ]

    operations = [
        migrations.RenameField(
            model_name="organization",
            old_name="is_interesting",
            new_name="is_in_target",
        ),
        migrations.RenameField(
            model_name="channel",
            old_name="interesting_override",
            new_name="in_target_override",
        ),
        migrations.RenameField(
            model_name="channel",
            old_name="uninteresting_after",
            new_name="out_of_target_after",
        ),
    ]
