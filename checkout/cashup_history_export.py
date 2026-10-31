"""Read-only cashup history CSV export service for checkout.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a cashup, sale, or
payment; it only renders a history already computed by the
existing service.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module renders the existing
:mod:`checkout.cashup_history` service — the stored-snapshot
history (unlike :mod:`checkout.cashup_detail`, which recomputes
from payments) — as a plain, JSON-serializable list of dicts
(:func:`export_cashup_history`) and as a CSV string
(:func:`export_cashup_history_csv`) built from that same list,
so the two formats can never disagree — one source of truth.
The history computation itself is never reimplemented here:
every row comes verbatim from
:func:`checkout.cashup_history.cashup_history`, called with the
same arguments. No re-querying, no recounting, no invented
fields.

Columns: the base columns in :data:`BASE_FIELDNAMES` (also
:data:`EXPORT_FIELDNAMES`), followed by flattened tender
columns as in :mod:`checkout.cashup_export`:

* ``id`` / ``cashup_id`` — the entry's cashup primary key;
* ``salon_id`` — the entry's salon;
* ``period_start`` / ``period_end`` / ``created_at`` — the
  period the cashup closes out and when the snapshot was
  taken, as ISO-8601 strings;
* ``note`` — the cashup's stored note (blank when none);
* ``total`` — the entry's stored grand total, as a string to
  two decimal places (money is never passed through a float);
* ``expected_total`` / ``variance`` — the entry's expected
  total and its variance (actual - expected), as money
  strings, or empty (``None`` in dicts, blank in CSV) when
  the record carries no expected figures: unknown is exported
  as empty, never a fabricated ``"0.00"``;
* ``is_locked`` — the entry's ``is_locked``, always ``False``:
  a cashup is a snapshot, not a lock, and multiple cashups
  per day are normal — every one of them exports;
* one column per tender key — that tender's stored total for
  the cashup, as a money string, ``"0.00"`` for a tender a
  cashup in the range did not record (the sorted union of
  keys across the range, zero-filled exactly as in
  :mod:`checkout.cashup_export`); when any entry carries
  per-tender expected / variance figures, one
  ``expected_<tender>`` column per expected key and one
  ``variance_<tender>`` column per variance key follow —
  entries without such figures leave those cells empty,
  never zero-filled.

Salon scope and range semantics follow the service verbatim:
a salon is required, dates are inclusive whole local days in
the salon's timezone (datetimes an inclusive instant window),
and the service's own errors propagate unchanged (e.g.
``ValueError`` for a missing salon or a reversed range).

Ordering is deterministic: the service's own order (newest
period first). An empty range exports as ``[]`` / a CSV whose
header is the base columns alone (no tender keys are known),
never ``None``. Lines end with ``"\\n"``. Core stays
provider-agnostic — no payment-provider SDK, field, or name
appears here; tender keys are exactly the core slugs the
service returns, treated purely as data.
"""
import csv
import io
from decimal import Decimal

from .cashup_history import cashup_history

__all__ = [
    "BASE_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "cashup_history_csv",
    "cashup_history_export_fieldnames",
    "cashup_history_export_row",
    "export_cashup_history",
    "export_cashup_history_csv",
    "export_cashup_history_rows",
]

#: Base column order, before the flattened tender columns.
BASE_FIELDNAMES = [
    "id",
    "cashup_id",
    "salon_id",
    "period_start",
    "period_end",
    "created_at",
    "note",
    "total",
    "expected_total",
    "variance",
    "is_locked",
]

#: The base columns; CSV fieldnames extend these with the
#: sorted union of tender keys for the exported range.
EXPORT_FIELDNAMES = BASE_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(str(value)).quantize(_CENTS))


def _money_or_none(value):
    """Money string, or ``None`` (CSV-blank) when unknown."""
    return None if value is None else _money(value)


def _dt(value):
    return value.isoformat() if value is not None else None


def _keys(entries, attr):
    keys = set()
    for entry in entries:
        mapping = getattr(entry, attr, None)
        if isinstance(mapping, dict):
            keys.update(str(k) for k in mapping)
    return sorted(keys)


def cashup_history_export_fieldnames(entries):
    """Return base columns plus the entries' flattened columns."""
    entries = list(entries)
    return (
        BASE_FIELDNAMES
        + _keys(entries, "tender_totals")
        + ["expected_" + k for k in _keys(
            entries, "expected_tender_totals")]
        + ["variance_" + k for k in _keys(
            entries, "variance_by_tender")]
    )


def _flatten(row, prefix, mapping, keys):
    for key in keys:
        if not isinstance(mapping, dict):
            row[prefix + key] = None
        elif key in mapping:
            row[prefix + key] = _money(mapping[key])
        else:
            row[prefix + key] = "0.00"


def cashup_history_export_row(entry, tender_keys=None,
                              expected_keys=None, variance_keys=None):
    """Return one history ``entry`` as an export row dict.

    The key lists default to the entry's own sorted keys;
    callers exporting a range pass the unions so every row
    has the same keys.
    """
    totals = entry.tender_totals if isinstance(
        entry.tender_totals, dict) else {}
    if tender_keys is None:
        tender_keys = sorted(str(k) for k in totals)
    if expected_keys is None:
        expected_keys = _keys([entry], "expected_tender_totals")
    if variance_keys is None:
        variance_keys = _keys([entry], "variance_by_tender")
    row = {
        "id": entry.id,
        "cashup_id": entry.cashup_id,
        "salon_id": entry.salon_id,
        "period_start": _dt(entry.period_start),
        "period_end": _dt(entry.period_end),
        "created_at": _dt(entry.created_at),
        "note": entry.note,
        "total": _money(entry.total),
        "expected_total": _money_or_none(entry.expected_total),
        "variance": _money_or_none(entry.variance),
        "is_locked": entry.is_locked,
    }
    for key in tender_keys:
        row[key] = _money(totals[key]) if key in totals else "0.00"
    _flatten(row, "expected_", entry.expected_tender_totals,
             expected_keys)
    _flatten(row, "variance_", entry.variance_by_tender,
             variance_keys)
    return row


def export_cashup_history(salon, date_from, date_to):
    """Return ``salon``'s cashup history as one dict per cashup.

    All arguments are passed verbatim to
    :func:`checkout.cashup_history.cashup_history`; rows are
    rendered from its entries in the service's own order.
    An empty range yields ``[]``, as the service returns.
    The service's errors propagate. Read-only.
    """
    history = cashup_history(salon, date_from, date_to)
    entries = list(history.entries)
    tender_keys = _keys(entries, "tender_totals")
    expected_keys = _keys(entries, "expected_tender_totals")
    variance_keys = _keys(entries, "variance_by_tender")
    return [
        cashup_history_export_row(
            entry, tender_keys, expected_keys, variance_keys)
        for entry in entries
    ]


def export_cashup_history_csv(salon, date_from, date_to):
    """Return :func:`export_cashup_history` for the range as CSV.

    The header row is the base columns plus the flattened
    tender columns for the range, and every data row comes
    from :func:`export_cashup_history` with the same
    arguments, so the CSV and list exports always agree. An
    empty range exports as the base header row alone. Lines
    end with ``"\\n"``.
    """
    rows = export_cashup_history(salon, date_from, date_to)
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
export_cashup_history_rows = export_cashup_history
cashup_history_csv = export_cashup_history_csv
