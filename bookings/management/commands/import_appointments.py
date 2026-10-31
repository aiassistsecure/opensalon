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
  corrected in the same run that imports its book. If end is not
  after start it is taken to fall on the following day (an
  overnight appointment).
- State: ``BOOKED`` -> booked, ``CHECKED_IN`` -> arrived,
  ``PAID`` -> completed; any other state maps to booked. (These are
  the only states present in a verbatim extract.)
- The source ``price`` is not stored: Appointment carries no price —
  money lives in the checkout app.
- Records flagged ``deleted`` and records without an
  ``appointmentId`` or with unparseable date/times are skipped and
  counted under ``skipped``.

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
            ["created", "updated", "skipped", "unresolved_client",
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
                try:
                    tz = ZoneInfo(salon.timezone)
                except Exception:
                    tz = ZoneInfo("UTC")
            clients = {c.external_id: c for c in
                       Client.objects.filter(salon=salon)
                       .exclude(external_id="")}
            staff = {s.external_id: s for s in
                     StaffMember.objects.filter(salon=salon)
                     .exclude(external_id="")}
            services = {s.external_id: s for s in
                        Service.objects.filter(category__salon=salon)
                        .exclude(external_id="")}
            total = len(records)
            seen = 0
            for row in records:
                seen += 1
                if total >= 1000 and seen % 500 == 0:
                    self.stdout.write(
                        f"  ... {seen} / {total} appointments processed")
                if not isinstance(row, dict) or row.get("deleted"):
                    stats["skipped"] += 1
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
                _, created = Appointment.objects.update_or_create(
                    external_id=external_id,
                    defaults={
                        "client": client, "staff_member": member,
                        "service": service, "service_name": snapshot,
                        "start": start, "end": end,
                        "status": STATE_MAP.get(
                            str(row.get("state") or "").upper(),
                            Appointment.Status.BOOKED),
                    })
                stats["created" if created else "updated"] += 1
                dates.append(row.get("appointmentDate"))
        stats["total"] = len(records)
        if dates:
            stats["date_min"], stats["date_max"] = min(dates), max(dates)
        self.stdout.write(
            "Imported appointments for {salon}: {created} created, "
            "{updated} updated, {skipped} skipped, {unresolved_client} "
            "unresolved client, {unresolved_staff} unresolved staff, "
            "{unresolved_service} unresolved service "
            "({imported_with_service_snapshot} of those imported with "
            "a service-name snapshot).".format(
                salon=options["salon"], **stats))
        # Machine-readable line for validation runs (counts only).
        self.stdout.write("IMPORT_SUMMARY " + json.dumps(
            {"salon": options["salon"], **stats}, sort_keys=True))
