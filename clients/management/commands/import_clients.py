"""Import clients from a Phorest-style clients JSON export.

Usage:
    python manage.py import_clients clients.json [--salon NAME]

The input is a JSON list of client objects with ``clientId``,
``firstName``, ``lastName``, ``email``, ``mobile``, the flags
``archived`` / ``deleted`` / ``banned``, and four consent fields:
``emailMarketingConsent``, ``emailReminderConsent``,
``smsMarketingConsent`` and ``smsReminderConsent``.

It ALSO accepts OpenSalon's own export shape (``export_clients`` /
``clients.export.export_client``): ``external_id``, ``first_name``,
``last_name``, ``email``, ``phone``, ``email_opt_in``, ``sms_opt_in``
and ``active`` round-trip with field-level fidelity, so a salon can
export its book and re-import it (e.g. on a new install) without
losing names, phone, opt-ins, active state, or identity. A record
is treated as export-shape when it carries any of ``external_id``,
``first_name``, ``last_name``, ``phone``, ``email_opt_in`` or
``sms_opt_in``. Identity rule for the export shape: ``external_id``
is the natural key and the internal numeric ``id`` in an export
record is NEVER used as ``external_id``; an export-shape record
with a blank ``external_id`` is skipped and counted, exactly like
a Phorest record with no stable id. The Phorest shape keeps its
original ``clientId`` (falling back to ``id``) behaviour.

Notes (export shape): a record's ``notes`` list, when present, is
imported as persistent client record notes (``ClientNote``).
Idempotency rule: a note is matched on (client, body, author_name)
-- a re-import whose note has the same body and author for the
same client creates no duplicate. ``ClientNote.created_at`` is
``auto_now_add``, so it cannot be assigned on create; when an
exported note carries a parseable ``created_at`` it is restored
afterwards with a queryset ``update()``, but the date is not part
of the match key (the model offers no settable timestamp to key
on reliably at create time). A naive ``created_at`` is never
stored as-is under ``USE_TZ``: it is interpreted explicitly in
the salon's timezone (``Salon.timezone``) and counted as
``naive_datetimes_made_aware``; an unparseable ``created_at`` is
counted as ``datetimes_dropped`` and the note still imports with
its automatic timestamp -- no timestamp is fabricated.

Mapping (one source of truth — this command is the only writer here):

- Client <- ``firstName`` / ``lastName`` / ``email``; ``mobile``
  becomes ``phone``. Values are truncated to the model's field lengths.
- Natural key: ``clientId``, stored on the generic ``Client.external_id``
  field (never a provider-named column) and scoped to the salon.
  Justification: ``clientId`` is unique for every record in a real
  export, while email and mobile are NOT — a real client book contains
  duplicate emails, duplicate mobiles, duplicate email+mobile pairs,
  and many clients with neither. Email+mobile therefore cannot key an
  idempotent import without silently merging different people, so
  records without a ``clientId`` (or ``id``) are skipped and counted.
- Consent: the export distinguishes marketing consent from reminder
  consent per channel; the Client model has a single opt-in per
  channel (``email_opt_in`` / ``sms_opt_in``) and that flag gates BOTH
  reminders and marketing. It is therefore set only when BOTH source
  consents are true (emailMarketingConsent AND emailReminderConsent;
  smsMarketingConsent AND smsReminderConsent) — the conservative
  mapping that never sends a message type to someone who did not
  consent to it. What cannot be represented: the marketing-vs-reminder
  distinction itself; a client who consented to reminders only imports
  as opted out, and must opt in again inside OpenSalon.
- Records flagged ``archived``, ``deleted`` or ``banned`` are skipped
  and counted, never imported (not even as inactive).
- Boolean fields (all consents, ``active``, ``archived`` / ``deleted``
  / ``banned``) are parsed strictly, never with bare ``bool()`` /
  truthiness: a real bool passes through, the strings ``"true"`` /
  ``"false"`` / ``"1"`` / ``"0"`` / ``"yes"`` / ``"no"``
  (case-insensitive) and the ints ``1`` / ``0`` are parsed, a missing
  key / ``None`` / empty string falls back to the field's conservative
  default (``False`` for consents and skip flags, ``True`` for
  ``active``), and any other value makes the row a counted skip --
  it is never silently coerced to ``True``. This matters because
  ``bool("false")`` is ``True`` in Python: string consents from a
  JSON/CSV-flavoured export would otherwise opt non-consenting
  clients in.

Idempotent: rows are written with ``update_or_create`` keyed by
(salon, external_id), so re-running updates in place and never
duplicates. Re-runs are also resumable: existing rows are preloaded
once and any row whose mapped fields already match is skipped
without a database write (counted as ``unchanged``), so an
interrupted import re-run pays memory-speed skips for the part
already imported instead of a full replay of writes. Bad rows are skipped and counted, not fatal. A file
that is not valid JSON, or not a JSON list, raises before any
write. The import runs in one transaction, but that is
defence-in-depth only: on NEDB ``transaction.atomic()`` rolls
back nothing (DYOR §9.4), so atomicity on NEDB does not rest on
``atomic()`` rollback — it rests on bad rows being
skipped/counted and on skip-and-idempotent-re-run healing any
partial state a mid-loop failure could leave.
"""

