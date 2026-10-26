"""Tell bots from people among the stored user accounts.

The crawler now records Telethon's ``User.bot`` flag when a handle resolves to a user
account. Rows stored before carry only the handle, so they are backfilled from it:
Telegram requires every bot username to end in "bot". A user account stored without a
username stays a person — every bot has one.
"""

from django.db import migrations, models


def backfill(apps, schema_editor):
    Channel = apps.get_model("webapp", "Channel")
    Channel.objects.filter(is_user_account=True, username__iendswith="bot").update(is_bot=True)


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0067_message_reply_to_peer_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="channel",
            name="is_bot",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
