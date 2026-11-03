"""Set one staff member's services (the capability matrix column).

Usage:
    python manage.py set_member_services --staff-member-id ID
        --service-id ID [--service-id ID ...] [--dry-run]
    python manage.py set_member_services
        --staff-member-external-id EXT
        --service-external-id EXT [...] [--dry-run]

Thin wrapper around
:func:`team.capabilities.set_member_services`: the member is
resolved by id or external_id, services by id or external_id
(scoped to the member's salon), then passed to the service
verbatim -- the matrix written is the one the team page's
per-stylist services modal writes, so command and page can
never disagree. Naming no service sets the member's list to
empty.

With ``--dry-run`` nothing is written: the command validates
via the validate-only helper
(:func:`team.capabilities.validate_set_member_services`),
prints the list that WOULD apply, and returns before the
writer runs -- no write at all, so the preview is safe on
every backend (NEDB does not roll back transaction writes).

Invalid input -- an unknown member, an unknown or
out-of-salon service, or a service ``ValidationError`` --
raises ``CommandError`` and nothing is written. Backend only.
"""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Service
from team.capabilities import (
    set_member_services, validate_set_member_services,
)
from team.models import StaffMember


def _as_list(value):
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple, set)) else [value]


def _resolve_member(options):
    member_id = options.get("staff_member_id")
    external = options.get("staff_member_external_id")
    if isinstance(external, str):
        external = external.strip()
    if member_id is not None and external:
        raise CommandError(
            "Give only one of --staff-member-id / "
            "--staff-member-external-id.")
    if member_id is not None:
        try:
            return StaffMember.objects.get(pk=member_id)
        except StaffMember.DoesNotExist:
            raise CommandError(
                f"No staff member with id {member_id}.") from None
    if external:
        try:
            return StaffMember.objects.get(external_id=external)
        except StaffMember.DoesNotExist:
            raise CommandError(
                f"No staff member with external_id "
                f"{external!r}.") from None
        except StaffMember.MultipleObjectsReturned:
            raise CommandError(
                f"Multiple staff members with external_id "
                f"{external!r}.") from None
    raise CommandError(
        "Provide --staff-member-id or "
        "--staff-member-external-id.")


def _service_ids(member, options):
    ids = {int(v) for v in _as_list(options.get("service_id"))}
    for external in _as_list(options.get("service_external_id")):
        service = Service.objects.filter(
            category__salon=member.salon, external_id=external).first()
        if service is None:
            raise CommandError(
                f"No service with external_id {external!r} "
                f"in this member's salon.")
        ids.add(service.pk)
    return ids


def _describe(member, wanted, total):
    return (f"StaffService staff_member={member} "
            f"staff_member_id={member.pk} "
            f"service_ids={sorted(wanted)} "
            f"enabled={len(wanted)} of {total} services")


class Command(BaseCommand):
    help = ("Set one staff member's services: materialise "
            "their capability rows with exactly the named "
            "services enabled.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--staff-member-id", type=int, default=None,
            help="Id of the staff member whose services are set.")
        parser.add_argument(
            "--staff-member-external-id", default="",
            help="External id of the staff member (alternative "
                 "to --staff-member-id).")
        parser.add_argument(
            "--service-id", dest="service_id", action="append",
            type=int, default=None,
            help="Id of a service the member performs; repeat "
                 "for each service. Omit all to set an empty "
                 "list.")
        parser.add_argument(
            "--service-external-id", dest="service_external_id",
            action="append", default=None,
            help="External id of a performed service; repeat "
                 "for each service.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: validate without writing, "
                 "print the list that would apply, write nothing.")

    def handle(self, *args, **options):
        member = _resolve_member(options)
        wanted = _service_ids(member, options)
        try:
            wanted = validate_set_member_services(member, wanted)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        total = Service.objects.filter(
            category__salon=member.salon, active=True).count()
        if options.get("dry_run"):
            self.stdout.write(
                f"Dry run: would set "
                f"{_describe(member, wanted, total)} "
                f"-- no rows written.")
            return
        set_member_services(member, wanted)
        self.stdout.write(
            f"Set {_describe(member, wanted, total)}.")
