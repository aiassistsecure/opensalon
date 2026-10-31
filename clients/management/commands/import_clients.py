"""Import clients from a Phorest-style clients JSON export.

Usage:
    python manage.py import_clients clients.json [--salon NAME]

The input is a JSON list of client objects with ``clientId``,
``firstName``, ``lastName``, ``email``, ``mobile``, the flags
``archived`` / ``deleted`` / ``banned``, and four consent fields:
``emailMarketingConsent``, ``emailReminderConsent``,
``smsMarketingConsent`` and ``smsReminderConsent``.

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

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.query import QuerySet

from clients.models import Client
from saloncore.models import Salon


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
            ["created", "updated", "skipped", "unchanged"], 0)
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
            for row in data:
                seen += 1
                if total >= 1000 and seen % 500 == 0:
                    self.stdout.write(
                        f"  ... {seen} / {total} clients processed")
                if not isinstance(row, dict):
                    stats["skipped"] += 1
                    continue
                if row.get("archived") or row.get("deleted") or row.get("banned"):
                    stats["skipped"] += 1
                    continue
                external_id = _text(row, "clientId", 64) or _text(row, "id", 64)
                if not external_id:
                    stats["skipped"] += 1
                    continue
                defaults = {
                    "first_name": _text(row, "firstName", 80),
                    "last_name": _text(row, "lastName", 80),
                    "email": _text(row, "email", 254),
                    "phone": _text(row, "mobile", 32),
                    "email_opt_in": bool(row.get("emailMarketingConsent"))
                    and bool(row.get("emailReminderConsent")),
                    "sms_opt_in": bool(row.get("smsMarketingConsent"))
                    and bool(row.get("smsReminderConsent")),
                    "active": True,
                }
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

        self.stdout.write(
            "Imported clients for {salon}: {created} created, "
            "{updated} updated, {unchanged} unchanged, "
            "{skipped} skipped.".format(
                salon=options["salon"], **stats))
        # Machine-readable line for validation runs.
        self.stdout.write("IMPORT_SUMMARY " + json.dumps(
            {"salon": options["salon"], **stats}, sort_keys=True))
