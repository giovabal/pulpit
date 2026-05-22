import math

from django.db import migrations, models
from django.utils import timezone

# Same defaults as webapp.scoring; duplicated here so the migration stays
# self-contained (apps.get_model() returns the historical Message, which
# might differ from the live model in future replays).
_WEIGHTS = {"reactions": 0.5, "forwards": 0.3, "views": 0.2}
_MIN_SAMPLE = 30
_FACET_IDX = {"views": 1, "forwards": 2, "reactions": 3}


def _facet_stats(values, min_sample):
    if len(values) < min_sample:
        return None
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    std = math.sqrt(var)
    if std == 0:
        return None
    return mean, std


def backfill_interest_score(apps, schema_editor):
    Message = apps.get_model("webapp", "Message")
    total_weight = sum(_WEIGHTS.values())
    weights = {k: v / total_weight for k, v in _WEIGHTS.items()}
    channel_ids = list(Message.objects.filter(is_lost=False).values_list("channel_id", flat=True).distinct())
    now = timezone.now()
    for channel_id in channel_ids:
        rows = list(
            Message.objects.filter(is_lost=False, channel_id=channel_id).values_list(
                "pk", "views", "forwards", "total_reactions"
            )
        )
        if not rows:
            continue
        stats = {}
        for facet, idx in _FACET_IDX.items():
            values = [r[idx] for r in rows if r[idx] is not None]
            stats[facet] = _facet_stats(values, _MIN_SAMPLE)
        updates = []
        for row in rows:
            pk = row[0]
            z = {"views": None, "forwards": None, "reactions": None}
            score_sum = 0.0
            weight_sum = 0.0
            for facet, idx in _FACET_IDX.items():
                stat = stats[facet]
                if stat is None:
                    continue
                value = row[idx]
                if value is None:
                    continue
                mean, std = stat
                z[facet] = (value - mean) / std
                score_sum += weights[facet] * z[facet]
                weight_sum += weights[facet]
            interest_score = score_sum / weight_sum if weight_sum > 0 else None
            updates.append(
                Message(
                    pk=pk,
                    z_views=z["views"],
                    z_forwards=z["forwards"],
                    z_reactions=z["reactions"],
                    interest_score=interest_score,
                    interest_scored_at=now,
                )
            )
        Message.objects.bulk_update(
            updates,
            ["z_views", "z_forwards", "z_reactions", "interest_score", "interest_scored_at"],
            batch_size=1000,
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("webapp", "0045_message_media_shared_paths"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="z_views",
            field=models.FloatField(null=True),
        ),
        migrations.AddField(
            model_name="message",
            name="z_forwards",
            field=models.FloatField(null=True),
        ),
        migrations.AddField(
            model_name="message",
            name="z_reactions",
            field=models.FloatField(null=True),
        ),
        migrations.AddField(
            model_name="message",
            name="interest_score",
            field=models.FloatField(null=True, db_index=True),
        ),
        migrations.AddField(
            model_name="message",
            name="interest_scored_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.AddIndex(
            model_name="message",
            index=models.Index(fields=["channel", "interest_score"], name="webapp_msg_chan_interest_idx"),
        ),
        migrations.RunPython(backfill_interest_score, noop_reverse),
    ]
