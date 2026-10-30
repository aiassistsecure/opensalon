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
duplicates. The import runs in one transaction: a bad file changes
nothing.
"""

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

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

        stats = dict.fromkeys(["created", "updated", "skipped"], 0)
        with transaction.atomic():
            salon, _ = Salon.objects.get_or_create(name=options["salon"])
            for row in data:
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
                _, created = Client.objects.update_or_create(
                    salon=salon, external_id=external_id,
                    defaults={
                        "first_name": _text(row, "firstName", 80),
                        "last_name": _text(row, "lastName", 80),
                        "email": _text(row, "email", 254),
                        "phone": _text(row, "mobile", 32),
                        "email_opt_in": bool(row.get("emailMarketingConsent"))
                        and bool(row.get("emailReminderConsent")),
                        "sms_opt_in": bool(row.get("smsMarketingConsent"))
                        and bool(row.get("smsReminderConsent")),
                        "active": True,
                    })
                stats["created" if created else "updated"] += 1

        self.stdout.write(
            "Imported clients for {salon}: {created} created, "
            "{updated} updated, {skipped} skipped.".format(
                salon=options["salon"], **stats))
        # Machine-readable line for validation runs.
        self.stdout.write("IMPORT_SUMMARY " + json.dumps(
            {"salon": options["salon"], **stats}, sort_keys=True))
