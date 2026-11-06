"""No-show appointments CSV/JSON export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes an appointment.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's no-show appointments
as a list of dict rows (:func:`export_noshow`) and as a CSV string
(:func:`export_noshow_csv`) built from that same list, so the two
formats can never disagree. The export is built ON TOP of
:mod:`bookings.noshow` — the
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
    "export_noshow",
    "export_noshow_rows",
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


def export_noshow(salon, date_from, date_to=None, *, now=None):
    """Return ``salon``'s no-show appointments as a list of dicts.

    Accepts exactly the parameters of
    :func:`bookings.noshow.noshow_appointments`, passed through
    unchanged: ``salon``, the inclusive local-date range
    ``date_from`` / ``date_to``, and the keyword-only ``now``
    reference instant for "past".

    Every row mirrors a CSV row exactly: keys are
    :data:`NOSHOW_EXPORT_FIELDNAMES` in order, and a ``None``
    value from the service (e.g. ``service_id`` for snapshot-only
    appointments, or an unset ``start`` / ``end``) renders as
    ``""`` -- exactly as the CSV writer rendered it historically.
    Rows follow the no-show service's ordering exactly. An empty
    result exports as an empty list. Records nothing.
    """
    rows = noshow_appointments(salon, date_from, date_to, now=now)
    return [{
        name: ("" if row[name] is None else row[name])
        for name in NOSHOW_EXPORT_FIELDNAMES
    } for row in rows]


def export_noshow_csv(salon, date_from, date_to=None, *, now=None):
    """Return ``salon``'s no-show appointments as a CSV string.

    Accepts exactly the parameters of
    :func:`bookings.noshow.noshow_appointments`, passed through
    unchanged: ``salon``, the inclusive local-date range
    ``date_from`` / ``date_to``, and the keyword-only ``now``
    reference instant for "past". Built from
    :func:`export_noshow` with the same arguments, so the CSV
    and dict exports always agree.

    Returns:
        A CSV string whose header row is
        :data:`NOSHOW_EXPORT_FIELDNAMES` and whose data rows
        follow the no-show service's ordering exactly. An empty
        result exports as the header row alone. Lines end with
        ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=NOSHOW_EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for row in export_noshow(salon, date_from, date_to, now=now):
        writer.writerow(row)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_noshow_rows = export_noshow
noshow_csv = export_noshow_csv
