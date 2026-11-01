"""Import a price book (categories, services, staff levels, prices).

Usage:
    python manage.py import_price_book services.json [--salon NAME]
        [--staff staff.json] [--base-level NAME]
    python manage.py import_price_book price-book.csv [--salon NAME]

Two input shapes are accepted, detected by file extension and by
content (a ``.csv`` path, or a file whose first line is the
price-book CSV header). The JSON shape below is the original one
and is unchanged. The CSV shape is the ``export_price_book``
output — the canonical round-trip: a salon can export its price
book and re-import that exact file. CSV rows are grouped by
service (one row per service/level price, plus one price-less row
for an unpriced service); ``service_name`` / ``category_name`` /
``description`` / ``external_id`` / the three minutes fields /
``service_active`` map back onto the service, and ``amount`` /
``is_from`` / ``price_active`` / ``staff_level_name`` map back
onto the price at that level. Source-system row ids in the CSV
(``salon_id``, ``service_id``, ``staff_level_id`` …) are ignored:
identity is ``external_id`` when present, else (category, name),
and levels are keyed by name within the target salon.

The input shape is the services export of the salon's previous system:
a JSON list of service objects with ``name``, ``categoryName``,
``duration`` (minutes), ``gapTime``, ``price`` (the base price),
``archived``, ``internetDescription`` and optionally
``staffCategories: {"prices": [{"id": ..., "price": ...}]}`` — per-level
prices keyed by staff-category id — plus per-person ``userPrices``.

Mapping (one source of truth — this command is the only writer here):

- Category  <- ``categoryName`` (fallback: ``categoryId``, then
  "Uncategorized"), scoped to the salon.
- Service   <- one row per (category, name); ``duration`` becomes
  ``service_minutes``, ``gapTime`` becomes ``processing_minutes``,
  ``internetDescription`` becomes ``description``, ``archived``
  becomes ``active=False``. A source ``serviceId`` (fallback: ``id``)
  is stored on the generic ``Service.external_id`` field: when a
  record carries an id, the import keys on it (falling back to
  (category, name) so a row first imported without an id gains it in
  place); when it carries none, the existing (category, name) key is
  used and ``external_id`` is left untouched — a blank source id never
  clobbers a stored one.
- StaffLevel <- each distinct ``staffCategories.prices`` id. With
  ``--staff`` (a staff export in the same system's shape), ids that are
  staff *category* ids resolve to their category names (e.g.
  "Artist Level 6"); ids that belong to an individual staff member are
  NOT level prices and are skipped (counted in the summary). Without
  ``--staff`` every id becomes a level named by that id.
- ServicePrice <- the base ``price`` attaches to a level named by
  ``--base-level`` (default "Base"); each staff-category price attaches
  to its level. Per-person ``userPrices`` are skipped and counted —
  ServicePrice is per level by design, never per person.
- Ids are never silently truncated (TF-6, mirroring import_clients /
  import_appointments): a service id (``serviceId`` / ``id`` in JSON,
  ``external_id`` in CSV) longer than ``Service.external_id``'s limit
  raises ``CommandError`` naming the row in phase 1 and writes
  nothing — truncating it would silently turn it into a DIFFERENT
  id and corrupt the identity join. Staff-file ids
  (``staffCategoryId``, ``userId`` / ``staffId``) and staff-category
  price ids are normalised to ``str`` before any lookup, so a
  numeric id in one file matches its string form in the other; a
  resolved level name longer than ``StaffLevel.name``'s limit
  likewise raises ``CommandError`` naming the row.

Idempotent: every row is written with ``update_or_create`` keyed by its
natural identity above, so re-running updates in place and never
duplicates. When a re-import changes an existing price amount, a
PriceChange audit row is appended (changed_by="import_price_book").

Verbatim retention (TF-10): the source record for each service is
stored whole in ``Service.payload`` (mirroring ``Client.payload``)
on create and on update, so fields with no mapped column are never
dropped. For the JSON shape the payload is the entire source row.
For the CSV (export) shape, a record's own ``payload`` column value
(a JSON object written by ``export_price_book``) is restored as-is,
never re-wrapped; a CSV carrying no payload imports with an empty
payload. The import summary counts a service whose only change is
its payload as ``services_updated``; a service whose mapped fields
and payload both already match counts as ``services_unchanged``.

Two-phase, validate-before-write (N-M20a, following N-M19): phase 1
validates and normalises the ENTIRE services file — every
``duration``/``gapTime`` parsed to int, ``staffCategories`` verified
as an object, every ``staffCategories.prices`` entry verified as an
object with a parseable amount, and the staff-level plan pre-resolved
(including the ``--staff`` category/user id mapping) — before phase 2
writes a single row. A bad file raises ``CommandError`` naming the
row index and changes nothing on ANY backend. This must not rely on
``transaction.atomic`` rollback: on NEDB ``atomic()`` rolls back
nothing (DYOR §9.4 — NEDB's atomicity unit is the CAS batch /
``if_seq`` transaction, not SQL savepoints; the strictness lives in
this command layer, DYOR §9.3), so the atomicity guarantee lives
here. ``transaction.atomic`` is kept only as defence-in-depth on
backends that do support transactions.
"""

