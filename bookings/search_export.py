"""Appointment search CSV export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes an appointment.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports the results of an appointment
search as a CSV string built ON TOP of :mod:`bookings.search` —
the definition of a search result (salon scoping via both client
and staff member, name/date/staff/status filtering, ordering) is
that service's alone and is reused verbatim via
:func:`bookings.search.search_appointments`; this module never
reimplements its filtering, re-queries appointments, or
re-orders rows. Ordering is exactly the service's ordering:
by ``start``, then ``pk``.

Columns are only fields carried by the search results (which are
``Appointment`` instances):

- ``id``: the appointment's pk.
- ``client``: the client's display name (``str(client)``, i.e.
  ``"First Last"``).
- ``staff``: the staff member's display name.
- ``service_name``: resolved exactly as the search service's
  docstring and the day book resolve it — the live
  ``Service.name`` when a service is linked, otherwise the
  appointment's stored ``service_name`` snapshot, so
  snapshot-only appointments (service FK null) still export
  with their name.
- ``start`` / ``end``: ISO-8601 strings, as stored.
- ``status``: the ``Appointment.status`` value.
- ``origin``: the ``Appointment.origin`` value.
"""
import csv
import io

from bookings.search import search_appointments

__all__ = [
    "SEARCH_EXPORT_FIELDNAMES",
    "export_search_csv",
    "search_csv",
]

#: Column order of the CSV export.
SEARCH_EXPORT_FIELDNAMES = [
    "id",
    "client",
    "staff",
    "service_name",
    "start",
    "end",
    "status",
    "origin",
]


def export_search_csv(
    salon, query=None, date_from=None, date_to=None,
    staff_member=None, status=None,
):
    """Return search results for ``salon`` as a CSV string.

    Accepts exactly the parameters of
    :func:`bookings.search.search_appointments`, passed through
    unchanged: ``salon`` plus the optional ``query``,
    ``date_from``, ``date_to``, ``staff_member``, and ``status``
    filters.

    Returns:
        A CSV string whose header row is
        :data:`SEARCH_EXPORT_FIELDNAMES` and whose data rows
        follow the search service's ordering exactly. An empty
        search exports as the header row alone. Lines end with
        ``"\\n"``.
    """
    appointments = search_appointments(
        salon, query=query, date_from=date_from, date_to=date_to,
        staff_member=staff_member, status=status,
    )
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=SEARCH_EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for appt in appointments:
        writer.writerow({
            "id": appt.pk,
            "client": str(appt.client),
            "staff": appt.staff_member.display_name,
            "service_name": (
                appt.service.name if appt.service else appt.service_name
            ),
            "start": appt.start.isoformat() if appt.start else "",
            "end": appt.end.isoformat() if appt.end else "",
            "status": appt.status,
            "origin": appt.origin,
        })
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
search_csv = export_search_csv
