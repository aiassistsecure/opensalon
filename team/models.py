from django.db import models
from django.utils import timezone

from saloncore.models import Salon, StaffLevel


class StaffMember(models.Model):
    """A person who works at a salon.

    ``online_bookable`` is the per-staff online-booking toggle: whether
    this staff member can be booked through online booking. It is
    independent of the roster — roster/availability (programmed in a
    later microtask) decides *when* someone works, while this toggle
    decides *whether* they are offered online at all, regardless of
    their rostered time.
    """

    salon = models.ForeignKey(
        Salon, on_delete=models.CASCADE, related_name="staff_members"
    )
    display_name = models.CharField(max_length=120)
    staff_level = models.ForeignKey(
        StaffLevel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members",
    )
    online_bookable = models.BooleanField(default=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["display_name"]

    def __str__(self):
        return self.display_name

    def is_checked_in(self):
        """True when this member's latest attendance event is a check-in."""
        latest = self.attendance_records.first()
        return latest is not None and latest.event_type == AttendanceRecord.EventType.CHECK_IN


class RosterPattern(models.Model):
    """Recurring weekly availability for a staff member.

    This is the ROSTER where availability is programmed: one row is a
    recurring block on a single weekday (e.g. Mondays 09:00-17:00).
    Appointments and online booking only offer rostered time.
    """

    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    staff_member = models.ForeignKey(
        StaffMember, on_delete=models.CASCADE, related_name="roster_patterns"
    )
    weekday = models.IntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["weekday", "start_time"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F("start_time")),
                name="roster_pattern_end_after_start",
            )
        ]

    def __str__(self):
        return (
            f"{self.staff_member} {self.get_weekday_display()} "
            f"{self.start_time}-{self.end_time}"
        )


class AttendanceRecord(models.Model):
    """A single check-in / check-out event for a staff member.

    Attendance is an event log: each row is one event, and a member's
    current state is derived from their latest event (see
    ``StaffMember.is_checked_in``). Records are never edited to change
    state — a new event is recorded instead.
    """

    class EventType(models.TextChoices):
        CHECK_IN = "check_in", "Check in"
        CHECK_OUT = "check_out", "Check out"

    staff_member = models.ForeignKey(
        StaffMember, on_delete=models.CASCADE, related_name="attendance_records"
    )
    event_type = models.CharField(max_length=10, choices=EventType.choices)
    recorded_at = models.DateTimeField(default=timezone.now)
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-recorded_at", "-id"]

    def __str__(self):
        return f"{self.staff_member} {self.get_event_type_display()} at {self.recorded_at}"
