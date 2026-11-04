"""Create one salon via the saloncore add_salon service.

Usage:
    python manage.py add_salon --name TEXT [--timezone ZONE]
        [--currency CODE] [--tagline TEXT] [--logo-url URL]
        [--primary-color #RRGGBB] [--accent-color #RRGGBB]
        [--dry-run]

There is NO salon argument: this command creates the salon
(the tenant root every other command's ``--salon-id`` names).

With ``--dry-run`` nothing is written: the command calls the
service's read-only ``validate_add_salon`` helper and prints
the salon that WOULD be created. The writer is never called,
so the preview is safe on every backend (including NEDB,
where a rolled-back transaction does not undo writes).

Backend only -- no views, templates, or UI. A thin wrapper
around :func:`saloncore.add_salon.add_salon`: it delegates
all validation to that service verbatim and prints a one-line
summary -- no logic of its own.

A service ``ValueError`` (blank/over-long name, unknown
timezone, bad currency, invalid branding) is surfaced here
as ``CommandError``.
"""
from django.core.management.base import BaseCommand, CommandError

from saloncore.add_salon import add_salon, validate_add_salon


class Command(BaseCommand):
    help = "Create one salon (the tenant root record)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--name", required=True,
            help="Salon name.")
        parser.add_argument(
            "--timezone", default=None,
            help="IANA timezone (default: UTC).")
        parser.add_argument(
            "--currency", default=None,
            help="Three-letter currency code (default: USD).")
        parser.add_argument(
            "--tagline", default=None,
            help="Optional salon tagline.")
        parser.add_argument(
            "--logo-url", dest="logo_url", default=None,
            help="Optional logo URL.")
        parser.add_argument(
            "--primary-color", dest="primary_color", default=None,
            help="Optional primary colour #RRGGBB.")
        parser.add_argument(
            "--accent-color", dest="accent_color", default=None,
            help="Optional accent colour #RRGGBB.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview the salon that would be created "
                 "without writing anything.")

    def handle(self, *args, **options):
        kwargs = dict(
            name=options.get("name"),
            timezone=options.get("timezone"),
            currency=options.get("currency"),
            tagline=options.get("tagline"),
            logo_url=options.get("logo_url"),
            primary_color=options.get("primary_color"),
            accent_color=options.get("accent_color"))
        # None = flag omitted: the service supplies the defaults
        # (UTC / USD / blank branding) for None optional fields.
        if options.get("dry_run"):
            try:
                cleaned = validate_add_salon(**kwargs)
            except (TypeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(
                f"Dry run: would create salon {cleaned['name']!r}: "
                f"timezone={cleaned['timezone']} "
                f"currency={cleaned['currency']} "
                f"tagline={cleaned['tagline']!r} "
                f"logo_url={cleaned['logo_url']!r} "
                f"primary_color={cleaned['primary_color']!r} "
                f"accent_color={cleaned['accent_color']!r} "
                f"-- no salon written.")
            return
        try:
            salon = add_salon(**kwargs)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Created salon {salon.pk}: {salon.name!r} "
            f"timezone={salon.timezone} currency={salon.currency} "
            f"tagline={salon.tagline!r} logo_url={salon.logo_url!r} "
            f"primary_color={salon.primary_color!r} "
            f"accent_color={salon.accent_color!r}.")