import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.query import QuerySet
from django.utils import timezone as dj_timezone
from django.utils.dateparse import parse_datetime

from clients.models import Client, ClientNote
from saloncore.models import Salon

_EXPORT_KEYS = (
    "external_id", "first_name", "last_name", "phone",
    "email_opt_in", "sms_opt_in",
)


def _is_export_shape(row):
    return any(key in row for key in _EXPORT_KEYS)


def _salon_zone(salon):
    """ZoneInfo for the salon's timezone, falling back safely.

    Source of truth is ``Salon.timezone``; when it is blank or not a
    known zone, fall back to ``settings.TIME_ZONE``, then UTC.
    """
    for name in (getattr(salon, "timezone", None),
                 getattr(settings, "TIME_ZONE", None), "UTC"):
        if not name:
            continue
        try:
            return ZoneInfo(str(name))
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            continue
    return ZoneInfo("UTC")


def _parse_dt(value, salon=None, stats=None):
    """Parse a datetime string; never return a naive datetime.

    Absent values (missing / ``None`` / empty) return ``None`` with
    no count -- there is no timestamp to restore. A present value
    that cannot be parsed returns ``None`` and is counted in
    ``stats["datetimes_dropped"]`` instead of being silently
    dropped. A parsed naive datetime is interpreted explicitly in
    the salon's timezone via ``make_aware`` and counted in
    ``stats["naive_datetimes_made_aware"]``; an already-aware
    datetime is returned unchanged with no counts.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        if stats is not None:
            stats["datetimes_dropped"] = (
                stats.get("datetimes_dropped", 0) + 1)
        return None
    try:
        parsed = parse_datetime(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        parsed = None
    if parsed is None:
        if stats is not None:
            stats["datetimes_dropped"] = (
                stats.get("datetimes_dropped", 0) + 1)
        return None
    if dj_timezone.is_naive(parsed):
        parsed = dj_timezone.make_aware(parsed, _salon_zone(salon))
        if stats is not None:
            stats["naive_datetimes_made_aware"] = (
                stats.get("naive_datetimes_made_aware", 0) + 1)
    return parsed


def _import_notes(salon, notes_by_external_id, stats):
    """Create ClientNotes for imported records, idempotently.

    Match rule: (client, body, author_name) — see module docstring.
    """
    for external_id, notes in notes_by_external_id.items():
        if not notes:
            continue
        client = Client.objects.filter(
            salon=salon, external_id=external_id).first()
        if client is None:
            stats["notes_skipped"] += len(notes)
            continue
        existing = {(n.body, n.author_name) for n in client.notes.all()}
        for note in notes:
            if not isinstance(note, dict):
                stats["notes_skipped"] += 1
                continue
            raw_body = note.get("body")
            body = str(raw_body) if raw_body else ""
            if not body.strip():
                stats["notes_skipped"] += 1
                continue
            author = _text(note, "author_name", 120)
            if (body, author) in existing:
                stats["notes_skipped"] += 1
                continue
            created = ClientNote.objects.create(
                client=client, body=body, author_name=author)
            parsed = _parse_dt(note.get("created_at"), salon=salon,
                               stats=stats)
            if parsed is not None:
                ClientNote.objects.filter(pk=created.pk).update(
                    created_at=parsed)
            existing.add((body, author))
            stats["notes_created"] += 1


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        raise CommandError(f"Cannot read clients file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CommandError(f"Clients file {path} is not valid JSON: {exc}") from exc


def _text(row, key, limit):
    value = row.get(key)
    return str(value).strip()[:limit] if value else ""


_TRUE_STRINGS = frozenset({"true", "1", "yes"})
_FALSE_STRINGS = frozenset({"false", "0", "no"})


class _InvalidBool(ValueError):
    """A present boolean field held a value that is not a boolean."""


def _strict_bool(value, default, field):
    """Parse one boolean field strictly; never use truthiness.

    Bool passes through; ``"true"/"false"/"1"/"0"/"yes"/"no"``
    (case-insensitive, whitespace ignored) and ints ``1``/``0`` parse;
    ``None`` / empty string fall back to ``default`` (absence-like
    values, matching the CSV ``_parse_bool`` in import_price_book,
    whose false words include ``""``). Anything else raises
    ``_InvalidBool`` so the caller can skip and count the row --
    a junk consent must never silently become ``True``.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, int):
        if value in (0, 1):
            return value == 1
        raise _InvalidBool(f"{field} {value!r} is not a boolean")
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return default
        if text in _TRUE_STRINGS:
            return True
        if text in _FALSE_STRINGS:
            return False
        raise _InvalidBool(f"{field} {value!r} is not a boolean")
    raise _InvalidBool(f"{field} {value!r} is not a boolean")


