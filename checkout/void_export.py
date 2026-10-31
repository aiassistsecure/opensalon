"""Read-only voided-sale CSV export service for checkout.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a sale; it only reads
stored ``Sale`` records back.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports one salon's voided sales
in an inclusive local-date range as a plain, JSON-serializable
list of dicts (:func:`export_voided_sales`) and as a CSV string
(:func:`export_voided_sales_csv`) built from that same list, so
the two formats can never disagree — one source of truth.

Note on delegation: :mod:`checkout.void` exposes only the
:func:`checkout.void.void_sale` action — there is no existing
query service to delegate to. This export is therefore built
as a read-only queryset over the same ``Sale`` fields that
``void_sale`` writes (``status``, ``void_reason``,
``voided_at``), filtering to ``Sale.Status.VOIDED`` only.

Every row has exactly :data:`EXPORT_FIELDNAMES` keys:

* ``id`` / ``sale_id`` — the sale's primary key;
* ``salon_id`` — the sale's salon;
* ``client_id`` — the sale's client primary key, or ``None``
  when no client was recorded;
* ``status`` — the sale's stored status (always ``"voided"``
  in this export);
* ``created_at`` — when the sale was created, as an ISO-8601
  string;
* ``completed_at`` — when the sale was completed, as an
  ISO-8601 string or ``None``;
* ``voided_at`` — when the sale was voided, as an ISO-8601
  string; this is the timestamp the range filters on;
* ``void_reason`` — the sale's stored void reason;
* ``total`` — the sale's ``total`` property (sum of its item
  line totals), as a string to two decimal places, because
  ``Decimal`` is not JSON-serializable and no money value is
  ever passed through a float.

No other field is exported. Core stays provider-agnostic —
no payment-provider SDK, field, or name appears here, and no
provider reference is invented.

Range semantics: ``date_from`` / ``date_to`` are inclusive
whole local days in the salon's timezone (``Salon.timezone``,
falling back to UTC), judged on the sale's ``voided_at``:
the window is [start of ``date_from``, start of the day after
``date_to``) in that timezone. ``date_to`` may be omitted for
a single-day export. Datetimes are reduced to their date in
the salon timezone, as in sibling exports. A reversed range
exports as ``[]`` / a header-only CSV.

Ordering is deterministic and chronological: oldest first
(``voided_at``, then ``id``). An empty range exports as
``[]`` / the CSV header row alone, never ``None``.
"""
import csv
import datetime
import io
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import Sale

__all__ = [
    "EXPORT_FIELDNAMES",
    "export_voided_sales",
    "export_voided_sales_csv",
    "export_void_rows",
    "void_export_row",
    "voided_sales_csv",
]

#: Column / key order shared by the dict export and the CSV export.
EXPORT_FIELDNAMES = [
    "id",
    "sale_id",
    "salon_id",
    "client_id",
    "status",
    "created_at",
    "completed_at",
    "voided_at",
    "void_reason",
    "total",
]

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _tz_for(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _as_local_date(value, tz):
    if isinstance(value, datetime.datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    return value


def void_export_row(sale):
    """Return one stored voided ``sale`` as an export row dict."""
    return {
        "id": sale.pk,
        "sale_id": sale.pk,
        "salon_id": sale.salon_id,
        "client_id": sale.client_id,
        "status": sale.status,
        "created_at": (
            sale.created_at.isoformat() if sale.created_at else None
        ),
        "completed_at": (
            sale.completed_at.isoformat() if sale.completed_at else None
        ),
        "voided_at": (
            sale.voided_at.isoformat() if sale.voided_at else None
        ),
        "void_reason": sale.void_reason,
        "total": _money(sale.total),
    }


def export_voided_sales(salon, date_from, date_to=None):
    """Return ``salon``'s voided-sale rows in a range, as dicts.

    ``date_from`` / ``date_to`` are inclusive whole local days
    in the salon's timezone, judged on ``voided_at``;
    ``date_to`` defaults to ``date_from`` (a single-day
    export). Only sales with ``status == Sale.Status.VOIDED``
    are included. Rows are ordered oldest first
    (``voided_at``, then ``id``). An empty or reversed range,
    a missing salon, or a missing start date exports as
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
    sales = (
        Sale.objects.filter(
            salon=salon,
            status=Sale.Status.VOIDED,
            voided_at__gte=window_start,
            voided_at__lt=window_end,
        )
        .prefetch_related("items")
        .order_by("voided_at", "id")
    )
    return [void_export_row(sale) for sale in sales]


def export_voided_sales_csv(salon, date_from, date_to=None):
    """Return ``salon``'s voided sales in a range as a CSV string.

    The header row is :data:`EXPORT_FIELDNAMES` and every data
    row comes from :func:`export_voided_sales` with the same
    arguments, so the CSV and list exports always agree. An
    empty range exports as the header row alone. Lines end
    with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_voided_sales(salon, date_from, date_to):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_void_rows = export_voided_sales
voided_sales_csv = export_voided_sales_csv
