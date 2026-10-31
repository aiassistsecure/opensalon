"""Upcoming appointments CSV export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes an appointment.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's upcoming appointments
as a CSV string built ON TOP of :mod:`bookings.upcoming` — the
definition of "upcoming" (window, cancelled exclusion, salon
scoping, ordering) is that service's alone and is reused verbatim
via :func:`bookings.upcoming.upcoming_appointments`; this module
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


def export_upcoming_csv(salon, start=None, days=DEFAULT_DAYS, **kwargs):
    """Return ``salon``'s upcoming appointments as a CSV string.

    Args:
        salon: ``saloncore.Salon`` instance to scope to, passed
            through to :func:`bookings.upcoming.upcoming_appointments`.
        start: window start, as accepted by that service
            (defaults to now there).
        days: horizon length in days, as accepted by that service.
        **kwargs: forwarded to that service (e.g. ``horizon_days``,
            ``now``).

    Returns:
        A CSV string whose header row is
        :data:`UPCOMING_FIELDNAMES` and whose data rows follow the
        upcoming service's ordering exactly. An empty window
        exports as the header row alone. Lines end with ``"\\n"``.
    """
    result = upcoming_appointments(salon, start, days, **kwargs)
    origins = {}
    if result.appointments:
        origins = dict(
            Appointment.objects.filter(
                pk__in=[entry.appointment_id for entry in result.appointments]
            ).values_list("pk", "origin")
        )
    salon_id = result.salon.pk if result.salon is not None else None
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=UPCOMING_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for entry in result.appointments:
        writer.writerow({
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
        })
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
upcoming_csv = export_upcoming_csv