import csv
import json
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from saloncore.models import (
    PriceChange,
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)

BASE_LEVEL_DEFAULT = "Base"

_EXTERNAL_ID_LIMIT = Service._meta.get_field("external_id").max_length
_LEVEL_NAME_LIMIT = StaffLevel._meta.get_field("name").max_length


def _external_id(value, index, field):
    """Service external id for a row: stringified, never truncated.

    An id longer than ``Service.external_id``'s limit raises
    CommandError naming the row (TF-6) — phase 1 raises before any
    write, so the row (and the whole file) writes nothing, instead
    of a silently shortened id becoming a different identity.
    """
    if not value:
        return ""
    text = str(value).strip()
    if len(text) > _EXTERNAL_ID_LIMIT:
        raise CommandError(
            f"Row {index}: {field} {text!r} exceeds "
            f"{_EXTERNAL_ID_LIMIT} characters; refusing to truncate "
            f"an id (truncation would create a different id).")
    return text


def _str_id(value):
    """Lookup id normalised to ``str`` (TF-6): stripped string form,
    or "" for an absent/falsy value. Staff-file ids and price-entry
    ids pass through here so numeric and string spellings of the
    same id match in the level-resolution maps."""
    if not value:
        return ""
    return str(value).strip()


def _decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _load_json(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        raise CommandError(f"Cannot read {what} file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CommandError(f"{what} file {path} is not valid JSON: {exc}") from exc


#: Header columns an export_price_book CSV must carry to be
#: recognised as the round-trip shape.
_CSV_REQUIRED_FIELDS = {"service_name", "category_name", "amount"}

_TRUE_WORDS = {"true", "1", "yes", "t", "y"}
_FALSE_WORDS = {"false", "0", "no", "f", "n", ""}


def _is_csv_import(path):
    """Whether ``path`` holds the export_price_book CSV shape.

    True for a ``.csv`` extension, or when the first line is the
    price-book CSV header (content sniff, so an extensionless
    export still round-trips). JSON inputs start with ``{``/``[``
    and never match.
    """
    if str(path).lower().endswith(".csv"):
        return True
    try:
        with open(path, encoding="utf-8-sig") as fh:
            first_line = fh.readline()
    except OSError:
        return False  # _load_json raises the proper read error.
    return "service_name" in first_line and "," in first_line


def _load_csv_rows(path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                raise CommandError(
                    f"services file {path} is not valid CSV: "
                    f"missing header row.")
            missing = _CSV_REQUIRED_FIELDS - {
                (name or "").strip() for name in reader.fieldnames}
            if missing:
                raise CommandError(
                    f"services file {path} is not a price-book CSV: "
                    f"missing columns {sorted(missing)}.")
            return list(reader)
    except OSError as exc:
        raise CommandError(f"Cannot read services file {path}: {exc}") from exc
    except csv.Error as exc:
        raise CommandError(
            f"services file {path} is not valid CSV: {exc}") from exc


def _parse_bool(value, index, field):
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    raise CommandError(f"Row {index}: {field} {value!r} is not a boolean.")


_STRICT_TRUE_WORDS = {"true", "1", "yes"}
_STRICT_FALSE_WORDS = {"false", "0", "no"}


def _parse_archived(row, index):
    """Strict ``archived`` parse for the JSON shape (TF-2).

    A missing key means not archived (False). A present value must be
    a real bool, the int 1/0, or one of the strings
    "true"/"false"/"1"/"0"/"yes"/"no" (case-insensitive) — anything
    else (junk strings, null, empty string, other numbers) raises
    CommandError in phase 1, so it is never silently guessed the way
    ``not row.get("archived")`` guessed (string "false" is truthy).
    """
    if "archived" not in row:
        return False
    value = row["archived"]
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _STRICT_TRUE_WORDS:
            return True
        if text in _STRICT_FALSE_WORDS:
            return False
    raise CommandError(
        f"Row {index}: archived {value!r} is not a boolean.")


def _parse_csv_minutes(row, index, field):
    raw = row.get(field)
    try:
        return int(str(raw).strip() or 0)
    except (ValueError, TypeError, OverflowError) as exc:
        raise CommandError(
            f"Row {index}: {field} {raw!r} is not a valid number "
            f"of minutes.") from exc


def _parse_csv_payload(row, index):
    """The CSV shape's ``payload`` cell: a JSON object, or None.

    ``export_price_book`` writes the service's verbatim source
    record as a JSON string in this column (only on books that
    carry payloads). It is restored as-is — never re-wrapped in
    the CSV row. An absent column or empty cell means no payload.
    Anything else malformed raises CommandError in phase 1.
    """
    raw = row.get("payload")
    if raw is None or not str(raw).strip():
        return None
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise CommandError(
            f"Row {index}: payload {raw!r} is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise CommandError(
            f"Row {index}: payload must be a JSON object.")
    return payload


def _normalise_csv_rows(rows):
    """Phase 1 for the CSV shape: group rows into service plans.

    Returns ``(plans, skipped_services)`` in the same plan shape
    :func:`_normalise_row` produces (plus ``finishing_minutes``
    and per-price ``is_from``/``price_active``). Conflicting
    service fields or prices within one service raise
    CommandError before anything is written.
    """
    plans, by_key, skipped = [], {}, 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not (row.get("service_name") or "").strip():
            skipped += 1
            continue
        service_fields = {
            # Verbatim, never stripped: service names must round-trip
            # byte-for-byte through export -> import (real names carry
            # trailing spaces). The blank-row skip above judges
            # emptiness with strip(); the stored name does not.
            "name": row["service_name"],
            "cat_name": (row.get("category_name") or "").strip()
                        or "Uncategorized",
            "external_id": _external_id(
                row.get("external_id"), index, "external_id"),
            "description": row.get("description") or "",
            "service_minutes": _parse_csv_minutes(
                row, index, "service_minutes"),
            "processing_minutes": _parse_csv_minutes(
                row, index, "processing_minutes"),
            "finishing_minutes": _parse_csv_minutes(
                row, index, "finishing_minutes"),
            "active": _parse_bool(row.get("service_active"), index,
                                  "service_active"),
        }
        key = (service_fields["external_id"] or
               (service_fields["cat_name"], service_fields["name"]))
        plan = by_key.get(key)
        if plan is None:
            plan = {**service_fields, "base_amount": None,
                    "level_prices": [], "user_prices_count": 0,
                    "payload": None}
            by_key[key] = plan
            plans.append(plan)
        elif any(plan[field] != value
                 for field, value in service_fields.items()):
            raise CommandError(
                f"Row {index}: conflicting service fields for "
                f"{service_fields['name']!r} in the CSV import.")

        row_payload = _parse_csv_payload(row, index)
        if row_payload is not None:
            if plan["payload"] is None:
                plan["payload"] = row_payload
            elif plan["payload"] != row_payload:
                raise CommandError(
                    f"Row {index}: conflicting payloads for "
                    f"{service_fields['name']!r} in the CSV import.")

        level_name = (row.get("staff_level_name") or "").strip()
        if len(level_name) > _LEVEL_NAME_LIMIT:
            raise CommandError(
                f"Row {index}: staff_level_name {level_name!r} exceeds "
                f"{_LEVEL_NAME_LIMIT} characters; refusing to truncate "
                f"a level name.")
        amount_raw = (row.get("amount") or "").strip()
        if not level_name and not amount_raw:
            continue  # The one price-less row of an unpriced service.
        if not level_name or not amount_raw:
            raise CommandError(
                f"Row {index}: staff_level_name and amount must "
                f"appear together.")
        amount = _decimal(amount_raw)
        if amount is None:
            raise CommandError(
                f"Row {index}: amount {amount_raw!r} is not a "
                f"valid price.")
        price = {"level_name": level_name, "amount": amount,
                 "is_from": _parse_bool(row.get("is_from"), index,
                                        "is_from"),
                 "price_active": _parse_bool(row.get("price_active"),
                                             index, "price_active")}
        prior = next((p for p in plan["level_prices"]
                      if p["level_name"] == level_name), None)
        if prior is not None and prior != price:
            raise CommandError(
                f"Row {index}: conflicting prices for level "
                f"{level_name!r} on {service_fields['name']!r}.")
        if prior is None:
            plan["level_prices"].append(price)
    for plan in plans:
        if plan["payload"] is None:
            plan["payload"] = {}
    return plans, skipped


def _parse_minutes(row, index, field):
    raw = row.get(field)
    try:
        return int(raw or 0)
    except (ValueError, TypeError, OverflowError) as exc:
        raise CommandError(
            f"Row {index}: {field} {raw!r} is not a valid number "
            f"of minutes.") from exc


def _resolve_level_name(level_id, category_names, user_category, index):
    """Level name for a staff-category id, or None when the id belongs
    to an individual (not a level) and the staff mapping is known.

    ``level_id`` and both maps' keys are ``str``-normalised (TF-6),
    so numeric and string spellings of the same id match. A resolved
    name longer than ``StaffLevel.name``'s limit raises CommandError
    naming the row instead of being stored truncated or failing
    unnamed at the database."""
    if isinstance(level_id, (list, dict)):
        raise CommandError(
            f"Row {index}: staff category id {level_id!r} is not a "
            f"valid identifier.")
    level_id = _str_id(level_id)
    if level_id in category_names:
        name = category_names[level_id]
    elif level_id in user_category or category_names:
        return None
    else:
        name = level_id
    if isinstance(name, (list, dict)):
        raise CommandError(
            f"Row {index}: staff category id {level_id!r} does not "
            f"resolve to a level name.")
    name = str(name)
    if len(name) > _LEVEL_NAME_LIMIT:
        raise CommandError(
            f"Row {index}: staff level name {name!r} for id "
            f"{level_id!r} exceeds {_LEVEL_NAME_LIMIT} characters; "
            f"refusing to truncate a level name.")
    return name


def _normalise_row(row, index, category_names, user_category):
    """Phase 1 for one row: validate + normalise, write nothing.

    Returns a write plan for phase 2, or None for a row phase 2 skips
    (not an object, or no name — the command's long-standing skip).
    Any other malformed content raises CommandError with the row
    index, so a bad row anywhere aborts the import before any write.
    """
    if not isinstance(row, dict) or not row.get("name"):
        return None
    if isinstance(row["name"], (list, dict)):
        raise CommandError(f"Row {index}: name must be a string.")
    cat_name = (row.get("categoryName") or row.get("categoryId")
                or "Uncategorized")
    if isinstance(cat_name, (list, dict)):
        raise CommandError(
            f"Row {index}: category name must be a string.")
    # A categoryId fallback is an id: normalise it to str (TF-6) so
    # a numeric category id keys the same category as its string form.
    cat_name = str(cat_name)

    raw_categories = row.get("staffCategories")
    if not raw_categories:
        staff_categories = {}
    elif isinstance(raw_categories, dict):
        staff_categories = raw_categories
    else:
        raise CommandError(
            f"Row {index}: staffCategories must be an object, got "
            f"{type(raw_categories).__name__}.")
    raw_prices = staff_categories.get("prices")
    if not raw_prices:
        price_entries = []
    elif isinstance(raw_prices, list):
        price_entries = raw_prices
    else:
        raise CommandError(
            f"Row {index}: staffCategories.prices must be a list, got "
            f"{type(raw_prices).__name__}.")

    level_prices = []
    for entry_index, entry in enumerate(price_entries):
        if not isinstance(entry, dict):
            raise CommandError(
                f"Row {index}: staffCategories.prices entry "
                f"{entry_index} must be an object, got "
                f"{type(entry).__name__}.")
        amount = _decimal(entry.get("price"))
        if amount is None:
            raise CommandError(
                f"Row {index}: staffCategories.prices entry "
                f"{entry_index} has an unparseable price "
                f"{entry.get('price')!r}.")
        entry_id = entry.get("id")
        level_name = (
            _resolve_level_name(entry_id, category_names, user_category,
                                index)
            if entry_id else None)
        level_prices.append({"level_name": level_name, "amount": amount,
                             "is_from": None, "price_active": None})

    try:
        user_prices_count = len(row.get("userPrices") or [])
    except TypeError as exc:
        raise CommandError(
            f"Row {index}: userPrices must be a list.") from exc

    return {
        "name": row["name"],
        "cat_name": cat_name,
        "external_id": _external_id(
            row.get("serviceId") or row.get("id"), index,
            "serviceId" if row.get("serviceId") else "id"),
        "description": row.get("internetDescription")
                       or row.get("description") or "",
        "service_minutes": _parse_minutes(row, index, "duration"),
        "processing_minutes": _parse_minutes(row, index, "gapTime"),
        # The JSON shape carries no finishing segment: None means
        # phase 2 leaves the stored value (model default on create).
        "finishing_minutes": None,
        "active": not _parse_archived(row, index),
        "base_amount": _decimal(row.get("price")),
        "level_prices": level_prices,
        "user_prices_count": user_prices_count,
        # Verbatim source record (TF-10): the whole row, as loaded.
        "payload": dict(row),
    }


class Command(BaseCommand):
    help = "Import service categories, services, staff levels and prices from a JSON or price-book CSV export."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the services JSON export, or an export_price_book CSV.")
        parser.add_argument("--salon", default="My Salon",
                            help="Salon name to import into (created if missing).")
        parser.add_argument("--staff", default=None,
                            help="Optional staff JSON export, used to resolve "
                                 "staff-category ids to level names.")
        parser.add_argument("--base-level", default=BASE_LEVEL_DEFAULT,
                            help="Staff level name the base price attaches to.")

    def handle(self, *args, **options):
        # Phase 1: validate + normalise the whole file, pre-resolving
        # the level plan. Nothing has been written yet; any failure
        # here raises CommandError and changes nothing on any backend.
        pre_skipped = 0
        if _is_csv_import(options["path"]):
            plans, pre_skipped = _normalise_csv_rows(
                _load_csv_rows(options["path"]))
        else:
            data = _load_json(options["path"], "services")
            if isinstance(data, dict):
                data = data.get("services", [])
            if not isinstance(data, list):
                raise CommandError(
                    "Services file must be a JSON list of services.")

            category_names, user_category = {}, {}
            if options["staff"]:
                staff = _load_json(options["staff"], "staff")
                for row in staff if isinstance(staff, list) else []:
                    if not isinstance(row, dict):
                        continue
                    name = row.get("staffCategoryName")
                    # Staff-file ids are normalised to str (TF-6):
                    # a numeric staffCategoryId / userId / staffId
                    # must key the same map entry as the string id
                    # a services row carries (and vice versa).
                    cid = _str_id(row.get("staffCategoryId"))
                    if cid and name:
                        category_names[cid] = name
                    uid = _str_id(row.get("userId") or row.get("staffId"))
                    if uid and name:
                        user_category[uid] = name

            plans = [
                _normalise_row(row, index, category_names, user_category)
                for index, row in enumerate(data)
            ]

        stats = dict.fromkeys(
            ["services", "services_updated", "services_unchanged",
             "categories", "levels", "prices",
             "skipped_services", "skipped_individual_prices"], 0)
        stats["skipped_services"] = pre_skipped

        # Phase 2: write the pre-validated plans. atomic() is kept
        # only as defence-in-depth (see module docstring).
        with transaction.atomic():
            salon, _ = Salon.objects.get_or_create(name=options["salon"])
            levels = {}

            def level_for(level_name):
                """StaffLevel for a pre-resolved level name."""
                if level_name in levels:
                    return levels[level_name]
                level, created = StaffLevel.objects.get_or_create(
                    salon=salon, name=level_name)
                levels[level_name] = level
                stats["levels"] += int(created)
                return level

            def set_price(service, level, amount, is_from=None,
                          price_active=None):
                defaults = {"amount": amount,
                            "active": True if price_active is None
                            else price_active}
                if is_from is not None:
                    defaults["is_from"] = is_from
                old = ServicePrice.objects.filter(
                    service=service, staff_level=level).first()
                price, created = ServicePrice.objects.update_or_create(
                    service=service, staff_level=level,
                    defaults=defaults)
                stats["prices"] += int(created)
                if old and not created and old.amount != amount:
                    PriceChange.objects.create(
                        service_price=price, changed_by="import_price_book",
                        old_amount=old.amount, new_amount=amount,
                        note="Price book import")
                return price

            base_level = None
            for plan in plans:
                if plan is None:
                    stats["skipped_services"] += 1
                    continue
                category, created = ServiceCategory.objects.get_or_create(
                    salon=salon, name=plan["cat_name"])
                stats["categories"] += int(created)
                external_id = plan["external_id"]
                defaults = {
                    "description": plan["description"],
                    "service_minutes": plan["service_minutes"],
                    "processing_minutes": plan["processing_minutes"],
                    "active": plan["active"],
                    "payload": plan["payload"],
                }
                if plan.get("finishing_minutes") is not None:
                    defaults["finishing_minutes"] = plan["finishing_minutes"]
                if external_id:
                    # Attach the id to a row first imported without one,
                    # so the external_id lookup below finds and updates
                    # it instead of duplicating the (category, name) row.
                    legacy = Service.objects.filter(
                        category=category, name=plan["name"],
                        external_id="").first()
                    if legacy is not None and not Service.objects.filter(
                            external_id=external_id).exists():
                        legacy.external_id = external_id
                        legacy.save(update_fields=["external_id"])
                    existing = Service.objects.filter(
                        external_id=external_id).first()
                    service, created = Service.objects.update_or_create(
                        external_id=external_id,
                        defaults={"category": category, "name": plan["name"],
                                  "external_id": external_id, **defaults})
                else:
                    # No source id: keep the natural key and leave any
                    # stored external_id untouched (never clobber with
                    # blank).
                    existing = Service.objects.filter(
                        category=category, name=plan["name"]).first()
                    service, created = Service.objects.update_or_create(
                        category=category, name=plan["name"],
                        defaults=defaults)
                stats["services"] += int(created)
                if not created:
                    # A payload-only difference counts as an update;
                    # a fully identical re-run counts as unchanged.
                    new_values = {
                        "category_id": category.pk, "name": plan["name"],
                        **defaults}
                    if external_id:
                        new_values["external_id"] = external_id
                    changed = any(
                        getattr(existing, field) != value
                        for field, value in new_values.items())
                    stats["services_updated" if changed
                          else "services_unchanged"] += 1

                if plan["base_amount"] is not None:
                    if base_level is None:
                        base_level, created = StaffLevel.objects.get_or_create(
                            salon=salon, name=options["base_level"])
                        stats["levels"] += int(created)
                    set_price(service, base_level, plan["base_amount"])

                for level_price in plan["level_prices"]:
                    if level_price["level_name"] is None:
                        stats["skipped_individual_prices"] += 1
                        continue
                    set_price(service, level_for(level_price["level_name"]),
                              level_price["amount"],
                              is_from=level_price.get("is_from"),
                              price_active=level_price.get("price_active"))
                # Per-person prices are not level prices; count and skip.
                stats["skipped_individual_prices"] += plan["user_prices_count"]

        self.stdout.write(
            "Imported price book for {salon}: {services} services, "
            "{categories} categories, {levels} staff levels, {prices} prices "
            "created; {skipped_services} services skipped, "
            "{skipped_individual_prices} per-person prices skipped.".format(
                salon=options["salon"], **stats))
        # Machine-readable line for validation runs.
        self.stdout.write("IMPORT_SUMMARY " + json.dumps(
            {"salon": options["salon"], **stats}, sort_keys=True))
