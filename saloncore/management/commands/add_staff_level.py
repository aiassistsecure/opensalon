"""Create one staff level via the saloncore add_staff_level service.

Usage:
    python manage.py add_staff_level --salon-id ID --name TEXT
        [--sort-order N] [--inactive] [--dry-run]
        [--format text|json]

With ``--format json`` the command prints exactly one JSON
object to stdout carrying the same facts as the text output
(staff level id, name, salon id, sort order, the active flag,
and ``dry_run``; on ``--dry-run`` the id is ``None`` and only
the fields that would be created are carried, exactly as the
text preview shows); no prose lines are printed in json mode.
The default ``--format text`` output is unchanged.

With ``--dry-run`` nothing is written: the command calls the
service's read-only ``validate_add_staff_level`` helper and
prints the level that WOULD be created. The writer is never
called, so the preview is safe on every backend (including
NEDB, where a rolled-back transaction does not undo writes).

Backend only -- no views, templates, or UI. A thin wrapper
around :func:`saloncore.add_staff_level.add_staff_level`: it
resolves the salon by id, delegates all validation to that
service verbatim, and prints a one-line summary.

An unknown salon or a service ``ValueError`` is surfaced
here as ``CommandError``.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from saloncore.add_staff_level import add_staff_level, validate_add_staff_level
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Create one staff level in a salon."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon owning the staff level.")
        parser.add_argument(
            "--name", required=True,
            help="Staff level name.")
        parser.add_argument(
            "--sort-order", type=int, default=0,
            help="Sort order (default 0).")
        parser.add_argument(
            "--inactive", action="store_true",
            help="Create the level inactive (default: active).")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview the level that would be created "
                 "without writing anything.")
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
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        if options.get("active") is not None:
            active = bool(options["active"])
        else:
            active = not options.get("inactive", False)
        kwargs = dict(
            name=options["name"],
            sort_order=options.get("sort_order") or 0,
            active=active)
        if options.get("dry_run"):
            try:
                cleaned = validate_add_staff_level(salon, **kwargs)
            except (TypeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            if fmt == "json":
                self.stdout.write(json.dumps(dict(
                    id=None,
                    name=cleaned["name"],
                    salon_id=salon.pk,
                    sort_order=cleaned["sort_order"],
                    active=cleaned["active"],
                    dry_run=True)))
                return
            self.stdout.write(
                f"Dry run: would create staff level "
                f"{cleaned['name']!r} in salon {salon.pk}: "
                f"sort_order={cleaned['sort_order']} "
                f"active={cleaned['active']} "
                f"-- no staff level written.")
            return
        try:
            level = add_staff_level(salon, **kwargs)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if fmt == "json":
            self.stdout.write(json.dumps(dict(
                id=level.pk,
                name=level.name,
                salon_id=salon.pk,
                sort_order=level.sort_order,
                active=level.active,
                dry_run=False)))
            return
        self.stdout.write(
            f"Created staff level {level.pk}: {level.name!r} "
            f"in salon {salon.pk}: sort_order={level.sort_order} "
            f"active={level.active}.")
