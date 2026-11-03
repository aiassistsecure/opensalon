"""Staff capability matrix CSV export service for the team app.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a capability row, a
staff member, or a service.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export.

One source of truth: every row is a stored
:class:`team.models.StaffService` row, verbatim -- this module
does not derive capabilities from the price book, call
:mod:`team.capabilities`, or compute anything new. A service
with no rows exports no rows here, exactly as stored; the
derived / fallback reading of the matrix stays in
``team.capabilities`` and is not this export's business.

Scoping: a salon's matrix is the rows whose staff member
belongs to that salon (``staff_member__salon``), in the model's
own ordering (service, then staff member).

Columns are only fields the row and its stored relations
actually carry: ``id``, ``salon_id`` (the staff member's
salon), ``staff_member_id`` / ``staff_name`` (the member's
``display_name``), ``service_id`` / ``service_name``,
``category_id`` / ``category_name`` (the service's stored
category), and ``enabled`` (the stored boolean).

Deliberately excluded: the staff member's ``pin`` (a
credential) and ``email`` (contact detail), as in the other
team exports. No rows exports as ``[]`` / the header row
alone. Lines end with ``"\\n"``.
"""
import csv
import io

from team.models import StaffService

__all__ = [
    "CAPABILITY_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "capability_matrix_csv",
    "export_capability_matrix",
    "export_capability_matrix_csv",
]

#: Column / key order shared by the dict export and the CSV export.
CAPABILITY_EXPORT_FIELDNAMES = [
    "id",
    "salon_id",
    "staff_member_id",
    "staff_name",
    "service_id",
    "service_name",
    "category_id",
    "category_name",
    "enabled",
]
EXPORT_FIELDNAMES = CAPABILITY_EXPORT_FIELDNAMES


def _record(row):
    return {
        "id": row.pk,
        "salon_id": row.staff_member.salon_id,
        "staff_member_id": row.staff_member_id,
        "staff_name": row.staff_member.display_name,
        "service_id": row.service_id,
        "service_name": row.service.name,
        "category_id": row.service.category_id,
        "category_name": row.service.category.name,
        "enabled": bool(row.enabled),
    }


def export_capability_matrix(salon):
    """Return ``salon``'s capability matrix as a list of dicts.

    Each entry is one stored :class:`team.models.StaffService`
    row of the salon, as a dict with exactly
    :data:`CAPABILITY_EXPORT_FIELDNAMES` keys, in the model's
    ordering (service, then staff member). Read-only.
    """
    rows = (
        StaffService.objects.filter(staff_member__salon=salon)
        .select_related("staff_member", "service", "service__category")
    )
    return [_record(row) for row in rows]


def export_capability_matrix_csv(salon):
    """Return ``salon``'s capability matrix as a CSV string.

    The header row is :data:`CAPABILITY_EXPORT_FIELDNAMES` and
    every data row is rendered from
    :func:`export_capability_matrix` with the same argument, so
    the CSV and the dict export can never disagree. Lines end
    with ``"\\n"``. Read-only.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=CAPABILITY_EXPORT_FIELDNAMES,
        lineterminator="\n",
    )
    writer.writeheader()
    for record in export_capability_matrix(salon):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
capability_matrix_csv = export_capability_matrix_csv
