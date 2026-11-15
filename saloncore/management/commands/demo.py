"""Seed the demo salon: a fully populated, wholly invented salon.

Usage:
    OPENSALON_DEMO=1 python manage.py demo

Demo mode is how a stranger who clones OpenSalon gets to a
busy, clickable salon in minutes. EVERY record is invented in
code (see :mod:`saloncore.demo_seed`): a fictional salon,
fictional people, plausible invented prices — no real salon's
data is read or named.

The guard is the point: this command REFUSES to run unless the
environment variable ``OPENSALON_DEMO=1`` is set, so it can
never be pointed at a real store by accident. Re-running
rebuilds the demo salon cleanly (same counts every time); only
the salon named "Demo Salon" is ever touched.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from saloncore.demo_seed import seed_demo_salon


class Command(BaseCommand):
    help = "Seed the demo salon (invented data; OPENSALON_DEMO=1 only)."

    def handle(self, *args, **options):
        if os.environ.get("OPENSALON_DEMO") != "1":
            raise CommandError(
                "demo mode is off: set OPENSALON_DEMO=1 to seed the "
                "demo salon. Refusing to write invented data without "
                "it — this guard keeps demo data out of real stores."
            )
        counts = seed_demo_salon()
        self.stdout.write(
            f"Demo salon ready: {counts['salon'].name!r} "
            f"({counts['salon'].timezone}) — all data invented.\n"
            f"  staff {counts['staff']} · services {counts['services']} "
            f"({counts['prices']} prices) · products {counts['products']} "
            f"· clients {counts['clients']} · appointments "
            f"{counts['appointments']} · sales {counts['sales']} "
            f"· refunds {counts['refunds']}\n"
            "To view it, keep OPENSALON_DEMO=1 set (it turns the demo "
            "banner on) with your database env, e.g.:\n"
            "  export OPENSALON_NEDB_EMBEDDED=1\n"
            "  export NEDB_DATA_DIR=<a demo dir>\n"
            "  export OPENSALON_DEMO=1\n"
            "  python manage.py collectstatic\n"
            "  waitress-serve --host 127.0.0.1 --port 8000 "
            "opensalon.wsgi:application\n"
            "  then open http://127.0.0.1:8000/"
        )
