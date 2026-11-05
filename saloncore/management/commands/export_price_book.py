"""Export a salon's full price book as CSV or JSON.

Usage:
    python manage.py export_price_book --salon-id ID
        [--service-id ID] [--category-id ID]
        [--format json|csv] [--output PATH]

Thin wrapper around :mod:`saloncore.price_book_export` -- that
service is the one source of truth for the price book export;
this command only resolves the salon, delegates to it verbatim,
and writes what it returns (to ``--output`` when given,
otherwise to stdout). For ``--format csv`` (the default) it
writes :func:`saloncore.price_book_export.export_price_book_csv`'s
CSV string, exactly as before; for ``--format json`` it
serialises the SAME dict rows from
:func:`saloncore.price_book_export.export_price_book` as JSON.
Backend only; read-only.

With ``--service-id`` the export is narrowed to that one
service's rows: the service is resolved by id within the
salon (via its category's salon, the app's service scoping
convention; a service from another salon, or an unknown id, is
a ``CommandError``), and the resolved service is passed to the
service as its optional ``service`` argument. Without
``--service-id`` the command exports the whole salon, exactly
as before.

With ``--category-id`` the export is narrowed to that one
category's rows: the category is resolved by id within the
salon (a category from another salon, or an unknown id, is a
``CommandError``), and the resolved category is passed to the
service as its optional ``category`` argument. Without
``--category-id`` the command exports the whole salon, exactly
as before. ``--category-id`` composes with ``--service-id``
(AND): a service outside the category exports as the header
row alone (CSV) or an empty list (JSON). Both filters compose
with ``--format`` exactly as they do for CSV.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon, Service, ServiceCategory
from saloncore.price_book_export import (
    export_price_book,
    export_price_book_csv,
)

_FORMATS = ("json", "csv")


class Command(BaseCommand):
    help = "Export a salon's full price book as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose price book to export.",
        )
        parser.add_argument(
            "--service-id", type=int, default=None,
            help="Id of the service (in the salon) whose price "
                 "book rows to export (default: all services).",
        )
        parser.add_argument(
            "--category-id", type=int, default=None,
            help="Id of the category (in the salon) whose price "
                 "book rows to export (default: all categories).",
        )
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path of the export file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from None
        service = None
        if options.get("service_id") is not None:
            try:
                service = Service.objects.get(
                    pk=options["service_id"], category__salon=salon)
            except Service.DoesNotExist:
                raise CommandError(
                    f"No service with id {options['service_id']} "
                    f"for salon {options['salon_id']}."
                ) from None
        category = None
        if options.get("category_id") is not None:
            try:
                category = ServiceCategory.objects.get(
                    pk=options["category_id"], salon=salon)
            except ServiceCategory.DoesNotExist:
                raise CommandError(
                    f"No category with id {options['category_id']} "
                    f"for salon {options['salon_id']}."
                ) from None
        if fmt == "json":
            rows = export_price_book(
                salon, service=service, category=category)
            text = json.dumps(rows, indent=2) + "\n"
        else:
            text = export_price_book_csv(
                salon, service=service, category=category)
        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(text, ending="")
