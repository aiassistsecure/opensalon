"""No-show appointments CSV export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes an appointment.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's no-show appointments
as a CSV string built ON TOP of :mod:`bookings.noshow` — the
definition of a no-show (past, non-cancelled denominator; the
numerator set; salon scoping via both client and staff member;
most-recent-first ordering) is that service's alone and is reused
verbatim via :func:`bookings.noshow.noshow_appointments`; this
module never reimplements its logic, re-queries appointments, or
re-orders rows. Ordering is exactly the service's ordering:
by ``start`` descending, then ``id`` descending.

Columns are exactly the fields carried by the service's listing
dicts:

- ``id``: the appointment's pk.
- ``client_id`` / ``client_name``: the client pk and the name
  already on the client record.
- ``staff_member_id`` / ``staff_name``: the staff member pk and
  display name.
- ``service_id`` / ``service_name``: the linked service pk (empty
  for snapshot-only appointments) and the name as resolved by the
  service (live ``Service.name``, otherwise the stored snapshot).
- ``start`` / ``end``: ISO-8601 strings, as carried by the service.
- ``status``: the ``Appointment.status`` value (``no_show``).

No client contact details (email, phone, address) are included —
the underlying service never carries them.
"""
import csv
import io

from bookings.noshow import noshow_appointments

__all__ = [
    "NOSHOW_EXPORT_FIELDNAMES",
    "export_noshow_csv",
    "noshow_csv",
]

#: Column order of the CSV export — exactly the keys of the
#: dicts returned by :func:`bookings.noshow.noshow_appointments`.
NOSHOW_EXPORT_FIELDNAMES = [
    "id",
    "client_id",
    "client_name",
    "staff_member_id",
    "staff_name",
    "service_id",
    "service_name",
    "start",
    "end",
    "status",
]


def export_noshow_csv(salon, date_from, date_to=None, *, now=None):
    """Return ``salon``'s no-show appointments as a CSV string.

    Accepts exactly the parameters of
    :func:`bookings.noshow.noshow_appointments`, passed through
    unchanged: ``salon``, the inclusive local-date range
    ``date_from`` / ``date_to``, and the keyword-only ``now``
    reference instant for "past".

    Returns:
        A CSV string whose header row is
        :data:`NOSHOW_EXPORT_FIELDNAMES` and whose data rows
        follow the no-show service's ordering exactly. An empty
        result exports as the header row alone. Lines end with
        ``"\\n"``.
    """
    rows = noshow_appointments(salon, date_from, date_to, now=now)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=NOSHOW_EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({
            name: ("" if row[name] is None else row[name])
            for name in NOSHOW_EXPORT_FIELDNAMES
        })
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
noshow_csv = export_noshow_csv
