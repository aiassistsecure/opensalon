"""Read-only cashup detail CSV export service for checkout.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a sale, payment, or
refund; it only renders a detail report already computed by
the existing service.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module renders the existing
:mod:`checkout.cashup_detail` service as a plain,
JSON-serializable list of dicts (:func:`export_cashup_detail`)
and as a CSV string (:func:`export_cashup_detail_csv`) built
from that same list, so the two formats can never disagree --
one source of truth. The detail computation itself is never
reimplemented here: every row comes verbatim from
:func:`checkout.cashup_detail.cashup_detail`, called with the
same arguments. No re-querying, no recounting, and no invented
fields. This is distinct from :mod:`checkout.cashup_export`,
which exports stored ``Cashup`` close-out snapshots; this
export renders the live per-tender detail report (gross /
refunds / voids / net) that had no export before.

Every row has exactly :data:`EXPORT_FIELDNAMES` keys -- the
fields ``CashupDetail`` / ``TenderDetail`` produce:

* ``salon_id`` -- the detail's ``salon_id``;
* ``date_from`` / ``date_to`` -- the detail's range bounds,
  as ISO-8601 date strings;
* ``tender`` -- each key of the detail's ``by_tender``, in
  the service's own order (every core tender, zero-filled);
* ``gross`` / ``refunds`` / ``voids`` / ``net`` -- that
  tender's ``TenderDetail`` amounts, as strings to two
  decimal places, because ``Decimal`` is not JSON-serializable
  and no money value is ever passed through a float;
* ``payment_count`` / ``refund_count`` / ``void_count`` --
  that tender's ``TenderDetail`` counts.

Salon scope follows the service verbatim: a salon is REQUIRED
(this service is always salon-scoped -- there is no unscoped
form), and only that salon's records are ever exported. Range
semantics also follow the service: ``date_from`` / ``date_to``
are both required, inclusive whole local days in the salon's
timezone, and the service's own errors propagate unchanged
(e.g. ``ValueError`` for a missing salon or a reversed range).
Because the service zero-fills every tender, an empty range
still exports one explicit ``"0.00"`` row per tender -- never
``None`` and never a header-only CSV for a valid range.

Ordering is deterministic: the service's ``by_tender`` order.
Lines end with ``"\\n"``. Core stays provider-agnostic -- no
payment-provider SDK, field, or name appears here; ``tender``
values are exactly the core tender slugs the service returns.
"""
import csv
import io
from decimal import Decimal

from .cashup_detail import cashup_detail

__all__ = [
    "EXPORT_FIELDNAMES",
    "cashup_detail_csv",
    "cashup_detail_export_row",
    "export_cashup_detail",
    "export_cashup_detail_csv",
    "export_cashup_detail_rows",
]

#: Column / key order shared by the dict export and the CSV export.
EXPORT_FIELDNAMES = [
    "salon_id",
    "date_from",
    "date_to",
    "tender",
    "gross",
    "refunds",
    "voids",
    "net",
    "payment_count",
    "refund_count",
    "void_count",
]

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def cashup_detail_export_row(tender_detail, detail):
    """Return one ``by_tender`` entry of ``detail`` as a row dict."""
    return {
        "salon_id": detail.salon_id,
        "date_from": detail.date_from.isoformat(),
        "date_to": detail.date_to.isoformat(),
        "tender": tender_detail.tender,
        "gross": _money(tender_detail.gross),
        "refunds": _money(tender_detail.refunds),
        "voids": _money(tender_detail.voids),
        "net": _money(tender_detail.net),
        "payment_count": tender_detail.payment_count,
        "refund_count": tender_detail.refund_count,
        "void_count": tender_detail.void_count,
    }


def export_cashup_detail(salon, date_from, date_to):
    """Return ``salon``'s cashup detail as one dict per tender.

    All arguments are passed verbatim to
    :func:`checkout.cashup_detail.cashup_detail`; rows are
    rendered from its ``by_tender`` mapping in its own order.
    An empty range yields zero-filled rows (one per tender),
    as the service returns. The service's errors propagate.
    Read-only.
    """
    detail = cashup_detail(salon, date_from, date_to)
    return [
        cashup_detail_export_row(tender_detail, detail)
        for tender_detail in detail.by_tender.values()
    ]


def export_cashup_detail_csv(salon, date_from, date_to):
    """Return :func:`export_cashup_detail` for the range as CSV.

    The header row is :data:`EXPORT_FIELDNAMES` and every data
    row comes from :func:`export_cashup_detail` with the same
    arguments, so the CSV and list exports always agree. An
    empty range exports as the header plus zero-filled rows.
    Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_cashup_detail(salon, date_from, date_to):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_cashup_detail_rows = export_cashup_detail
cashup_detail_csv = export_cashup_detail_csv
