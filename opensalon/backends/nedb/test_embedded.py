"""Tests for the NEDB backend's embedded (in-process) mode.

Run with: python manage.py test opensalon.backends.nedb.test_embedded

The selection unit tests run anywhere. The cursor classes need the
nedb-engine wheel importable (they skip unless ``nedb.__has_native__``)
and the acceptance class additionally needs
``OPENSALON_NEDB_EMBEDDED_TEST=1`` -- the same guarded-live pattern as
``NedbTestDatabaseLifecycleLiveTests`` in tests.py.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from opensalon.backends.nedb import embedded
from opensalon.backends.nedb.base import DatabaseWrapper
from opensalon.backends.nedb.embedded import EmbeddedConnection


def _native_available():
    try:
        import nedb
    except ImportError:
        return False
    return bool(getattr(nedb, "__has_native__", False))


def _settings(root, name, **options):
    return {
        "ENGINE": "opensalon.backends.nedb",
        "NAME": name,
        # A dead pgwire port on purpose: anything that reaches for the
        # daemon path in these tests fails loudly instead of passing
        # by accident against a daemon that happens to be running.
        "HOST": "127.0.0.1",
        "PORT": "59999",
        "USER": "opensalon",
        "PASSWORD": "",
        "OPTIONS": {"nedb_embedded": True, "nedb_data_dir": root, **options},
        "TIME_ZONE": None,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "AUTOCOMMIT": True,
        "TEST": {
            "CHARSET": None,
            "COLLATION": None,
            "MIGRATE": True,
            "MIRROR": None,
            "NAME": None,
        },
    }


class EmbeddedSelectionTests(SimpleTestCase):
    def test_env_selects_embedded(self):
        with mock.patch.dict(os.environ, {"OPENSALON_NEDB_EMBEDDED": "1"}):
            self.assertTrue(embedded.embedded_enabled({}))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENSALON_NEDB_EMBEDDED", None)
            self.assertFalse(embedded.embedded_enabled({}))

    def test_options_select_embedded(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENSALON_NEDB_EMBEDDED", None)
            settings = {"OPTIONS": {"nedb_embedded": True}}
            self.assertTrue(embedded.embedded_enabled(settings))

    def test_data_root_is_required(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NEDB_DATA_DIR", None)
            with self.assertRaises(RuntimeError):
                embedded.data_root({"OPTIONS": {}})

    def test_wrapper_returns_embedded_connection(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        wrapper = DatabaseWrapper(_settings(root, "selection_probe"), "default")
        connection = wrapper.get_new_connection({})
        self.assertIsInstance(connection, EmbeddedConnection)


class EmbeddedStatementShapeTests(SimpleTestCase):
    def test_verb_skips_comments(self):
        self.assertEqual(
            embedded._statement_verb("/* x */ -- y\n update t set a=1"),
            "UPDATE",
        )

    def test_values_tuple_count(self):
        sql = (
            'INSERT INTO "t" ("id", "name") VALUES (1, \'a\'), '
            "(2, 'b, (c)'), (3, 'd') RETURNING \"id\""
        )
        self.assertEqual(embedded._values_tuple_count(sql), 3)
        self.assertEqual(embedded._values_tuple_count("SELECT 1"), 0)


@unittest.skipUnless(_native_available(), "nedb native core not importable")
class EmbeddedRowcountTests(SimpleTestCase):
    """The spike's one deterministic defect: writes reported rowcount 0."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.name = "rc_" + uuid.uuid4().hex[:12]
        self.settings = _settings(self.root, self.name)
        core = embedded.core_for(self.name, self.settings)
        # Materialize the scratch table the way creation.py does.
        core.put("rowcount_t", "__opensalon_materialized__", '{"id": 0}')
        core.delete("rowcount_t", "__opensalon_materialized__")
        self.connection = EmbeddedConnection(self.name, self.settings)

    def cursor(self):
        return self.connection.cursor()

    def test_insert_values_rowcount(self):
        with self.cursor() as cur:
            cur.execute(
                'INSERT INTO "rowcount_t" ("id", "name") '
                "VALUES (%s, %s), (%s, %s)",
                [1, "a", 2, "b"],
            )
            self.assertEqual(cur.rowcount, 2)

    def test_insert_returning_rowcount(self):
        with self.cursor() as cur:
            cur.execute(
                'INSERT INTO "rowcount_t" ("id", "name") '
                'VALUES (1, \'a\') RETURNING "id"'
            )
            self.assertEqual(cur.rowcount, 1)
            self.assertIsNotNone(cur.fetchone())

    def test_update_and_delete_rowcount(self):
        with self.cursor() as cur:
            cur.execute(
                'INSERT INTO "rowcount_t" ("id", "name") '
                "VALUES (1, 'a'), (2, 'b')"
            )
            cur.execute(
                'UPDATE "rowcount_t" SET "name" = \'z\' '
                'WHERE "rowcount_t"."id" = 1'
            )
            self.assertEqual(cur.rowcount, 1)
            cur.execute(
                'UPDATE "rowcount_t" SET "name" = \'z\' '
                'WHERE "rowcount_t"."id" = 999'
            )
            self.assertEqual(cur.rowcount, 0)
            cur.execute('SELECT "name" FROM "rowcount_t" WHERE "id" = 1')
            self.assertEqual(cur.fetchone()[0], "z")
            self.assertEqual(cur.rowcount, 1)
            cur.execute(
                'DELETE FROM "rowcount_t" WHERE "rowcount_t"."id" = 2'
            )
            self.assertEqual(cur.rowcount, 1)


