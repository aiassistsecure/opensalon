"""Who performs what: the capability rule.

One rule, read by availability, by the booking write path, and by
the pages that present staff for a service:

1. If any :class:`team.models.StaffService` row exists for the
   service, the rows are the whole truth — a member performs the
   service exactly when their row is enabled (no row, no service).
   A salon that curates a service owns its whole list.
2. Otherwise the price book speaks: a member performs the service
   when their staff level carries an active price for it. This is
   how the salon's imported book already behaves, so an untouched
   salon sees no change.
3. A service with no rows and no prices at all is *open* — there
   is no signal to seed from, so nobody is restricted.

:func:`seed_salon_capabilities` materialises rule 2 (and the open
case, as all-enabled) into explicit rows, so a salon can start
editing from the truth its book already states. Seeding never
flips an existing row: once the salon has spoken, its word stands.
"""

from django.core.exceptions import ValidationError

from saloncore.models import Service, ServicePrice
from team.models import StaffMember, StaffService


def performer_ids(salon, service):
    """Member ids who perform ``service`` at ``salon``.

    Returns ``None`` when the service is open (rule 3): no rows
    and no prices, so no restriction applies.
    """
    rows = StaffService.objects.filter(service=service)
    if rows.exists():
        return set(
            rows.filter(enabled=True).values_list("staff_member_id", flat=True)
        )
    level_ids = list(
        ServicePrice.objects.filter(service=service, active=True).values_list(
            "staff_level_id", flat=True
        )
    )
    if not level_ids:
        return None
    return set(
        StaffMember.objects.filter(
            salon=salon, staff_level_id__in=level_ids
        ).values_list("pk", flat=True)
    )


def performs(staff_member, service):
    """True when ``staff_member`` performs ``service``."""
    ids = performer_ids(staff_member.salon, service)
    return ids is None or staff_member.pk in ids


def performer_map(salon):
    """Every active service's performers at ``salon``, in three
    queries: ``{service_id: {member_id, ...}}`` over ACTIVE
    members. The pages read this — an open service maps to the
    full active team, so callers never handle the None case
    that :func:`performer_ids` returns."""
    members = list(StaffMember.objects.filter(salon=salon, active=True))
    member_ids = {member.pk for member in members}
    by_level = {}
    for member in members:
        if member.staff_level_id is not None:
            by_level.setdefault(member.staff_level_id, set()).add(member.pk)
    rows = {}
    for row in StaffService.objects.filter(staff_member__salon=salon):
        rows.setdefault(row.service_id, {})[row.staff_member_id] = row.enabled
    prices = {}
    for price in ServicePrice.objects.filter(
        service__category__salon=salon, active=True
    ):
        prices.setdefault(price.service_id, set()).add(price.staff_level_id)
    result = {}
    for service in Service.objects.filter(category__salon=salon, active=True):
        if service.pk in rows:
            result[service.pk] = {
                member_id
                for member_id, on in rows[service.pk].items()
                if on
            } & member_ids
        elif service.pk in prices:
            ids = set()
            for level_id in prices[service.pk]:
                ids |= by_level.get(level_id, set())
            result[service.pk] = ids
        else:
            result[service.pk] = set(member_ids)
    return result


def set_service_performers(service, member_ids):
    """Materialise the matrix for one service: every member of
    the salon gets a row, enabled exactly for ``member_ids``.
    From the save on, rows rule this service."""
    wanted = set(member_ids)
    for member in StaffMember.objects.filter(salon=service.category.salon):
        StaffService.objects.update_or_create(
            staff_member=member,
            service=service,
            defaults={"enabled": member.pk in wanted},
        )


def _complete_service_rows(service):
    """Make one service's grid complete without changing its
    effective truth: a service with no rows gets a row for
    every member of the salon, enabled exactly as the rule
    derives today. Writers keep the invariant that a service's
    rows are either absent (the price book speaks) or complete
    (rows rule) — never a partial grid that would silently
    drop a bystander when the service flips to ruled."""
    if StaffService.objects.filter(service=service).exists():
        return
    salon = service.category.salon
    ids = performer_ids(salon, service)
    for member in StaffMember.objects.filter(salon=salon):
        StaffService.objects.create(
            staff_member=member,
            service=service,
            enabled=ids is None or member.pk in ids,
        )


def set_member_services(member, service_ids):
    """Materialise the matrix for one member: every active
    service of the salon gets a row, enabled exactly for
    ``service_ids``. Each service's grid is completed first,
    so ruling one member's list never changes a colleague's
    effective set."""
    wanted = set(service_ids)
    services = Service.objects.filter(
        category__salon=member.salon, active=True
    )
    for service in services:
        _complete_service_rows(service)
        StaffService.objects.update_or_create(
            staff_member=member,
            service=service,
            defaults={"enabled": service.pk in wanted},
        )


