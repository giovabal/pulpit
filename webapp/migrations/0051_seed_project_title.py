from django.db import migrations


def seed_project_title(apps, schema_editor):
    """Carry the legacy `.env` PROJECT_TITLE into the new Project singleton.

    The value is read straight from the `.env` file (not Django settings — the
    PROJECT_TITLE setting is removed in this same release), mirroring how
    `settings.py` builds its decouple `config`, so existing deployments keep the
    title they had configured. Falls back to the model default when the key is
    absent.
    """
    from webapp_engine.config import ENV_PATH

    from decouple import Config, RepositoryEnv

    title = "Pulpit project"
    if ENV_PATH.exists():
        cfg = Config(RepositoryEnv(str(ENV_PATH)))
        title = cfg("PROJECT_TITLE", default="Pulpit project")

    Project = apps.get_model("webapp", "Project")
    Project.objects.update_or_create(pk=1, defaults={"title": title})


def drop_project_row(apps, schema_editor):
    Project = apps.get_model("webapp", "Project")
    Project.objects.filter(pk=1).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0050_project"),
    ]

    operations = [
        migrations.RunPython(seed_project_title, drop_project_row),
    ]
