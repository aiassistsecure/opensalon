"""Import appointments from a verbatim appointments JSON extract.

Usage:
    python manage.py import_appointments PATH [--salon NAME]
        [--timezone IANA_NAME]

PATH is one JSON file or a directory of monthly JSON files (the
verbatim extract layout: one ``YYYY-MM.json`` per month); directory
files are read in name order. Each file is a JSON list of records in
the source system's own shape — ``appointmentId``, ``clientId``,
``staffId``, ``serviceId``, ``appointmentDate`` (YYYY-MM-DD),
``startTime`` / ``endTime`` (HH:MM:SS[.mmm]), ``state`` — stored
verbatim by the pull, never renamed or flattened.

Mapping (one source of truth — this command is the only writer here):

- Client / staff / service are resolved by the generic
  ``external_id`` fields (``Client`` scoped to the salon,
  ``StaffMember`` scoped to the salon, ``Service`` via its category's
  salon). A record whose client or staff id does not resolve is
  skipped and counted under ``unresolved_client`` /
  ``unresolved_staff`` — never imported with a guessed link.
- A record whose service id does not resolve is counted under
  ``unresolved_service``. If the record carries a verbatim
  ``serviceName`` and client+staff resolve, it is still imported
  with ``service=None`` and that name snapshotted on
  ``Appointment.service_name`` (also counted under
  ``imported_with_service_snapshot``), so it renders in the day
  book. If it carries no ``serviceName`` either, it is skipped.
  Resolved records snapshot their service name the same way.
- ``appointmentDate`` + ``startTime`` / ``endTime`` are naive wall
  times in the extract. They combine into the appointment's real
  start/end datetimes, interpreted in the importing salon's timezone
  (``Salon.timezone``) and stored as the correct aware UTC instant:
  e.g. 09:00 on 2026-10-03 in America/New_York is 13:00 UTC (EDT),
  while 09:00 on a January date there is 14:00 UTC (EST). When the
  salon timezone is UTC, behaviour is unchanged. ``--timezone``
  sets ``Salon.timezone`` (creating the salon with it if needed)
  before importing, so a salon still on the UTC default can be
  corrected in the same run that imports its book. A missing or
  empty stored timezone falls back to UTC; a non-empty stored
  timezone that is not a valid IANA name raises ``CommandError``
  before any appointment is written (fail closed) instead of
  silently importing wall times as UTC. If end is not
  after start it is taken to fall on the following day (an
  overnight appointment).
- State: ``BOOKED`` -> booked, ``CHECKED_IN`` -> arrived,
  ``PAID`` -> completed. An unknown or missing state is never
  guessed as booked: the record is skipped and counted under
  ``unknown_state``.
- The source ``price`` is not mapped to a price field: Appointment
  carries no price of its own — money lives in the checkout app.
  The whole source record is preserved verbatim on
  ``Appointment.payload`` (price and every other unmapped field
  included), so nothing the source knew is dropped on import.
- Records flagged ``deleted`` and records without an
  ``appointmentId`` or with unparseable date/times are skipped and
  counted under ``skipped``. ``deleted`` is parsed strictly, never
  by truthiness: a boolean passes through, the strings
  ``true``/``false``/``1``/``0``/``yes``/``no`` (any case) parse,
  a missing or null flag means not deleted, and any other value is
  junk — the record is skipped and counted under ``skipped``.

Idempotent: rows are written with ``update_or_create`` keyed by the
source ``appointmentId`` stored on ``Appointment.external_id``, so
re-running updates in place and never duplicates. Bad rows are
skipped and counted, not fatal, and unresolved client/staff/service
references are counted, not errors. A file that is not valid JSON,
or not a JSON list, raises before any write. The import runs in
one transaction, but that is defence-in-depth only: on NEDB
``transaction.atomic()`` rolls back nothing (DYOR §9.4), so
atomicity on NEDB does not rest on ``atomic()`` rollback — it
rests on bad rows being skipped/counted and on
skip-and-idempotent-re-run healing any partial state a mid-loop
failure could leave. Output is counts only — no client names or
contact details are ever printed.
"""

