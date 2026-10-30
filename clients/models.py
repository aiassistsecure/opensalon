from django.db import models

from saloncore.models import Salon


class Client(models.Model):
    """A salon client.

    Opt-ins default to False: appointment reminders and marketing
    may only ever be sent to clients who have explicitly opted in.
    ``sms_opt_in`` and ``email_opt_in`` are independent and both
    start False.
    """

    salon = models.ForeignKey(
        Salon, on_delete=models.CASCADE, related_name="clients"
    )
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    sms_opt_in = models.BooleanField(default=False)
    email_opt_in = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class ClientNote(models.Model):
    """A persistent client record note.

    Persistent on the client profile across visits; appointment-only
    notes live in the bookings app, never here.
    """

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="notes"
    )
    body = models.TextField()
    author_name = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        text = self.body[:47] + "..." if len(self.body) > 50 else self.body
        return f"Note for {self.client}: {text}"
