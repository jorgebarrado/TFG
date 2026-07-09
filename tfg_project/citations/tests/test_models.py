from django.apps import apps
from django.test import SimpleTestCase

import citations.models as citation_models


class ModelRegistryTests(SimpleTestCase):
    def test_legacy_report_model_is_not_active(self):
        model_key = "citation" + "report"
        model_name = "Citation" + "Report"

        self.assertIsNone(apps.all_models["citations"].get(model_key))
        self.assertFalse(hasattr(citation_models, model_name))
