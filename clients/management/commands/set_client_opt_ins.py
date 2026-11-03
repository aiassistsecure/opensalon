"""Set one client's messaging opt-in flags.

Usage:
    python manage.py set_client_opt_ins --salon-id ID --client-id ID
        [--sms-opt-in true|false] [--email-opt-in true|false]
        [--dry-run]

Thin wrapper around ``clients.optins.update_client_opt_ins`` --
that service is the one source of truth for consent changes;
this command only resolves the salon and client, delegates
verbatim, and reports the result. At least one flag must be
given; an omitted flag is left unchanged, exactly as the
service defines.

With ``--dry-run`` nothing is written: the command prints the
flag changes that WOULD apply (old -> new for each flag whose
requested value differs from the stored value) and returns.
The preview is computed from the client's stored flags and the
requested values only; the real run still delegates to the
service, whose validation decides.

Invalid input -- an unknown salon, a client that does not
belong to the salon, neither flag given, or a service refusal
-- raises ``CommandError`` and nothing is written.

Output names the client and salon by id only -- no client
names or contact details are printed.

Backend only: no views, templates, or UI. No provider concepts.
"""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from clients.models import Client
from clients.optins import update_client_opt_ins
from saloncore.models import Salon

_FIELDS = ("sms_opt_in", "email_opt_in")


def _parse_flag(value):
    """Normalize a flag option to True/False/None."""
    if value is None or type(value) is bool:
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off"):
            return False
    raise CommandError(f"Invalid opt-in value {value!r}; use true or false.")


class Command(BaseCommand):
    help = "Set one client's SMS/email opt-in flags."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon the client belongs to.",
        )
        parser.add_argument(
            "--client-id", type=int, required=True,
            help="ID of the client whose opt-ins to set.",
        )
        parser.add_argument(
            "--sms-opt-in", dest="sms_opt_in", default=None,
            choices=("true", "false"),
            help="Set the SMS opt-in flag (true/false); omitted = unchanged.",
        )
        parser.add_argument(
            "--email-opt-in", dest="email_opt_in", default=None,
            choices=("true", "false"),
            help="Set the email opt-in flag (true/false); omitted = unchanged.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: print the flag changes that would "
                 "apply and write nothing.",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from None
        try:
            client = Client.objects.get(
                pk=options["client_id"], salon=salon
            )
        except Client.DoesNotExist:
            raise CommandError(
                f"No client with id {options['client_id']} "
                f"for salon {options['salon_id']}."
            ) from None

        requested = {
            "sms_opt_in": _parse_flag(options.get("sms_opt_in")),
            "email_opt_in": _parse_flag(options.get("email_opt_in")),
        }
        if all(value is None for value in requested.values()):
            raise CommandError(
                "At least one of --sms-opt-in or --email-opt-in "
                "must be given."
            )

        if options.get("dry_run"):
            changes = [
                (field, getattr(client, field), requested[field])
                for field in _FIELDS
                if requested[field] is not None
                and requested[field] != getattr(client, field)
            ]
            if not changes:
                self.stdout.write(
                    f"set_client_opt_ins dry-run: client_id={client.pk} "
                    f"salon_id={salon.pk} no changes"
                )
            for field, old, new in changes:
                self.stdout.write(
                    f"set_client_opt_ins dry-run: client_id={client.pk} "
                    f"salon_id={salon.pk} would set "
                    f"{field}: {old} -> {new}"
                )
            return

        try:
            result = update_client_opt_ins(salon, client, **requested)
        except ValidationError as exc:
            raise CommandError(str(exc)) from exc
        if not result.changed:
            self.stdout.write(
                f"set_client_opt_ins: client_id={client.pk} "
                f"salon_id={salon.pk} no changes "
                f"sms_opt_in={result.sms_opt_in} "
                f"email_opt_in={result.email_opt_in}"
            )
            return
        for change in result.changes:
            self.stdout.write(
                f"set_client_opt_ins: client_id={client.pk} "
                f"salon_id={salon.pk} set "
                f"{change.field}: {change.old_value} -> {change.new_value}"
            )
