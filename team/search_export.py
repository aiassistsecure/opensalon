"""Staff search CSV export. Backend only, read-only.

Founding rule: anything a salon can enter, it can fully export.
Every row comes from :func:`team.search.search_staff` with the
arguments given here -- no re-implemented matching, scoping,
filters, or ordering; CSV is built from the dict list, so the
formats never disagree. Deliberately excluded: ``pin`` (a
credential) and ``email``. No match: ``[]`` / header row alone.
"""
import csv
import io

from team.search import search_staff

__all__ = [
    "EXPORT_FIELDNAMES",
    "STAFF_SEARCH_FIELDNAMES",
    "export_staff_search",
    "export_staff_search_csv",
    "export_staff_search_results",
    "export_staff_search_results_csv",
    "staff_search_csv",
]

#: Column / key order shared by the dict and CSV exports.
STAFF_SEARCH_FIELDNAMES = [
    "id",
    "staff_id",
    "salon_id",
    "external_id",
    "display_name",
    "staff_level_id",
    "staff_level_name",
    "active",
    "online_bookable",
]
EXPORT_FIELDNAMES = STAFF_SEARCH_FIELDNAMES


def _record(member):
    level = member.staff_level
    return {
        "id": member.pk,
        "staff_id": member.pk,
        "salon_id": member.salon_id,
        "external_id": member.external_id,
        "display_name": member.display_name,
        "staff_level_id": member.staff_level_id,
        "staff_level_name": level.name if level is not None else "",
        "active": bool(member.active),
        "online_bookable": bool(member.online_bookable),
    }


def export_staff_search_results(
    salon, query=None, active=None, online_bookable=None
):
    """Return ``salon``'s staff matching the criteria as dicts.

    Arguments are exactly those of :func:`team.search.search_staff`
    and are passed through unchanged. Each entry has exactly
    :data:`STAFF_SEARCH_FIELDNAMES` keys, in the service's order
    (display name, then id). No matches exports as ``[]``.
    """
    members = search_staff(
        salon, query, active=active, online_bookable=online_bookable
    )
    return [_record(member) for member in members]


def export_staff_search_results_csv(
    salon, query=None, active=None, online_bookable=None
):
    """Return the same staff search as CSV (header + rows)."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=STAFF_SEARCH_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_staff_search_results(
        salon, query, active=active, online_bookable=online_bookable
    ):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_staff_search = export_staff_search_results
export_staff_search_csv = export_staff_search_results_csv
staff_search_csv = export_staff_search_results_csv
