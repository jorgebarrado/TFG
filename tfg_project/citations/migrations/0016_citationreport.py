from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("citations", "0015_userprofile_contact_email_userprofile_social_link_1_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CitationReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("original_doi", models.CharField(max_length=255)),
                ("original_metadata", models.JSONField(blank=True, null=True)),
                ("original_pdf_url", models.URLField(blank=True, null=True)),
                ("original_pdf_uploaded", models.FileField(blank=True, null=True, upload_to="original_pdfs/")),
                ("original_snippet", models.TextField(blank=True, null=True)),
                ("citing_doi", models.CharField(max_length=255)),
                ("citing_metadata", models.JSONField(blank=True, null=True)),
                ("citing_pdf_url", models.URLField(blank=True, null=True)),
                ("citing_pdf_uploaded", models.FileField(blank=True, null=True, upload_to="citing_pdfs/")),
                ("citing_paragraphs", models.JSONField(blank=True, null=True)),
                ("citing_pages", models.JSONField(blank=True, null=True)),
                ("error_type", models.CharField(max_length=100)),
                ("user_explanation", models.TextField()),
                ("ai_assessment", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=models.SET_NULL, to=settings.AUTH_USER_MODEL
                    ),
                ),
            ],
        ),
    ]
