"""Read-only sales summary CSV export service.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a sale or item; it
only renders summaries already computed by the existing
service.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module renders the existing
:mod:`checkout.summary` service for an inclusive date range
as a plain list of dicts (:func:`export_summary`) and as a CSV
string (:func:`export_summary_csv`) built from that same list,
so the two formats can never disagree -- one source of truth.
The totals computation itself is never reimplemented here:
every value comes verbatim from
:func:`checkout.summary.daily_sales_summary`, called once per
day in the range. No recounting, no re-querying, and no
invented fields.

Columns -- exactly the fields ``DailySalesSummary`` produces:

* ``salon_id`` -- the summary's ``salon_id``;
* ``date`` -- the summary's ``day``, as an ISO-8601 string;
* ``sales_count`` -- ``DailySalesSummary.sales_count``;
* ``gross_total`` -- ``DailySalesSummary.gross_total``, as a
  string to two decimal places (money is never passed
  through a float);
* ``service_total`` -- ``DailySalesSummary.service_total``,
  as a string to two decimal places;
* ``retail_total`` -- ``DailySalesSummary.retail_total``, as
  a string to two decimal places;
* ``series_total`` -- ``DailySalesSummary.series_total``, as
  a string to two decimal places (the series column, mirroring
  the ``series`` column of the insights revenue-split export);
* ``item_count`` -- ``DailySalesSummary.item_count``.

Range semantics: ``date_from`` / ``date_to`` are inclusive
whole local days in the salon's timezone (``Salon.timezone``,
falling back to UTC), following the sibling export services;
``date_to`` may be omitted for a single-day export, and
datetimes are reduced to their date in the salon timezone.
One row is exported per day in the range, in deterministic
chronological order, including days with no sales -- the
service returns zeroes for an empty day, so such a day exports
as an explicit zero row, never ``None``. A reversed range, a
missing salon, or a missing start date exports as ``[]`` / a
header-only CSV. The service's own day attribution
(completed/created, voided excluded, salon scoping) applies
unchanged because each row delegates to it. Lines end with
``"\\n"``. Core stays provider-agnostic -- no payment-provider
SDK, field, or name appears here.
"""
import csv
import datetime
import io
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .summary import daily_sales_summary

__all__ = [
    "EXPORT_FIELDNAMES",
    "summary_export_row",
    "export_summary",
    "export_summary_csv",
    "export_summary_rows",
    "summary_csv",
]

#: Column / key order shared by the dict export and the CSV export.
EXPORT_FIELDNAMES = [
    "salon_id",
    "date",
    "sales_count",
    "gross_total",
    "service_total",
    "retail_total",
    "series_total",
    "item_count",
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


def summary_export_row(summary):
    """Return one ``DailySalesSummary`` as an export row dict."""
    return {
        "salon_id": summary.salon_id,
        "date": summary.day.isoformat(),
        "sales_count": summary.sales_count,
        "gross_total": _money(summary.gross_total),
        "service_total": _money(summary.service_total),
        "retail_total": _money(summary.retail_total),
        "series_total": _money(summary.series_total),
        "item_count": summary.item_count,
    }


def export_summary(salon, date_from, date_to=None):
    """Return sales summary rows for ``salon`` in a range, as dicts.

    ``date_from`` / ``date_to`` are inclusive whole local days
    in the salon's timezone; ``date_to`` defaults to
    ``date_from`` (a single-day export). One row per day,
    oldest first, each rendered verbatim from
    :func:`checkout.summary.daily_sales_summary` for that day.
    An empty or reversed range, a missing salon, or a missing
    start date exports as ``[]``. Read-only.
    """
    if salon is None or date_from is None:
        return []
    tz = _tz_for(salon)
    first = _as_local_date(date_from, tz)
    last = _as_local_date(date_to, tz) if date_to is not None else first
    if last < first:
        return []
    rows = []
    day = first
    while day <= last:
        rows.append(summary_export_row(daily_sales_summary(salon, day)))
        day += datetime.timedelta(days=1)
    return rows


def export_summary_csv(salon, date_from, date_to=None):
    """Return :func:`export_summary` for the range as CSV.

    The header row is :data:`EXPORT_FIELDNAMES` and every data
    row comes from :func:`export_summary` with the same
    arguments, so the CSV and list exports always agree. An
    empty range exports as the header row alone. Lines end
    with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_summary(salon, date_from, date_to):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_summary_rows = export_summary
summary_csv = export_summary_csv
