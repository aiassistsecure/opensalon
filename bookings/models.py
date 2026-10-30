from django.db import models

from clients.models import Client
from saloncore.models import Service
from team.models import StaffMember


class Appointment(models.Model):
    """A booked appointment in the day book.

    One appointment links one client, one staff member, and one
    service, with a start and an end. Availability/roster logic is
    not enforced here; this model records the booking itself.
    """

    class Status(models.TextChoices):
        BOOKED = "booked", "Booked"
        CONFIRMED = "confirmed", "Confirmed"
        ARRIVED = "arrived", "Arrived"
        IN_SERVICE = "in_service", "In service"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        NO_SHOW = "no_show", "No show"

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="appointments"
    )
    staff_member = models.ForeignKey(
        StaffMember, on_delete=models.CASCADE, related_name="appointments"
    )
    service = models.ForeignKey(
        Service, on_delete=models.CASCADE, related_name="appointments"
    )
    start = models.DateTimeField()
    end = models.DateTimeField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.BOOKED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start"]

    def __str__(self):
        return f"{self.client} — {self.service} at {self.start}"


class AppointmentNote(models.Model):
    """An appointment-only note.

    Attached to one appointment only; it does not persist on the
    client profile across visits. Persistent client record notes
    live in the clients app as ``ClientNote`` — the two kinds never
    blur.
    """

    appointment = models.ForeignKey(
        Appointment, on_delete=models.CASCADE, related_name="notes"
    )
    body = models.TextField()
    author_name = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        text = self.body[:47] + "..." if len(self.body) > 50 else self.body
        return f"Note for appointment {self.appointment_id}: {text}"
