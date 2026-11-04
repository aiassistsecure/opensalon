"""Export a salon's duplicate client candidates as CSV.

Usage:
    python manage.py export_dedupe_candidates --salon-id ID
        [--key-type KEY_TYPE] [--output PATH]

Thin wrapper around
``clients.dedupe_export.export_duplicate_candidates_csv`` --
that service is the one source of truth for the dedupe export
shape; this command only resolves the salon, delegates verbatim
(with the same optional ``key_type`` filter), and routes the CSV
it returns to the ``--output`` file when given
or to stdout otherwise. It never reimplements serialization or
querying.

Key-type semantics are the service's own: ``--key-type`` narrows
the export to groups whose key type exactly matches it
(``email`` / ``phone``) and composes with the salon scope;
without ``--key-type`` the command exports every key type,
exactly as before. Read-only: this selects rows, it merges
nothing.

Backend only: no views, templates, or UI. No provider concepts.
"""
from django.core.management.base import BaseCommand, CommandError

from clients.dedupe_export import export_duplicate_candidates_csv
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Export a salon's duplicate client candidates as CSV."

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
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from None

        try:
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
