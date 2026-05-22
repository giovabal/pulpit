from django.db import migrations, models


def backfill_total_reactions(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        sql = (
            "UPDATE webapp_message AS m "
            "SET total_reactions = COALESCE(r.total, 0) "
            "FROM ("
            "    SELECT message_id, SUM(count) AS total "
            "    FROM webapp_messagereaction "
            "    GROUP BY message_id"
            ") AS r "
            "WHERE m.id = r.message_id"
        )
    else:
        sql = (
            "UPDATE webapp_message "
            "SET total_reactions = ("
            "    SELECT COALESCE(SUM(count), 0) "
            "    FROM webapp_messagereaction "
            "    WHERE webapp_messagereaction.message_id = webapp_message.id"
            ")"
        )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(sql)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("webapp", "0043_alter_messageaudio_audio_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="total_reactions",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddIndex(
            model_name="message",
            index=models.Index(fields=["channel", "views"], name="webapp_msg_chan_views_idx"),
        ),
        migrations.AddIndex(
            model_name="message",
            index=models.Index(fields=["channel", "total_reactions"], name="webapp_msg_chan_react_idx"),
        ),
        migrations.RunPython(backfill_total_reactions, noop_reverse),
    ]
