"""Unit tests for the NEDB backend skeleton (mock-level, no nedbd).

Run with: python manage.py test opensalon.backends.nedb
These tests pin the skeleton's two behaviours: no session-setup SQL,
and no SQL test-database creation.
"""

from unittest import mock

from django.db.backends.postgresql.base import (
    DatabaseWrapper as PostgresDatabaseWrapper,
)
from django.test import SimpleTestCase

from opensalon.backends.nedb.base import DatabaseWrapper
from opensalon.backends.nedb.creation import DatabaseCreation
from opensalon.backends.nedb.operations import DatabaseOperations

NEDB_DATABASES = {
    "default": {
        "ENGINE": "opensalon.backends.nedb",
        "NAME": "opensalon",
        "HOST": "127.0.0.1",
        "PORT": "5432",
        "USER": "opensalon",
        "PASSWORD": "",
    }
}


def _wrapper():
    # Fresh wrapper built straight from a settings dict, never connected.
    settings_dict = {
        **NEDB_DATABASES["default"],
        "OPTIONS": {},
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
    return DatabaseWrapper(settings_dict, "default")


class BackendSelectionTests(SimpleTestCase):
    def test_wrapper_subclasses_postgresql_backend(self):
        self.assertTrue(issubclass(DatabaseWrapper, PostgresDatabaseWrapper))

    def test_engine_loads_this_wrapper(self):
        wrapper = _wrapper()
        self.assertIsInstance(wrapper, DatabaseWrapper)
        self.assertEqual(wrapper.vendor, "postgresql")
        self.assertIs(wrapper.ops_class, DatabaseOperations)
        self.assertIs(wrapper.creation_class, DatabaseCreation)


class NoSessionSetupSqlTests(SimpleTestCase):
    def test_set_time_zone_sql_contains_no_set_config(self):
        wrapper = _wrapper()
        sql = wrapper.ops.set_time_zone_sql()
        self.assertNotIn("set_config", sql)

    def test_configure_connection_is_a_noop(self):
        wrapper = _wrapper()
        fake_connection = mock.Mock()
        self.assertFalse(wrapper._configure_connection(fake_connection))
        self.assertFalse(wrapper._configure_timezone(fake_connection))
        fake_connection.cursor.assert_not_called()

    def test_init_connection_state_sends_nothing(self):
        wrapper = _wrapper()
        with mock.patch.object(wrapper, "_configure_connection") as configure:
            wrapper.init_connection_state()
        configure.assert_not_called()

    def test_ensure_timezone_is_a_noop(self):
        wrapper = _wrapper()
        self.assertFalse(wrapper.ensure_timezone())


class TestDatabaseCreationTests(SimpleTestCase):
    def test_create_test_db_issues_no_sql(self):
        wrapper = _wrapper()
        creation = wrapper.creation
        with mock.patch.object(creation, "_nodb_cursor") as nodb_cursor:
            name = creation._create_test_db(verbosity=0, autoclobber=False)
        self.assertEqual(name, "test_opensalon")
        nodb_cursor.assert_not_called()

    def test_execute_create_test_db_never_touches_cursor(self):
        wrapper = _wrapper()
        cursor = mock.Mock()
        wrapper.creation._execute_create_test_db(cursor, {"dbname": "x"})
        cursor.execute.assert_not_called()

    def test_destroy_test_db_issues_no_sql(self):
        wrapper = _wrapper()
        with mock.patch.object(wrapper.creation, "_nodb_cursor") as nodb_cursor:
            wrapper.creation._destroy_test_db("test_opensalon", verbosity=0)
        nodb_cursor.assert_not_called()
