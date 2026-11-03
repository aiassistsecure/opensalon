"""Copy one staff member's services to another (the matrix).

Usage:
    python manage.py copy_member_services --source-member-id ID
        --target-member-id ID [--dry-run]
    python manage.py copy_member_services
        --source-member-external-id EXT
        --target-member-external-id EXT [--dry-run]

Thin wrapper around
:func:`team.capabilities.copy_member_services`: source and
target are resolved by id or external_id, scoped to ONE salon
(the target must belong to the source's salon), then passed
to the service verbatim -- the matrix written is the one the
team page's "copy another stylist" action writes, so command
and page can never disagree. The target's services become
the source's effective set.

With ``--dry-run`` nothing is written: the command resolves
both members, reads the would-land effective set via
:func:`team.capabilities.performer_map`, prints it, and
returns before the writer runs -- no write at all, so the
preview is safe on every backend (NEDB does not roll back
transaction writes).

Invalid input -- an unknown member, an out-of-salon target,
or giving both id forms for one member -- raises
``CommandError`` and nothing is written. Backend only.
"""
from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Service
from team.capabilities import copy_member_services, performer_map
from team.models import StaffMember


def _resolve_member(options, prefix, salon=None):
    member_id = options.get(f"{prefix}_member_id")
    external = options.get(f"{prefix}_member_external_id")
    if isinstance(external, str):
        external = external.strip()
    if member_id is not None and external:
        raise CommandError(
            f"Give only one of --{prefix}-member-id / "
            f"--{prefix}-member-external-id.")
    if member_id is not None:
        try:
            member = StaffMember.objects.get(pk=member_id)
        except StaffMember.DoesNotExist:
            raise CommandError(
                f"No staff member with id {member_id}.") from None
        if salon is not None and member.salon_id != salon.pk:
            raise CommandError(
                f"Staff member {member_id} is not in the "
                f"source member's salon.")
        return member
    if external:
        queryset = StaffMember.objects.filter(external_id=external)
        if salon is not None:
            queryset = queryset.filter(salon=salon)
        member = queryset.first()
        if member is None:
            scope = " in this salon" if salon is not None else ""
            raise CommandError(
                f"No staff member with external_id "
                f"{external!r}{scope}.")
        if salon is None and queryset.count() > 1:
            raise CommandError(
                f"Multiple staff members with external_id "
                f"{external!r}.")
        return member
    raise CommandError(
        f"Provide --{prefix}-member-id or "
        f"--{prefix}-member-external-id.")


def _effective_service_ids(source):
    effective = performer_map(source.salon)
    return {
        service_id
        for service_id, ids in effective.items()
        if source.pk in ids
    }


def _describe(source, target, wanted, total):
    return (f"StaffService source_member={source} "
            f"source_member_id={source.pk} "
            f"target_member={target} "
            f"target_member_id={target.pk} "
            f"service_ids={sorted(wanted)} "
            f"enabled={len(wanted)} of {total} services")


class Command(BaseCommand):
    help = ("Copy one staff member's services to another: "
            "the target's capability rows are materialised "
            "with exactly the source's effective services "
            "enabled.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-member-id", type=int, default=None,
            help="Id of the staff member to copy services from.")
        parser.add_argument(
            "--source-member-external-id", default="",
            help="External id of the source member (alternative "
                 "to --source-member-id).")
        parser.add_argument(
            "--target-member-id", type=int, default=None,
            help="Id of the staff member to copy services to; "
                 "must belong to the source member's salon.")
        parser.add_argument(
            "--target-member-external-id", default="",
            help="External id of the target member, scoped to "
                 "the source member's salon (alternative to "
                 "--target-member-id).")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: print the effective service "
                 "list that would land on the target, write "
                 "nothing.")

    def handle(self, *args, **options):
        source = _resolve_member(options, "source")
        target = _resolve_member(options, "target", salon=source.salon)
        wanted = _effective_service_ids(source)
        total = Service.objects.filter(
            category__salon=source.salon, active=True).count()
        if options.get("dry_run"):
            self.stdout.write(
                f"Dry run: would copy "
                f"{_describe(source, target, wanted, total)} "
                f"-- no rows written.")
            return
        copy_member_services(source, target)
        self.stdout.write(
            f"Copied {_describe(source, target, wanted, total)}.")
