from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0048_migrate_attributions"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="channel",
            name="organization",
        ),
        migrations.RemoveField(
            model_name="channel",
            name="out_of_target_after",
        ),
    ]
