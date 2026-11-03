"""Create one draft marketing campaign.

Usage:
    python manage.py create_campaign --salon-id ID --name NAME
        --channel sms|email [--subject SUBJECT] --body BODY
        [--dry-run]

Thin wrapper around :func:`messaging.campaigns.create_campaign`:
the salon is resolved by id and the name/channel/subject/body
are passed to the service verbatim -- its validation (unknown
channel, empty name/body, missing email subject) stays the
single source of truth and surfaces here as ``CommandError``.
The service only ever creates a DRAFT; this command never
sends anything and writes no ``CampaignSend`` rows.

With ``--dry-run`` nothing is created: the command calls the
service's validate-only helper
(:func:`messaging.campaigns.validate_create_campaign`, so the
preview applies the service's own validation with no write at
all -- safe on every backend, including NEDB, where a
rolled-back transaction does not undo writes), resolves the
audience via :func:`messaging.campaigns.audience_for` for the
named channel from reads only, and prints that audience count
only -- no client names or contact details. Output is
counts/ids of the campaign itself only. An unknown salon
raises ``CommandError``, as does any service
``ValidationError``. Backend only -- no views, templates, or
UI. Core stays provider-agnostic -- no provider SDK, field,
or name here.
"""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from messaging.campaigns import (
    audience_for, create_campaign, validate_create_campaign)
from saloncore.models import Salon


def _as_command_error(exc):
    try:
        messages = exc.messages
    except AttributeError:
        messages = [str(exc)]
    return CommandError("; ".join(messages))


class Command(BaseCommand):
    help = "Create a draft marketing campaign (or preview with --dry-run)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon that owns the campaign.")
        parser.add_argument(
            "--name", required=True,
            help="Campaign name.")
        parser.add_argument(
            "--channel", required=True,
            help="Campaign channel: sms or email.")
        parser.add_argument(
            "--subject", default="",
            help="Subject line (required for email campaigns).")
        parser.add_argument(
            "--body", required=True,
            help="Campaign body text.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: validate, print audience count, "
                 "create nothing.")

    def handle(self, *args, **options):
        salon_id = options.get("salon_id")
        if salon_id is None:
            raise CommandError("Provide --salon-id.")
        try:
            salon = Salon.objects.get(pk=salon_id)
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {salon_id}.") from None
        name = options.get("name")
        channel = options.get("channel")
        subject = options.get("subject") or ""
        body = options.get("body")
        if options.get("dry_run"):
            try:
                validate_create_campaign(
                    salon, name, channel, subject=subject, body=body)
                count = audience_for(salon, channel).count()
            except ValidationError as exc:
                raise _as_command_error(exc) from exc
            self.stdout.write(
                f"Dry run: would create draft campaign "
                f"{name!r} ({channel}) for salon {salon.pk}: "
                f"audience {count} -- no campaign created.")
            return
        try:
            campaign = create_campaign(
                salon, name, channel, subject=subject, body=body)
        except ValidationError as exc:
            raise _as_command_error(exc) from exc
        count = audience_for(salon, campaign.channel).count()
        self.stdout.write(
            f"Created draft campaign {campaign.pk} "
            f"({campaign.channel}) for salon {salon.pk}: "
            f"{campaign.name!r} audience {count}.")
