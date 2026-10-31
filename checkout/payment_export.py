"""Read-only payment CSV export service for checkout.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a payment or sale; it
only reads stored ``Payment`` records back.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports one salon's payments in
an inclusive local-date range as a plain, JSON-serializable
list of dicts (:func:`export_payments`) and as a CSV string
(:func:`export_payments_csv`) built from that same list, so
the two formats can never disagree -- one source of truth.
Every row has exactly :data:`EXPORT_FIELDNAMES` keys, exactly
the fields ``checkout.models.Payment`` defines:

* ``id`` / ``payment_id`` -- the payment's primary key;
* ``salon_id`` -- the salon of the payment's sale (``Payment``
  carries no salon of its own; the salon is read through its
  sale, never invented);
* ``sale_id`` -- the sale the payment was taken against;
* ``method`` -- the payment's stored core tender slug
  (``Payment.Method``, e.g. ``"cash"`` / ``"external"``),
  exactly as stored;
* ``amount`` -- money as a string to two decimal places (e.g.
  ``"85.00"``), because ``Decimal`` is not JSON-serializable
  and no money value is ever passed through a float;
* ``status`` -- the payment's stored status slug
  (``Payment.Status``), exactly as stored;
* ``provider_reference`` -- the opaque reference string stored
  on the payment (blank when none was recorded), exactly as
  stored; it is never interpreted or generated here;
* ``created_at`` / ``updated_at`` -- the payment's timestamps,
  as ISO-8601 strings; ``created_at`` is the timestamp the
  range filters on.

No suitable per-payment query service exists to delegate to:
:mod:`checkout.tender_totals` only aggregates payments into
totals, and :mod:`checkout.cashup` / ``cashup_detail`` build
close-out snapshots, so this module builds its queryset
directly from ``Payment`` -- and says so, rather than
reimplementing an aggregation or snapshot.

Range semantics: ``date_from`` / ``date_to`` are inclusive
whole local days in the salon's timezone (``Salon.timezone``,
falling back to UTC), judged on the payment's ``created_at``:
the window is [start of ``date_from``, start of the day after
``date_to``) in that timezone. ``date_to`` may be omitted for
a single-day export. Datetimes are reduced to their date in
the salon timezone, as in :mod:`checkout.refund_export`. A
reversed range exports as ``[]`` / a header-only CSV.

Ordering is deterministic and chronological: oldest first
(``created_at``, then ``id``) -- export order, so rows can be
appended to an external ledger without re-sorting. An empty
range exports as ``[]`` / the CSV header row alone, never
``None``.

Core stays provider-agnostic: no payment-provider SDK, field,
or name appears here; ``method`` / ``status`` values are
exactly the core slugs the model stores.
"""
import csv
import datetime
import io
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import Payment

__all__ = [
    "EXPORT_FIELDNAMES",
    "export_payments",
    "export_payments_csv",
    "export_payment_rows",
    "payment_export_row",
    "payments_csv",
]

#: Column / key order shared by the dict export and the CSV export.
EXPORT_FIELDNAMES = [
    "id",
    "payment_id",
    "salon_id",
    "sale_id",
    "method",
    "amount",
    "status",
    "provider_reference",
    "created_at",
    "updated_at",
]

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


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


def payment_export_row(payment):
    """Return one stored ``payment`` as an export row dict."""
    return {
        "id": payment.pk,
        "payment_id": payment.pk,
        "salon_id": payment.sale.salon_id if payment.sale_id else None,
        "sale_id": payment.sale_id,
        "method": payment.method,
        "amount": _money(payment.amount),
        "status": payment.status,
        "provider_reference": payment.provider_reference,
        "created_at": _dt(payment.created_at),
        "updated_at": _dt(payment.updated_at),
    }


def export_payments(salon, date_from, date_to=None):
    """Return ``salon``'s payment rows in a date range, as dicts.

    ``date_from`` / ``date_to`` are inclusive whole local days
    in the salon's timezone; ``date_to`` defaults to
    ``date_from`` (a single-day export). Rows are ordered oldest
    first (``created_at``, then ``id``). An empty or reversed
    range, a missing salon, or a missing start date exports as
    ``[]``. Read-only.
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
    payments = (
        Payment.objects.filter(
            sale__salon=salon,
            created_at__gte=window_start,
            created_at__lt=window_end,
        )
        .select_related("sale")
        .order_by("created_at", "id")
    )
    return [payment_export_row(payment) for payment in payments]


def export_payments_csv(salon, date_from, date_to=None):
    """Return ``salon``'s payments in a date range as a CSV string.

    The header row is :data:`EXPORT_FIELDNAMES` and every data
    row comes from :func:`export_payments` with the same
    arguments, so the CSV and list exports always agree. An
    empty range exports as the header row alone. Lines end
    with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_payments(salon, date_from, date_to):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_payment_rows = export_payments
payments_csv = export_payments_csv
