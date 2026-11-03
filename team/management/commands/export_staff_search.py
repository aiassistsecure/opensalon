"""Export a salon's staff search results as CSV.

Usage: python manage.py export_staff_search --salon-id ID
    [--query TEXT] [--active-only | --inactive-only]
    [--online-bookable-only | --not-online-bookable] [--output PATH]
Thin wrapper around ``team.search_export`` -- that service is the
one source of truth; flag switches map to its tri-state filters
(not given = no filter). Backend only, no provider concepts.
"""
from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon
from team.search_export import export_staff_search_results_csv


class Command(BaseCommand):
    help = "Export a salon's staff search results as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon whose staff to search.")
        parser.add_argument(
            "--query", dest="query", default=None,
            help="Search text matched against display name and "
                 "level name (default: all staff).")
        parser.add_argument(
            "--active-only", action="store_true",
            help="Only active staff members.")
        parser.add_argument(
            "--inactive-only", action="store_true",
            help="Only inactive staff members.")
        parser.add_argument(
            "--online-bookable-only", action="store_true",
            help="Only staff bookable online.")
        parser.add_argument(
            "--not-online-bookable", action="store_true",
            help="Only staff not bookable online.")
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).")

    def handle(self, *args, **options):
        if options["active_only"] and options["inactive_only"]:
            raise CommandError(
                "--active-only and --inactive-only conflict.")
        if options["online_bookable_only"] and options["not_online_bookable"]:
            raise CommandError(
                "--online-bookable-only and --not-online-bookable conflict.")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None
        active = (
            True if options["active_only"]
            else False if options["inactive_only"] else None)
        online = (
            True if options["online_bookable_only"]
            else False if options["not_online_bookable"] else None)
        try:
            text = export_staff_search_results_csv(
                salon, query=options.get("query"), active=active,
                online_bookable=online)
        except Exception as exc:
            raise CommandError(
                f"Staff search export failed: {exc}") from exc
        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8",
                          newline="") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(text, ending="")
