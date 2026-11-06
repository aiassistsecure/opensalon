"""Upcoming appointments CSV/JSON export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes an appointment.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's upcoming appointments
as a list of dict rows (:func:`export_upcoming`) and as a CSV
string (:func:`export_upcoming_csv`) built from that same list,
so the two formats can never disagree. The export is built ON
TOP of :mod:`bookings.upcoming` — the definition of "upcoming"
(window, cancelled exclusion, salon scoping, ordering) is that
service's alone and is reused verbatim via
:func:`bookings.upcoming.upcoming_appointments`; this module
never redefines it, re-queries appointments for membership, or
re-orders rows. Ordering is exactly the service's ordering:
by ``start``, then ``pk``.

Columns are only real ``Appointment`` model fields:

- ``id``: the appointment's pk.
- ``salon_id``: the salon the export was scoped to (appointments
  belong to a salon via both client and staff member — see the
  upcoming service).
- ``client_id`` / ``client_name``: the client pk and its display
  name (``str(client)``), as carried by the service entry.
- ``staff_member_id`` / ``staff_name``: the staff member pk and
  display name, as carried by the service entry.
- ``service_name``: resolved exactly as the service resolves it —
  the live ``Service.name`` when a service is linked, otherwise
  the appointment's stored ``service_name`` snapshot.
- ``start`` / ``end``: ISO-8601 strings, as stored.
- ``status``: the ``Appointment.status`` value (cancelled
  appointments never appear — the service excludes them).
- ``origin``: the ``Appointment.origin`` value. The upcoming
  service's entries do not carry it, so it is read back from the
  model by pk in one query for exactly the ids the service
  returned; it decides nothing about membership or order.
"""
import csv
import io

from bookings.models import Appointment
from bookings.upcoming import DEFAULT_DAYS, upcoming_appointments

__all__ = [
    "UPCOMING_FIELDNAMES",
    "export_upcoming",
    "export_upcoming_rows",
    "export_upcoming_csv",
    "upcoming_csv",
]

#: Column order of the CSV export.
UPCOMING_FIELDNAMES = [
    "id",
    "salon_id",
    "client_id",
    "client_name",
    "staff_member_id",
    "staff_name",
    "service_name",
    "start",
    "end",
    "status",
    "origin",
]


def export_upcoming(salon, start=None, days=DEFAULT_DAYS, **kwargs):
    """Return ``salon``'s upcoming appointments as a list of dicts.

    Args:
        salon: ``saloncore.Salon`` instance to scope to, passed
            through to :func:`bookings.upcoming.upcoming_appointments`.
        start: window start, as accepted by that service
            (defaults to now there).
        days: horizon length in days, as accepted by that service.
        **kwargs: forwarded to that service (e.g. ``horizon_days``,
            ``now``).

    Returns:
        A list of dicts mirroring the CSV rows exactly: keys are
        :data:`UPCOMING_FIELDNAMES` in order, id fields are pks,
        and ``start`` / ``end`` are ISO-8601 strings (``""`` when
        missing). Rows follow the upcoming service's ordering
        exactly. An empty window exports as an empty list.
        Records nothing.
    """
    result = upcoming_appointments(salon, start, days, **kwargs)
    origins = {}
    if result.appointments:
        origins = dict(
            Appointment.objects.filter(
                pk__in=[entry.appointment_id for entry in result.appointments]
            ).values_list("pk", "origin")
        )
    salon_id = result.salon.pk if result.salon is not None else ""
    return [{
        "id": entry.appointment_id,
        "salon_id": salon_id,
        "client_id": entry.client_id,
        "client_name": entry.client_display_name,
        "staff_member_id": entry.staff_member_id,
        "staff_name": entry.staff_display_name,
        "service_name": entry.service_name,
        "start": entry.start.isoformat() if entry.start else "",
        "end": entry.end.isoformat() if entry.end else "",
        "status": entry.status,
        "origin": origins.get(entry.appointment_id, ""),
    } for entry in result.appointments]


def export_upcoming_csv(salon, start=None, days=DEFAULT_DAYS, **kwargs):
    """Return ``salon``'s upcoming appointments as a CSV string.

    Accepts exactly the parameters of :func:`export_upcoming`,
    passed through unchanged. Built from :func:`export_upcoming`
    with the same arguments, so the CSV and dict exports always
    agree.

    Returns:
        A CSV string whose header row is
        :data:`UPCOMING_FIELDNAMES` and whose data rows follow the
        upcoming service's ordering exactly. An empty window
        exports as the header row alone. Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=UPCOMING_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for row in export_upcoming(salon, start, days, **kwargs):
        writer.writerow(row)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_upcoming_rows = export_upcoming
upcoming_csv = export_upcoming_csv
