from django.db import models

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
