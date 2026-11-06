"""Tests for the export_salon_profile command --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the ``export_salon_profile_csv``
service), that JSON parses to the single verbatim dict from
``export_salon_profile`` -- the same dict the CSV is built
from -- serialised with ``DjangoJSONEncoder`` (indent=2 +
trailing newline, B(i) verbatim-dict precedent), and that
unknown formats fail cleanly.
"""
import io
import json
from unittest import mock

from django.core.management import call_command, load_command_class
from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from saloncore.models import Salon
from saloncore.salon_profile_export import (
    SALON_FIELDNAMES,
    export_salon_profile,
    export_salon_profile_csv,
)


def _cmd():
    return load_command_class("saloncore", "export_salon_profile")


def _expected_json(salon):
    return json.dumps(export_salon_profile(salon),
                      indent=2, cls=DjangoJSONEncoder) + "\n"


class ExportSalonProfileFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Example Salon", timezone="America/New_York",
            currency="EUR", tagline="Hair, honestly.",
            logo_url="https://example.com/logo.png",
            primary_color="#123456", accent_color="#abcdef")

    def _pinned_csv(self):
        s = self.salon
        return (
            ",".join(SALON_FIELDNAMES) + "\n"
            f"{s.pk},Example Salon,America/New_York,EUR,"
            '"Hair, honestly.",https://example.com/logo.png,'
            f"#123456,#abcdef,{s.created_at.isoformat()},"
            f"{s.updated_at.isoformat()}\n"
        )

    def _call(self, **kwargs):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.pk, stdout=out, **kwargs)
        return out.getvalue()

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(
            export_salon_profile_csv(self.salon), self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        self.assertEqual(self._call(), self._pinned_csv())
        self.assertEqual(self._call(), export_salon_profile_csv(self.salon))

    def test_explicit_csv_format_kwargs_matches_service(self):
        self.assertEqual(
            self._call(format="csv"), export_salon_profile_csv(self.salon))

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command(_cmd(), "--salon-id", str(self.salon.pk),
                     "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), export_salon_profile_csv(self.salon))

    def test_json_parses_and_equals_service_dict(self):
        text = self._call(format="json")
        row = export_salon_profile(self.salon)
        self.assertIsInstance(row, dict)
        self.assertEqual(json.loads(text), row)
        self.assertEqual(text, _expected_json(self.salon))
        self.assertEqual(list(json.loads(text)), SALON_FIELDNAMES)
        self.assertIn("Example Salon", text)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command(_cmd(), "--salon-id", str(self.salon.pk),
                     "--format", "json", stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon))

    def test_json_output_file(self):
        out = io.StringIO()
        mocked = mock.mock_open()
        with mock.patch(
                "saloncore.management.commands.export_salon_profile"
                ".open", mocked, create=True):
            call_command(_cmd(), salon_id=self.salon.pk, format="json",
                         output="profile.json", stdout=out)
        mocked.assert_called_once_with(
            "profile.json", "w", encoding="utf-8", newline="")
        mocked().write.assert_called_once_with(_expected_json(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        out = io.StringIO()
        mocked = mock.mock_open()
        with mock.patch(
                "saloncore.management.commands.export_salon_profile"
                ".open", mocked, create=True):
            call_command(_cmd(), salon_id=self.salon.pk,
                         output="profile.csv", stdout=out)
        mocked.assert_called_once_with(
            "profile.csv", "w", encoding="utf-8", newline="")
        mocked().write.assert_called_once_with(
            export_salon_profile_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command(_cmd(), "--salon-id", str(self.salon.pk),
                         "--format", "xml", stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command(_cmd(), salon_id=999999, format="json",
                         stdout=io.StringIO())

    def test_unwritable_output_raises_command_error_json(self):
        mocked = mock.mock_open()
        mocked.side_effect = OSError("cannot write")
        with mock.patch(
                "saloncore.management.commands.export_salon_profile"
                ".open", mocked, create=True):
            with self.assertRaises(CommandError):
                call_command(_cmd(), salon_id=self.salon.pk, format="json",
                             output="out.json", stdout=io.StringIO())
