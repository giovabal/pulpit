from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0023_add_message_edit_date"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="post_author",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
