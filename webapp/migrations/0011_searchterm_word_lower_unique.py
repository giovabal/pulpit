import django.db.models.functions
from django.db import migrations, models
from django.db.models import Count
from django.db.models.functions import Lower


def _deduplicate_search_terms(apps, schema_editor):
    """Remove duplicate SearchTerm rows that share the same lowercased word.

    The old unique=True constraint was case-sensitive, so mixed-case entries
    could coexist (e.g. 'Ukraine' and 'ukraine'). Keep the most recently
    checked entry for each lowercase group; delete the rest.
    """
    SearchTerm = apps.get_model("webapp", "SearchTerm")
    dup_groups = SearchTerm.objects.annotate(lw=Lower("word")).values("lw").annotate(n=Count("id")).filter(n__gt=1)
    for group in dup_groups:
        entries = list(
            SearchTerm.objects.filter(word__iexact=group["lw"]).order_by(
                models.F("last_check").desc(nulls_last=True), "id"
            )
        )
        for duplicate in entries[1:]:
            duplicate.delete()
        # Ensure the surviving entry is stored in lowercase.
        kept = entries[0]
        if kept.word != group["lw"]:
            kept.word = group["lw"]
            kept.save(update_fields=["word"])


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0010_add_channel_is_private"),
    ]

    operations = [
        # Step 1: collapse mixed-case duplicates before changing the constraint.
        migrations.RunPython(_deduplicate_search_terms, migrations.RunPython.noop),
        # Step 2: drop the old case-sensitive unique constraint.
        migrations.AlterField(
            model_name="searchterm",
            name="word",
            field=models.CharField(max_length=255),
        ),
        # Step 3: add a case-insensitive unique index via LOWER(word).
        migrations.AddConstraint(
            model_name="searchterm",
            constraint=models.UniqueConstraint(
                django.db.models.functions.Lower("word"),
                name="search_term_word_lower_unique",
            ),
        ),
    ]