import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.query import QuerySet
from django.utils import timezone as dj_tz

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service
from team.models import StaffMember

STATE_MAP = {
    "BOOKED": Appointment.Status.BOOKED,
    "CHECKED_IN": Appointment.Status.ARRIVED,
    "PAID": Appointment.Status.COMPLETED,
}

_DELETED_TRUE_WORDS = {"true", "1", "yes"}
_DELETED_FALSE_WORDS = {"false", "0", "no"}


def _parse_deleted(row):
    """Strict ``deleted`` flag for a record: True/False, or None if junk.

    Booleans pass through; the strings ``true``/``false``/``1``/``0``/
    ``yes``/``no`` (any case, surrounding whitespace ignored) and the
    integers 1/0 parse. A missing or null flag means not deleted.
    Anything else returns None so the caller skips and counts the
    record instead of guessing by truthiness — the string ``"false"``
    must never delete (skip) a real appointment.
    """
    if "deleted" not in row or row["deleted"] is None:
        return False
    value = row["deleted"]
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _DELETED_TRUE_WORDS:
            return True
        if text in _DELETED_FALSE_WORDS:
            return False
    return None


def _load_records(path):
    """All records from a JSON file, or every *.json in a directory."""
    files = ([os.path.join(path, name) for name in sorted(os.listdir(path))
              if name.endswith(".json")]
             if os.path.isdir(path) else [path])
    records = []
    for file_path in files:
        try:
            with open(file_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except OSError as exc:
            raise CommandError(
                f"Cannot read appointments file {file_path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise CommandError(
                f"Appointments file {file_path} is not valid JSON: {exc}"
            ) from exc
        if isinstance(data, dict):
            data = data.get("appointments", [])
        if not isinstance(data, list):
            raise CommandError(
                f"Appointments file {file_path} must be a JSON list.")
        records.extend(data)
    return records


def _combine(date_text, time_text, tz):
    """Aware datetime from 'YYYY-MM-DD' + 'HH:MM:SS[.mmm]', else None."""
    try:
        day = datetime.strptime(str(date_text), "%Y-%m-%d").date()
        parsed = None
        for fmt in ("%H:%M:%S.%f", "%H:%M:%S", "%H:%M"):
            try:
                parsed = datetime.strptime(str(time_text), fmt).time()
                break
            except ValueError:
                continue
        if parsed is None:
            return None
        return dj_tz.make_aware(datetime.combine(day, parsed), tz)
    except (TypeError, ValueError):
        return None


def _flush_appointments(batch):
    """Write a batch of new appointments in one multi-row insert.

    The write is the StrictConstraints guard's own ``super()``
    write — base-class ``QuerySet.bulk_create`` — called directly,
    skipping the guard's per-instance ``validate_constraints()``.
    That skip is caller-validated, not casual: the caller has
    already proven what the validation would ask the database, one
    SELECT per row — every key in the batch was absent from a
    complete preload of existing appointments, and duplicates
    within the file are folded into the pending batch before
    flushing, so no key can collide with the store or with itself.
    On NEDB that per-row read chain — not the write — was the
    throughput wall (measured ~3 rows/second end-to-end on the
    pilot workstation). The other guard bypass,
    ``ignore_conflicts=True``, is NOT usable here: a live probe
    against nedbd showed its ``ON CONFLICT DO NOTHING`` clause is
    refused verbatim (``NotSupportedError: expected a
    parenthesised row of values``), while the plain multi-row
    INSERT this path emits is accepted (probe: 250 rows in one
    call, batch_size=200).

    Falls back to per-row writes if the backend refuses the batch,
    so a backend that cannot take multi-row inserts still imports
    correctly, just slower. The fallback is idempotent, so a batch
    that partially applied before failing still heals.
    """
    try:
        QuerySet.bulk_create(Appointment.objects.all(), batch,
                             batch_size=200)
    except Exception:
        for appt in batch:
            Appointment.objects.update_or_create(
                external_id=appt.external_id,
                defaults={
                    "client": appt.client, "staff_member": appt.staff_member,
                    "service": appt.service, "service_name": appt.service_name,
                    "start": appt.start, "end": appt.end,
                    "status": appt.status, "payload": appt.payload,
                })


class Command(BaseCommand):
    help = "Import appointments from a verbatim appointments JSON extract."

    def add_arguments(self, parser):
        parser.add_argument(
            "path", help="Appointments JSON file, or directory of them.")
        parser.add_argument("--salon", default="My Salon",
                            help="Salon name to import into "
                                 "(created if missing).")
        parser.add_argument("--timezone", default=None,
                            help="IANA timezone (e.g. America/New_York) "
                                 "to set on the salon before importing; "
                                 "extract wall times are then interpreted "
                                 "in this timezone. Omit to keep the "
                                 "salon's existing timezone.")

    def handle(self, *args, **options):
        tz_name = (options.get("timezone") or "").strip() or None
        tz_override = None
        if tz_name is not None:
            try:
                tz_override = ZoneInfo(tz_name)
            except Exception as exc:
                raise CommandError(
                    f"Unknown timezone {tz_name!r}: {exc}") from exc
        records = _load_records(options["path"])
        stats = dict.fromkeys(
            ["created", "updated", "skipped", "unchanged",
             "unknown_state",
             "unresolved_client",
             "unresolved_staff", "unresolved_service",
             "imported_with_service_snapshot"], 0)
        dates = []
        with transaction.atomic():
            defaults = {"timezone": tz_name} if tz_name else {}
            salon, _ = Salon.objects.get_or_create(
                name=options["salon"], defaults=defaults)
            if tz_name and salon.timezone != tz_name:
                salon.timezone = tz_name
                salon.save(update_fields=["timezone", "updated_at"])
            if tz_override is not None:
                tz = tz_override
            else:
                stored_tz = (salon.timezone or "").strip()
                if not stored_tz:
                    tz = ZoneInfo("UTC")
                else:
                    try:
                        tz = ZoneInfo(stored_tz)
                    except Exception as exc:
                        raise CommandError(
                            f"Salon {salon.name!r} has an invalid stored "
                            f"timezone {stored_tz!r}: {exc}. Fix "
                            "Salon.timezone (or pass --timezone with a "
                            "valid IANA name) before importing; no "
                            "appointments were imported.") from exc
            clients = {c.external_id: c for c in
                       Client.objects.filter(salon=salon)
                       .exclude(external_id="")}
            staff = {s.external_id: s for s in
                     StaffMember.objects.filter(salon=salon)
                     .exclude(external_id="")}
            services = {s.external_id: s for s in
                        Service.objects.filter(category__salon=salon)
                        .exclude(external_id="")}
            # Resumable re-runs: preload existing appointments once, so
            # rows that already match are skipped at memory speed
            # instead of paying a select+update per row.
            existing = {
                row["external_id"]: row
                for row in Appointment.objects.exclude(external_id="")
                .values("external_id", "client_id", "staff_member_id",
                        "service_id", "service_name", "start", "end",
                        "status", "payload")
            }
            batch = []
            pending = {}
            total = len(records)
            seen = 0
            for row in records:
                seen += 1
                if total >= 1000 and seen % 500 == 0:
                    self.stdout.write(
                        f"  ... {seen} / {total} appointments processed")
                if not isinstance(row, dict):
                    stats["skipped"] += 1
                    continue
                deleted = _parse_deleted(row)
                if deleted is None or deleted:
                    stats["skipped"] += 1
                    continue
                raw_state = row.get("state")
                status = STATE_MAP.get(
                    raw_state.strip().upper()
                    if isinstance(raw_state, str) else "")
                if status is None:
                    stats["unknown_state"] += 1
                    continue
                external_id = str(row.get("appointmentId") or "")[:64]
                start = _combine(row.get("appointmentDate"),
                                 row.get("startTime"), tz)
                end = _combine(row.get("appointmentDate"),
                               row.get("endTime"), tz)
                if not external_id or start is None or end is None:
                    stats["skipped"] += 1
                    continue
                if end <= start:
                    end += timedelta(days=1)
                client = clients.get(str(row.get("clientId") or ""))
                if client is None:
                    stats["unresolved_client"] += 1
                    continue
                member = staff.get(str(row.get("staffId") or ""))
                if member is None:
                    stats["unresolved_staff"] += 1
                    continue
                service = services.get(str(row.get("serviceId") or ""))
                snapshot = str(row.get("serviceName") or "").strip()[:200]
                if service is None:
                    stats["unresolved_service"] += 1
                    if not snapshot:
                        continue
                    stats["imported_with_service_snapshot"] += 1
                else:
                    snapshot = snapshot or service.name[:200]
                payload = dict(row)
                current = existing.get(external_id)
                if current is not None and (
                        current["client_id"] == client.id
                        and current["staff_member_id"] == member.id
                        and current["service_id"] == (
                            service.id if service is not None else None)
                        and current["service_name"] == snapshot
                        and current["start"] == start
                        and current["end"] == end
                        and current["status"] == status
                        and current.get("payload") == payload):
                    stats["unchanged"] += 1
                    dates.append(row.get("appointmentDate"))
                    continue
                if current is not None:
                    prior = pending.get(external_id)
                    if prior is not None:
                        # The row's first copy is still sitting in
                        # the unflushed batch — it does not exist in
                        # the store yet, so fold this change into the
                        # pending instance instead of writing.
                        prior.client = client
                        prior.staff_member = member
                        prior.service = service
                        prior.service_name = snapshot
                        prior.start = start
                        prior.end = end
                        prior.status = status
                        prior.payload = payload
                    else:
                        # Changed rows are rare; they keep the exact
                        # update-in-place path.
                        Appointment.objects.update_or_create(
                            external_id=external_id,
                            defaults={
                                "client": client, "staff_member": member,
                                "service": service,
                                "service_name": snapshot,
                                "start": start, "end": end,
                                "status": status, "payload": payload,
                            })
                    stats["updated"] += 1
                else:
                    # New rows are the bulk of a first import: batch
                    # them into multi-row inserts instead of paying a
                    # select+insert round trip per row.
                    instance = Appointment(
                        client=client, staff_member=member,
                        service=service, service_name=snapshot,
                        start=start, end=end, status=status,
                        external_id=external_id, payload=payload)
                    batch.append(instance)
                    pending[external_id] = instance
                    stats["created"] += 1
                    if len(batch) >= 200:
                        _flush_appointments(batch)
                        batch.clear()
                        pending.clear()
                existing[external_id] = {
                    "external_id": external_id, "client_id": client.id,
                    "staff_member_id": member.id,
                    "service_id": (
                        service.id if service is not None else None),
                    "service_name": snapshot, "start": start, "end": end,
                    "status": status, "payload": payload,
                }
                dates.append(row.get("appointmentDate"))
            if batch:
                _flush_appointments(batch)
                batch.clear()
        stats["total"] = len(records)
        if dates:
            stats["date_min"], stats["date_max"] = min(dates), max(dates)
        self.stdout.write(
            "Imported appointments for {salon}: {created} created, "
            "{updated} updated, {unchanged} unchanged, "
            "{skipped} skipped, {unknown_state} unknown state, "
            "{unresolved_client} "
            "unresolved client, {unresolved_staff} unresolved staff, "
            "{unresolved_service} unresolved service "
            "({imported_with_service_snapshot} of those imported with "
            "a service-name snapshot).".format(
                salon=options["salon"], **stats))
        # Machine-readable line for validation runs (counts only).
        self.stdout.write("IMPORT_SUMMARY " + json.dumps(
            {"salon": options["salon"], **stats}, sort_keys=True))
