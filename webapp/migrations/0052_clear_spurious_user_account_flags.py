from django.db import migrations
from django.db.models import Exists, OuterRef, Q


def clear_spurious_user_account_flags(apps, schema_editor):
    """Repair channels mislabelled ``is_user_account=True`` despite being real channels.

    ``resolve_channel_or_classify`` used to return ``"user_account"`` when a known
    channel's stored handle had been recycled onto a user (the User variant of the
    recycled-handle bug); the caller then stamped ``is_user_account=True`` onto the
    real channel, which ``channel_type`` reports as "user" and which silently drops
    the row from channel-scope crawls. The crawler no longer does this, but rows
    flagged by earlier runs must be corrected.

    A flag is spurious — provably contradicting reality — when the same row carries
    channel-only evidence: ``megagroup``/``gigagroup`` (copied solely from a Telegram
    Channel entity) or any crawled message. Rows with no such evidence are left
    untouched: without it we cannot tell a genuine user account from a channel that
    was mislabelled before it was ever crawled, and the fixed crawler will reclassify
    those on the next successful resolve.
    """
    Channel = apps.get_model("webapp", "Channel")
    Message = apps.get_model("webapp", "Message")

    spurious = (
        Channel.objects.filter(is_user_account=True)
        .annotate(_has_message=Exists(Message.objects.filter(channel=OuterRef("pk"))))
        .filter(Q(megagroup=True) | Q(gigagroup=True) | Q(_has_message=True))
    )
    pks = list(spurious.values_list("pk", flat=True))
    Channel.objects.filter(pk__in=pks).update(is_user_account=False)


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0051_seed_project_title"),
    ]

    operations = [
        # Irreversible: the prior value was wrong, so there is nothing to restore.
        migrations.RunPython(clear_spurious_user_account_flags, migrations.RunPython.noop),
    ]
