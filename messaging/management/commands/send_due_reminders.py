"""Dispatch due appointment reminders on both channels.

Usage:
    python manage.py send_due_reminders [--hours 24]

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

Output is counts only: no client names or contact details
are printed. Invalid input -- a negative window -- raises
``CommandError``, as does a ``TypeError``/``ValueError``
from the service. Core stays provider-agnostic -- no
provider SDK, field, or name appears here.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError

from messaging.dispatch import send_due_reminders


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

    def handle(self, *args, **options):
        hours = options["hours"]
        if hours < 0:
            raise CommandError(
                f"Invalid --hours {hours!r}; expected 0 or more."
            )
        try:
            summary = send_due_reminders(
                within=timedelta(hours=hours)
            )
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
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
