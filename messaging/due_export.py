"""Read-only due-reminder CSV export (L8-M12).

Backend only -- no views, templates, or UI. Read-only: nothing
is sent, dispatched, stored, or mutated here, and no provider
adapter is touched.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module renders the existing due-reminder
listing (:mod:`messaging.due`) as a plain list of dicts
(:func:`export_due_reminders`) and as a CSV string
(:func:`export_due_reminders_csv`) built from that same list,
so the two formats can never disagree -- one source of truth.

Listing -- reused verbatim, never reimplemented: membership,
window, ordering, and per-channel eligibility come exactly
from :func:`messaging.due.due_reminders`. This module never
re-checks opt-ins, contact details, or statuses itself:

* one row per appointment per ELIGIBLE channel, in the
  listing's channel order (``DueAppointment.eligible_channels``,
  email then SMS). A client opted out of a channel -- or
  missing that channel's contact detail, or on a
  non-remindable status -- produces NO row for that channel:
  per-channel opt-in rules carry through exactly, so email
  opt-in never produces an SMS row and vice versa.
* an appointment eligible on no channel produces no rows;
  an appointment outside the ``[start, end]`` window (not
  yet due, or past it) produces no rows -- the listing's
  window filter decides, not this module.

Salon scoping -- the one filter this export adds on top: only
appointments whose client belongs to ``salon`` export
(``appointment.client.salon``, the scoping the send services
use via ``client__salon``). A missing salon exports as ``[]``
/ a header-only CSV. A reversed window raises ``ValueError``,
exactly as the listing does.

Columns -- exactly the listing's actual fields, no invented
fields:

* ``salon_id`` -- the salon the export was scoped to;
* ``appointment_id`` -- ``DueAppointment.appointment`` pk;
* ``client_id`` / ``client_name`` -- the appointment's client
  pk and display name (``str(client)``);
* ``channel`` -- one eligible channel from the listing;
* ``due_at`` -- the appointment's ``start`` (its due time in
  the listing's window), ISO-8601.

Ordering is deterministic: the listing's ordering (by
appointment start), then its channel order. Lines end
``"\\n"``.
"""
import csv
import io

from .due import due_reminders

__all__ = [
    "DUE_EXPORT_FIELDNAMES",
    "due_export_csv",
    "export_due_reminders",
    "export_due_reminders_csv",
]

#: Column / key order shared by the dict and CSV exports.
DUE_EXPORT_FIELDNAMES = [
    "salon_id", "appointment_id", "client_id", "client_name",
    "channel", "due_at",
]


def _salon_id(salon):
    if salon is None:
        return None
    return salon.pk if hasattr(salon, "pk") else salon


def export_due_reminders(salon, start, end, appointments=None):
    """Return due reminders for ``salon`` as dict rows.

    Rows are rendered verbatim from
    :func:`messaging.due.due_reminders` over ``[start, end]``:
    one dict per appointment per eligible channel, listing
    order then channel order, scoped to ``salon`` via the
    appointment's client. A missing salon returns ``[]``; a
    reversed window raises ``ValueError`` as the listing
    does. Read-only.
    """
    salon_id = _salon_id(salon)
    if salon_id is None:
        return []
    rows = []
    for entry in due_reminders(start, end, appointments=appointments):
        appointment = entry.appointment
        if appointment.client.salon_id != salon_id:
            continue
        for channel in entry.eligible_channels:
            rows.append({
                "salon_id": salon_id,
                "appointment_id": appointment.pk,
                "client_id": appointment.client_id,
                "client_name": str(appointment.client),
                "channel": channel,
                "due_at": (
                    appointment.start.isoformat()
                    if appointment.start else ""
                ),
            })
    return rows


def export_due_reminders_csv(salon, start, end, appointments=None):
    """Return :func:`export_due_reminders` as CSV text.

    The header row is :data:`DUE_EXPORT_FIELDNAMES` and every
    data row comes from :func:`export_due_reminders` with the
    same arguments, so CSV and list exports always agree. An
    empty window exports as the header row alone.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=DUE_EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_due_reminders(
            salon, start, end, appointments=appointments):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
due_export_csv = export_due_reminders_csv
