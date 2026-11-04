"""Create one client via the clients add_client service.

Usage:
    python manage.py add_client --salon-id ID --first-name TEXT
        --last-name TEXT [--email ADDRESS] [--phone NUMBER]
        [--sms-opt-in] [--email-opt-in] [--inactive] [--dry-run]

Opt-ins default to False and are set only by the explicit
``--sms-opt-in`` / ``--email-opt-in`` flags -- the command
never defaults an opt-in on.

With ``--dry-run`` nothing is written: the command calls the
service's read-only ``validate_add_client`` helper and prints
the client that WOULD be created. The writer is never called,
so the preview is safe on every backend (including NEDB,
where a rolled-back transaction does not undo writes).

Backend only -- no views, templates, or UI. This command is a
thin wrapper around :func:`clients.add_client.add_client`: it
resolves the salon by id, delegates to that service verbatim,
and prints a one-line summary. It adds no creation or
validation logic of its own -- the service alone is the single
source of truth -- so the printed result and the created
client can never disagree.

An unknown salon or a service ``ValueError`` (blank/over-long
name, invalid/over-long email, over-long phone) is surfaced
here as ``CommandError``. Output names the client and salon
by id only -- no names or contact details are printed.
"""
from django.core.management.base import BaseCommand, CommandError

from clients.add_client import add_client, validate_add_client
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Create one client in a salon."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon owning the client.")
        parser.add_argument(
            "--first-name", required=True,
            help="Client first name.")
        parser.add_argument(
            "--last-name", required=True,
            help="Client last name.")
        parser.add_argument(
            "--email", default="",
            help="Optional email address.")
        parser.add_argument(
            "--phone", default="",
            help="Optional phone number.")
        parser.add_argument(
            "--sms-opt-in", action="store_true",
            help="Explicitly set the SMS opt-in (default: off).")
        parser.add_argument(
            "--email-opt-in", action="store_true",
            help="Explicitly set the email opt-in (default: off).")
        parser.add_argument(
            "--inactive", action="store_true",
            help="Create the client inactive (default: active).")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview the client that would be created "
                 "without writing anything.")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        # call_command may pass active= directly; CLI uses --inactive.
        if options.get("active") is not None:
            active = bool(options["active"])
        else:
            active = not options.get("inactive", False)
        kwargs = dict(
            first_name=options["first_name"],
            last_name=options["last_name"],
            email=options.get("email") or "",
            phone=options.get("phone") or "",
            sms_opt_in=bool(options.get("sms_opt_in", False)),
            email_opt_in=bool(options.get("email_opt_in", False)),
            active=active)
        if options.get("dry_run"):
            try:
                cleaned = validate_add_client(salon, **kwargs)
            except (TypeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(
                f"Dry run: would create client in salon {salon.pk}: "
                f"sms_opt_in={cleaned['sms_opt_in']} "
                f"email_opt_in={cleaned['email_opt_in']} "
                f"active={cleaned['active']} "
                f"-- no client written.")
            return
        try:
            client = add_client(salon, **kwargs)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Created client {client.pk} in salon {salon.pk}: "
            f"sms_opt_in={client.sms_opt_in} "
            f"email_opt_in={client.email_opt_in} "
            f"active={client.active}.")
