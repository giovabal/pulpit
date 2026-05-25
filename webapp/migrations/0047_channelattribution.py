import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0046_message_interest_score"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChannelAttribution",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("_created", models.DateTimeField(auto_now_add=True)),
                ("_updated", models.DateTimeField(auto_now=True)),
                ("start", models.DateField(blank=True, null=True)),
                ("end", models.DateField(blank=True, null=True)),
                (
                    "channel",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="attributions", to="webapp.channel"
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attributions",
                        to="webapp.organization",
                    ),
                ),
            ],
            options={
                "ordering": ["channel_id", "start"],
                "indexes": [
                    models.Index(fields=["channel", "organization"], name="webapp_chattr_chan_org_idx"),
                    models.Index(fields=["organization"], name="webapp_chattr_org_idx"),
                    models.Index(fields=["channel", "start", "end"], name="webapp_chattr_chan_span_idx"),
                ],
            },
        ),
    ]
