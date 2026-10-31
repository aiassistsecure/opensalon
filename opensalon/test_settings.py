"""Settings tests for the NEDB-shaped DATABASES config (N-M3a)."""
import importlib
import os
from unittest import mock

from django.test import SimpleTestCase

import opensalon.settings as settings_module

DB_ENV = [
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "OPENSALON_USE_SQLITE",
]


def reload_settings(env):
    clean = {k: v for k, v in os.environ.items() if k not in DB_ENV}
    clean.update(env)
    with mock.patch.dict(os.environ, clean, clear=True):
        importlib.reload(settings_module)
        return settings_module.DATABASES["default"]


def reload_time_zone(env):
    clean = {
        k: v for k, v in os.environ.items() if k != "OPENSALON_TIME_ZONE"
    }
    clean.update(env)
    with mock.patch.dict(os.environ, clean, clear=True):
        importlib.reload(settings_module)
        return settings_module.TIME_ZONE, settings_module.USE_TZ


class DatabasesConfigTests(SimpleTestCase):
    def tearDown(self):
        # Restore the module to the environment the test runner used.
        importlib.reload(settings_module)

    def test_defaults_are_nedb_backend_with_port(self):
        db = reload_settings({})
        self.assertEqual(db["ENGINE"], "opensalon.backends.nedb")
        self.assertNotEqual(db["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(db["HOST"], "nedbd")
        self.assertEqual(db["NAME"], "opensalon")
        self.assertEqual(db["USER"], "opensalon")
        self.assertEqual(db["PASSWORD"], "")
        self.assertEqual(db["PORT"], 5432)

    def test_env_overrides_including_port(self):
        db = reload_settings(
            {
                "POSTGRES_HOST": "db.example",
                "POSTGRES_PORT": "15432",
                "POSTGRES_DB": "salonx",
                "POSTGRES_USER": "alice",
                "POSTGRES_PASSWORD": "secret",
            }
        )
        self.assertEqual(db["ENGINE"], "opensalon.backends.nedb")
        self.assertEqual(db["HOST"], "db.example")
        self.assertEqual(db["PORT"], 15432)
        self.assertEqual(db["NAME"], "salonx")
        self.assertEqual(db["USER"], "alice")
        self.assertEqual(db["PASSWORD"], "secret")

    def test_sqlite_only_behind_explicit_flag(self):
        db = reload_settings({"OPENSALON_USE_SQLITE": "1"})
        self.assertEqual(db["ENGINE"], "django.db.backends.sqlite3")
        # Without the flag, SQLite is not selected even with no POSTGRES_* set.
        db = reload_settings({})
        self.assertNotEqual(db["ENGINE"], "django.db.backends.sqlite3")


class TimeZoneConfigTests(SimpleTestCase):
    def tearDown(self):
        # Restore the module to the environment the test runner used.
        importlib.reload(settings_module)

    def test_time_zone_defaults_to_utc(self):
        time_zone, use_tz = reload_time_zone({})
        self.assertEqual(time_zone, "UTC")
        self.assertTrue(use_tz)

    def test_time_zone_env_var_is_honored(self):
        time_zone, use_tz = reload_time_zone(
            {"OPENSALON_TIME_ZONE": "America/New_York"}
        )
        self.assertEqual(time_zone, "America/New_York")
        self.assertTrue(use_tz)
