"""Repair rows written by two crawler bugs fixed in 0.28.

* A ``t.me/<user or bot>`` link used to be stored as a CHANNEL row: the reference
  resolver built it from the Telegram ``User`` with ``Channel.from_telegram_object``,
  which leaves ``title`` empty, ``date`` NULL and ``broadcast`` at its default. Every
  Telegram channel or group carries a title and a creation date, so a row with an
  access hash but neither — never crawled, never labelled, not to_inspect — can only
  be such a user. It is re-typed as a user account, as the resolver now stores them.
* The environment pass used to stamp ``environment_depth`` even when the channel
  turned out lost, private or a user account. Such a channel stamped without a
  single stored message was never actually crawled, so its stamp is cleared; one
  that holds messages was crawled before it went dark and keeps it.
"""

from django.db import migrations
from django.db.models import Exists, OuterRef, Q


def repair(apps, schema_editor):
    Channel = apps.get_model("webapp", "Channel")
    Message = apps.get_model("webapp", "Message")
    ChannelLabel = apps.get_model("webapp", "ChannelLabel")
    has_messages = Exists(Message.objects.filter(channel=OuterRef("pk")))

    Channel.objects.filter(
        title="",
        date__isnull=True,
        access_hash__isnull=False,
        is_user_account=False,
        to_inspect=False,
    ).exclude(has_messages).exclude(Exists(ChannelLabel.objects.filter(channel=OuterRef("pk")))).update(
        is_user_account=True, broadcast=False
    )

    Channel.objects.filter(
        Q(is_lost=True) | Q(is_private=True) | Q(is_user_account=True), environment_depth__isnull=False
    ).exclude(has_messages).update(environment_depth=None)


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0064_channel_history_coverage_pending_forward_index"),
    ]

    operations = [
        migrations.RunPython(repair, migrations.RunPython.noop),
    ]
