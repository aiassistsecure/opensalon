"""Dispatch due appointment reminders on both channels.

Usage:
    python manage.py send_due_reminders [--hours 24]
        [--now ISO-8601-DATETIME] [--dry-run]

Thin wrapper around the existing combined service
:func:`messaging.dispatch.send_due_reminders`: sends email
and SMS reminders, in a single run, to appointments starting
within the window whose clients opted in to each channel --
see ``messaging.dispatch`` for the exact gates. This command
adds no delivery or eligibility logic of its own, so command
and service can never disagree -- one source of truth. In
particular the service's per-channel opt-in behaviour carries
through exactly; this command never re-checks opt-ins and
never bypasses them. Reminders go only to opted-in clients.

``--now`` pins the reference instant the window is measured
from (parsed as ISO-8601 to an aware datetime); when omitted
the service's own default applies -- today's clock, exactly
as before.

Output is counts only: no client names or contact details
are printed. Invalid input -- a negative window or an
unparseable ``--now`` -- raises ``CommandError``, as does a
``TypeError``/``ValueError`` from the service. Core stays
provider-agnostic -- no provider SDK, field, or name appears
here.
"""
import argparse
import datetime
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from messaging.dispatch import send_due_reminders


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
    help = (
        "Send due appointment reminders (email + SMS) to "
        "opted-in clients."
    )

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

    def handle(self, *args, **options):
        hours = options["hours"]
        dry_run = options["dry_run"]
        if hours < 0:
            raise CommandError(
                f"Invalid --hours {hours!r}; expected 0 or more."
            )
        now = _coerce_now(options.get("now"))
        try:
            summary = send_due_reminders(
                now=now, within=timedelta(hours=hours), dry_run=dry_run
            )
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if dry_run:
            opt_in_skipped = (
                summary.email.skipped_not_opted_in
                + summary.sms.skipped_not_opted_in
            )
            self.stdout.write(
                "Dry run: Reminders: {sent} would send, "
                "{skipped} skipped ({opt} skipped by opt-in; "
                "email: {e_sent} would send, {e_skipped} skipped; "
                "SMS: {s_sent} would send, {s_skipped} skipped).".format(
                    sent=summary.sent,
                    skipped=summary.skipped,
                    opt=opt_in_skipped,
                    e_sent=summary.email.sent,
                    e_skipped=summary.email.skipped,
                    s_sent=summary.sms.sent,
                    s_skipped=summary.sms.skipped,
                )
            )
            return
        self.stdout.write(
            "Reminders: {sent} sent, {skipped} skipped "
            "(email: {e_sent} sent, {e_skipped} skipped; "
            "SMS: {s_sent} sent, {s_skipped} skipped).".format(
                sent=summary.sent,
                skipped=summary.skipped,
                e_sent=summary.email.sent,
                e_skipped=summary.email.skipped,
                s_sent=summary.sms.sent,
                s_skipped=summary.sms.skipped,
            )
        )
