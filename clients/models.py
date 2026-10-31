from django.db import models

from saloncore.models import Salon, StrictConstraints

# N-M17: StrictConstraints rollout (NEDB DYOR §9.3/§9.4) — declared
# Meta.constraints are enforced in the app layer on save(), since
# schemaless NEDB creates no database-level constraints.


class Client(StrictConstraints):
    """A salon client.

    Opt-ins default to False: appointment reminders and marketing
    may only ever be sent to clients who have explicitly opted in.
    ``sms_opt_in`` and ``email_opt_in`` are independent and both
    start False.
    """

    salon = models.ForeignKey(
        Salon, on_delete=models.CASCADE, related_name="clients"
    )
    # Stable id from the system the record was imported from, kept
    # under a generic (not provider-named) field: imports key on
    # (salon, external_id) so re-imports update in place. Blank for
    # clients created directly in OpenSalon.
    external_id = models.CharField(max_length=64, blank=True)
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
        constraints = [
            models.UniqueConstraint(
                fields=["salon", "external_id"],
                condition=models.Q(external_id__gt=""),
                name="uniq_client_external_id_per_salon",
            )
        ]

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
