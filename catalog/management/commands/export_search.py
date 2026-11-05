"""Export a salon's product search results as CSV or JSON.

Usage:
    python manage.py export_search --salon-id ID [--query TEXT]
        [--include-inactive] [--format json|csv] [--output PATH]

Backend only — no views, templates, or UI. This command is a thin
wrapper around :mod:`catalog.search_export`: it resolves the
salon by id and delegates to that service verbatim (with the
same ``query`` and ``include_inactive``). For ``--format csv``
(the default) it writes
:func:`catalog.search_export.export_search_products_csv`'s CSV
string as-is, so the historical CSV output is byte-identical;
for ``--format json`` it serialises the same dict rows from
:func:`catalog.search_export.export_search_products` as JSON
via ``DjangoJSONEncoder``, so the two formats can never
disagree — one source of truth. Output goes to ``--output``
when given, otherwise to stdout. It adds no fields, filtering,
or formatting of its own. Unknown format raises
``CommandError``.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export.
"""
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from catalog.search_export import (
    export_search_products,
    export_search_products_csv,
)
from saloncore.models import Salon

_FORMATS = ("json", "csv")


class Command(BaseCommand):
    help = "Export a salon's product search results as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon whose products to search.",
        )
        parser.add_argument(
            "--query", default=None,
            help="Name substring (case-insensitive) or exact SKU / "
                 "barcode to match (default: no query, which "
                 "matches nothing, exactly as the service defines).",
        )
        parser.add_argument(
            "--include-inactive", action="store_true", default=False,
            help="Include inactive products (default: excluded).",
        )
        parser.add_argument(
            "--format", dest="format", default="csv",
            choices=_FORMATS,
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
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        try:
            if fmt == "json":
                rows = export_search_products(
                    salon, options["query"],
                    include_inactive=options["include_inactive"])
                text = json.dumps(
                    rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_search_products_csv(
                    salon, options["query"],
                    include_inactive=options["include_inactive"])
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8",
                          newline="") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(text, ending="")