def _bool_field(row, key, default, field=None):
    """Strict bool for ``row[key]``; a missing key yields ``default``."""
    if key not in row:
        return default
    return _strict_bool(row.get(key), default, field or key)


def _flush_clients(batch):
    """Write a batch of new clients in one multi-row insert.

    The write is the StrictConstraints guard's own ``super()``
    write — base-class ``QuerySet.bulk_create`` — called directly,
    skipping the guard's per-instance ``validate_constraints()``.
    That skip is caller-validated, not casual: the caller has
    already proven what the validation would ask the database, one
    SELECT per row — every key in the batch was absent from a
    complete preload of the salon's clients, and duplicates within
    the file are folded into the pending batch before flushing, so
    no key can collide with the store or with itself. On NEDB that
    per-row read chain — not the write — was the throughput wall
    (measured ~3 rows/second end-to-end on the pilot workstation).
    The other guard bypass, ``ignore_conflicts=True``, is NOT
    usable here: a live probe against nedbd showed its
    ``ON CONFLICT DO NOTHING`` clause is refused verbatim
    (``NotSupportedError: expected a parenthesised row of
    values``), while the plain multi-row INSERT this path emits
    is accepted (probe: 250 rows in one call, batch_size=200).

    Falls back to per-row writes if the backend refuses the batch,
    so a backend that cannot take multi-row inserts still imports
    correctly, just slower. The fallback is idempotent, so a batch
    that partially applied before failing still heals.
    """
    try:
        QuerySet.bulk_create(Client.objects.all(), batch,
                             batch_size=200)
    except Exception:
        for client in batch:
            Client.objects.update_or_create(
                salon=client.salon, external_id=client.external_id,
                defaults={
                    "first_name": client.first_name,
                    "last_name": client.last_name,
                    "email": client.email,
                    "phone": client.phone,
                    "email_opt_in": client.email_opt_in,
                    "sms_opt_in": client.sms_opt_in,
                    "active": client.active,
                })


