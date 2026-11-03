"""Set one service's performers (the capability matrix row).

Usage:
    python manage.py set_service_performers --service-id ID
        --staff-member-id ID [--staff-member-id ID ...]
        [--dry-run]
    python manage.py set_service_performers
        --service-external-id EXT
        --staff-member-external-id EXT [...] [--dry-run]

Thin wrapper around
:func:`team.capabilities.set_service_performers`: the service
is resolved by id or external_id, performers by id or
external_id (scoped to the service's salon), then passed to
the service verbatim -- the matrix written is the one the
price book's "Who performs this" modal writes, so command
and page can never disagree. Naming no performer sets the
service's list to empty.

With ``--dry-run`` nothing is written: the command validates
via the validate-only helper
(:func:`team.capabilities.validate_set_service_performers`),
prints the list that WOULD apply, and returns before the
writer runs -- no write at all, so the preview is safe on
every backend (NEDB does not roll back transaction writes).

Invalid input -- an unknown service, an unknown or
out-of-salon performer, or a service ``ValidationError`` --
raises ``CommandError`` and nothing is written. Backend only.
"""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Service
from team.capabilities import (
    set_service_performers, validate_set_service_performers,
)
from team.models import StaffMember


def _as_list(value):
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple, set)) else [value]


def _resolve_service(options):
    service_id = options.get("service_id")
    external = (options.get("service_external_id") or "").strip() \
        if isinstance(options.get("service_external_id"), str) \
        else options.get("service_external_id")
    if service_id is not None and external:
        raise CommandError(
            "Give only one of --service-id / --service-external-id.")
    if service_id is not None:
        try:
            return Service.objects.get(pk=service_id)
        except Service.DoesNotExist:
            raise CommandError(
                f"No service with id {service_id}.") from None
    if external:
        try:
            return Service.objects.get(external_id=external)
        except Service.DoesNotExist:
            raise CommandError(
                f"No service with external_id {external!r}.") from None
        except Service.MultipleObjectsReturned:
            raise CommandError(
                f"Multiple services with external_id "
                f"{external!r}.") from None
    raise CommandError(
        "Provide --service-id or --service-external-id.")


def _performer_ids(service, options):
    ids = {int(v) for v in _as_list(options.get("staff_member_id"))}
    for external in _as_list(options.get("staff_member_external_id")):
        member = StaffMember.objects.filter(
            salon=service.category.salon, external_id=external).first()
        if member is None:
            raise CommandError(
                f"No staff member with external_id {external!r} "
                f"in this service's salon.")
        ids.add(member.pk)
    return ids


def _describe(service, wanted, total):
    return (f"StaffService service={service} "
            f"service_id={service.pk} "
            f"staff_member_ids={sorted(wanted)} "
            f"enabled={len(wanted)} of {total} members")


class Command(BaseCommand):
    help = ("Set one service's performers: materialise its "
            "capability rows with exactly the named members "
            "enabled.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--service-id", type=int, default=None,
            help="Id of the service whose performers are set.")
        parser.add_argument(
            "--service-external-id", default="",
            help="External id of the service (alternative to "
                 "--service-id).")
        parser.add_argument(
            "--staff-member-id", dest="staff_member_id",
            action="append", type=int, default=None,
            help="Id of a member who performs the service; "
                 "repeat for each performer. Omit all to set "
                 "an empty list.")
        parser.add_argument(
            "--staff-member-external-id",
            dest="staff_member_external_id", action="append",
            default=None,
            help="External id of a performing member; repeat "
                 "for each performer.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: validate without writing, "
                 "print the list that would apply, write nothing.")

    def handle(self, *args, **options):
        service = _resolve_service(options)
        wanted = _performer_ids(service, options)
        try:
            wanted = validate_set_service_performers(service, wanted)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        total = StaffMember.objects.filter(
            salon=service.category.salon).count()
        if options.get("dry_run"):
            self.stdout.write(
                f"Dry run: would set "
                f"{_describe(service, wanted, total)} "
                f"-- no rows written.")
            return
        set_service_performers(service, wanted)
        self.stdout.write(
            f"Set {_describe(service, wanted, total)}.")
