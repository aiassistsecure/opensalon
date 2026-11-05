"""Read-only receipt export service for checkout.

Backend only — no views, templates, or UI, and no re-send
behaviour: this service never sends, creates, or mutates a
receipt; it only reads stored ``Receipt`` snapshots back as
structured rows.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. :func:`export_receipts` returns a plain,
JSON-serializable list of dicts — one per receipt issued in a
date range — with exactly :data:`EXPORT_FIELDNAMES` keys:

* ``id`` / ``receipt_id`` — the receipt's primary key;
* ``sale_id`` — the sale the receipt snapshots;
* ``salon_id`` — the sale's salon;
* ``client_id`` — the sale's client, or ``None`` for a walk-in
  sale (the ``Receipt`` model carries no client of its own; the
  client is read through its sale, never invented);
* ``salon_name`` — the salon name as snapshotted at issue;
* ``total`` — money as a string to two decimal places (e.g.
  ``"133.00"``), because ``Decimal`` is not JSON-serializable
  and no money value is ever passed through a float;
* ``issued_at`` — when the receipt was issued, as an ISO-8601
  string; this is the timestamp the range filters on.
* Delivery, exactly as the model stores it: a receipt's only
  delivery channel in core is email (see
  :mod:`checkout.receipts`), recorded by ``recipient_email``
  and ``sent_at``. So ``delivery_channel`` is ``"email"`` when
  a send is recorded and ``None`` otherwise, and
  ``delivery_status`` is ``"sent"`` when ``sent_at`` is set and
  ``"not_sent"`` otherwise. No other channel or status is
  invented.

Range semantics: ``date_from`` / ``date_to`` are optional.
Plain dates mean whole local days in the salon's timezone
(``Salon.timezone``, falling back to UTC when no salon or
timezone is given), inclusive at both ends; datetimes are an
inclusive instant window. Either bound may be omitted for an
open-ended range, and both may be omitted to export every
receipt. ``salon`` may be passed to scope the export to one
salon (through the receipts' sales).

Ordering is deterministic and chronological: oldest first
(``issued_at``, then ``id``) — export order, so rows can be
appended to an external ledger without re-sorting. An empty
range exports as ``[]``, never ``None``.

Per-sale filter: both export functions accept an optional
keyword-only ``sale`` (default ``None``). With ``None`` the
output is the salon-wide export, unchanged. With a sale, only
that sale's receipts are included; the date window still
applies. The sale — a saved ``Sale`` instance or its id — is
resolved within the salon (through ``sale__salon``), so an
unknown id, an unsaved instance, or another salon's sale
raises ``ValueError`` rather than leaking or silently
exporting nothing. :func:`export_receipts_csv` is the CSV
twin of :func:`export_receipts`, built from that same list,
so the two formats can never disagree.

Delivery-status filter: both export functions also accept an
optional keyword-only ``delivery_status`` (default ``None``).
With ``None`` the output is unchanged. With a status, only
receipts whose derived ``delivery_status`` — exactly as
:func:`receipt_export_row` defines it, ``"sent"`` when
``sent_at`` is set and ``"not_sent"`` otherwise — matches it
exactly are included; it composes with the date window, the
salon scope, and the per-sale filter (all AND). An unknown
status matches nothing — ``[]`` / a header-only CSV — exactly
as the sibling categorical filters behave.

Core stays provider-agnostic: no payment-provider SDK, field,
or name appears here; tender detail stays on the receipt
snapshot itself and is not part of these rows.
"""
import csv
import datetime
import io
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import Receipt, Sale

__all__ = [
    "EXPORT_FIELDNAMES",
    "export_receipts",
    "export_receipts_csv",
    "export_receipt_rows",
    "receipt_export_row",
    "receipts_csv",
    "receipts_in_range",
]

#: Column / key order for every exported receipt row.
EXPORT_FIELDNAMES = [
    "id",
    "receipt_id",
    "sale_id",
    "salon_id",
    "client_id",
    "salon_name",
    "total",
    "issued_at",
    "delivery_channel",
    "delivery_status",
    "recipient_email",
    "sent_at",
]

_CENTS = Decimal("0.01")


