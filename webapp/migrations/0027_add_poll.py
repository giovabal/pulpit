import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0026_add_messagereply"),
    ]

    operations = [
        migrations.CreateModel(
            name="Poll",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("poll_id", models.BigIntegerField()),
                ("question", models.TextField()),
                ("closed", models.BooleanField(default=False)),
                ("public_voters", models.BooleanField(default=False)),
                ("multiple_choice", models.BooleanField(default=False)),
                ("quiz", models.BooleanField(default=False)),
                ("close_date", models.DateTimeField(blank=True, null=True)),
                ("total_voters", models.PositiveIntegerField(blank=True, null=True)),
                ("solution", models.TextField(blank=True)),
                (
                    "message",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE, related_name="poll", to="webapp.message"
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="PollAnswer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("option", models.BinaryField(max_length=8)),
                ("text", models.TextField()),
                ("voters", models.PositiveIntegerField(default=0)),
                ("correct", models.BooleanField(null=True)),
                (
                    "poll",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="answers", to="webapp.poll"
                    ),
                ),
            ],
            options={
                "ordering": ["id"],
                "unique_together": {("poll", "option")},
            },
        ),
    ]
