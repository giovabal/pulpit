from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0016_add_channelvacancy"),
    ]

    operations = [
        migrations.RenameField(
            model_name="channelvacancy",
            old_name="death_date",
            new_name="closure_date",
        ),
    ]
