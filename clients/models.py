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
