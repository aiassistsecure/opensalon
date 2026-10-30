"""Deliver due appointment SMS reminders via the SMS adapter.

Usage:
    python manage.py send_sms_reminders [--hours 24]

Sends, through the configured provider-agnostic SMS adapter
(``MESSAGING_SMS_ADAPTER``), to appointments starting within
the window whose clients opted in to SMS -- see
``messaging.sms_reminders`` for the exact gates. Output is
counts only: no client names or contact details are printed.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand

from messaging.sms_reminders import send_due_sms_reminders


class Command(BaseCommand):
    help = "Send due appointment reminder SMS messages to opted-in clients."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours", type=int, default=24,
            help="Remind appointments starting within this many hours.",
        )

    def handle(self, *args, **options):
        summary = send_due_sms_reminders(
            within=timedelta(hours=options["hours"])
        )
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