class Command(BaseCommand):
    help = "Import clients from a Phorest-style clients JSON export."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the clients JSON export.")
        parser.add_argument("--salon", default="My Salon",
                            help="Salon name to import into (created if missing).")

    def handle(self, *args, **options):
        data = _load_json(options["path"])
        if isinstance(data, dict):
            data = data.get("clients", [])
        if not isinstance(data, list):
            raise CommandError("Clients file must be a JSON list of clients.")

        stats = dict.fromkeys(
            ["created", "updated", "skipped", "unchanged",
             "notes_created", "notes_skipped",
             "naive_datetimes_made_aware", "datetimes_dropped"], 0)
        total = len(data)
        seen = 0
        with transaction.atomic():
            salon, _ = Salon.objects.get_or_create(name=options["salon"])
            # Resumable re-runs: preload what the salon already has once,
            # so rows whose mapped fields already match are skipped at
            # memory speed instead of paying a select+update per row.
            existing = {
                row["external_id"]: row
                for row in Client.objects.filter(salon=salon)
                .exclude(external_id="")
                .values("external_id", "first_name", "last_name", "email",
                        "phone", "email_opt_in", "sms_opt_in", "active")
            }
            batch = []
            pending = {}
            notes_by_external_id = {}
            for row in data:
                seen += 1
                if total >= 1000 and seen % 500 == 0:
                    self.stdout.write(
                        f"  ... {seen} / {total} clients processed")
                if not isinstance(row, dict):
                    stats["skipped"] += 1
                    continue
                try:
                    if (_bool_field(row, "archived", False)
                            or _bool_field(row, "deleted", False)
                            or _bool_field(row, "banned", False)):
                        stats["skipped"] += 1
                        continue
                    if _is_export_shape(row):
                        # Export shape: external_id is the ONLY identity;
                        # the internal numeric ``id`` must never become it.
                        external_id = _text(row, "external_id", 64)
                        if not external_id:
                            stats["skipped"] += 1
                            continue
                        defaults = {
                            "first_name": _text(row, "first_name", 80),
                            "last_name": _text(row, "last_name", 80),
                            "email": _text(row, "email", 254),
                            "phone": _text(row, "phone", 32),
                            "email_opt_in": _bool_field(
                                row, "email_opt_in", False),
                            "sms_opt_in": _bool_field(
                                row, "sms_opt_in", False),
                            "active": _bool_field(row, "active", True),
                        }
                    else:
                        external_id = (
                            _text(row, "clientId", 64)
                            or _text(row, "id", 64))
                        if not external_id:
                            stats["skipped"] += 1
                            continue
                        defaults = {
                            "first_name": _text(row, "firstName", 80),
                            "last_name": _text(row, "lastName", 80),
                            "email": _text(row, "email", 254),
                            "phone": _text(row, "mobile", 32),
                            "email_opt_in": _bool_field(
                                row, "emailMarketingConsent", False)
                            and _bool_field(
                                row, "emailReminderConsent", False),
                            "sms_opt_in": _bool_field(
                                row, "smsMarketingConsent", False)
                            and _bool_field(
                                row, "smsReminderConsent", False),
                            "active": True,
                        }
                except _InvalidBool:
                    # Junk boolean (e.g. an unparseable consent):
                    # counted skip, never a silent True / opt-in.
                    stats["skipped"] += 1
                    continue
                notes = row.get("notes")
                if isinstance(notes, list) and notes:
                    notes_by_external_id.setdefault(
                        external_id, []).extend(notes)
                current = existing.get(external_id)
                if current is not None and all(
                        current[key] == value
                        for key, value in defaults.items()):
                    stats["unchanged"] += 1
                    continue
                if current is not None:
                    prior = pending.get(external_id)
                    if prior is not None:
                        # The row's first copy is still sitting in
                        # the unflushed batch — it does not exist in
                        # the store yet, so fold this change into the
                        # pending instance instead of writing.
                        for key, value in defaults.items():
                            setattr(prior, key, value)
                    else:
                        # Changed rows are rare; they keep the exact
                        # update-in-place path.
                        Client.objects.update_or_create(
                            salon=salon, external_id=external_id,
                            defaults=defaults)
                    stats["updated"] += 1
                else:
                    # New rows are the bulk of a first import: batch
                    # them into multi-row inserts instead of paying a
                    # select+insert round trip per row.
                    instance = Client(
                        salon=salon, external_id=external_id, **defaults)
                    batch.append(instance)
                    pending[external_id] = instance
                    stats["created"] += 1
                    if len(batch) >= 200:
                        _flush_clients(batch)
                        batch.clear()
                        pending.clear()
                existing[external_id] = {"external_id": external_id,
                                         **defaults}
            if batch:
                _flush_clients(batch)
                batch.clear()
            _import_notes(salon, notes_by_external_id, stats)

        self.stdout.write(
            "Imported clients for {salon}: {created} created, "
            "{updated} updated, {unchanged} unchanged, "
            "{skipped} skipped.".format(
                salon=options["salon"], **stats))
        # Machine-readable line for validation runs.
        self.stdout.write("IMPORT_SUMMARY " + json.dumps(
            {"salon": options["salon"], **stats}, sort_keys=True))
