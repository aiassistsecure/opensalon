"""Deliver due appointment email reminders via the salon's SMTP.

Usage:
    python manage.py send_email_reminders [--hours 24]

Sends, over Django's standard mail framework (the salon's own
``EMAIL_*`` SMTP settings), to appointments starting within the
window whose clients opted in to email -- see
``messaging.email_reminders`` for the exact gates. Output is
counts only: no client names or contact details are printed.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand

from messaging.email_reminders import send_due_email_reminders


class Command(BaseCommand):
    help = "Send due appointment reminder emails to opted-in clients."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours", type=int, default=24,
            help="Remind appointments starting within this many hours.",
        )

    def handle(self, *args, **options):
        summary = send_due_email_reminders(
            within=timedelta(hours=options["hours"])
        )
        self.stdout.write(
            "Email reminders: {sent} sent, {skipped} skipped "
            "({opt} not opted in, {missing} missing email, "
            "{status} not remindable status).".format(
                sent=summary.sent,
                skipped=summary.skipped,
                opt=summary.skipped_not_opted_in,
                missing=summary.skipped_missing_email,
                status=summary.skipped_status,
            )
        )
