"""Price-change window summary CSV export service.

Backend only — no views, templates, or UI. Read-only.
Founding rule (Exit Principle): anything a salon can enter, it
can fully export. Renders
:func:`saloncore.price_change_summary.price_change_summary` as
a list of dicts (:func:`export_price_change_summary`) and as a
CSV string built from that same list, so the two formats can
never disagree — one source of truth; figures verbatim, same
arguments (``salon``, ``start``, ``end``). First row is the
salon total (service fields empty), then one row per service
in ``by_service`` order. Metrics flatten into ``current_*`` /
``prior_*`` / ``*_delta`` / ``*_percent_change`` columns;
dict-export money and percent values are Decimals (percent
``None`` when prior is zero); in CSV they render to two places
(``None`` empty).
"""
import csv
import io

from saloncore.price_change_summary import price_change_summary

__all__ = ["PRICE_CHANGE_SUMMARY_FIELDNAMES",
           "PRICE_CHANGE_SUMMARY_EXPORT_FIELDNAMES", "EXPORT_FIELDNAMES",
           "export_price_change_summary", "export_price_change_summary_csv",
           "price_change_summary_csv"]
_BASE = ["salon_id", "current_start_date", "current_end_date",
         "prior_start_date", "prior_end_date", "service_id", "service_name"]
_METRICS = ["change_count", "increase_count", "decrease_count",
            "net_amount_delta"]
PRICE_CHANGE_SUMMARY_FIELDNAMES = (
    _BASE + [n for m in _METRICS for n in
             (f"current_{m}", f"prior_{m}", f"{m}_delta",
              f"{m}_percent_change")])
PRICE_CHANGE_SUMMARY_EXPORT_FIELDNAMES = PRICE_CHANGE_SUMMARY_FIELDNAMES
EXPORT_FIELDNAMES = PRICE_CHANGE_SUMMARY_FIELDNAMES


def _record(base, service_id, service_name, source):
    row = {**base, "service_id": service_id, "service_name": service_name}
    for metric in _METRICS:
        comparison = getattr(source, metric)
        row[f"current_{metric}"] = comparison.current
        row[f"prior_{metric}"] = comparison.prior
        row[f"{metric}_delta"] = comparison.delta
        row[f"{metric}_percent_change"] = comparison.percent_change
    return row


def _rows(result):
    iso = lambda d: d.isoformat() if d else ""  # noqa: E731
    base = {"salon_id": result.salon_id,
            "current_start_date": iso(result.start_date),
            "current_end_date": iso(result.end_date),
            "prior_start_date": iso(result.prior_start_date),
            "prior_end_date": iso(result.prior_end_date)}
    return [_record(base, "", "", result)] + [
        _record(base, r.service_id, r.service_name, r)
        for r in result.by_service]


def export_price_change_summary(salon, start, end):
    """Return the comparison as a list of dicts. Read-only.

    First entry is the salon total, then one per service; each
    has exactly :data:`PRICE_CHANGE_SUMMARY_FIELDNAMES` keys. A
    window pair with no changes returns the total row alone.
    """
    return _rows(price_change_summary(salon, start, end))


def export_price_change_summary_csv(salon, start, end):
    """Return the price-change summary comparison as CSV.

    Header is :data:`PRICE_CHANGE_SUMMARY_FIELDNAMES`; every
    data row comes from :func:`export_price_change_summary` with
    the same arguments, so CSV and list exports agree. Money
    and percent values render to two places, ``None`` empty.
    Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=PRICE_CHANGE_SUMMARY_FIELDNAMES,
                            lineterminator="\n")
    writer.writeheader()
    for record in export_price_change_summary(salon, start, end):
        row = dict(record)
        for metric in _METRICS:
            pct = record[f"{metric}_percent_change"]
            row[f"{metric}_percent_change"] = "" if pct is None else f"{pct:.2f}"
        for column in ("current_net_amount_delta", "prior_net_amount_delta",
                       "net_amount_delta_delta"):
            row[column] = f"{record[column]:.2f}"
        writer.writerow(row)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
price_change_summary_csv = export_price_change_summary_csv
