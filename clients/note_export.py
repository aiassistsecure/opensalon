"""Client record-note CSV export service.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a client or a note.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's persistent client
record notes as a plain, JSON-serializable list of dicts
(:func:`export_notes`) and as a CSV string
(:func:`export_notes_csv`) built from that same list, so the two
formats can never disagree -- one source of truth.

Kind separation: only persistent client record notes are exported
(``ClientNote``). Appointment-only notes live in the bookings app
(``AppointmentNote``) and must never appear here -- the two note
kinds never blur. This module therefore queries ``ClientNote``
only; it does not import or query the bookings models.

Columns are only real fields: the client's ``external_id`` and
name (``first_name`` / ``last_name``), the note's ``id``, its
``created_at``, its author (``author_name``, exactly as the
salon_data bundle and the bookings appointment-note twin carry
it), and its text (``body``). No other client fields are
included -- in particular no contact details beyond the name
(no email, no phone) -- and no fields are invented.

:func:`note_record` is the one record builder for a client
record note: :mod:`clients.note_search_export` reuses it (and
:data:`NOTE_FIELDNAMES`) rather than building a parallel dict,
so the two standalone note surfaces can never disagree.

Ordering is deterministic: by client (``last_name``, then
``first_name``, then client ``id``, matching ``Client``'s model
ordering tightened with the ``id`` tie-break), then the note's
``created_at``, then the note's ``id``.

Salon isolation: only notes whose client belongs to the given
salon (``client__salon``) are included.

Per-client filter: both export functions accept an optional
``client`` (default ``None``). With ``None`` the output is the
salon-wide export, unchanged. With a client, only that client's
record notes are included; the salon filter still applies, so a
client from another salon exports as empty.

Date window: both export functions also accept an optional
``start`` / ``end`` window pair (each default ``None`` =
unbounded) filtering on the note's ``created_at``. With both
``None`` the output is the salon-wide export, unchanged and
byte-identical. The window composes with the per-client filter
(window AND record). Range semantics mirror
:mod:`saloncore.price_change_export`: a bound may be a
``date``, a ``datetime``, or ``None``; the range is
start-inclusive and end-exclusive after normalisation -- a
``date`` start means the start of that day, and a ``date`` end
means the start of the *following* day, so passing two dates
includes the whole end day. A ``datetime`` is used as given
(naive datetimes are interpreted in the current time zone).
``start_date`` / ``end_date`` are accepted as keyword aliases.
"""
import csv
import io
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from clients.models import ClientNote

__all__ = [
    "NOTE_FIELDNAMES",
    "note_record",
    "export_notes",
    "export_notes_csv",
    "notes_csv",
]

#: Column / key order shared by the dict export and the CSV export.
NOTE_FIELDNAMES = [
    "client_external_id",
    "client_first_name",
    "client_last_name",
    "note_id",
    "created_at",
    "author_name",
    "body",
]


def _dt(value):
    return value.isoformat() if value is not None else None


def note_record(note):
    client = note.client
    return {
        "client_external_id": client.external_id,
        "client_first_name": client.first_name,
        "client_last_name": client.last_name,
        "note_id": note.pk,
        "created_at": _dt(note.created_at),
        "author_name": note.author_name,
        "body": note.body,
    }


#: Backwards-compatible private alias for the one record builder.
_record = note_record


def _bound(value, *, is_end):
    """Normalise a window bound to an aware datetime or ``None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        bound = value
    elif isinstance(value, date):
        bound = datetime.combine(value, time.min)
        if is_end:
            bound += timedelta(days=1)
    else:
        raise ValueError("window bounds must be a date, datetime, or None")
    if timezone.is_naive(bound):
        bound = timezone.make_aware(bound, timezone.get_current_timezone())
    return bound


def _resolve_window(start, end, kwargs):
    if start is None:
        start = kwargs.pop("start_date", None)
    if end is None:
        end = kwargs.pop("end_date", None)
    if kwargs:
        raise TypeError(
            f"Unexpected arguments: {', '.join(sorted(kwargs))}")
    return start, end


def export_notes(salon, client=None, start=None, end=None, **kwargs):
    """Return ``salon``'s persistent client record notes as dicts.

    Each entry is a dict with exactly :data:`NOTE_FIELDNAMES`
    keys. Only notes on clients of ``salon`` are included, ordered
    by (client ``last_name``, client ``first_name``, client
    ``id``, note ``created_at``, note ``id``). A salon with no
    record notes exports as ``[]``.

    ``client`` is optional: the default ``None`` is the salon-wide
    export, unchanged. When a client is given, only that client's
    notes are included; a client belonging to another salon
    exports as ``[]`` because the salon filter still applies.

    ``start`` / ``end`` are optional window bounds on the note's
    ``created_at`` (see the module docstring for semantics): the
    defaults ``None`` are unbounded, so the default output is
    unchanged. The window composes with ``client`` (window AND
    record).
    """
    start, end = _resolve_window(start, end, kwargs)
    notes = (
        ClientNote.objects.filter(client__salon=salon)
        .select_related("client")
        .order_by(
            "client__last_name",
            "client__first_name",
            "client__id",
            "created_at",
            "id",
        )
    )
    if client is not None:
        notes = notes.filter(client=client)
    start_bound = _bound(start, is_end=False)
    end_bound = _bound(end, is_end=True)
    if start_bound is not None:
        notes = notes.filter(created_at__gte=start_bound)
    if end_bound is not None:
        notes = notes.filter(created_at__lt=end_bound)
    return [_record(note) for note in notes]


def export_notes_csv(salon, client=None, start=None, end=None, **kwargs):
    """Return ``salon``'s record notes as a CSV string.

    The header row is :data:`NOTE_FIELDNAMES` and every data row
    comes from :func:`export_notes` with the same arguments, so
    the CSV and list exports always agree. A salon with no record
    notes exports as the header row alone. Lines end ``"\\n"``.

    ``client`` is optional and passed through to
    :func:`export_notes`: the default ``None`` is the salon-wide
    export, unchanged; a given client exports only that client's
    notes (header alone when that client has none, or belongs to
    another salon).

    ``start`` / ``end`` are optional window bounds on the note's
    ``created_at``, passed through to :func:`export_notes` with
    the same semantics; the defaults ``None`` are unbounded, so
    the default CSV is byte-identical to before.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=NOTE_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_notes(
            salon, client=client, start=start, end=end, **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
notes_csv = export_notes_csv
