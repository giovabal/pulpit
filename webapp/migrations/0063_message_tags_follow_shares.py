"""Message tags follow shares: a tagging now belongs to a post — the original and every share.

Each existing tagging takes the Telegram origin of the message it was put on;
taggings of one tag that land on the same post are folded into the earliest
(its empty note filled from the others), and every stored message that is, or
shares, a tagged post is linked through the new ``TaggedMessage`` table.
"""

from collections import defaultdict

import django.db.models.deletion
from django.db import migrations, models


def _origin(message):
    if message.fwd_from_channel_post is not None:
        if message.forwarded_from_id is not None:
            return message.forwarded_from.telegram_id, message.fwd_from_channel_post
        if message.forwarded_from_private is not None:
            return message.forwarded_from_private, message.fwd_from_channel_post
    return message.channel.telegram_id, message.telegram_id


def link_taggings_to_posts(apps, schema_editor):
    # Historical models only, so this mirrors webapp.models.tag_models.message_origin /
    # resolve_origin_messages instead of importing them.
    MessageTagging = apps.get_model("webapp", "MessageTagging")
    TaggedMessage = apps.get_model("webapp", "TaggedMessage")
    Message = apps.get_model("webapp", "Message")
    Channel = apps.get_model("webapp", "Channel")

    kept = {}
    for tagging in MessageTagging.objects.select_related("message__channel", "message__forwarded_from").order_by(
        "_created", "pk"
    ):
        origin = _origin(tagging.message)
        first = kept.get((tagging.tag_id, origin))
        if first is None:
            tagging.origin_channel_tid, tagging.origin_post_tid = origin
            tagging.save(update_fields=["origin_channel_tid", "origin_post_tid"])
            kept[(tagging.tag_id, origin)] = tagging
        else:
            if tagging.note and not first.note:
                first.note = tagging.note
                first.save(update_fields=["note"])
            tagging.delete()
    if not kept:
        return

    origins = {origin for _, origin in kept}
    tid_by_pk = dict(Channel.objects.filter(telegram_id__in={t for t, _ in origins}).values_list("pk", "telegram_id"))
    members = defaultdict(set)
    for tid, post in origins:
        for pk in [pk for pk, channel_tid in tid_by_pk.items() if channel_tid == tid]:
            members[(tid, post)].update(
                Message.objects.filter(
                    models.Q(channel_id=pk, telegram_id=post)
                    | models.Q(forwarded_from_id=pk, fwd_from_channel_post=post)
                ).values_list("pk", flat=True)
            )
        members[(tid, post)].update(
            Message.objects.filter(
                forwarded_from_private__isnull=False, forwarded_from_private=tid, fwd_from_channel_post=post
            ).values_list("pk", flat=True)
        )
    TaggedMessage.objects.bulk_create(
        [
            TaggedMessage(tagging=tagging, message_id=pk)
            for (_, origin), tagging in kept.items()
            for pk in members[origin]
        ],
        batch_size=500,
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0062_messagetag_messagetagging"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="message",
            index=models.Index(
                condition=models.Q(("forwarded_from_private__isnull", False)),
                fields=["forwarded_from_private", "fwd_from_channel_post"],
                name="webapp_msg_fwd_private_idx",
            ),
        ),
        migrations.AddField(
            model_name="messagetagging",
            name="origin_channel_tid",
            field=models.BigIntegerField(null=True),
        ),
        migrations.AddField(
            model_name="messagetagging",
            name="origin_post_tid",
            field=models.BigIntegerField(null=True),
        ),
        migrations.RemoveConstraint(
            model_name="messagetagging",
            name="webapp_messagetagging_unique",
        ),
        migrations.CreateModel(
            name="TaggedMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "message",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="tag_links", to="webapp.message"
                    ),
                ),
                (
                    "tagging",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="members",
                        to="webapp.messagetagging",
                    ),
                ),
            ],
            options={
                "ordering": ["tagging__tag__key"],
                "constraints": [
                    models.UniqueConstraint(fields=("tagging", "message"), name="webapp_taggedmessage_unique")
                ],
            },
        ),
        migrations.RunPython(link_taggings_to_posts, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="messagetagging",
            name="message",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="entered_taggings",
                to="webapp.message",
            ),
        ),
        migrations.AlterField(
            model_name="messagetagging",
            name="origin_channel_tid",
            field=models.BigIntegerField(),
        ),
        migrations.AlterField(
            model_name="messagetagging",
            name="origin_post_tid",
            field=models.BigIntegerField(),
        ),
        migrations.AddConstraint(
            model_name="messagetagging",
            constraint=models.UniqueConstraint(
                fields=("tag", "origin_channel_tid", "origin_post_tid"), name="webapp_messagetagging_post_unique"
            ),
        ),
        migrations.AddIndex(
            model_name="messagetagging",
            index=models.Index(fields=["origin_channel_tid", "origin_post_tid"], name="webapp_tagging_origin_idx"),
        ),
    ]
