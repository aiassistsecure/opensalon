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

    # Stable id from the system the record was imported from, kept
    # under a generic (not provider-named) field: imports key on it
    # so re-imports update in place. Blank for appointments created
    # directly in OpenSalon. Source ids are globally unique, so the
    # uniqueness scope is the id itself.
    external_id = models.CharField(max_length=64, blank=True)
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="appointments"
    )
    staff_member = models.ForeignKey(
        StaffMember, on_delete=models.CASCADE, related_name="appointments"
    )
    service = models.ForeignKey(
        Service, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="appointments"
    )
    # Verbatim service name snapshot, captured at import/creation
    # time. Lets an appointment whose service is absent from the
    # price book still render in the day book, and keeps the name
    # if the service is later removed.
    service_name = models.CharField(max_length=200, blank=True)
    start = models.DateTimeField()
    end = models.DateTimeField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.BOOKED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start"]
        constraints = [
            models.UniqueConstraint(
                fields=["external_id"],
                condition=models.Q(external_id__gt=""),
                name="uniq_appointment_external_id",
            )
        ]

    def __str__(self):
        name = self.service.name if self.service else self.service_name
        return f"{self.client} — {name or 'Unknown service'} at {self.start}"


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
