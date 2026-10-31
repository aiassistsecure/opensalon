"""Derive weekly roster patterns from the appointment history.

Usage:
    python manage.py import_roster_derived [--salon NAME]
        [--weeks 16] [--min-days 4]

Why this exists: some source systems (Phorest's third-party API
among them) expose no roster or shift resource at all — the
roster lives only in their UI. A salon migrating in still needs
a roster on day one, because the day book measures utilization
and openings against it. This command derives an honest starting
roster from the salon's own book: for each staff member and
weekday it looks at the trailing weeks of real appointments,
takes each date's first start and last end, and proposes the
modal band (rounded to 30 minutes). It is a DERIVATION, labelled
as such everywhere it is described — a light Tuesday reads as a
short band, which is exactly why the roster screen lets the desk
correct any band in seconds; the day book then follows the
corrected roster, not the derivation.

Rules:
- Window: the trailing ``--weeks`` weeks ending at the salon's
  latest appointment. Cancelled appointments never count.
- A band is proposed only when the member worked that weekday
  on at least ``--min-days`` distinct dates in the window.
- Writes are get_or_create on (member, weekday, start, end):
  idempotent, and a band a human already corrected is never
  overwritten or deleted by a re-run.
- Output is counts only — no staff names are ever printed.
"""

import datetime
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand

from bookings.models import Appointment
from saloncore.models import Salon
from team.availability import _tz
from team.models import RosterPattern, StaffMember


def _round30(t):
    minutes = t.hour * 60 + t.minute
    rounded = ((minutes + 15) // 30) * 30
    rounded = min(rounded, 1410)  # 23:30 — never round past the day
    return datetime.time(rounded // 60, rounded % 60)


def _minutes(t):
    return t.hour * 60 + t.minute


class Command(BaseCommand):
    help = (
        "Derive RosterPattern bands from the trailing weeks of "
        "real appointments (for sources that expose no roster API)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--salon", default=None)
        parser.add_argument("--weeks", type=int, default=16)
        parser.add_argument("--min-days", type=int, default=4)

    def handle(self, *args, **options):
        salons = Salon.objects.all()
        if options["salon"]:
            salons = salons.filter(name=options["salon"])
        totals = Counter()
        for salon in salons:
            totals.update(self._derive(salon, options["weeks"], options["min_days"]))
        self.stdout.write(
            "import_roster_derived: "
            f"salons={totals['salons']} members={totals['members']} "
            f"created={totals['created']} existing={totals['existing']} "
            f"skipped_bands={totals['skipped']}"
        )

    def _derive(self, salon, weeks, min_days):
        counts = Counter()
        counts["salons"] += 1
        tz = _tz(salon)
        members = list(StaffMember.objects.filter(salon=salon, active=True))
        counts["members"] += len(members)
        if not members:
            return counts
        latest = (
            Appointment.objects.filter(staff_member__salon=salon)
            .order_by("-start")
            .values_list("start", flat=True)
            .first()
        )
        if latest is None:
            return counts
        window_end = latest.astimezone(tz).date()
        window_start = window_end - datetime.timedelta(weeks=weeks)
        appts = (
            Appointment.objects.filter(
                staff_member__salon=salon,
                start__gte=datetime.datetime.combine(
                    window_start, datetime.time.min, tzinfo=tz
                ),
            )
            .exclude(status=Appointment.Status.CANCELLED)
            .select_related("staff_member")
            .order_by("start")
        )
        # (member_id, weekday) -> {date: [first_start_time, last_end_time]}
        days = defaultdict(dict)
        for appt in appts:
            local_start = appt.start.astimezone(tz)
            local_end = appt.end.astimezone(tz)
            key = (appt.staff_member_id, local_start.weekday())
            day = days[key].setdefault(
                local_start.date(), [local_start.time(), local_end.time()]
            )
            day[0] = min(day[0], local_start.time())
            day[1] = max(day[1], local_end.time())
        by_id = {m.pk: m for m in members}
        for (member_id, weekday), per_date in days.items():
            if len(per_date) < min_days:
                counts["skipped"] += 1
                continue
            starts = Counter(_round30(span[0]) for span in per_date.values())
            ends = Counter(_round30(span[1]) for span in per_date.values())
            start_mode = sorted(starts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            end_mode = sorted(
                ends.items(), key=lambda kv: (-kv[1], -_minutes(kv[0]))
            )[0][0]
            if end_mode <= start_mode:
                counts["skipped"] += 1
                continue
            _pattern, created = RosterPattern.objects.get_or_create(
                staff_member=by_id[member_id],
                weekday=weekday,
                start_time=start_mode,
                end_time=end_mode,
            )
            counts["created" if created else "existing"] += 1
        return counts
