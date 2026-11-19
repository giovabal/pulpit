"""Drop ChannelSource: the editable Sources tags, their Manage page and --channel-sources are removed."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0077_commenter_review"),
    ]

    operations = [
        migrations.DeleteModel(name="ChannelSource"),
    ]
