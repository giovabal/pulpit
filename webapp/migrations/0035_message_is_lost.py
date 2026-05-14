from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0034_rename_interesting_in_target"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="is_lost",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
