"""The account email rides the salon_data export (full export
import law): a salon's export must carry everything needed to
restore its accounts — email included, beside the PIN.
"""

import json
import tempfile

from django.core.management import call_command
from django.test import TestCase

from saloncore.models import Salon
from team.models import StaffMember


class StaffEmailExportTests(TestCase):
    def test_staff_email_is_exported(self):
        salon = Salon.objects.create(name="Export Salon", timezone="UTC")
        StaffMember.objects.create(
            salon=salon, display_name="Dana",
            email="dana@salon.test", pin="2468",
        )
        with tempfile.NamedTemporaryFile(
            mode="r", suffix=".json", delete=False
        ) as fh:
            path = fh.name
        call_command("export_salon_data", path)
        with open(path) as fh:
            data = json.load(fh)
        rows = data["staff_members"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["email"], "dana@salon.test")
        self.assertEqual(rows[0]["pin"], "2468")
