"""PriceChange audit CSV export service.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a price or a change
record; the audit ledger is append-only and is only read here.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports a salon's
:class:`~saloncore.models.PriceChange` audit records as a plain,
JSON-serializable list of dicts
(:func:`export_price_changes`) and as a CSV string
(:func:`export_price_changes_csv`) built from that same list,
so the two formats can never disagree -- one source of truth.

One source of truth for price history: rows are read verbatim
from the stored ``PriceChange`` records. No price history is
recomputed from current ``ServicePrice`` rows.

Columns are only real fields: the change's ``id``, its
``service_price`` (``service_price_id``, plus the price's
``service_id`` / ``service_name`` and ``staff_level_id`` /
``staff_level_name`` via that price), ``old_amount`` and
``new_amount`` (formatted to two decimal places as strings,
``"85.00"``; ``old_amount`` is ``None`` when the stored change
has no old amount), ``changed_by``, ``changed_at`` (ISO-8601),
and ``note``. No fields are invented.

Salon isolation: only changes whose price belongs to the given
salon are included -- the price's service category salon and
staff level salon must both be ``salon``
(``service_price__service__category__salon`` and
``service_price__staff_level__salon``).

Ordering is chronological: by ``changed_at``, then ``id``
(the reverse of the model's newest-first ordering, tightened
with the ``id`` tie-break).

Range semantics: ``start`` / ``end`` filter on ``changed_at``
and may each be a ``date``, a ``datetime``, or ``None``
(unbounded). The range is start-inclusive and end-exclusive
after normalisation: a ``date`` start means the start of that
day, and a ``date`` end means the start of the *following*
day, so passing two dates includes the whole end day. A
``datetime`` is used as given (naive datetimes are interpreted
in the current time zone).
"""
import csv
import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.utils import timezone

from saloncore.models import PriceChange

__all__ = [
    "PRICE_CHANGE_FIELDNAMES",
    "export_price_changes",
    "export_price_changes_csv",
    "price_changes_csv",
]

#: Column / key order shared by the dict export and the CSV export.
PRICE_CHANGE_FIELDNAMES = [
    "id",
    "service_price_id",
    "service_id",
    "service_name",
    "staff_level_id",
    "staff_level_name",
    "old_amount",
    "new_amount",
    "changed_by",
    "changed_at",
    "note",
]

_ZERO = Decimal("0.00")


def _money(value):
    return str(Decimal(value).quantize(_ZERO)) if value is not None else None


def _bound(value, *, is_end):
    """Normalise a range bound to an aware datetime or ``None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        bound = value
    elif isinstance(value, date):
        bound = datetime.combine(value, time.min)
        if is_end:
            bound += timedelta(days=1)
    else:
        raise ValueError("range bounds must be a date, datetime, or None")
    if timezone.is_naive(bound):
        bound = timezone.make_aware(bound, timezone.get_current_timezone())
    return bound


def _changes_in_range(salon, start, end):
    queryset = (
        PriceChange.objects.filter(
            service_price__service__category__salon=salon,
            service_price__staff_level__salon=salon,
        )
        .select_related(
            "service_price",
            "service_price__service",
            "service_price__staff_level",
        )
        .order_by("changed_at", "id")
    )
    start_bound = _bound(start, is_end=False)
    end_bound = _bound(end, is_end=True)
    if start_bound is not None:
        queryset = queryset.filter(changed_at__gte=start_bound)
    if end_bound is not None:
        queryset = queryset.filter(changed_at__lt=end_bound)
    return queryset


def _record(change):
    price = change.service_price
    service = price.service
    level = price.staff_level
    return {
        "id": change.pk,
        "service_price_id": price.pk,
        "service_id": service.pk,
        "service_name": service.name,
        "staff_level_id": level.pk,
        "staff_level_name": level.name,
        "old_amount": _money(change.old_amount),
        "new_amount": _money(change.new_amount),
        "changed_by": change.changed_by,
        "changed_at": change.changed_at.isoformat() if change.changed_at else None,
        "note": change.note,
    }


def export_price_changes(salon, start=None, end=None):
    """Return ``salon``'s price changes in the range as dicts.

    Each entry is a dict with exactly
    :data:`PRICE_CHANGE_FIELDNAMES` keys. Only ``salon``'s
    changes are included, ordered chronologically by
    (``changed_at``, ``id``). See the module docstring for
    range semantics. A salon / range with no changes exports
    as ``[]``. Read-only.
    """
    return [_record(c) for c in _changes_in_range(salon, start, end)]


def export_price_changes_csv(salon, start=None, end=None):
    """Return ``salon``'s price changes in the range as CSV.

    The header row is :data:`PRICE_CHANGE_FIELDNAMES` and every
    data row comes from :func:`export_price_changes` with the
    same arguments, so the CSV and list exports always agree.
    A salon / range with no changes exports as the header row
    alone. Lines end ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=PRICE_CHANGE_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_price_changes(salon, start=start, end=end):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
price_changes_csv = export_price_changes_csv
