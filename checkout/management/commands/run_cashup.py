"""Run a cashup (close-out) for a salon.

Usage:
    python manage.py run_cashup --salon-id ID
        --since ISO-DATETIME --until ISO-DATETIME
        [--note TEXT] [--dry-run]

With ``--dry-run`` nothing is created: the command prints the
tender totals a real run over the same period WOULD record --
computed by the read-only :func:`checkout.cashup.compute_tender_totals`
(the same function the service snapshots) and broken down
gross / refunds / voids / net by the read-only
:func:`checkout.cashup_detail.cashup_detail` service -- and
creates no ``Cashup``.

Thin wrapper around the existing
:func:`checkout.cashup.run_cashup` service: the salon is
resolved by id, the datetimes are parsed, and both are passed
to the service verbatim -- the created ``Cashup`` snapshot is
what the summary prints, so command and service can never
disagree -- one source of truth.

A cashup is a snapshot, not a lock: closing more than once a
day is fine, and this command locks nothing. Invalid input --
an unknown salon, an unparseable datetime, or a period the
service rejects -- raises ``CommandError``. Core stays
provider-agnostic -- no payment-provider SDK, field, or name
appears here.
"""
import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.management.base import BaseCommand, CommandError

from checkout.cashup import compute_tender_totals, run_cashup
from checkout.cashup_detail import cashup_detail
from saloncore.models import Salon


def _tz_for(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("UTC")


def _parse_datetime(value, salon, label):
    if isinstance(value, datetime.datetime):
        parsed = value
    else:
        text = str(value).strip()
        try:
            parsed = datetime.datetime.fromisoformat(
                text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise CommandError(
                f"Invalid {label} {value!r}; expected an ISO datetime."
            ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_tz_for(salon))
    return parsed


class Command(BaseCommand):
    help = "Run a cashup (close-out snapshot) for a salon."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon to run the cashup for.",
        )
        parser.add_argument(
            "--since", required=True,
            help="Period start, ISO datetime (inclusive).",
        )
        parser.add_argument(
            "--until", required=True,
            help="Period end, ISO datetime (inclusive).",
        )
        parser.add_argument(
            "--note", default="",
            help="Optional note stored on the cashup.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: print the tender totals a cashup "
                 "over this period would record and create no "
                 "Cashup.",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from exc
        since = _parse_datetime(options["since"], salon, "since")
        until = _parse_datetime(options["until"], salon, "until")
        if options.get("dry_run"):
            if until < since:
                raise CommandError(
                    "cashup period end must not be before its start")
            totals = compute_tender_totals(salon, since, until)
            try:
                detail = cashup_detail(salon, since, until)
            except (TypeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            total = sum(totals.values(), Decimal("0.00"))
            self.stdout.write(
                f"Dry run: no cashup created for salon {salon.pk} "
                f"({salon}): {since.isoformat()} to {until.isoformat()}"
            )
            if totals:
                tenders = ", ".join(
                    f"{method}: {amount}"
                    for method, amount in sorted(totals.items())
                )
            else:
                tenders = "(none)"
            self.stdout.write(f"Tender totals: {tenders}")
            self.stdout.write(f"Total: {total}")
            self.stdout.write(
                f"Detail: gross {detail.gross}, refunds "
                f"{detail.refunds}, voids {detail.voids}, "
                f"net {detail.net}"
            )
            if options["note"]:
                self.stdout.write(f"Note: {options['note']}")
            return
        try:
            cashup = run_cashup(
                salon, since, until, note=options["note"] or "")
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Cashup #{cashup.pk} for salon {salon.pk} ({salon}): "
            f"{cashup.period_start.isoformat()} to "
            f"{cashup.period_end.isoformat()}"
        )
        if cashup.tender_totals:
            tenders = ", ".join(
                f"{method}: {amount}"
                for method, amount in sorted(
                    cashup.tender_totals.items())
            )
        else:
            tenders = "(none)"
        self.stdout.write(f"Tender totals: {tenders}")
        self.stdout.write(f"Total: {cashup.total}")
        if cashup.note:
            self.stdout.write(f"Note: {cashup.note}")
