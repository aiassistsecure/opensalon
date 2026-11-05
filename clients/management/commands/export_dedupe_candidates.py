"""Export a salon's duplicate client candidates as CSV or JSON.

Usage:
    python manage.py export_dedupe_candidates --salon-id ID
        [--key-type KEY_TYPE] [--format json|csv] [--output PATH]

Thin wrapper around ``clients.dedupe_export`` -- that service is
the one source of truth for the dedupe export shape; this command
only resolves the salon, delegates verbatim (with the same
optional ``key_type`` filter), and routes the result to the
``--output`` file when given or to stdout otherwise. For
``--format csv`` (the default) it writes
:func:`clients.dedupe_export.export_duplicate_candidates_csv`'s
CSV string, exactly as before; for ``--format json`` it serialises
the SAME dict rows from
:func:`clients.dedupe_export.export_duplicate_candidates` as JSON
via ``DjangoJSONEncoder``, so the two formats can never disagree.
It never reimplements serialization or querying.

Key-type semantics are the service's own: ``--key-type`` narrows
the export to groups whose key type exactly matches it
(``email`` / ``phone``) and composes with the salon scope;
without ``--key-type`` the command exports every key type,
exactly as before. Read-only: this selects rows, it merges
nothing.

Backend only: no views, templates, or UI. No provider concepts.
"""
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from clients.dedupe_export import (
    export_duplicate_candidates,
    export_duplicate_candidates_csv,
)
from saloncore.models import Salon

_FORMATS = ("json", "csv")


class Command(BaseCommand):
    help = "Export a salon's duplicate client candidates as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon whose duplicate candidates to export.",
        )
        parser.add_argument(
            "--key-type", dest="key_type", default=None,
            help="Key type to filter by (email / phone; "
                 "default: all key types).",
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

        try:
            if fmt == "json":
                rows = export_duplicate_candidates(
                    salon, key_type=options.get("key_type"))
                text = json.dumps(
                    rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_duplicate_candidates_csv(
                    salon, key_type=options.get("key_type"))
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
