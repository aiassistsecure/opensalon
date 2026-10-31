"""Roster week service for the team app.

Backend only — no views, templates, or UI. Pure read-only.

For a salon and a week-start date, return every active staff
member's rostered availability for the whole week (Monday through
Sunday), built entirely on :mod:`team.availability`:

* :func:`team.availability.salon_roster` supplies each day's
  per-staff ``RosterAvailability`` (merged rostered intervals,
  salon timezone, inactive members excluded, off members included
  with empty intervals) — no ``RosterPattern`` logic is duplicated
  here.
* ``StaffMember.online_bookable`` is carried per staff member as a
  separate flag, exactly as ``RosterAvailability`` carries it: it
  never removes rostered intervals.

Week semantics: ``week_start`` may be any date (or a datetime,
reduced to its date in the salon timezone via the availability
helpers); the week is the Monday of that date through the Sunday
six days later. Passing a Monday — the expected week-start —
is therefore unchanged.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from team.availability import _as_date, _tz, roster_availability, salon_roster

__all__ = [
    "RosterWeek",
    "StaffRosterWeek",
    "StaffWeekRoster",
    "get_roster_week",
    "roster_for_week",
    "roster_week",
    "roster_week_for_staff",
    "salon_roster_week",
    "staff_roster_week",
    "week_roster",
]


@dataclass(frozen=True)
class StaffWeekRoster:
    """One staff member's rostered availability for a week.

    ``days`` is a tuple of seven ``RosterAvailability`` entries,
    Monday through Sunday, in date order.
    """

    staff_member: object
    online_bookable: bool
    days: tuple = ()

    @property
    def staff_member_id(self):
        return self.staff_member.pk

    @property
    def display_name(self):
        return self.staff_member.display_name

    @property
    def availability(self):
        return self.days

    @property
    def by_date(self):
        return {day.day: day for day in self.days}

    def for_date(self, day):
        """Return this member's ``RosterAvailability`` for ``day``."""
        return self.by_date.get(day)

    @property
    def intervals(self):
        """All rostered intervals in the week, in date order."""
        return tuple(i for day in self.days for i in day.intervals)

    @property
    def total_minutes(self):
        return sum(day.total_minutes for day in self.days)

    @property
    def working_days(self):
        return sum(1 for day in self.days if day.is_working)

    @property
    def is_working(self):
        return self.working_days > 0

    is_working_any_day = is_working


# Alias: both word orders read naturally at call sites.
StaffRosterWeek = StaffWeekRoster


@dataclass(frozen=True)
class RosterWeek:
    """A salon's roster for one week: per-staff week availability."""

    salon: object
    week_start: object
    entries: list = field(default_factory=list)

    @property
    def salon_id(self):
        return getattr(self.salon, "pk", self.salon)

    @property
    def week_end(self):
        return self.week_start + timedelta(days=6)

    end = week_end

    @property
    def days(self):
        return tuple(self.week_start + timedelta(days=i) for i in range(7))

    dates = days

    @property
    def staff(self):
        return self.entries

    # Alias matching ``entries`` naming used elsewhere.
    @property
    def staff_roster(self):
        return self.entries

    @property
    def total_minutes(self):
        return sum(entry.total_minutes for entry in self.entries)

    def __iter__(self):
        return iter(self.entries)

    def __len__(self):
        return len(self.entries)

    def __getitem__(self, index):
        return self.entries[index]


def _monday(salon, week_start):
    if week_start is None:
        raise ValueError("roster week needs a week-start date")
    day = _as_date(week_start, _tz(salon))
    return day - timedelta(days=day.weekday())


def roster_week(salon, week_start):
    """Return the :class:`RosterWeek` for ``salon`` and ``week_start``.

    Args:
        salon: a ``saloncore.Salon`` instance.
        week_start: a ``datetime.date`` for the week's Monday (any
            other date is snapped to the Monday of its week; a
            datetime is reduced in the salon timezone).

    Returns:
        ``RosterWeek`` with one :class:`StaffWeekRoster` per active
        staff member, ordered by display name (the ordering
        ``salon_roster`` / ``StaffMember`` provides), each holding
        seven ``RosterAvailability`` days and the member's separate
        ``online_bookable`` flag. Read-only: nothing is created or
        changed.
    """
    if salon is None:
        raise ValueError("roster week needs a salon")
    monday = _monday(salon, week_start)
    days = [monday + timedelta(days=i) for i in range(7)]
    # salon_roster already returns one RosterAvailability per active
    # member, in display-name order, for a single day. Transpose its
    # seven daily results into one entry per staff member.
    by_staff = {}
    order = []
    for day in days:
        for availability in salon_roster(salon, day):
            key = availability.staff_member_id
            if key not in by_staff:
                by_staff[key] = {
                    "staff_member": availability.staff_member,
                    "online_bookable": availability.online_bookable,
                    "days": [],
                }
                order.append(key)
            by_staff[key]["days"].append(availability)
    entries = [
        StaffWeekRoster(
            staff_member=by_staff[key]["staff_member"],
            online_bookable=by_staff[key]["online_bookable"],
            days=tuple(by_staff[key]["days"]),
        )
        for key in order
    ]
    return RosterWeek(salon=salon, week_start=monday, entries=entries)


def staff_roster_week(staff_member, week_start):
    """Return one member's :class:`StaffWeekRoster` for a week.

    Built from :func:`team.availability.roster_availability` per day.
    A week containing ``week_start`` (Monday-snapped, as above).
    """
    if staff_member is None:
        raise ValueError("roster week needs a staff member")
    salon = staff_member.salon
    monday = _monday(salon, week_start)
    days = tuple(
        roster_availability(staff_member, monday + timedelta(days=i))
        for i in range(7)
    )
    return StaffWeekRoster(
        staff_member=staff_member,
        online_bookable=staff_member.online_bookable,
        days=days,
    )


# Aliases.
week_roster = roster_week
salon_roster_week = roster_week
roster_for_week = roster_week
get_roster_week = roster_week
roster_week_for_staff = staff_roster_week
