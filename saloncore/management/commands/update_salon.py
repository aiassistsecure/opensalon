"""Update one salon's profile and branding fields.

Usage:
    python manage.py update_salon --salon-id ID [--name TEXT]
        [--timezone ZONE] [--currency CODE] [--tagline TEXT]
        [--logo-url URL] [--primary-color #RRGGBB]
        [--accent-color #RRGGBB] [--dry-run] [--format text|json]

With ``--format json`` the command prints exactly one JSON
object to stdout carrying the same facts as the text output
(salon id, the resulting salon fields, the list of fields
that changed, and ``dry_run``; on ``--dry-run`` only the
fields that would change are carried, with their would-be
values, exactly as the text preview shows); no prose lines
are printed in json mode. The default ``--format text``
output is unchanged.

Thin wrapper around ``saloncore.update_salon.update_salon``:
resolves the salon by id, delegates verbatim, reports by id and
field name only. At least one field required; omitted =
unchanged, "" clears tagline / logo_url / colours. ``--dry-run``
calls only the read-only validate twin (no writer, no rollback
relied on -- NEDB-safe). Invalid input raises ``CommandError``,
nothing written. Backend only.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon
from saloncore.update_salon import update_salon, validate_update_salon

_FIELDS = ("name", "timezone", "currency", "tagline", "logo_url",
           "primary_color", "accent_color")


class Command(BaseCommand):
    help = "Update one salon's profile and branding fields."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon to update.")
        parser.add_argument(
            "--name", dest="name", default=None,
            help="New salon name; omitted = unchanged.")
        parser.add_argument(
            "--timezone", dest="timezone", default=None,
            help="New IANA timezone; omitted = unchanged.")
        parser.add_argument(
            "--currency", dest="currency", default=None,
            help="New three-letter currency code; omitted = unchanged.")
        parser.add_argument(
            "--tagline", dest="tagline", default=None,
            help="New tagline (empty string clears); omitted = unchanged.")
        parser.add_argument(
            "--logo-url", dest="logo_url", default=None,
            help="New logo URL (empty string clears); omitted = unchanged.")
        parser.add_argument(
            "--primary-color", dest="primary_color", default=None,
            help="New primary colour #RRGGBB (empty clears); "
                 "omitted = unchanged.")
        parser.add_argument(
            "--accent-color", dest="accent_color", default=None,
            help="New accent colour #RRGGBB (empty clears); "
                 "omitted = unchanged.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: validate, print fields that would "
                 "change, and write nothing.")
        parser.add_argument(
            "--format", dest="format", default="text",
            choices=["text", "json"],
            help="Output format: text (default) or json.")

    def handle(self, *args, **options):
        fmt = options.get("format") or "text"
        if fmt not in ("text", "json"):
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'text' or 'json'.")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None

        requested = {field: options.get(field) for field in _FIELDS}
        if all(value is None for value in requested.values()):
            raise CommandError(
                "At least one field must be given: --name, "
                "--timezone, --currency, --tagline, --logo-url, "
                "--primary-color, or --accent-color.")

        if options.get("dry_run"):
            try:
                cleaned = validate_update_salon(salon, **requested)
            except (TypeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            changes = [
                field for field in _FIELDS
                if field in cleaned
                and cleaned[field] != getattr(salon, field)
            ]
            if fmt == "json":
                payload = dict(salon_id=salon.pk)
                for field in changes:
                    payload[field] = cleaned[field]
                payload["changed_fields"] = changes
                payload["dry_run"] = True
                self.stdout.write(json.dumps(payload))
                return
            if not changes:
                self.stdout.write(
                    f"update_salon dry-run: salon_id={salon.pk} no changes")
                return
            for field in changes:
                self.stdout.write(
                    f"update_salon dry-run: salon_id={salon.pk} "
                    f"would set {field}")
            return

        try:
            result = update_salon(salon, **requested)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if fmt == "json":
            self.stdout.write(json.dumps(dict(
                salon_id=salon.pk,
                name=result.name,
                timezone=result.timezone,
                currency=result.currency,
                tagline=result.tagline,
                logo_url=result.logo_url,
                primary_color=result.primary_color,
                accent_color=result.accent_color,
                changed_fields=list(result.changed_fields),
                dry_run=False)))
            return
        if not result.changed:
            self.stdout.write(f"update_salon: salon_id={salon.pk} no changes")
            return
        for change in result.changes:
            self.stdout.write(
                f"update_salon: salon_id={salon.pk} "
                f"set {change.field}")
