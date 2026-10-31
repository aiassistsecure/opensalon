"""Read-only cashup CSV export service for checkout.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a cashup, sale, or
payment; it only reads stored ``Cashup`` records back.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports one salon's cashups in an
inclusive local-date range as a plain, JSON-serializable list of
dicts (:func:`export_cashups`) and as a CSV string
(:func:`export_cashups_csv`) built from that same list, so the
two formats can never disagree — one source of truth.

Columns: the base columns in :data:`BASE_FIELDNAMES` (also
:data:`EXPORT_FIELDNAMES`), followed by one column per tender
key found in the exported cashups' stored ``tender_totals``
(the union of keys across the range, sorted):

* ``id`` / ``cashup_id`` — the cashup's primary key;
* ``salon_id`` — the cashup's salon;
* ``period_start`` / ``period_end`` — the period the cashup
  closes out, as ISO-8601 strings;
* ``created_at`` — when the cashup snapshot was taken, as an
  ISO-8601 string. The ``Cashup`` model has no separate
  opened/closed timestamps, so none are invented;
* ``total`` — the cashup's stored grand total, as a string to
  two decimal places (money is never passed through a float);
* ``note`` — the cashup's stored note (blank when none);
* one column per tender key — that tender's stored total for
  the cashup, as a string to two decimal places, ``"0.00"``
  for a tender a cashup in the range did not record.

No other field is exported, because the ``Cashup`` model
carries no other detail. Core stays provider-agnostic — no
payment-provider SDK, field, or name appears here; tender keys
are exactly the core slugs stored in ``tender_totals``.

Range semantics: ``date_from`` / ``date_to`` are inclusive
whole local days in the salon's timezone (``Salon.timezone``,
falling back to UTC). A cashup belongs to the period it closes
out, so it is in the range when ``[period_start, period_end]``
overlaps the window (the same attribution as
:mod:`checkout.cashup_history`). ``date_to`` may be omitted
for a single-day export. Datetimes are reduced to their date
in the salon timezone, as in :mod:`checkout.refund_export`.
A reversed range exports as ``[]`` / a header-only CSV.

Ordering is deterministic and chronological: oldest first
(``period_start``, then ``created_at``, then ``id``). An empty
range exports as ``[]`` / a CSV whose header is the base
columns alone (no tender keys are known), never ``None``.
"""
import csv
import datetime
import io
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import Cashup

__all__ = [
    "BASE_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "cashup_export_fieldnames",
    "cashup_export_row",
    "export_cashups",
    "export_cashups_csv",
    "export_cashup_rows",
    "cashups_csv",
]

#: Base column order, before the per-tender columns.
BASE_FIELDNAMES = [
    "id",
    "cashup_id",
    "salon_id",
    "period_start",
    "period_end",
    "created_at",
    "total",
    "note",
]

#: The base columns; CSV fieldnames extend these with the
#: sorted union of tender keys for the exported range.
EXPORT_FIELDNAMES = BASE_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    try:
        return str(Decimal(str(value)).quantize(_CENTS))
    except (InvalidOperation, ValueError, TypeError):
        return "0.00"


def _dt(value):
    return value.isoformat() if value is not None else None


def _tz_for(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _as_local_date(value, tz):
    if isinstance(value, datetime.datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    return value


def _tender_keys(cashups):
    keys = set()
    for cashup in cashups:
        if isinstance(getattr(cashup, "tender_totals", None), dict):
            keys.update(str(k) for k in cashup.tender_totals)
    return sorted(keys)


def cashup_export_fieldnames(cashups):
    """Return base columns plus sorted tender keys of ``cashups``."""
    return BASE_FIELDNAMES + _tender_keys(cashups)


def cashup_export_row(cashup, tender_keys=None):
    """Return one stored ``cashup`` as an export row dict.

    ``tender_keys`` defaults to the cashup's own sorted tender
    keys; callers exporting a range pass the union so every row
    has the same keys.
    """
    totals = cashup.tender_totals if isinstance(
        cashup.tender_totals, dict) else {}
    if tender_keys is None:
        tender_keys = sorted(str(k) for k in totals)
    row = {
        "id": cashup.pk,
        "cashup_id": cashup.pk,
        "salon_id": cashup.salon_id,
        "period_start": _dt(cashup.period_start),
        "period_end": _dt(cashup.period_end),
        "created_at": _dt(cashup.created_at),
        "total": _money(cashup.total),
        "note": cashup.note,
    }
    for key in tender_keys:
        row[key] = _money(totals[key]) if key in totals else "0.00"
    return row


def export_cashups(salon, date_from, date_to=None):
    """Return ``salon``'s cashup rows in a date range, as dicts.

    ``date_from`` / ``date_to`` are inclusive whole local days
    in the salon's timezone; ``date_to`` defaults to
    ``date_from`` (a single-day export). A cashup is included
    when its period overlaps the window. Rows are ordered
    oldest first (``period_start``, ``created_at``, ``id``)
    and every row carries the union of tender keys across the
    range. An empty or reversed range, a missing salon, or a
    missing start date exports as ``[]``. Read-only.
    """
    if salon is None or date_from is None:
        return []
    tz = _tz_for(salon)
    first = _as_local_date(date_from, tz)
    last = _as_local_date(date_to, tz) if date_to is not None else first
    if last < first:
        return []
    window_start = datetime.datetime.combine(
        first, datetime.time.min, tzinfo=tz
    )
    window_end = datetime.datetime.combine(
        last + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz
    )
    cashups = list(
        Cashup.objects.filter(
            salon=salon,
            period_end__gte=window_start,
            period_start__lt=window_end,
        ).order_by("period_start", "created_at", "id")
    )
    tender_keys = _tender_keys(cashups)
    return [cashup_export_row(c, tender_keys) for c in cashups]


def export_cashups_csv(salon, date_from, date_to=None):
    """Return ``salon``'s cashups in a date range as a CSV string.

    The header row is the base columns plus the sorted union of
    tender keys for the range, and every data row comes from
    :func:`export_cashups` with the same arguments, so the CSV
    and list exports always agree. An empty range exports as
    the base header row alone. Lines end with ``"\\n"``.
    """
    rows = export_cashups(salon, date_from, date_to)
    fieldnames = BASE_FIELDNAMES + (
        [k for k in rows[0] if k not in BASE_FIELDNAMES] if rows else []
    )
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=fieldnames, lineterminator="\n"
    )
    writer.writeheader()
    for record in rows:
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_cashup_rows = export_cashups
cashups_csv = export_cashups_csv
