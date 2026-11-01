"""Shared dry-run / schema-proposal helper for importer commands.

Pure functions over in-memory source records: nothing here imports a
model, touches the database, or writes anything. The five importer
commands (``clients.import_clients``, ``bookings.import_appointments``
and ``saloncore.import_price_book`` / ``import_products`` /
``import_salon_data``) can call this before importing to report what
a source file actually contains -- the TF-12 first half. Wiring it
into any command is deliberately NOT done here.

For one record set the report covers, per key:

- inferred field types (counts per inferred type plus one summary
  ``inferred_type`` -- the single type, ``"mixed"``, or ``"unknown"``
  when no usable value was seen);
- three DISTINCT absence counts that never blur together: ``null``
  (key present, value ``None``), ``missing`` (key absent from the
  record) and ``empty_string`` (key present, value ``""``);
- the list of UNMAPPED keys: keys present in the source but absent
  from the set of keys the importer maps (so nothing a source carries
  is silently dropped without being named first).

Type inference is faithful, never lossy: ``bool`` is checked before
``int`` (``bool`` subclasses ``int``), :class:`~decimal.Decimal` is
reported as ``"decimal"`` never ``"float"``, and strings are never
coerced -- a string that merely looks numeric / boolean / date-like
is reported as ``"integer_string"`` / ``"decimal_string"`` /
``"bool_string"`` / ``"date_string"`` / ``"datetime_string"`` so a
schema proposal keeps ids and amounts as the strings they are until
an importer explicitly maps them.
"""

import re
from datetime import date, datetime
from decimal import Decimal

__all__ = [
    "build_dry_run_report",
    "build_dry_run_reports",
    "dry_run_report",
    "infer_value_type",
    "propose_schema",
]

_INT_RE = re.compile(r"^[+-]?\d+$")
_DECIMAL_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BOOL_WORDS = {"true", "false"}


def infer_value_type(value):
    """Return the faithful type name for one non-absent value.

    ``None`` -> ``"null"`` and ``""`` -> ``"empty_string"`` are
    returned for completeness; report counting treats both as their
    own absence buckets and excludes them from type inference.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, Decimal):
        return "decimal"
    if isinstance(value, float):
        return "float"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, (list, tuple)):
        return "list"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, str):
        return _infer_string_type(value)
    return type(value).__name__


def _infer_string_type(value):
    text = value.strip()
    if text == "":
        return "empty_string"
    if text.lower() in _BOOL_WORDS:
        return "bool_string"
    if _INT_RE.match(text):
        return "integer_string"
    if _DECIMAL_RE.match(text) and ("." in text or "e" in text.lower()):
        return "decimal_string"
    if _DATE_RE.match(text):
        try:
            date.fromisoformat(text)
        except ValueError:
            return "string"
        return "date_string"
    if "T" in text or (" " in text and ":" in text):
        try:
            datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return "string"
        return "datetime_string"
    return "string"


def _empty_field():
    return {
        "types": {},
        "inferred_type": "unknown",
        "present": 0,
        "null": 0,
        "missing": 0,
        "empty_string": 0,
        "valued": 0,
    }


def build_dry_run_report(records, mapped_keys, source_name=None):
    """Build a dry-run schema report for one record set.

    ``records`` is a list (or any iterable) of dicts; ``mapped_keys``
    is the set of source keys the calling importer maps. Returns a
    plain JSON-friendly dict. Pure: no database or file access, and
    the inputs are never mutated.

    Raises ``TypeError`` if any record is not a dict.
    """
    records = list(records)
    mapped = set(mapped_keys)
    total = len(records)

    fields = {}
    unmapped = set()
    for record in records:
        if not isinstance(record, dict):
            raise TypeError(
                "dry-run records must be dicts, got %s" % type(record).__name__
            )
        for key in record:
            if key not in mapped:
                unmapped.add(key)

    all_keys = mapped | unmapped
    for key in all_keys:
        fields[key] = _empty_field()

    for record in records:
        for key in all_keys:
            entry = fields[key]
            if key not in record:
                entry["missing"] += 1
                continue
            entry["present"] += 1
            value = record[key]
            if value is None:
                entry["null"] += 1
                continue
            if isinstance(value, str) and value == "":
                entry["empty_string"] += 1
                continue
            entry["valued"] += 1
            kind = infer_value_type(value)
            entry["types"][kind] = entry["types"].get(kind, 0) + 1

    for entry in fields.values():
        kinds = sorted(entry["types"])
        if len(kinds) == 1:
            entry["inferred_type"] = kinds[0]
        elif len(kinds) > 1:
            entry["inferred_type"] = "mixed"
        entry["types"] = {k: entry["types"][k] for k in kinds}

    return {
        "source": source_name,
        "record_count": total,
        "mapped_keys": sorted(mapped),
        "unmapped_keys": sorted(unmapped),
        "fields": {key: fields[key] for key in sorted(fields)},
    }


def build_dry_run_reports(record_sets):
    """Build one report per named record set (e.g. per source file).

    ``record_sets`` maps a source name to either a
    ``(records, mapped_keys)`` pair or a dict with ``records`` and
    ``mapped_keys`` keys. Returns ``{source_name: report}`` in the
    input's order.
    """
    reports = {}
    for name, spec in record_sets.items():
        if isinstance(spec, dict):
            records, mapped = spec["records"], spec["mapped_keys"]
        else:
            records, mapped = spec
        reports[name] = build_dry_run_report(records, mapped, source_name=name)
    return reports


# Friendly aliases: "dry run" at call sites, "schema proposal" in docs.
dry_run_report = build_dry_run_report
propose_schema = build_dry_run_report
