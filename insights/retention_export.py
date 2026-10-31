"""Repeat-visit retention CSV export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes an appointment.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's repeat-visit
retention report as a CSV string built ON TOP of
:mod:`insights.retention` — the definition of retention (completed
appointments only as visits, salon scoping via staff member,
inclusive window judged in the salon's timezone, active / repeat
client counts and rates) is that service's alone and is reused
verbatim via :func:`insights.retention.repeat_visit_retention`;
this module never recomputes retention, re-queries appointments,
or invents fields.

The service returns a single :class:`insights.retention.Retention`
for the window, so the export is exactly one data row.

Columns are only fields the service's result actually carries:

- ``start_date``: the result's inclusive window start (ISO date).
- ``end_date``: the result's inclusive window end (ISO date).
- ``active_clients``: the result's active client count.
- ``repeat_clients``: the result's repeat client count.
- ``total_visits``: the result's total visit count.
- ``repeat_rate``: the result's repeat rate, as carried.
- ``average_visits_per_active_client``: the result's average
  visits per active client, as carried.
"""
import csv
import io

from insights.retention import repeat_visit_retention

__all__ = [
    "RETENTION_FIELDNAMES",
    "RETENTION_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_retention_csv",
    "retention_csv",
]

#: Column order of the CSV export.
RETENTION_FIELDNAMES = [
    "start_date",
    "end_date",
    "active_clients",
    "repeat_clients",
    "total_visits",
    "repeat_rate",
    "average_visits_per_active_client",
]

RETENTION_EXPORT_FIELDNAMES = RETENTION_FIELDNAMES
EXPORT_FIELDNAMES = RETENTION_FIELDNAMES


def export_retention_csv(salon, start=None, end=None, **kwargs):
    """Return ``salon``'s repeat-visit retention as a CSV string.

    Args:
        salon: ``saloncore.Salon`` instance to scope to, passed
            through to
            :func:`insights.retention.repeat_visit_retention`.
        start: inclusive window start, as accepted by that service.
        end: inclusive window end, as accepted by that service.
        **kwargs: forwarded to that service (including its
            ``start_date`` / ``end_date`` and ``since`` / ``until``
            keyword aliases).

    Returns:
        A CSV string whose header row is
        :data:`RETENTION_FIELDNAMES` and whose single data row
        matches the retention service's result exactly. A window
        with no visits exports as that single zero row, exactly
        as the service returns it. Lines end with ``"\\n"``.
    """
    result = repeat_visit_retention(salon, start, end, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=RETENTION_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    writer.writerow({
        "start_date": result.start_date.isoformat(),
        "end_date": result.end_date.isoformat(),
        "active_clients": result.active_clients,
        "repeat_clients": result.repeat_clients,
        "total_visits": result.total_visits,
        "repeat_rate": result.repeat_rate,
        "average_visits_per_active_client": (
            result.average_visits_per_active_client
        ),
    })
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
retention_csv = export_retention_csv
