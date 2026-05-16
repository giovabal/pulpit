import mimetypes

from django.db import migrations


def backfill_mime_type(apps, schema_editor):
    ProfilePicture = apps.get_model("webapp", "ProfilePicture")
    for pp in ProfilePicture.objects.filter(mime_type=""):
        if not pp.picture:
            continue
        guess, _ = mimetypes.guess_type(pp.picture.name)
        if guess:
            pp.mime_type = guess
            pp.save(update_fields=["mime_type"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0039_profilepicture_mime_type_profilepicture_thumbnail"),
    ]

    operations = [
        migrations.RunPython(backfill_mime_type, noop_reverse),
    ]
