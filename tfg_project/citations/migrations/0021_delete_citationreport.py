from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("citations", "0020_notification"),
    ]

    operations = [
        migrations.DeleteModel(
            name="CitationReport",
        ),
    ]
