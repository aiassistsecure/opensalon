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