def _dt(value):
    return value.isoformat() if value is not None else None


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _tz_for(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _window(date_from, date_to, tz):
    """Return ``(start_dt, end_dt, end_inclusive)``; bounds may be None."""
    values = (date_from, date_to)
    if any(isinstance(v, datetime.datetime) for v in values if v is not None):
        start = end = None
        if date_from is not None:
            start = date_from if isinstance(
                date_from, datetime.datetime
            ) else datetime.datetime.combine(date_from, datetime.time.min, tzinfo=tz)
        if date_to is not None:
            end = date_to if isinstance(
                date_to, datetime.datetime
            ) else datetime.datetime.combine(date_to, datetime.time.max, tzinfo=tz)
        if start is not None and end is not None and end < start:
            raise ValueError("range end must not be before its start")
        return start, end, True
    start = end = None
    if date_from is not None:
        if not isinstance(date_from, datetime.date):
            raise ValueError("receipt export needs a date for its range")
        start = datetime.datetime.combine(date_from, datetime.time.min, tzinfo=tz)
    if date_to is not None:
        if not isinstance(date_to, datetime.date):
            raise ValueError("receipt export needs a date for its range")
        end = datetime.datetime.combine(
            date_to, datetime.time.min, tzinfo=tz
        ) + datetime.timedelta(days=1)
    if start is not None and end is not None and end <= start:
        raise ValueError("range end must not be before its start")
    return start, end, False


def receipt_export_row(receipt):
    """Return one stored ``receipt`` as an export row dict."""
    sent = receipt.sent_at is not None
    delivered = sent or bool(receipt.recipient_email)
    return {
        "id": receipt.pk,
        "receipt_id": receipt.pk,
        "sale_id": receipt.sale_id,
        "salon_id": receipt.sale.salon_id if receipt.sale_id else None,
        "client_id": receipt.sale.client_id if receipt.sale_id else None,
        "salon_name": receipt.salon_name,
        "total": _money(receipt.total),
        "issued_at": _dt(receipt.issued_at),
        "delivery_channel": "email" if delivered else None,
        "delivery_status": "sent" if sent else "not_sent",
        "recipient_email": receipt.recipient_email,
        "sent_at": _dt(receipt.sent_at),
    }


def _resolve_sale(sale, salon):
    """Resolve ``sale`` (instance or id) to a saved sale in scope.

    Scope is the salon, following the ``sale__salon`` scoping
    used across checkout's exports: when ``salon`` is given the
    sale must belong to it. An unknown id, an unsaved instance,
    or another salon's sale raises ``ValueError``.
    """
    if isinstance(sale, Sale):
        if sale.pk is None:
            raise ValueError(
                "receipt export sale filter needs a saved sale")
        sale_id = sale.pk
    else:
        sale_id = sale
    sales = Sale.objects.all()
    if salon is not None:
        sales = sales.filter(salon_id=getattr(salon, "pk", salon))
    try:
        return sales.get(pk=sale_id)
    except (Sale.DoesNotExist, TypeError, ValueError) as exc:
        raise ValueError(
            f"no sale with id {sale_id!r} for this salon") from exc


def export_receipts(date_from=None, date_to=None, salon=None, *, sale=None,
                    delivery_status=None):
    """Return receipt rows issued in a range, as a list of dicts.

    Dates are inclusive whole local days (in ``salon``'s
    timezone, or UTC when no salon is given); datetimes are an
    inclusive instant window. Either bound may be omitted, and
    ``salon`` may be omitted to export across salons. Rows are
    ordered oldest first (``issued_at``, then ``id``). An empty
    range is ``[]``. Read-only.

    ``sale`` is optional and keyword-only: the default ``None``
    is the salon-wide export, unchanged. When a sale (instance
    or id) is given, only that sale's receipts are included;
    it is resolved within ``salon``, so an unknown id, an
    unsaved instance, or another salon's sale raises
    ``ValueError``.

    ``delivery_status`` is optional and keyword-only: the
    default ``None`` is unchanged. When a status is given,
    only receipts whose derived delivery status matches it
    exactly are included (``"sent"`` is ``sent_at`` set,
    ``"not_sent"`` is ``sent_at`` unset); an unknown status
    matches nothing.
    """
    resolved_sale = _resolve_sale(sale, salon) if sale is not None else None
    tz = _tz_for(salon)
    start_dt, end_dt, end_inclusive = _window(date_from, date_to, tz)
    qs = Receipt.objects.select_related("sale").all()
    if salon is not None:
        qs = qs.filter(sale__salon=salon)
    if resolved_sale is not None:
        qs = qs.filter(sale=resolved_sale)
    if delivery_status is not None:
        if delivery_status == "sent":
            qs = qs.filter(sent_at__isnull=False)
        elif delivery_status == "not_sent":
            qs = qs.filter(sent_at__isnull=True)
        else:
            qs = qs.none()
    if start_dt is not None:
        qs = qs.filter(issued_at__gte=start_dt)
    if end_dt is not None:
        if end_inclusive:
            qs = qs.filter(issued_at__lte=end_dt)
        else:
            qs = qs.filter(issued_at__lt=end_dt)
    return [
        receipt_export_row(receipt)
        for receipt in qs.order_by("issued_at", "id")
    ]


def export_receipts_csv(date_from=None, date_to=None, salon=None, *, sale=None,
                        delivery_status=None):
    """Return receipt rows issued in a range as a CSV string.

    The header row is :data:`EXPORT_FIELDNAMES` and every data
    row comes from :func:`export_receipts` with the same
    arguments, so the CSV and list exports always agree. An
    empty range exports as the header row alone. Lines end
    with ``"\\n"``.

    ``sale`` is optional and keyword-only, passed through to
    :func:`export_receipts`: the default ``None`` is the
    salon-wide export, unchanged; a given sale exports only
    that sale's receipts.

    ``delivery_status`` is likewise optional and keyword-only
    and passed through: the default ``None`` is unchanged; a
    given status exports only receipts with that derived
    delivery status.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_receipts(
            date_from, date_to, salon=salon, sale=sale,
            delivery_status=delivery_status):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_receipt_rows = export_receipts
receipts_csv = export_receipts_csv
receipts_in_range = export_receipts
