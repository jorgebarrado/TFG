from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("citations", "0017_alter_userprofile_profession_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="incorrectcitation",
            name="citation_contexts",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
