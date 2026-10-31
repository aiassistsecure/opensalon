"""Read-only tender-totals CSV export service for checkout.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a sale or payment; it
only renders totals already computed by the existing service.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module renders the existing
:mod:`checkout.tender_totals` service for a period as a plain
list of dicts (:func:`export_tender_totals`) and as a CSV
string (:func:`export_tender_totals_csv`) built from that same
list, so the two formats can never disagree -- one source of
truth. The totals computation itself is never reimplemented
here: every value comes verbatim from
:func:`checkout.tender_totals.tender_totals` (whose
``by_method`` mapping is also returned directly by
:func:`checkout.tender_totals.totals_by_tender`). No recounting,
no re-querying, and no invented fields.

Columns -- exactly the fields ``TenderTotals`` produces, plus
the caller-supplied ``salon`` scope:

* ``salon_id`` -- the ``pk`` of the ``salon`` argument, or
  ``None`` when unscoped (the totals service is unscoped then);
* ``start`` / ``end`` -- ``TenderTotals.start`` / ``.end``,
  as ISO-8601 strings when they carry ``isoformat``;
* ``method`` -- each key of ``TenderTotals.by_method``, in the
  service's own order;
* ``amount`` -- ``by_method[method]``, as a string to two
  decimal places (money is never passed through a float);
* ``total`` -- ``TenderTotals.total``, as a string to two
  decimal places, repeated on every row;
* ``count`` -- ``TenderTotals.count``, repeated on every row.
  The per-method amounts sum to ``total``.

Range and salon semantics follow the totals service verbatim:
``start`` / ``end`` are datetimes (inclusive range) or dates
(whole days, inclusive), and ``salon`` optionally scopes to
one salon's sales. The service's errors propagate unchanged
(e.g. ``ValueError`` for a missing or inverted range). Because
the service zero-fills every ``Payment.Method``, an empty
range still exports one explicit ``"0.00"`` row per method,
with ``total`` ``"0.00"`` and ``count`` ``0`` -- never ``None``.

Ordering is deterministic: the service's ``by_method`` order.
Lines end with ``"\\n"``. Core stays provider-agnostic -- no
payment-provider SDK, field, or name appears here; ``method``
values are exactly the core tender slugs the service returns.
"""
import csv
import io
from decimal import Decimal

from .tender_totals import tender_totals

__all__ = [
    "EXPORT_FIELDNAMES",
    "export_tender_totals",
    "export_tender_totals_csv",
    "export_tender_rows",
    "tender_export_row",
    "tender_totals_csv",
]

#: Column / key order shared by the dict export and the CSV export.
EXPORT_FIELDNAMES = [
    "salon_id",
    "start",
    "end",
    "method",
    "amount",
    "total",
    "count",
]

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def tender_export_row(method, amount, totals, salon=None):
    """Return one ``by_method`` entry of ``totals`` as a row dict."""
    return {
        "salon_id": salon.pk if salon is not None else None,
        "start": _iso(totals.start),
        "end": _iso(totals.end),
        "method": method,
        "amount": _money(amount),
        "total": _money(totals.total),
        "count": totals.count,
    }


def export_tender_totals(start, end, salon=None):
    """Return tender totals for a period as one dict per method.

    Rows are rendered verbatim from
    :func:`checkout.tender_totals.tender_totals` called with
    the same arguments: one row per ``by_method`` entry, in
    the service's order. An empty range yields zero-filled
    rows (one per method), as the service returns. Read-only.
    """
    totals = tender_totals(start, end, salon=salon)
    return [
        tender_export_row(method, amount, totals, salon=salon)
        for method, amount in totals.by_method.items()
    ]


def export_tender_totals_csv(start, end, salon=None):
    """Return :func:`export_tender_totals` for the period as CSV.

    The header row is :data:`EXPORT_FIELDNAMES` and every data
    row comes from :func:`export_tender_totals` with the same
    arguments, so the CSV and list exports always agree. An
    empty range exports as the header plus zero-filled rows.
    Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_tender_totals(start, end, salon=salon):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_tender_rows = export_tender_totals
tender_totals_csv = export_tender_totals_csv