_PROBE = """
import json
from django.utils import timezone
from saloncore.models import Salon
from checkout.models import Sale
from checkout.summary import daily_sales_summary

salon = Salon.objects.create(name="Embedded Acceptance Salon")
now = timezone.now()
for amount, status in [
    ("2.50", Sale.Status.COMPLETED),
    ("3.25", Sale.Status.COMPLETED),
    ("0.00", Sale.Status.COMPLETED),
    ("99.00", Sale.Status.VOIDED),
]:
    Sale.objects.create(
        salon=salon, status=status, discount_amount=amount,
        completed_at=now,
    )
summary = daily_sales_summary(salon, now.date())
sale = Sale.objects.filter(salon=salon, status=Sale.Status.COMPLETED).first()
sale.void_reason = "probe"
sale.save(update_fields=["void_reason"])
print("PROBE_RESULT " + json.dumps({
    "discount_total": str(summary.discount_total),
    "sales_count": summary.sales_count,
    "update_fields": "ok",
}))
"""


@unittest.skipUnless(_native_available(), "nedb native core not importable")
@unittest.skipUnless(
    os.environ.get("OPENSALON_NEDB_EMBEDDED_TEST") == "1",
    "embedded acceptance: set OPENSALON_NEDB_EMBEDDED_TEST=1",
)
class EmbeddedAcceptanceTests(SimpleTestCase):
    """Migrate + the box-killer SUM + update_fields, daemon-free."""

    def test_migrate_sum_and_update_fields_embedded(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        repo = Path(__file__).resolve().parents[3]
        db_name = "embedded_acceptance"
        env = {
            **os.environ,
            "OPENSALON_NEDB_EMBEDDED": "1",
            "NEDB_DATA_DIR": root,
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": "59999",  # dead: no daemon may be involved
            "POSTGRES_DB": db_name,
        }
        env.pop("OPENSALON_USE_SQLITE", None)

        migrate = subprocess.run(
            [sys.executable, "manage.py", "migrate", "--noinput"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            timeout=900,
        )
        self.assertEqual(
            migrate.returncode, 0, migrate.stdout[-2000:] + migrate.stderr[-2000:]
        )

        probe = subprocess.run(
            [sys.executable, "manage.py", "shell"],
            cwd=repo,
            env=env,
            input=_PROBE,
            capture_output=True,
            text=True,
            timeout=900,
        )
        self.assertEqual(
            probe.returncode, 0, probe.stdout[-2000:] + probe.stderr[-2000:]
        )
        result = None
        for line in probe.stdout.splitlines():
            if line.startswith("PROBE_RESULT "):
                result = json.loads(line[len("PROBE_RESULT ") :])
        self.assertIsNotNone(result, probe.stdout[-2000:])
        # The aggregate that killed the daemon connection on the pilot
        # box: SUM(discount_amount) over real ORM sales, voided excluded.
        self.assertEqual(result["discount_total"], "5.75")
        self.assertEqual(result["sales_count"], 3)
        self.assertEqual(result["update_fields"], "ok")

        # Reopen the same store in-process: chain verifies, and the
        # migration recorder rows the subprocess wrote are all there.
        settings = _settings(root, db_name)
        core = embedded.core_for(db_name, settings)
        self.assertTrue(core.verify())
        rows = core.nesql('SELECT "id" FROM "django_migrations"')
        self.assertGreaterEqual(len(rows), 59)
