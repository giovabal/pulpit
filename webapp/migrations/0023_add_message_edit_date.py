from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0022_add_channel_extra_metadata"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="edit_date",
            field=models.DateTimeField(null=True),
        ),
    ]
