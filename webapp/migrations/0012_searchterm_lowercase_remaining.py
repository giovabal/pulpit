from django.db import migrations


def _lowercase_all_search_terms(apps, schema_editor):
    SearchTerm = apps.get_model("webapp", "SearchTerm")
    for term in SearchTerm.objects.all():
        lowered = " ".join(term.word.split()).lower()
        if term.word != lowered:
            term.word = lowered
            term.save(update_fields=["word"])


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0011_searchterm_word_lower_unique"),
    ]

    operations = [
        migrations.RunPython(_lowercase_all_search_terms, migrations.RunPython.noop),
    ]
