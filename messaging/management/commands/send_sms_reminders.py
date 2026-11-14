"""Deliver due appointment SMS reminders via the SMS adapter.

Usage:
    python manage.py send_sms_reminders [--hours 24]
        [--now ISO-8601-DATETIME] [--dry-run] [--format text|json]

With ``--format json`` the command prints exactly one JSON
object to stdout carrying the same facts as the text output
(sent / would-send and skipped counts with the full
skipped breakdown, and ``dry_run``); no prose lines are
printed in json mode. The default ``--format text`` output
is unchanged.

Sends, through the configured provider-agnostic SMS adapter
(``MESSAGING_SMS_ADAPTER``), to appointments starting within
the window whose clients opted in to SMS -- see
``messaging.sms_reminders`` for the exact gates. ``--now``
pins the reference instant the window is measured from
(parsed as ISO-8601 to an aware datetime); when omitted the
service's own default applies -- today's clock, exactly as
before. Output is counts only: no client names or contact
details are printed. An unparseable ``--now`` raises
``CommandError``.
"""
import argparse
import datetime
import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from messaging.sms_reminders import send_due_sms_reminders


def _datetime_from_string(value):
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = timezone.make_aware(
            parsed, timezone.get_current_timezone())
    return parsed


def _parse_datetime(value):
    try:
        return _datetime_from_string(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid datetime {value!r}; expected ISO-8601."
        ) from exc


def _coerce_now(value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            return timezone.make_aware(
                value, timezone.get_current_timezone())
        return value
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(
            value, datetime.time.min, tzinfo=datetime.timezone.utc)
    try:
        return _datetime_from_string(value)
    except ValueError as exc:
        raise CommandError(
            f"Invalid --now {value!r}; expected ISO-8601 datetime."
        ) from exc


class Command(BaseCommand):
    help = "Send due appointment reminder SMS messages to opted-in clients."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours", type=int, default=24,
            help="Remind appointments starting within this many hours.",
        )
        parser.add_argument(
            "--now", dest="now", type=_parse_datetime, default=None,
            help="Reference instant the window is measured from, "
                 "ISO-8601 (default: the service's own default).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: count would-send/skipped, send nothing.",
        )
        parser.add_argument(
            "--format", dest="format", default="text",
            choices=["text", "json"],
            help="Output format: text (default) or json.")

    def handle(self, *args, **options):
        fmt = options.get("format") or "text"
        if fmt not in ("text", "json"):
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'text' or 'json'.")
        dry_run = options["dry_run"]
        now = _coerce_now(options.get("now"))
        summary = send_due_sms_reminders(
            now=now, within=timedelta(hours=options["hours"]),
            dry_run=dry_run
        )
        if dry_run:
            if fmt == "json":
                self.stdout.write(json.dumps(dict(
                    would_send=summary.sent,
                    skipped=summary.skipped,
                    skipped_not_opted_in=summary.skipped_not_opted_in,
                    skipped_missing_phone=summary.skipped_missing_phone,
                    skipped_status=summary.skipped_status,
                    skipped_send_failed=summary.skipped_send_failed,
                    dry_run=True)))
                return
            self.stdout.write(
                "Dry run: SMS reminders: {sent} would send, "
                "{skipped} skipped "
                "({opt} not opted in, {missing} missing phone, "
                "{status} not remindable status, "
                "{failed} send failed).".format(
                    sent=summary.sent,
                    skipped=summary.skipped,
                    opt=summary.skipped_not_opted_in,
                    missing=summary.skipped_missing_phone,
                    status=summary.skipped_status,
                    failed=summary.skipped_send_failed,
                )
            )
            return
        if fmt == "json":
            self.stdout.write(json.dumps(dict(
                sent=summary.sent,
                skipped=summary.skipped,
                skipped_not_opted_in=summary.skipped_not_opted_in,
                skipped_missing_phone=summary.skipped_missing_phone,
                skipped_status=summary.skipped_status,
                skipped_send_failed=summary.skipped_send_failed,
                dry_run=False)))
            return
        self.stdout.write(
            "SMS reminders: {sent} sent, {skipped} skipped "
            "({opt} not opted in, {missing} missing phone, "
            "{status} not remindable status, "
            "{failed} send failed).".format(
                sent=summary.sent,
                skipped=summary.skipped,
                opt=summary.skipped_not_opted_in,
                missing=summary.skipped_missing_phone,
                status=summary.skipped_status,
                failed=summary.skipped_send_failed,
            )
        )