def validate_set_service_performers(service, member_ids):
    """Validate a :func:`set_service_performers` call, writing
    nothing. Returns the wanted member-id set; raises
    ``ValidationError`` when the service is missing or any id
    is not a member of the service's salon. Reads only, so it
    is safe for ``--dry-run`` previews on every backend
    (including NEDB, where rollback does not undo writes).
    The writer itself is unchanged."""
    if service is None or getattr(service, "pk", None) is None:
        raise ValidationError("A service is required.")
    wanted = set(member_ids or ())
    known = set(
        StaffMember.objects.filter(
            salon_id=service.category.salon_id
        ).values_list("pk", flat=True)
    )
    unknown = wanted - known
    if unknown:
        raise ValidationError(
            "Unknown staff member id(s) for this salon: "
            + ", ".join(str(pk) for pk in sorted(unknown))
            + "."
        )
    return wanted


def validate_set_member_services(member, service_ids):
    """Validate a :func:`set_member_services` call, writing
    nothing. Returns the wanted service-id set; raises
    ``ValidationError`` when the member is missing or any id
    is not a service of the member's salon. Reads only -- see
    :func:`validate_set_service_performers`."""
    if member is None or getattr(member, "pk", None) is None:
        raise ValidationError("A staff member is required.")
    wanted = set(service_ids or ())
    known = set(
        Service.objects.filter(
            category__salon_id=member.salon_id
        ).values_list("pk", flat=True)
    )
    unknown = wanted - known
    if unknown:
        raise ValidationError(
            "Unknown service id(s) for this salon: "
            + ", ".join(str(pk) for pk in sorted(unknown))
            + "."
        )
    return wanted


def copy_member_services(source, target):
    """``target``'s services become ``source``'s effective set —
    the modal's "make hers mirror hers" in one call."""
    effective = performer_map(source.salon)
    set_member_services(
        target,
        {
            service_id
            for service_id, ids in effective.items()
            if source.pk in ids
        },
    )


def _seed_plan(salon):
    """(members, candidates) the seed would create for ``salon``.

    Each candidate is a ``(member, service, enabled)`` triple for a
    (member, active service) pair that lacks a row. Read-only: both
    the real seed and its dry-run preview are built on this plan,
    so their counts can never disagree.
    """
    members = list(StaffMember.objects.filter(salon=salon))
    existing = set(
        StaffService.objects.filter(staff_member__salon=salon).values_list(
            "staff_member_id", "service_id"
        )
    )
    priced = set(
        ServicePrice.objects.filter(
            service__category__salon=salon, active=True
        ).values_list("service_id", "staff_level_id")
    )
    priced_services = {service_id for service_id, _ in priced}
    candidates = []
    for service in Service.objects.filter(category__salon=salon, active=True):
        for member in members:
            if (member.pk, service.pk) in existing:
                continue
            on = service.pk not in priced_services or (
                member.staff_level_id is not None
                and (service.pk, member.staff_level_id) in priced
            )
            candidates.append((member, service, on))
    return members, candidates


def seed_salon_capabilities(salon):
    """Materialise the derived matrix for ``salon`` into rows.

    Creates a :class:`StaffService` row for every (member, active
    service) pair that lacks one, with ``enabled`` set to what the
    price book derives today (an unpriced service seeds everyone
    enabled — the open case, made explicit). Existing rows are
    never touched. Returns ``(created, enabled)`` counts.
    """
    _members, candidates = _seed_plan(salon)
    created = enabled = 0
    for member, service, on in candidates:
        StaffService.objects.create(
            staff_member=member, service=service, enabled=on
        )
        created += 1
        if on:
            enabled += 1
    return created, enabled


def preview_seed_salon_capabilities(salon):
    """Dry-run twin of :func:`seed_salon_capabilities`: write nothing.

    Returns ``(would_create, would_enable, per_member)`` where
    ``per_member`` maps every member id of the salon to its own
    ``(would_create, would_enable)`` counts (zeroes included).
    """
    members, candidates = _seed_plan(salon)
    per_member = {member.pk: [0, 0] for member in members}
    for member, _service, on in candidates:
        per_member[member.pk][0] += 1
        if on:
            per_member[member.pk][1] += 1
    would_create = sum(counts[0] for counts in per_member.values())
    would_enable = sum(counts[1] for counts in per_member.values())
    return (
        would_create,
        would_enable,
        {pk: tuple(counts) for pk, counts in per_member.items()},
    )
