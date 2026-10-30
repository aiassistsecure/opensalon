"""Evidence probe for the NEDB backend skeleton (NOT a test).

Plain ORM insert/select round-trip on an existing model (saloncore.Salon)
against a real nedbd, using ENGINE="opensalon.backends.nedb". Records
verbatim what worked and what failed; expected known gap: NEDB's
INSERT ... RETURNING yields a NULL pk (DYOR implication 6, later
microtask), so the probe also falls back to a raw ORM query read-back.

Usage (nedbd running, database pre-created over HTTP):
    NEDB_PROBE_DB=opensalon_probe \\
    python opensalon/backends/nedb/evidence_probe.py
Run from the repo root with the project venv active. Env overrides:
NEDB_PROBE_HOST (127.0.0.1), NEDB_PROBE_PORT (5432), NEDB_PROBE_DB.
"""

import os
import sys
import traceback

sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "opensalon.settings")

import django  # noqa: E402

from django.conf import settings  # noqa: E402

settings.DATABASES = {
    "default": {
        "ENGINE": "opensalon.backends.nedb",
        "NAME": os.environ.get("NEDB_PROBE_DB", "opensalon_probe"),
        "HOST": os.environ.get("NEDB_PROBE_HOST", "127.0.0.1"),
        "PORT": os.environ.get("NEDB_PROBE_PORT", "5432"),
        "USER": "opensalon",
        "PASSWORD": "",
    }
}
django.setup()

from django.db import connection  # noqa: E402

from saloncore.models import Salon  # noqa: E402
from team.models import StaffMember  # noqa: E402


def main():
    print("ENGINE:", settings.DATABASES["default"]["ENGINE"])
    print("vendor/display:", connection.vendor, "/", connection.display_name)
    with connection.cursor() as cursor:
        cursor.execute("SELECT version()")
        print("SELECT version() ->", cursor.fetchone()[0])
    try:
        salon = Salon.objects.create(
            name="Evidence Salon", timezone="UTC", currency="USD"
        )
        print("ORM create OK, pk returned:", repr(salon.pk))
    except Exception:
        print("ORM create FAILED:")
        traceback.print_exc()
    try:
        rows = list(Salon.objects.filter(name="Evidence Salon").values())
        print("ORM Salon filter read-back rows:", rows)
    except Exception:
        print("ORM Salon read-back FAILED:")
        traceback.print_exc()
    # Second model, chosen because it has no DateTimeField/DecimalField:
    # team.StaffMember (plain str/int/bool columns + FK ids).
    try:
        member = StaffMember.objects.create(
            salon_id=1, display_name="Evidence Stylist", online_bookable=True
        )
        print("ORM StaffMember create returned, pk:", repr(member.pk))
    except Exception:
        print("ORM StaffMember create FAILED:")
        traceback.print_exc()
    try:
        rows = list(
            StaffMember.objects.filter(display_name="Evidence Stylist").values(
                "display_name", "online_bookable", "salon_id"
            )
        )
        print("ORM StaffMember read-back rows:", rows)
    except Exception:
        print("ORM StaffMember read-back FAILED:")
        traceback.print_exc()


if __name__ == "__main__":
    main()
