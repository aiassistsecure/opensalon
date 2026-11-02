"""Unit tests for the NEDB backend (mock-level, no nedbd).

Run with: python manage.py test opensalon.backends.nedb
These tests pin: no session-setup SQL, no SQL test-database creation,
the schema editor's catalog-validating no-op DDL handling (N-M3d),
savepoint no-ops so nested atomic() sends no savepoint SQL (N-M3e), and
no FOR UPDATE clause from select_for_update() (N-M3i, DYOR 9.7).
"""

from unittest import mock

from django.db.backends.postgresql.base import (
    DatabaseWrapper as PostgresDatabaseWrapper,
)
from django.test import SimpleTestCase

from opensalon.backends.nedb.base import DatabaseWrapper
from opensalon.backends.nedb.creation import DatabaseCreation
from opensalon.backends.nedb.features import DatabaseFeatures
from opensalon.backends.nedb.operations import DatabaseOperations
from opensalon.backends.nedb.schema import (
    DatabaseSchemaEditor,
    UncataloguedTableError,
    declared_catalog,
)

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


import os
import unittest


def _fake_http(existing=()):
    """Fake _http_request: records calls, serves a name registry."""
    calls = []
    names = set(existing)

    def fake(method, path, payload=None):
        calls.append((method, path, payload))
        if method == "GET" and path == "/v1/databases":
            return {"databases": [{"name": n} for n in sorted(names)]}
        if method == "POST" and path == "/v1/databases":
            names.add(payload["name"])
            return {"database": {"name": payload["name"]}}
        if method == "POST" and path.endswith("/batch"):
            return {"results": [], "count": len(payload["ops"])}
        if method == "DELETE" and path.startswith("/v1/databases/"):
            names.discard(path.rsplit("/", 1)[1])
            return {}
        raise AssertionError("unexpected HTTP call %s %s" % (method, path))

    return fake, calls, names


class TestDatabaseCreationTests(SimpleTestCase):
    def test_create_test_db_issues_no_sql_and_resets_over_http(self):
        wrapper = _wrapper()
        creation = wrapper.creation
        fake, calls, names = _fake_http(existing={"test_opensalon"})
        with mock.patch.object(creation, "_nodb_cursor") as nodb_cursor, \
                mock.patch.object(creation, "_http_request", fake):
            name = creation._create_test_db(verbosity=0, autoclobber=False)
        self.assertEqual(name, "test_opensalon")
        nodb_cursor.assert_not_called()
        methods = [c[0] for c in calls]
        # drop, confirm absent, recreate -- in that order, HTTP only.
        self.assertEqual(methods[0], "DELETE")
        self.assertEqual(methods[-1], "POST")
        self.assertIn("test_opensalon", names)

    def test_create_test_db_keepdb_ensures_without_wiping(self):
        wrapper = _wrapper()
        creation = wrapper.creation
        fake, calls, names = _fake_http(existing={"test_opensalon"})
        with mock.patch.object(creation, "_http_request", fake):
            name = creation._create_test_db(
                verbosity=0, autoclobber=False, keepdb=True
            )
        self.assertEqual(name, "test_opensalon")
        self.assertEqual([c[0] for c in calls], ["GET"])  # exists: no POST

    def test_execute_create_test_db_never_touches_cursor(self):
        wrapper = _wrapper()
        creation = wrapper.creation
        fake, calls, names = _fake_http()
        cursor = mock.Mock()
        with mock.patch.object(creation, "_http_request", fake):
            creation._execute_create_test_db(cursor, {"dbname": '"x"'})
        cursor.execute.assert_not_called()
        self.assertEqual(calls, [("POST", "/v1/databases", {"name": "x"})])

    def test_destroy_test_db_is_drop_plus_recreate_over_http(self):
        wrapper = _wrapper()
        creation = wrapper.creation
        fake, calls, names = _fake_http(existing={"test_opensalon"})
        with mock.patch.object(creation, "_nodb_cursor") as nodb_cursor, \
                mock.patch.object(creation, "_http_request", fake):
            result = creation._destroy_test_db("test_opensalon", verbosity=0)
        nodb_cursor.assert_not_called()
        self.assertEqual(result, "test_opensalon")
        pairs = [(c[0], c[1]) for c in calls]
        self.assertEqual(pairs[0], ("DELETE", "/v1/databases/test_opensalon"))
        self.assertEqual(pairs[-2], ("POST", "/v1/databases"))
        # N-M8c: the recreate is followed by catalog materialization.
        self.assertEqual(
            pairs[-1], ("POST", "/v1/databases/test_opensalon/batch")
        )
        self.assertIn("test_opensalon", names)  # recreated empty

    def test_drop_missing_database_is_success(self):
        from opensalon.backends.nedb.creation import NedbHttpError

        wrapper = _wrapper()
        creation = wrapper.creation

        def gone(method, path, payload=None):
            raise NedbHttpError("missing", status=404)

        with mock.patch.object(creation, "_http_request", gone):
            self.assertFalse(creation.drop_database("nope"))

    def test_create_http_failure_exits_like_postgres(self):
        from opensalon.backends.nedb.creation import NedbHttpError

        wrapper = _wrapper()
        creation = wrapper.creation

        def down(method, path, payload=None):
            raise NedbHttpError("unreachable")

        with mock.patch.object(creation, "_http_request", down), \
                mock.patch.object(creation, "log", lambda *a: None):
            with self.assertRaises(SystemExit):
                creation._create_test_db(verbosity=0, autoclobber=False)

    def test_http_base_url_defaults_to_spike_port(self):
        wrapper = _wrapper()
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(
                wrapper.creation.http_base_url(), "http://127.0.0.1:17070"
            )

    def test_http_base_url_env_wins(self):
        wrapper = _wrapper()
        with mock.patch.dict("os.environ", {"NEDBD_URL": "http://db:9999/"}):
            self.assertEqual(wrapper.creation.http_base_url(), "http://db:9999")

    def test_clone_test_db_creates_empty_db_over_http(self):
        wrapper = _wrapper()
        creation = wrapper.creation
        fake, calls, names = _fake_http()
        with mock.patch.object(creation, "_http_request", fake):
            creation._clone_test_db("2", verbosity=0)
        self.assertIn("opensalon_2", names)


class FlushNeverTruncateTests(SimpleTestCase):
    def test_sql_flush_builds_no_statements(self):
        from django.core.management.color import no_style

        wrapper = _wrapper()
        sql = wrapper.ops.sql_flush(
            no_style(), ["saloncore_salon", "clients_client"],
            reset_sequences=True, allow_cascade=True,
        )
        self.assertEqual(sql, [])
        self.assertNotIn("TRUNCATE", " ".join(sql))

    def test_execute_sql_flush_resets_database_over_http(self):
        wrapper = _wrapper()
        with mock.patch.object(
            DatabaseCreation, "reset_database", autospec=True
        ) as reset:
            wrapper.ops.execute_sql_flush(["TRUNCATE anything;"])
        reset.assert_called_once()
        self.assertEqual(reset.call_args[0][1], "opensalon")


class TestIsolationFeatureTests(SimpleTestCase):
    """N-M6a: TestCase must isolate by flush, not rollback (DYOR 9.4)."""

    def test_supports_transactions_is_false(self):
        # A pgwire ROLLBACK does not remove appended rows, so the
        # backend must not claim transaction support: Django's
        # TestCase checks this flag and, when False, behaves as
        # TransactionTestCase (flush between tests) instead of
        # entering a rollback wrap that would leak rows.
        wrapper = _wrapper()
        self.assertIs(wrapper.features_class, DatabaseFeatures)
        self.assertFalse(wrapper.features.supports_transactions)

    def test_testcase_support_probe_sees_no_transactions(self):
        from django.test.testcases import connections_support_transactions

        wrapper = _wrapper()
        with mock.patch(
            "django.test.testcases.connections"
        ) as conns:
            conns.all.return_value = [wrapper]
            self.assertFalse(connections_support_transactions())

    def test_isolation_path_is_the_http_flush(self):
        # The flush TransactionTestCase teardown calls is the
        # drop + recreate reset over HTTP, never TRUNCATE (9.5).
        wrapper = _wrapper()
        with mock.patch.object(
            DatabaseCreation, "reset_database", autospec=True
        ) as reset:
            wrapper.ops.execute_sql_flush([])
        reset.assert_called_once()


@unittest.skipUnless(
    os.environ.get("OPENSALON_NEDB_LIVE_TEST") == "1",
    "live nedbd test-database lifecycle: set OPENSALON_NEDB_LIVE_TEST=1 "
    "with nedbd running (HTTP 17070) and the NEDB backend configured",
)
class NedbTestDatabaseLifecycleLiveTests(SimpleTestCase):
    """N-M3h acceptance against a real nedbd (guarded, never offline)."""

    def test_create_reset_drop_over_http(self):
        from django.db import connection

        self.assertEqual(connection.display_name, "NEDB (PostgreSQL pgwire)")
        creation = connection.creation
        probe = "opensalon_nm3h_probe"
        try:
            self.assertTrue(creation.ensure_database(probe))
            self.assertTrue(creation.database_exists(probe))
            self.assertFalse(creation.ensure_database(probe))
            creation.reset_database(probe)
            self.assertTrue(creation.database_exists(probe))
        finally:
            creation.drop_database(probe)
        self.assertFalse(creation.database_exists(probe))


def _editor(catalog=None, collect_sql=False):
    """Schema editor on a never-connected wrapper with a mock cursor."""
    wrapper = _wrapper()
    cursor = mock.Mock(name="cursor")
    cursor_cm = mock.MagicMock(name="cursor_context")
    cursor_cm.__enter__.return_value = cursor
    wrapper.cursor = mock.Mock(return_value=cursor_cm)
    kwargs = {}
    if catalog is not None:
        kwargs["catalog"] = catalog
    editor = DatabaseSchemaEditor(
        wrapper, collect_sql=collect_sql, atomic=False, **kwargs
    )
    editor.deferred_sql = []
    return editor, wrapper, cursor


KNOWN_DDL = [
    'CREATE TABLE "saloncore_salon" ("id" bigint NOT NULL PRIMARY KEY)',
    'ALTER TABLE "saloncore_salon" ADD COLUMN "name" varchar(100) NOT NULL',
    'ALTER TABLE "clients_client" ADD CONSTRAINT "fk" FOREIGN KEY '
    '("salon_id") REFERENCES "saloncore_salon" ("id")',
    'CREATE INDEX "idx" ON "saloncore_salon" ("name")',
    'DROP INDEX IF EXISTS "saloncore_salon_name_idx"',
    'DROP TABLE IF EXISTS "saloncore_salon" CASCADE',
    'TRUNCATE TABLE "saloncore_salon"',
    'COMMENT ON TABLE "saloncore_salon" IS \'x\'',
    'GRANT SELECT ON TABLE "saloncore_salon" TO "opensalon"',
    'CREATE TABLE "django_migrations" ("id" bigint NOT NULL PRIMARY KEY)',
]


class SchemaEditorCatalogTests(SimpleTestCase):
    def test_declared_catalog_covers_registry_and_migrations_table(self):
        catalog = declared_catalog()
        self.assertIn("saloncore_salon", catalog)
        self.assertIn("clients_client", catalog)
        self.assertIn("django_migrations", catalog)
        self.assertNotIn("ghost_table", catalog)

    def test_wrapper_uses_nedb_schema_editor(self):
        self.assertIs(_wrapper().SchemaEditorClass, DatabaseSchemaEditor)


class SchemaEditorNoOpDdlTests(SimpleTestCase):
    def test_known_ddl_sends_zero_statements(self):
        editor, wrapper, cursor = _editor()
        for sql in KNOWN_DDL:
            with self.subTest(sql=sql[:40]):
                self.assertIsNone(editor.execute(sql, None))
        wrapper.cursor.assert_not_called()
        cursor.execute.assert_not_called()

    def test_ddl_with_params_still_sends_nothing(self):
        editor, wrapper, cursor = _editor()
        editor.execute(
            'CREATE TABLE "team_staffmember" ("id" bigint NOT NULL)', ()
        )
        wrapper.cursor.assert_not_called()
        cursor.execute.assert_not_called()

    def test_collect_sql_collects_no_ddl(self):
        editor, wrapper, cursor = _editor(collect_sql=True)
        editor.execute(KNOWN_DDL[0], None)
        self.assertEqual(editor.collected_sql, [])
        cursor.execute.assert_not_called()

    def test_deferred_sql_is_validated_and_skipped_on_exit(self):
        editor, wrapper, cursor = _editor()
        with editor:
            editor.deferred_sql.append(
                'CREATE INDEX "d_idx" ON "saloncore_salon" ("name")'
            )
        wrapper.cursor.assert_not_called()
        cursor.execute.assert_not_called()

    def test_create_model_for_catalogued_model_sends_nothing(self):
        from saloncore.models import Salon

        editor, wrapper, cursor = _editor()
        with editor:
            editor.create_model(Salon)
        wrapper.cursor.assert_not_called()
        cursor.execute.assert_not_called()


class SchemaEditorCatalogValidationTests(SimpleTestCase):
    def test_unknown_create_table_raises_and_sends_nothing(self):
        editor, wrapper, cursor = _editor()
        with self.assertRaises(UncataloguedTableError):
            editor.execute('CREATE TABLE "ghost_table" ("id" bigint)', None)
        wrapper.cursor.assert_not_called()
        cursor.execute.assert_not_called()

    def test_unknown_alter_and_reference_targets_raise(self):
        editor, wrapper, cursor = _editor()
        for sql in (
            'ALTER TABLE "ghost_table" ADD COLUMN "x" int',
            'ALTER TABLE "clients_client" ADD CONSTRAINT "fk" FOREIGN KEY '
            '("s") REFERENCES "ghost_table" ("id")',
        ):
            with self.subTest(sql=sql[:40]):
                with self.assertRaises(UncataloguedTableError):
                    editor.execute(sql, None)
        cursor.execute.assert_not_called()

    def test_injected_catalog_governs_validation(self):
        editor, wrapper, cursor = _editor(catalog={"only_table"})
        editor.execute('CREATE TABLE "only_table" ("id" bigint)', None)
        with self.assertRaises(UncataloguedTableError):
            editor.execute(KNOWN_DDL[0], None)
        cursor.execute.assert_not_called()

    def test_non_ddl_passes_through_to_cursor(self):
        editor, wrapper, cursor = _editor()
        editor.execute('UPDATE "saloncore_salon" SET "name" = %s', None)
        cursor.execute.assert_called_once()


def _savepoint_wrapper():
    """Wrapper in a transaction, backed by a mock cursor/connection."""
    wrapper = _wrapper()
    cursor = mock.Mock(name="cursor")
    cursor_cm = mock.MagicMock(name="cursor_context")
    cursor_cm.__enter__.return_value = cursor
    wrapper.cursor = mock.Mock(return_value=cursor_cm)
    wrapper.connection = mock.Mock(name="connection")
    wrapper.autocommit = False
    return wrapper, cursor


class SavepointFeatureTests(SimpleTestCase):
    def test_wrapper_uses_nedb_features_without_savepoints(self):
        wrapper = _wrapper()
        self.assertIs(wrapper.features_class, DatabaseFeatures)
        self.assertFalse(wrapper.features.uses_savepoints)
        self.assertFalse(wrapper.features.can_release_savepoints)

    def test_savepoint_not_allowed_in_transaction(self):
        wrapper, cursor = _savepoint_wrapper()
        self.assertFalse(wrapper._savepoint_allowed())
        wrapper.cursor.assert_not_called()


class SavepointNoOpTests(SimpleTestCase):
    def test_public_savepoint_methods_are_inert(self):
        wrapper, cursor = _savepoint_wrapper()
        self.assertIsNone(wrapper.savepoint())
        # Even a fabricated sid must not produce SQL on rollback/commit.
        wrapper.savepoint_rollback("s1_x1")
        wrapper.savepoint_commit("s1_x1")
        wrapper.cursor.assert_not_called()
        cursor.execute.assert_not_called()

    def test_private_hooks_are_inert(self):
        wrapper, cursor = _savepoint_wrapper()
        self.assertIsNone(wrapper._savepoint("s1_x1"))
        self.assertIsNone(wrapper._savepoint_rollback("s1_x1"))
        self.assertIsNone(wrapper._savepoint_commit("s1_x1"))
        wrapper.cursor.assert_not_called()
        cursor.execute.assert_not_called()

    def test_operations_build_no_savepoint_sql(self):
        wrapper = _wrapper()
        self.assertIsNone(wrapper.ops.savepoint_create_sql("s1"))
        self.assertIsNone(wrapper.ops.savepoint_commit_sql("s1"))
        self.assertIsNone(wrapper.ops.savepoint_rollback_sql("s1"))


class NestedAtomicSavepointTests(SimpleTestCase):
    def test_nested_atomic_emits_zero_savepoint_sql(self):
        from django.db.transaction import Atomic

        wrapper, cursor = _savepoint_wrapper()
        wrapper.autocommit = True
        wrapper.connection = mock.Mock(name="connection")

        def _set_autocommit(value, **kwargs):
            wrapper.autocommit = value

        wrapper.set_autocommit = _set_autocommit
        get_conn = "django.db.transaction.get_connection"
        with mock.patch(get_conn, return_value=wrapper):
            with Atomic("default", savepoint=True, durable=False):
                with Atomic("default", savepoint=True, durable=False):
                    pass
            with self.assertRaises(RuntimeError):
                with Atomic("default", savepoint=True, durable=False):
                    with Atomic("default", savepoint=True, durable=False):
                        raise RuntimeError("inner failure")
        wrapper.cursor.assert_not_called()
        cursor.execute.assert_not_called()
        executed = [
            str(call) for call in cursor.execute.call_args_list
        ]
        self.assertFalse(
            any("SAVEPOINT" in call for call in executed)
        )


# -- N-M3f: temporal adaptation --------------------------------------

import datetime
import os
import unittest

from django.utils import timezone as dj_timezone

from opensalon.backends.nedb import temporal

AWARE_DT = datetime.datetime(
    2026, 10, 30, 14, 15, 16, 123456, tzinfo=datetime.timezone.utc
)
NAIVE_DT = datetime.datetime(2026, 10, 30, 9, 30, 0)
A_DATE = datetime.date(2026, 10, 30)
A_TIME = datetime.time(9, 30, 15)


class TemporalAdaptTests(SimpleTestCase):
    def test_datetime_adapts_to_iso_string(self):
        wrapper = _wrapper()
        adapted = wrapper.ops.adapt_datetimefield_value(AWARE_DT)
        self.assertIsInstance(adapted, str)
        self.assertEqual(adapted, "2026-10-30T14:15:16.123456+00:00")
        self.assertNotIn("::", adapted)

    def test_naive_datetime_adapts_to_iso_string(self):
        self.assertEqual(
            temporal.adapt_datetime_value(NAIVE_DT), "2026-10-30T09:30:00"
        )

    def test_non_utc_aware_normalizes_to_utc(self):
        # N-M13 (DYOR §9.1/§9.9): -05:00 bound must become UTC shape.
        est = datetime.timezone(datetime.timedelta(hours=-5))
        value = datetime.datetime(2026, 11, 2, 0, 0, tzinfo=est)
        self.assertEqual(
            temporal.adapt_datetime_value(value),
            "2026-11-02T05:00:00+00:00",
        )
        wrapper = _wrapper()
        self.assertEqual(
            wrapper.ops.adapt_datetimefield_value(value),
            "2026-11-02T05:00:00+00:00",
        )

    def test_utc_aware_unchanged_and_naive_unchanged(self):
        # N-M13 (DYOR §9.1/§9.9): UTC stays identical; naive keeps no offset.
        self.assertEqual(
            temporal.adapt_datetime_value(AWARE_DT),
            "2026-10-30T14:15:16.123456+00:00",
        )
        self.assertEqual(
            temporal.adapt_datetime_value(NAIVE_DT), "2026-10-30T09:30:00"
        )

    def test_date_and_time_adapt_to_iso_strings(self):
        wrapper = _wrapper()
        self.assertEqual(wrapper.ops.adapt_datefield_value(A_DATE), "2026-10-30")
        self.assertEqual(wrapper.ops.adapt_timefield_value(A_TIME), "09:30:15")

    def test_none_passes_through_all_adapters(self):
        wrapper = _wrapper()
        self.assertIsNone(wrapper.ops.adapt_datetimefield_value(None))
        self.assertIsNone(wrapper.ops.adapt_datefield_value(None))
        self.assertIsNone(wrapper.ops.adapt_timefield_value(None))

    def test_expression_passes_through_untouched(self):
        expr = mock.Mock(name="expression")
        expr.resolve_expression = lambda *a, **k: expr
        wrapper = _wrapper()
        self.assertIs(wrapper.ops.adapt_datetimefield_value(expr), expr)
        self.assertIs(wrapper.ops.adapt_datefield_value(expr), expr)

    def test_adapt_unknown_value_uses_temporal_strings(self):
        # Raw-query / unknown-type adaptation routes through the same
        # hooks (BaseDatabaseOperations.adapt_unknown_value).
        wrapper = _wrapper()
        self.assertEqual(
            wrapper.ops.adapt_unknown_value(AWARE_DT),
            "2026-10-30T14:15:16.123456+00:00",
        )
        self.assertEqual(wrapper.ops.adapt_unknown_value(A_DATE), "2026-10-30")
        self.assertEqual(wrapper.ops.adapt_unknown_value(A_TIME), "09:30:15")

    def test_iso_strings_sort_chronologically(self):
        earlier = temporal.adapt_datetime_value(NAIVE_DT)
        later = temporal.adapt_datetime_value(
            NAIVE_DT + datetime.timedelta(hours=2)
        )
        self.assertLess(earlier, later)


class TemporalConvertTests(SimpleTestCase):
    def _converters(self, field):
        wrapper = _wrapper()
        expr = mock.Mock()
        expr.output_field = field
        return wrapper, wrapper.ops.get_db_converters(expr)

    def test_converters_registered_per_temporal_type(self):
        from django.db import models

        cases = [
            (models.DateTimeField(), "convert_datetimefield_value"),
            (models.DateField(), "convert_datefield_value"),
            (models.TimeField(), "convert_timefield_value"),
        ]
        for field, name in cases:
            with self.subTest(name=name):
                wrapper, converters = self._converters(field)
                self.assertIn(getattr(wrapper.ops, name), converters)

    def test_no_converter_for_non_temporal_field(self):
        from django.db import models

        wrapper, converters = self._converters(models.CharField())
        self.assertEqual(converters, [])

    def test_convert_parses_stored_strings_back(self):
        wrapper = _wrapper()
        conn = mock.Mock()
        conn.timezone = datetime.timezone.utc
        expr = mock.Mock()
        self.assertEqual(
            wrapper.ops.convert_datetimefield_value(
                "2026-10-30T14:15:16.123456+00:00", expr, conn
            ),
            AWARE_DT,
        )
        self.assertEqual(
            wrapper.ops.convert_datefield_value("2026-10-30", expr, conn),
            A_DATE,
        )
        self.assertEqual(
            wrapper.ops.convert_timefield_value("09:30:15", expr, conn),
            A_TIME,
        )

    def test_convert_passes_objects_and_none_through(self):
        wrapper = _wrapper()
        conn = mock.Mock()
        conn.timezone = datetime.timezone.utc
        expr = mock.Mock()
        self.assertIs(
            wrapper.ops.convert_datetimefield_value(AWARE_DT, expr, conn),
            AWARE_DT,
        )
        self.assertIsNone(
            wrapper.ops.convert_datetimefield_value(None, expr, conn)
        )
        self.assertIsNone(wrapper.ops.convert_datefield_value(None, expr, conn))
        self.assertIsNone(wrapper.ops.convert_timefield_value(None, expr, conn))

    def test_adapt_convert_round_trip(self):
        wrapper = _wrapper()
        conn = mock.Mock()
        conn.timezone = datetime.timezone.utc
        expr = mock.Mock()
        for value, adapt, convert in (
            (AWARE_DT, "adapt_datetimefield_value", "convert_datetimefield_value"),
            (A_DATE, "adapt_datefield_value", "convert_datefield_value"),
            (A_TIME, "adapt_timefield_value", "convert_timefield_value"),
        ):
            with self.subTest(convert=convert):
                stored = getattr(wrapper.ops, adapt)(value)
                self.assertIsInstance(stored, str)
                self.assertEqual(
                    getattr(wrapper.ops, convert)(stored, expr, conn), value
                )


@unittest.skipUnless(
    os.environ.get("OPENSALON_NEDB_LIVE_TEST") == "1",
    "live nedbd round-trip: set OPENSALON_NEDB_LIVE_TEST=1 with the "
    "default connection on the NEDB backend (nedbd running, test "
    "database pre-created over HTTP)",
)
class NedbTemporalRoundTripLiveTests(SimpleTestCase):
    """Salon ORM round-trip against a real nedbd (N-M3f acceptance).

    Guarded: only runs in a dedicated live invocation, never in the
    SQLite suite. Salon has auto_now_add/auto_now DateTimeFields, the
    exact shape NEDB refused before this adaptation (EVIDENCE.md).

    N-M6g: this test previously asserted
    ``type(connection).__module__ == "opensalon.backends.nedb.base"``,
    which can never pass -- ``django.db.connection`` is a
    ``django.utils.connection.ConnectionProxy``, so its type's module
    is always ``django.utils.connection`` regardless of the backend
    in use. The temporal round-trip underneath was sound (probe:
    stored ISO strings read back as aware datetimes in range). Like
    every other live test in this file, assert on the proxied
    backend's ``display_name`` instead.
    """

    databases = {"default"}

    def test_salon_datetime_round_trip(self):
        from django.db import connection

        # connection is a proxy object; check the backend it wraps.
        self.assertEqual(connection.display_name, "NEDB (PostgreSQL pgwire)")
        from saloncore.models import Salon

        before = dj_timezone.now()
        Salon.objects.create(name="Temporal Probe Salon", timezone="UTC")
        row = Salon.objects.filter(name="Temporal Probe Salon").values(
            "name", "created_at", "updated_at"
        ).first()
        self.assertIsNotNone(row)
        self.assertIsInstance(row["created_at"], datetime.datetime)
        self.assertIsInstance(row["updated_at"], datetime.datetime)
        self.assertGreaterEqual(row["created_at"], before)
        self.assertLessEqual(
            row["created_at"], dj_timezone.now() + datetime.timedelta(minutes=1)
        )


@unittest.skipUnless(
    os.environ.get("OPENSALON_NEDB_LIVE_TEST") == "1",
    "live nedbd datetime-UTC test: set OPENSALON_NEDB_LIVE_TEST=1",
)
class NedbDatetimeUtcLiveTests(SimpleTestCase):
    """N-M13 (DYOR §9.1/§9.9): salon-tz window buckets correctly live."""

    databases = {"default"}

    def test_salon_tz_window_counts_previous_day(self):
        from django.db import connection

        self.assertEqual(connection.display_name, "NEDB (PostgreSQL pgwire)")
        from bookings.models import Appointment
        from bookings.status_counts import appointment_status_counts
        from clients.models import Client
        from saloncore.models import Salon, Service, ServiceCategory
        from team.models import StaffMember

        ny = Salon.objects.create(name="NM13 NY Salon", timezone="America/New_York")
        staff = StaffMember.objects.create(salon=ny, display_name="NM13")
        client = Client.objects.create(salon=ny, first_name="NM13", last_name="Client")
        cat = ServiceCategory.objects.create(salon=ny, name="Hair")
        svc = Service.objects.create(category=cat, name="Cut", service_minutes=45)
        start = datetime.datetime(2026, 11, 2, 1, 30, tzinfo=datetime.timezone.utc)
        Appointment.objects.create(
            client=client, staff_member=staff, service=svc,
            start=start, end=start + datetime.timedelta(minutes=45),
        )
        self.assertEqual(
            appointment_status_counts(ny, datetime.date(2026, 11, 1)).total, 1
        )


# -- N-M3g: identity / RETURNING (DYOR 9.6) ---------------------------

from opensalon.backends.nedb import identity
from opensalon.backends.nedb.compiler import (
    SQLInsertCompiler as NedbSQLInsertCompiler,
)


class IdentityAllocatorTests(SimpleTestCase):
    def test_allocator_is_monotonic_with_frozen_clock(self):
        alloc = identity.ClientIdAllocator(clock_ms=lambda: 1_700_000_000_000)
        ids = [alloc.next_id() for _ in range(5)]
        self.assertEqual(ids, [1_700_000_000_000 + i for i in range(5)])

    def test_allocator_unique_and_positive_with_real_clock(self):
        alloc = identity.ClientIdAllocator()
        ids = {alloc.next_id() for _ in range(200)}
        self.assertEqual(len(ids), 200)
        self.assertTrue(all(i > 0 for i in ids))

    def test_assign_pk_if_missing_keeps_explicit_pk(self):
        from saloncore.models import Salon

        obj = Salon(id=42, name="x")
        pk = Salon._meta.pk
        self.assertEqual(identity.assign_pk_if_missing(obj, pk), 42)
        obj2 = Salon(name="y")
        assigned = identity.assign_pk_if_missing(obj2, pk)
        self.assertIsInstance(assigned, int)
        self.assertEqual(obj2.pk, assigned)


class IdentityConvertTests(SimpleTestCase):
    def test_numeric_string_becomes_int(self):
        self.assertEqual(identity.convert_integer_value("101"), 101)
        self.assertEqual(identity.convert_integer_value("-3"), -3)

    def test_int_and_none_pass_through(self):
        self.assertEqual(identity.convert_integer_value(7), 7)
        self.assertIsNone(identity.convert_integer_value(None))

    def test_legacy_engine_string_id_passes_through_unchanged(self):
        # Documented limit (identity.py): no integer is recoverable
        # from an engine-assigned string _id; never invent one.
        legacy = "r179339565244311531-0"
        self.assertEqual(identity.convert_integer_value(legacy), legacy)

    def test_ops_converters_registered_for_integer_and_fk_fields(self):
        from django.db import models

        from team.models import StaffMember

        wrapper = _wrapper()
        for field in (
            models.BigAutoField(primary_key=True),
            models.AutoField(primary_key=True),
            models.IntegerField(),
            StaffMember._meta.get_field("salon"),
        ):
            expr = mock.Mock()
            expr.output_field = field
            with self.subTest(field=type(field).__name__):
                self.assertIn(
                    wrapper.ops.convert_integerfield_value,
                    wrapper.ops.get_db_converters(expr),
                )

    def test_ops_converter_applies_identity_conversion(self):
        wrapper = _wrapper()
        self.assertEqual(
            wrapper.ops.convert_integerfield_value("202", mock.Mock(), mock.Mock()),
            202,
        )


def _insert_sql(objs, fields, returning=False):
    """Compile an InsertQuery offline on a never-connected NEDB wrapper."""
    from django.db.models.sql.subqueries import InsertQuery

    wrapper = _wrapper()
    query = InsertQuery(objs[0]._meta.model)
    query.insert_values(fields, objs)
    compiler = NedbSQLInsertCompiler(query, wrapper, "default")
    if returning:
        compiler.returning_fields = [objs[0]._meta.pk]
    return compiler.as_sql()


class InsertCompilerIdentityTests(SimpleTestCase):
    def test_wrapper_loads_nedb_insert_compiler(self):
        wrapper = _wrapper()
        self.assertEqual(
            wrapper.ops.compiler_module, "opensalon.backends.nedb.compiler"
        )
        self.assertIs(
            wrapper.ops.compiler("SQLInsertCompiler"), NedbSQLInsertCompiler
        )

    def test_single_insert_assigns_int_pk_and_includes_id_column(self):
        from saloncore.models import Salon

        obj = Salon(name="Identity Salon", timezone="UTC")
        fields = [f for f in Salon._meta.local_concrete_fields if f is not Salon._meta.pk]
        sql_params = _insert_sql([obj], fields, returning=True)
        self.assertIsInstance(obj.pk, int)
        sql, params = sql_params[0]
        self.assertIn('"id"', sql)
        self.assertIn("RETURNING", sql)
        self.assertIn(obj.pk, params)

    def test_explicit_pk_is_not_reassigned(self):
        from saloncore.models import Salon

        obj = Salon(id=777, name="Fixed Salon", timezone="UTC")
        fields = list(Salon._meta.local_concrete_fields)
        _insert_sql([obj], fields, returning=True)
        self.assertEqual(obj.pk, 777)

    def test_bulk_insert_assigns_distinct_pks_without_unnest(self):
        from saloncore.models import Salon

        objs = [Salon(name=f"Bulk {i}", timezone="UTC") for i in range(3)]
        fields = [f for f in Salon._meta.local_concrete_fields if f is not Salon._meta.pk]
        sql, params = _insert_sql(objs, fields, returning=True)[0]
        self.assertNotIn("UNNEST", sql)
        self.assertEqual(sql.count("VALUES"), 1)
        self.assertEqual(len({o.pk for o in objs}), 3)
        self.assertTrue(all(isinstance(o.pk, int) for o in objs))
        for o in objs:
            self.assertIn(o.pk, params)


@unittest.skipUnless(
    os.environ.get("OPENSALON_NEDB_LIVE_TEST") == "1",
    "live nedbd identity test: set OPENSALON_NEDB_LIVE_TEST=1 with the "
    "default connection on the NEDB backend (nedbd running, test "
    "database pre-created over HTTP)",
)
class NedbIdentityLiveTests(SimpleTestCase):
    """N-M3g acceptance against a real nedbd (guarded, never in SQLite)."""

    databases = {"default"}

    def test_single_and_bulk_inserts_present_int_pks(self):
        from django.db import connection

        # connection is a proxy object; check the backend it wraps.
        self.assertEqual(connection.display_name, "NEDB (PostgreSQL pgwire)")
        from saloncore.models import Salon
        from team.models import StaffMember

        salon = Salon.objects.create(name="Identity Probe Salon", timezone="UTC")
        self.assertIsInstance(salon.pk, int)
        fetched = Salon.objects.get(pk=salon.pk)
        self.assertIsInstance(fetched.pk, int)
        self.assertEqual(fetched.pk, salon.pk)

        staff = [
            StaffMember(display_name=f"Identity Stylist {i}", salon_id=salon.pk)
            for i in range(3)
        ]
        StaffMember.objects.bulk_create(staff)
        self.assertTrue(all(isinstance(s.pk, int) for s in staff))
        rows = list(
            StaffMember.objects.filter(salon_id=salon.pk).values_list(
                "id", flat=True
            )
        )
        self.assertEqual(sorted(rows), sorted(s.pk for s in staff))
        self.assertTrue(all(isinstance(r, int) for r in rows))

    def test_create_permissions_for_an_app_does_not_raise_value_error(self):
        # The N-M3c verbatim failure was in post-migrate
        # create_permissions: filtering by a ContentType whose pk had
        # been read back as the engine string _id. Re-running it for
        # an already-populated app exercises exactly that filter.
        from django.apps import apps as django_apps
        from django.contrib.auth.management import create_permissions

        create_permissions(django_apps.get_app_config("saloncore"), verbosity=0)
        from django.contrib.auth.models import Permission

        self.assertTrue(Permission.objects.exists())
        self.assertTrue(
            all(isinstance(p, int) for p in Permission.objects.values_list("id", flat=True))
        )


# -- N-M3i: FOR UPDATE guard (DYOR 9.7) -------------------------------

from django.db.models.sql import Query as DjangoQuery


def _select_for_update_sql(**flags):
    """Compile a select_for_update SELECT offline on a NEDB wrapper."""
    from saloncore.models import Salon

    wrapper = _wrapper()
    query = DjangoQuery(Salon)
    query.select_for_update = True
    query.select_for_update_nowait = flags.get("nowait", False)
    query.select_for_update_skip_locked = flags.get("skip_locked", False)
    query.select_for_update_of = flags.get("of", ())
    query.select_for_no_key_update = flags.get("no_key", False)
    compiler = query.get_compiler(connection=wrapper)
    sql, params = compiler.as_sql()
    return sql


class ForUpdateFeatureTests(SimpleTestCase):
    def test_wrapper_uses_nedb_features_without_select_for_update(self):
        wrapper = _wrapper()
        self.assertIs(wrapper.features_class, DatabaseFeatures)
        self.assertFalse(wrapper.features.has_select_for_update)
        self.assertFalse(wrapper.features.has_select_for_update_nowait)
        self.assertFalse(wrapper.features.has_select_for_update_skip_locked)
        self.assertFalse(wrapper.features.has_select_for_update_of)
        self.assertFalse(wrapper.features.has_select_for_no_key_update)


class ForUpdateSqlTests(SimpleTestCase):
    def test_operations_build_no_for_update_sql(self):
        wrapper = _wrapper()
        self.assertEqual(wrapper.ops.for_update_sql(), "")
        self.assertEqual(wrapper.ops.for_update_sql(nowait=True), "")
        self.assertEqual(wrapper.ops.for_update_sql(skip_locked=True), "")
        self.assertEqual(
            wrapper.ops.for_update_sql(of=("saloncore_salon",)), ""
        )
        self.assertEqual(wrapper.ops.for_update_sql(no_key=True), "")

    def test_compiled_select_for_update_has_no_lock_clause(self):
        for flags in (
            {},
            {"nowait": True},
            {"skip_locked": True},
            {"no_key": True},
        ):
            with self.subTest(flags=flags):
                sql = _select_for_update_sql(**flags)
                self.assertTrue(sql.startswith("SELECT"))
                self.assertIn('"saloncore_salon"', sql)
                self.assertNotIn("FOR UPDATE", sql)
                self.assertNotIn("FOR NO KEY UPDATE", sql)
                self.assertNotIn("NOWAIT", sql)
                self.assertNotIn("SKIP LOCKED", sql)


# -- N-M6c: AlterField never introspects constraints ------------------

import copy

from django.db import models as dj_models


def _alter_fields():
    from saloncore.models import Salon

    old_field = dj_models.CharField(max_length=100)
    old_field.set_attributes_from_name("name")
    new_field = dj_models.CharField(max_length=200)
    new_field.set_attributes_from_name("name")
    return Salon, old_field, new_field


class SchemaEditorAlterFieldTests(SimpleTestCase):
    def test_alter_field_sends_nothing_and_never_introspects(self):
        model, old_field, new_field = _alter_fields()
        editor, wrapper, cursor = _editor()
        with mock.patch.object(
            wrapper.introspection, "get_constraints"
        ) as get_constraints:
            result = editor.alter_field(model, old_field, new_field)
        self.assertIsNone(result)
        get_constraints.assert_not_called()
        wrapper.cursor.assert_not_called()
        cursor.execute.assert_not_called()

    def test_alter_field_on_fk_sends_nothing_and_never_introspects(self):
        # Mirrors bookings 0003: AlterField on Appointment.service.
        from bookings.models import Appointment

        editor, wrapper, cursor = _editor()
        new_field = copy.deepcopy(Appointment._meta.get_field("service"))
        old_field = copy.deepcopy(new_field)
        old_field.null = False
        old_field.blank = False
        with mock.patch.object(
            wrapper.introspection, "get_constraints"
        ) as get_constraints:
            result = editor.alter_field(
                Appointment, old_field, new_field
            )
        self.assertIsNone(result)
        get_constraints.assert_not_called()
        wrapper.cursor.assert_not_called()
        cursor.execute.assert_not_called()

    def test_private_alter_field_is_also_a_noop_without_introspection(self):
        model, old_field, new_field = _alter_fields()
        editor, wrapper, cursor = _editor()
        with mock.patch.object(
            wrapper.introspection, "get_constraints"
        ) as get_constraints:
            result = editor._alter_field(
                model, old_field, new_field,
                "varchar(100)", "varchar(200)", {}, {},
            )
        self.assertIsNone(result)
        get_constraints.assert_not_called()
        wrapper.cursor.assert_not_called()
        cursor.execute.assert_not_called()

    def test_constraint_names_returns_empty_without_introspection(self):
        model, old_field, _ = _alter_fields()
        editor, wrapper, cursor = _editor()
        with mock.patch.object(
            wrapper.introspection, "get_constraints"
        ) as get_constraints:
            names = editor._constraint_names(
                model, [old_field.column], foreign_key=True
            )
        self.assertEqual(names, [])
        get_constraints.assert_not_called()
        wrapper.cursor.assert_not_called()

    def test_alter_field_on_uncatalogued_table_raises_and_sends_nothing(self):
        model, old_field, new_field = _alter_fields()
        editor, wrapper, cursor = _editor(catalog={"only_table"})
        with mock.patch.object(
            wrapper.introspection, "get_constraints"
        ) as get_constraints:
            with self.assertRaises(UncataloguedTableError):
                editor.alter_field(model, old_field, new_field)
        get_constraints.assert_not_called()
        wrapper.cursor.assert_not_called()
        cursor.execute.assert_not_called()


# -- N-M6d: GROUP BY must not collapse to selected PKs (DYOR 9.1) ----

def _annotate_sql():
    """Compile the low_stock annotate shape offline on a NEDB wrapper."""
    from django.db.models import Sum, Value
    from django.db.models.functions import Coalesce
    from django.db.models.sql import Query as _Query

    from catalog.models import Product

    wrapper = _wrapper()
    query = _Query(Product)
    query.add_annotation(
        Coalesce(Sum("stock_movements__quantity_delta"), Value(0)),
        "_on_hand",
    )
    query.set_group_by()
    sql, _params = query.get_compiler(connection=wrapper).as_sql()
    return sql


class GroupBySelectedPksTests(SimpleTestCase):
    def test_allows_group_by_selected_pks_is_false(self):
        # PostgreSQL's flag (True, inherited) lets the compiler rely
        # on PK functional dependency; NEDB's evaluator rejects any
        # selected column not in GROUP BY (live-suite signatures 3/5).
        wrapper = _wrapper()
        self.assertIs(wrapper.features_class, DatabaseFeatures)
        self.assertFalse(wrapper.features.allows_group_by_selected_pks)

    def test_annotate_group_by_lists_every_selected_column(self):
        sql = _annotate_sql()
        group_by = sql.split("GROUP BY", 1)[1]
        for column in (
            '"catalog_product"."id"',
            '"catalog_product"."salon_id"',
            '"catalog_product"."name"',
            '"catalog_product"."sku"',
            '"catalog_product"."barcode"',
            '"catalog_product"."price"',
            '"catalog_product"."active"',
        ):
            with self.subTest(column=column):
                self.assertIn(column, group_by)


@unittest.skipUnless(
    os.environ.get("OPENSALON_NEDB_LIVE_TEST") == "1",
    "live nedbd GROUP BY test: set OPENSALON_NEDB_LIVE_TEST=1 with "
    "the default connection on the NEDB backend (nedbd running)",
)
class NedbGroupByLiveTests(SimpleTestCase):
    """N-M6d acceptance against a real nedbd (guarded, never offline).

    Before the fix this exact shape failed live with:
    column "catalog_product.salon_id" must appear in the GROUP BY
    clause or be used in an aggregate function.
    """

    databases = {"default"}

    def test_low_stock_annotate_passes_on_live_nedb(self):
        from django.db import connection

        self.assertEqual(connection.display_name, "NEDB (PostgreSQL pgwire)")
        from catalog.low_stock import low_stock
        from catalog.models import Product, StockMovement
        from saloncore.models import Salon

        salon = Salon.objects.create(name="GroupBy Probe Salon", timezone="UTC")
        product = Product.objects.create(
            salon=salon, name="Probe Shampoo", sku="GB-LIVE", price="10.00"
        )
        StockMovement.objects.create(
            product=product, kind="receive", quantity_delta=3
        )
        rows = low_stock(salon)
        self.assertEqual([(r.sku, r.on_hand) for r in rows], [("GB-LIVE", 3)])


# -- N-M6e: Decimal columns round-trip as Decimal, never float -------

import decimal

from django.db.models.expressions import Col

from opensalon.backends.nedb import decimalfield


def _decimal_expr():
    """A mock non-Col expression whose output_field is Decimal(10,2)."""
    from django.db import models

    expr = mock.Mock()
    expr.output_field = models.DecimalField(max_digits=10, decimal_places=2)
    return expr


def _decimal_col():
    from checkout.models import SaleItem

    field = SaleItem._meta.get_field("unit_price")
    return Col("checkout_saleitem", field)


class DecimalConverterRegistrationTests(SimpleTestCase):
    def test_converter_registered_for_decimal_field_only(self):
        from django.db import models

        wrapper = _wrapper()
        expr = _decimal_expr()
        self.assertIn(
            wrapper.ops.convert_decimalfield_value,
            wrapper.ops.get_db_converters(expr),
        )
        for field in (models.FloatField(), models.CharField(max_length=5)):
            other = mock.Mock()
            other.output_field = field
            with self.subTest(field=type(field).__name__):
                self.assertNotIn(
                    wrapper.ops.convert_decimalfield_value,
                    wrapper.ops.get_db_converters(other),
                )

    def test_write_path_stays_numeric_never_string(self):
        # adapt must NOT stringify: decimal strings compare/sort
        # lexicographically on NEDB (decimalfield.py evidence).
        wrapper = _wrapper()
        value = decimal.Decimal("19.99")
        self.assertIs(wrapper.ops.adapt_decimalfield_value(value), value)


class DecimalConvertTests(SimpleTestCase):
    def test_float_becomes_exact_decimal(self):
        # The live signature: NEDB returns 85.00 / 19.99 as float.
        self.assertEqual(
            decimalfield.convert_decimal_value(85.0, _decimal_expr()),
            decimal.Decimal("85.0"),
        )
        self.assertEqual(
            decimalfield.convert_decimal_value(19.99, _decimal_expr()),
            decimal.Decimal("19.99"),
        )

    def test_int_and_numeric_string_become_decimal(self):
        self.assertEqual(
            decimalfield.convert_decimal_value(85, _decimal_expr()),
            decimal.Decimal(85),
        )
        self.assertEqual(
            decimalfield.convert_decimal_value("85.00", _decimal_expr()),
            decimal.Decimal("85.00"),
        )

    def test_decimal_and_none_pass_through(self):
        value = decimal.Decimal("24.00")
        self.assertIs(
            decimalfield.convert_decimal_value(value, _decimal_expr()), value
        )
        self.assertIsNone(
            decimalfield.convert_decimal_value(None, _decimal_expr())
        )

    def test_unconvertible_passes_through_unchanged(self):
        self.assertEqual(
            decimalfield.convert_decimal_value("not-a-number", _decimal_expr()),
            "not-a-number",
        )

    def test_col_quantizes_to_field_scale(self):
        col = _decimal_col()
        for raw in (85.0, 85, "85.00", decimal.Decimal("85")):
            with self.subTest(raw=raw):
                converted = decimalfield.convert_decimal_value(raw, col)
                self.assertEqual(str(converted), "85.00")
        self.assertEqual(
            str(decimalfield.convert_decimal_value(19.9, col)), "19.90"
        )

    def test_ops_converter_applies_decimalfield_conversion(self):
        wrapper = _wrapper()
        converted = wrapper.ops.convert_decimalfield_value(
            85.0, _decimal_col(), mock.Mock()
        )
        self.assertIsInstance(converted, decimal.Decimal)
        self.assertEqual(converted, decimal.Decimal("85.00"))


@unittest.skipUnless(
    os.environ.get("OPENSALON_NEDB_LIVE_TEST") == "1",
    "live nedbd Decimal test: set OPENSALON_NEDB_LIVE_TEST=1 with "
    "the default connection on the NEDB backend (nedbd running)",
)
class NedbDecimalLiveTests(SimpleTestCase):
    """N-M6e acceptance against a real nedbd (guarded, never offline).

    Before the fix this exact shape failed live with:
    TypeError: unsupported operand type(s) for +: 'decimal.Decimal'
    and 'float' (Sale.total summing float unit_price values).
    """

    databases = {"default"}

    def test_sale_items_round_trip_as_decimal_and_total(self):
        from django.db import connection

        self.assertEqual(connection.display_name, "NEDB (PostgreSQL pgwire)")
        from checkout.models import Sale, SaleItem
        from saloncore.models import Salon

        salon = Salon.objects.create(name="Decimal Probe Salon", timezone="UTC")
        sale = Sale.objects.create(salon=salon)
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=decimal.Decimal("85.00"),
        )
        SaleItem.objects.create(
            sale=sale, kind="product", description="Shampoo", quantity=2,
            unit_price=decimal.Decimal("24.00"),
        )
        fresh = Sale.objects.get(pk=sale.pk)
        items = list(fresh.items.all())
        self.assertTrue(
            all(isinstance(i.unit_price, decimal.Decimal) for i in items)
        )
        self.assertEqual(fresh.total, decimal.Decimal("133.00"))
        values = list(
            SaleItem.objects.filter(sale=sale).values_list(
                "unit_price", flat=True
            )
        )
        self.assertTrue(
            all(isinstance(v, decimal.Decimal) for v in values)
        )
        # Numeric semantics survive: a magnitude filter across the
        # lexicographic trap (9 < 50 < 85 < 100) still works.
        SaleItem.objects.create(
            sale=sale, kind="service", description="Trim",
            unit_price=decimal.Decimal("9.00"),
        )
        big = SaleItem.objects.filter(
            sale=sale, unit_price__gt=decimal.Decimal("50")
        ).count()
        self.assertEqual(big, 1)


# -- N-M6f: auto-field PK ranges (DYOR 9.1/9.6) -----------------------
#
# The client allocator assigns millisecond-scale PKs (~1.79e12) to
# every table, but Django's built-in apps declare 32-bit AutoField
# PKs. With the stock PostgreSQL range, IntegerFieldOverflow turned
# a PK filter/update into EmptyResultSet before any SQL was sent:
# the UPDATE reported 0 rows and save(update_fields=[...]) raised
# "Save with update_fields did not affect any rows" (live-suite
# signature via update_last_login). NEDB stores _id as a string --
# there is no 32-bit column -- so auto-field ranges are 64-bit here.

BIG_CLIENT_PK = 1793418576690  # allocator-scale id, > 2**31
_BIG_RANGE = (-9223372036854775808, 9223372036854775807)


def _user_pk_query():
    from django.contrib.auth import get_user_model

    return get_user_model().objects.filter(pk=BIG_CLIENT_PK)


class AutoFieldRangeTests(SimpleTestCase):
    def test_auto_field_ranges_are_64_bit(self):
        wrapper = _wrapper()
        for internal_type in ("AutoField", "SmallAutoField", "BigAutoField"):
            with self.subTest(internal_type=internal_type):
                self.assertEqual(
                    wrapper.ops.integer_field_range(internal_type),
                    _BIG_RANGE,
                )

    def test_non_auto_integer_ranges_unchanged(self):
        wrapper = _wrapper()
        self.assertEqual(
            wrapper.ops.integer_field_range("IntegerField"),
            (-2147483648, 2147483647),
        )
        self.assertEqual(
            wrapper.ops.integer_field_range("PositiveIntegerField"),
            (0, 2147483647),
        )
        self.assertEqual(
            wrapper.ops.integer_field_range("SmallIntegerField"),
            (-32768, 32767),
        )

    def test_pk_filter_for_autofield_model_compiles(self):
        # Pre-fix this as_sql() raised EmptyResultSet (the lookup
        # overflow check), so the row was invisible to the ORM.
        wrapper = _wrapper()
        sql, params = (
            _user_pk_query().query.get_compiler(connection=wrapper).as_sql()
        )
        self.assertIn('"auth_user"."id" = %s', sql)
        self.assertEqual(params, (BIG_CLIENT_PK,))

    def test_pk_update_for_autofield_model_compiles(self):
        # The exact failing shape: UPDATE ... WHERE id = <big pk>,
        # whose compiler swallowed EmptyResultSet as rowcount 0.
        from django.db.models.sql.subqueries import UpdateQuery

        from django.contrib.auth import get_user_model

        wrapper = _wrapper()
        update = UpdateQuery(get_user_model())
        update.add_update_values({"username": "probe"})
        update.where = _user_pk_query().query.where
        sql, params = update.get_compiler(connection=wrapper).as_sql()
        self.assertTrue(sql.startswith('UPDATE "auth_user" SET'))
        self.assertIn('"auth_user"."id" = %s', sql)
        self.assertIn(BIG_CLIENT_PK, params)


@unittest.skipUnless(
    os.environ.get("OPENSALON_NEDB_LIVE_TEST") == "1",
    "live nedbd update_fields test: set OPENSALON_NEDB_LIVE_TEST=1 "
    "with the default connection on the NEDB backend (nedbd running)",
)
class NedbUpdateFieldsLiveTests(SimpleTestCase):
    """N-M6f acceptance against a real nedbd (guarded, never offline).

    Before the fix this exact shape failed live with:
    DatabaseError: Save with update_fields did not affect any rows
    (auth's update_last_login receiver, via force_login).
    """

    databases = {"default"}

    def test_user_update_fields_last_login_round_trip(self):
        from django.db import connection

        self.assertEqual(connection.display_name, "NEDB (PostgreSQL pgwire)")
        from django.contrib.auth import get_user_model
        from django.utils import timezone as dj_tz

        user = get_user_model().objects.create_superuser(
            username="updatefieldsprobe",
            email="updatefields@example.com",
            password="probe-password",
        )
        # The allocator's ids are the precondition of the bug.
        self.assertGreater(user.pk, 2147483647)
        user.last_login = dj_tz.now()
        user.save(update_fields=["last_login"])  # must not raise
        fresh = get_user_model().objects.get(pk=user.pk)
        self.assertEqual(fresh.last_login, user.last_login)
        self.assertEqual(
            get_user_model().objects.filter(pk=user.pk).update(
                username="updatefieldsrenamed"
            ),
            1,
        )


# -- N-M8a: JSON values travel as plain text, never a ::jsonb cast ---
#
# DYOR 9.7 (cast/expression VALUES refused by design) + 9.9 (nested
# data stored verbatim). Stock PostgreSQL adapt_json_value returns
# psycopg's Jsonb; under Django's client-side binding its text
# dumper renders '{...}'::jsonb, the live-suite signature #1 (~40
# errors, mostly checkout tender_totals / receipt JSON writes).

import json as _json

from django.core.serializers.json import DjangoJSONEncoder

from opensalon.backends.nedb import jsonfield


class JsonAdaptTests(SimpleTestCase):
    def test_dict_adapts_to_plain_json_text_not_jsonb(self):
        wrapper = _wrapper()
        adapted = wrapper.ops.adapt_json_value({"cash": "85.00"}, None)
        self.assertIsInstance(adapted, str)
        self.assertEqual(adapted, '{"cash": "85.00"}')
        self.assertNotIn("::jsonb", adapted)

    def test_list_adapts_to_plain_json_text(self):
        wrapper = _wrapper()
        adapted = wrapper.ops.adapt_json_value([{"a": 1}], None)
        self.assertEqual(adapted, '[{"a": 1}]')

    def test_field_encoder_is_honoured(self):
        wrapper = _wrapper()
        adapted = wrapper.ops.adapt_json_value(
            {"amount": decimal.Decimal("85.00")}, DjangoJSONEncoder
        )
        self.assertEqual(adapted, '{"amount": "85.00"}')

    def test_none_stays_none_never_json_null_text(self):
        wrapper = _wrapper()
        self.assertIsNone(wrapper.ops.adapt_json_value(None, None))

    def test_expression_passes_through_untouched(self):
        expr = mock.Mock(name="expression")
        expr.resolve_expression = lambda *a, **k: expr
        wrapper = _wrapper()
        self.assertIs(wrapper.ops.adapt_json_value(expr, None), expr)

    def test_jsonfield_module_matches_ops_hook(self):
        self.assertEqual(
            jsonfield.adapt_json_value({"x": [1, 2]}, None),
            _json.dumps({"x": [1, 2]}),
        )


class JsonInsertCompilerTests(SimpleTestCase):
    def test_cashup_insert_param_is_text_and_sql_has_no_cast(self):
        # The exact live-suite shape: a Cashup insert whose
        # tender_totals param must be a plain string, so the
        # client-side-bound SQL contains no ::jsonb cast.
        from checkout.models import Cashup
        from saloncore.models import Salon

        salon = Salon(id=4242, name="JSON Salon", timezone="UTC")
        obj = Cashup(
            salon=salon,
            period_start=AWARE_DT,
            period_end=AWARE_DT,
            tender_totals={"cash": "85.00"},
            note="",
        )
        fields = [
            f for f in Cashup._meta.local_concrete_fields
            if f is not Cashup._meta.pk
        ]
        sql, params = _insert_sql([obj], fields, returning=True)[0]
        self.assertNotIn("::jsonb", sql)
        json_params = [p for p in params if isinstance(p, str) and "cash" in p]
        self.assertEqual(json_params, ['{"cash": "85.00"}'])
        self.assertFalse(
            any(type(p).__name__ in ("Jsonb", "Json") for p in params)
        )


@unittest.skipUnless(
    os.environ.get("OPENSALON_NEDB_LIVE_TEST") == "1",
    "live nedbd JSON test: set OPENSALON_NEDB_LIVE_TEST=1 with "
    "the default connection on the NEDB backend (nedbd running)",
)
class NedbJsonLiveTests(SimpleTestCase):
    """N-M8a acceptance against a real nedbd (guarded, never offline).

    Before the fix this exact shape failed live with:
    NotSupportedError: cannot use "'{\"cash\": \"85.00\"}'::jsonb"
    as a value -- this endpoint accepts string literals, numbers,
    TRUE/FALSE and NULL.
    """

    databases = {"default"}

    def test_json_dict_and_list_round_trip_on_live_nedb(self):
        from django.db import connection

        self.assertEqual(connection.display_name, "NEDB (PostgreSQL pgwire)")
        from checkout.models import Cashup, Receipt, Sale
        from saloncore.models import Salon

        salon = Salon.objects.create(name="JSON Probe Salon", timezone="UTC")
        cashup = Cashup.objects.create(
            salon=salon,
            period_start=AWARE_DT,
            period_end=AWARE_DT,
            tender_totals={"cash": "85.00", "card": "24.00"},
            note="",
        )
        fresh = Cashup.objects.get(pk=cashup.pk)
        self.assertIsInstance(fresh.tender_totals, dict)
        self.assertEqual(
            fresh.tender_totals, {"cash": "85.00", "card": "24.00"}
        )
        # Update path carries a JSON value the same way.
        fresh.tender_totals = {"cash": "90.00"}
        fresh.save(update_fields=["tender_totals"])
        self.assertEqual(
            Cashup.objects.get(pk=cashup.pk).tender_totals,
            {"cash": "90.00"},
        )
        # List-shaped JSON fields (Receipt) round-trip too.
        sale = Sale.objects.create(salon=salon)
        lines = [{"description": "Haircut", "quantity": 1,
                  "unit_price": "85.00", "line_total": "85.00"}]
        tender = [{"method": "cash", "amount": "85.00", "status": "paid"}]
        Receipt.objects.create(
            sale=sale, salon_name="JSON Probe Salon", lines=lines,
            tender=tender,
        )
        receipt = Receipt.objects.get(sale=sale)
        self.assertEqual(receipt.lines, lines)
        self.assertEqual(receipt.tender, tender)


# -- N-M8b: no Django path emits a ::json (non-b) cast ----------------
#
# DYOR 9.7 (cast VALUES refused by design) + 9.9 (verbatim JSON text)
# + 9.1 (semantics layer only). Probe (evidence file cited in the PR):
# source sweep found no Django construction of psycopg's Json wrapper
# (the sole adaptation entry is adapt_json_value, already plain text
# since N-M8a), and a live 16-shape battery sent only ::jsonb, once,
# from a Cast in the SELECT list. Raw Json DOES mogrify to ::json and
# NEDB refuses it as a VALUE -- so adapt_json_value unwraps any
# Json/Jsonb wrapper a caller supplies, and the battery below pins
# the no-::json finding against regression.

import re as _re

_NONB_JSON_CAST = _re.compile(r"::json(?!b)")


def _compiled(qs):
    wrapper = _wrapper()
    return qs.query.get_compiler(connection=wrapper).as_sql()


def _json_shape_battery():
    from django.db.models import F, JSONField, Value
    from django.db.models.functions import Cast

    from checkout.models import Cashup, Receipt

    totals = {"cash": "85.00"}
    return {
        "exact": Cashup.objects.filter(tender_totals=totals),
        "contains": Cashup.objects.filter(tender_totals__contains=totals),
        "contained_by": Cashup.objects.filter(
            tender_totals__contained_by=totals
        ),
        "has_key": Cashup.objects.filter(tender_totals__has_key="cash"),
        "has_keys": Cashup.objects.filter(tender_totals__has_keys=["cash"]),
        "has_any_keys": Cashup.objects.filter(
            tender_totals__has_any_keys=["cash"]
        ),
        "key_exact": Cashup.objects.filter(tender_totals__cash="85.00"),
        "key_gt": Cashup.objects.filter(tender_totals__cash__gt="10"),
        "key_in": Cashup.objects.filter(tender_totals__cash__in=["85.00"]),
        "order_by_key": Cashup.objects.order_by("tender_totals__cash"),
        "values_key": Cashup.objects.values("tender_totals__cash"),
        "annotate_value": Cashup.objects.annotate(
            v=Value({"a": 1}, output_field=JSONField())
        ),
        "cast_to_jsonfield": Cashup.objects.annotate(
            v=Cast(F("tender_totals"), output_field=JSONField())
        ),
        "receipt_contains": Receipt.objects.filter(
            lines__contains=[{"a": 1}]
        ),
    }


class JsonNonBCastBatteryTests(SimpleTestCase):
    def test_no_shape_emits_a_nonb_json_cast(self):
        for name, qs in _json_shape_battery().items():
            sql, params = _compiled(qs)
            with self.subTest(shape=name):
                self.assertIsNone(_NONB_JSON_CAST.search(sql))
                self.assertFalse(
                    any(
                        type(p).__name__ in ("Json", "Jsonb")
                        for p in params
                    )
                )

    def test_cast_shape_emits_jsonb_only(self):
        # Pin the one cast the battery does produce: ::jsonb in the
        # SELECT list (accepted live), never its ::json sibling.
        sql, _params = _compiled(
            _json_shape_battery()["cast_to_jsonfield"]
        )
        self.assertIn("::jsonb", sql)

    def test_update_shape_param_is_plain_text(self):
        from django.db.models import Q
        from django.db.models.sql.subqueries import UpdateQuery

        from checkout.models import Cashup

        wrapper = _wrapper()
        query = UpdateQuery(Cashup)
        query.add_update_values({"tender_totals": {"cash": "1.00"}})
        query.add_q(Q(pk=1))
        sql, params = query.get_compiler(connection=wrapper).as_sql()
        self.assertIsNone(_NONB_JSON_CAST.search(sql))
        self.assertIn('{"cash": "1.00"}', params)


class JsonWrapperGuardTests(SimpleTestCase):
    def test_psycopg_json_wrapper_unwraps_to_plain_text(self):
        from psycopg.types.json import Json

        wrapper = _wrapper()
        adapted = wrapper.ops.adapt_json_value(Json({"cash": "85.00"}), None)
        self.assertEqual(adapted, '{"cash": "85.00"}')

    def test_psycopg_jsonb_wrapper_unwraps_to_plain_text(self):
        from psycopg.types.json import Jsonb

        wrapper = _wrapper()
        adapted = wrapper.ops.adapt_json_value(Jsonb([{"a": 1}]), None)
        self.assertEqual(adapted, '[{"a": 1}]')

    def test_wrapper_custom_dumps_is_honoured(self):
        from psycopg.types.json import Json

        wrapper = _wrapper()
        adapted = wrapper.ops.adapt_json_value(
            Json({"a": 1}, dumps=lambda obj: '{"custom": true}'), None
        )
        self.assertEqual(adapted, '{"custom": true}')


@unittest.skipUnless(
    os.environ.get("OPENSALON_NEDB_LIVE_TEST") == "1",
    "live nedbd ::json guard test: set OPENSALON_NEDB_LIVE_TEST=1 "
    "with the default connection on the NEDB backend (nedbd running)",
)
class NedbJsonNonBLiveTests(SimpleTestCase):
    """N-M8b acceptance against a real nedbd (guarded, never offline).

    Before the guard, a Json-wrapper value died in adaptation with
    TypeError; a raw one would have been refused as a ::json VALUE.
    """

    databases = {"default"}

    def test_json_wrapper_value_round_trips_on_live_nedb(self):
        from django.db import connection

        self.assertEqual(connection.display_name, "NEDB (PostgreSQL pgwire)")
        from psycopg.types.json import Json

        from checkout.models import Cashup
        from saloncore.models import Salon

        salon = Salon.objects.create(name="NonB Probe Salon", timezone="UTC")
        cashup = Cashup.objects.create(
            salon=salon,
            period_start=AWARE_DT,
            period_end=AWARE_DT,
            tender_totals={"cash": "85.00"},
            note="",
        )
        rows = list(
            Cashup.objects.filter(
                pk=cashup.pk, tender_totals=Json({"cash": "85.00"})
            )
        )
        # NEDB stores JSON as a text scalar; exact-match semantics on
        # it are a separate known surface -- the pin here is only
        # that the wrapper value is adapted (no TypeError, no cast
        # refusal) and the query executes.
        self.assertIsInstance(rows, list)
        fresh = Cashup.objects.get(pk=cashup.pk)
        self.assertEqual(fresh.tender_totals, {"cash": "85.00"})


# -- N-M8c: relation materialization (DYOR 9.3) -----------------------
#
# A catalogued collection that has never been written does not exist
# as a relation for NEDB's write path (DELETE/UPDATE) or its SQL
# evaluator's JOIN resolution: relation "<table>" does not exist
# (live-suite signature #2, x37). CREATE TABLE's semantics
# equivalent is materializing the empty collection -- sentinel put
# + tombstone delete in one CAS batch call (creation.py), applied
# on reset (flush/test-DB lifecycle) and at CREATE TABLE time
# (schema.py). Probe: nedb-relation-probe-2026-10-31.md.


class MaterializeCollectionsTests(SimpleTestCase):
    def test_one_batch_call_with_put_del_pair_per_table(self):
        wrapper = _wrapper()
        creation = wrapper.creation
        fake, calls, names = _fake_http()
        with mock.patch.object(creation, "_http_request", fake):
            count = creation.materialize_collections(
                "test_opensalon", ["b_table", "a_table", "a_table", ""]
            )
        self.assertEqual(count, 2)
        self.assertEqual(len(calls), 1)
        method, path, payload = calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/v1/databases/test_opensalon/batch")
        ops = payload["ops"]
        self.assertEqual(
            [(op["op"], op["coll"]) for op in ops],
            [
                ("put", "a_table"), ("del", "a_table"),
                ("put", "b_table"), ("del", "b_table"),
            ],
        )
        sentinel = creation.MATERIALIZED_SENTINEL_ID
        self.assertTrue(all(op["id"] == sentinel for op in ops))

    def test_no_tables_makes_no_http_call(self):
        wrapper = _wrapper()
        creation = wrapper.creation
        fake, calls, names = _fake_http()
        with mock.patch.object(creation, "_http_request", fake):
            self.assertEqual(creation.materialize_collections("db", []), 0)
        self.assertEqual(calls, [])

    def test_reset_recreates_then_materializes_the_catalog(self):
        wrapper = _wrapper()
        creation = wrapper.creation
        fake, calls, names = _fake_http(existing={"test_opensalon"})
        with mock.patch.object(creation, "_http_request", fake), \
                mock.patch(
                    "opensalon.backends.nedb.schema.declared_catalog",
                    return_value=frozenset({"only_table"}),
                ):
            creation.reset_database("test_opensalon")
        batch = [c for c in calls if c[1].endswith("/batch")]
        self.assertEqual(len(batch), 1)
        self.assertEqual(
            [(op["op"], op["coll"]) for op in batch[0][2]["ops"]],
            [("put", "only_table"), ("del", "only_table")],
        )


class SchemaMaterializeTests(SimpleTestCase):
    def _editor_with_creation(self):
        editor, wrapper, cursor = _editor()
        wrapper.creation = mock.Mock(name="creation")
        return editor, wrapper, cursor

    def test_create_table_materializes_that_table(self):
        editor, wrapper, cursor = self._editor_with_creation()
        editor.execute(KNOWN_DDL[0], None)
        wrapper.creation.materialize_collections.assert_called_once_with(
            "opensalon", {"saloncore_salon"}
        )
        cursor.execute.assert_not_called()

    def test_alter_table_does_not_materialize(self):
        editor, wrapper, cursor = self._editor_with_creation()
        editor.execute(KNOWN_DDL[1], None)
        wrapper.creation.materialize_collections.assert_not_called()

    def test_collect_sql_never_materializes(self):
        editor, wrapper, cursor = _editor(collect_sql=True)
        wrapper.creation = mock.Mock(name="creation")
        editor.execute(KNOWN_DDL[0], None)
        wrapper.creation.materialize_collections.assert_not_called()

    def test_materialize_failure_is_logged_not_raised(self):
        from opensalon.backends.nedb.creation import NedbHttpError

        editor, wrapper, cursor = self._editor_with_creation()
        wrapper.creation.materialize_collections.side_effect = NedbHttpError(
            "unreachable"
        )
        self.assertIsNone(editor.execute(KNOWN_DDL[0], None))
        cursor.execute.assert_not_called()


@unittest.skipUnless(
    os.environ.get("OPENSALON_NEDB_LIVE_TEST") == "1",
    "live nedbd relation-materialization test: set "
    "OPENSALON_NEDB_LIVE_TEST=1 with the default connection on the "
    "NEDB backend (nedbd running)",
)
class NedbRelationMaterializationLiveTests(SimpleTestCase):
    """N-M8c acceptance against a real nedbd (guarded, never offline).

    Before the guard both shapes failed live with
    relation "<table>" does not exist: the LEFT JOIN in
    stock_valuation against never-written catalog_stockmovement
    (SyntaxError), and the cascade DELETEs of a Sale against
    never-written checkout_saleitem / checkout_payment
    (UndefinedTable). The test database was materialized at
    creation/reset by the backend itself.
    """

    databases = {"default"}

    def test_join_to_never_written_collection_yields_zero(self):
        from django.db import connection

        self.assertEqual(connection.display_name, "NEDB (PostgreSQL pgwire)")
        from catalog.models import Product
        from catalog.valuation import stock_valuation
        from saloncore.models import Salon

        salon = Salon.objects.create(name="Materialize Probe Salon", timezone="UTC")
        Product.objects.create(
            salon=salon, name="Never Stocked", sku="MAT-LIVE", price="15.00"
        )
        result = stock_valuation(salon)
        self.assertEqual(
            [(row.sku, row.on_hand) for row in result.rows],
            [("MAT-LIVE", 0)],
        )

    def test_cascade_delete_over_never_written_children(self):
        from django.db import connection

        self.assertEqual(connection.display_name, "NEDB (PostgreSQL pgwire)")
        from checkout.models import Sale
        from saloncore.models import Salon

        salon = Salon.objects.create(name="Cascade Probe Salon", timezone="UTC")
        sale = Sale.objects.create(salon=salon)
        sale.delete()
        # Scoped to this sale: other live classes share the database.
        self.assertEqual(Sale.objects.filter(pk=sale.pk).count(), 0)


# -- N-M8d: filtered aggregates over joins (DYOR 9.1/9.9) -------------
#
# Census on nedbd-v2 12.15.16 (evidence file cited in the PR): plain
# JOIN shapes pass NEDB's SQL evaluator -- INNER/LEFT, select_related
# (incl. chains), filter-across forward/reverse/two-hop, unfiltered
# annotate Sum/Count/Max across a reverse relation. The one shape
# refused verbatim with "JOIN is not supported -- NQL is
# single-collection" is an aggregate FILTER (WHERE ...) clause over
# a join (all 19 live-suite JOIN errors; 17 are clients.inactive's
# filtered Max over appointments). The guard is a capability
# declaration: supports_aggregate_filter_clause = False makes
# Django compile the filter as CASE WHEN inside the aggregate --
# its own fallback expression tree, no SQL text rewritten here.

from django.db.models import Max as _Max, Q as _Q


def _filtered_max_sql():
    """Compile the clients.inactive annotate shape offline."""
    from clients.models import Client

    wrapper = _wrapper()
    qs = Client.objects.annotate(
        _last_visit=_Max(
            "appointments__start",
            filter=_Q(appointments__start__lte=AWARE_DT)
            & ~_Q(appointments__status="cancelled"),
        )
    )
    sql, _params = qs.query.get_compiler(connection=wrapper).as_sql()
    return sql


class AggregateFilterClauseFeatureTests(SimpleTestCase):
    def test_supports_aggregate_filter_clause_is_false(self):
        wrapper = _wrapper()
        self.assertIs(wrapper.features_class, DatabaseFeatures)
        self.assertFalse(wrapper.features.supports_aggregate_filter_clause)

    def test_filtered_aggregate_compiles_as_case_when_over_join(self):
        sql = _filtered_max_sql()
        self.assertIn("LEFT OUTER JOIN", sql)
        self.assertIn("MAX(CASE WHEN", sql)
        self.assertNotIn("FILTER (WHERE", sql)

    def test_unfiltered_aggregate_keeps_plain_join_shape(self):
        # The guard must not disturb shapes the evaluator already
        # answers: an unfiltered annotate still compiles to a plain
        # aggregate over the same LEFT JOIN, with no CASE rewrite.
        from clients.models import Client

        wrapper = _wrapper()
        qs = Client.objects.annotate(_last_visit=_Max("appointments__start"))
        sql, _params = qs.query.get_compiler(connection=wrapper).as_sql()
        self.assertIn("LEFT OUTER JOIN", sql)
        self.assertIn('MAX("bookings_appointment"."start")', sql)
        self.assertNotIn("CASE WHEN", sql)


@unittest.skipUnless(
    os.environ.get("OPENSALON_NEDB_LIVE_TEST") == "1",
    "live nedbd JOIN/filtered-aggregate test: set "
    "OPENSALON_NEDB_LIVE_TEST=1 with the default connection on the "
    "NEDB backend (nedbd running)",
)
class NedbFilteredAggregateJoinLiveTests(SimpleTestCase):
    """N-M8d acceptance against a real nedbd (guarded, never offline).

    Before the fix both shapes failed live with:
    NotSupportedError: JOIN is not supported -- NQL is
    single-collection; join in your client or model the relation
    with LINK/TRAVERSE.
    """

    databases = {"default"}

    def test_filtered_max_over_reverse_relation_on_live_nedb(self):
        from django.db import connection

        self.assertEqual(connection.display_name, "NEDB (PostgreSQL pgwire)")
        import datetime as _dt

        from django.db.models import Max, Q
        from django.utils import timezone as dj_tz

        from bookings.models import Appointment
        from clients.models import Client
        from saloncore.models import Salon, Service, ServiceCategory
        from team.models import StaffMember

        now = dj_tz.now()
        salon = Salon.objects.create(name="Join Probe Salon", timezone="UTC")
        category = ServiceCategory.objects.create(salon=salon, name="Hair")
        service = Service.objects.create(
            category=category, name="Cut", service_minutes=60
        )
        staff = StaffMember.objects.create(
            salon=salon, display_name="Join Stylist"
        )
        visited = Client.objects.create(
            salon=salon, first_name="Visited", last_name="Probe"
        )
        Appointment.objects.create(
            client=visited, staff_member=staff, service=service,
            start=now - _dt.timedelta(days=10),
            end=now - _dt.timedelta(days=10) + _dt.timedelta(hours=1),
            status=Appointment.Status.COMPLETED,
        )
        # A later CANCELLED appointment must not become the last visit.
        Appointment.objects.create(
            client=visited, staff_member=staff, service=service,
            start=now - _dt.timedelta(days=1),
            end=now - _dt.timedelta(days=1) + _dt.timedelta(hours=1),
            status=Appointment.Status.CANCELLED,
        )
        row = Client.objects.filter(pk=visited.pk).annotate(
            _last_visit=Max(
                "appointments__start",
                filter=Q(appointments__start__lte=now)
                & ~Q(appointments__status=Appointment.Status.CANCELLED),
            )
        ).get()
        self.assertEqual(row._last_visit.date(), (now - _dt.timedelta(days=10)).date())

    def test_inactive_clients_report_on_live_nedb(self):
        from django.db import connection

        self.assertEqual(connection.display_name, "NEDB (PostgreSQL pgwire)")
        import datetime as _dt

        from django.utils import timezone as dj_tz

        from bookings.models import Appointment
        from clients.inactive import inactive_clients
        from clients.models import Client
        from saloncore.models import Salon, Service, ServiceCategory
        from team.models import StaffMember

        now = dj_tz.now()
        salon = Salon.objects.create(name="Inactive Probe Salon", timezone="UTC")
        category = ServiceCategory.objects.create(salon=salon, name="Hair")
        service = Service.objects.create(
            category=category, name="Cut", service_minutes=60
        )
        staff = StaffMember.objects.create(
            salon=salon, display_name="Inactive Stylist"
        )
        never = Client.objects.create(
            salon=salon, first_name="Never", last_name="Probe"
        )
        recent = Client.objects.create(
            salon=salon, first_name="Recent", last_name="Probe"
        )
        Appointment.objects.create(
            client=recent, staff_member=staff, service=service,
            start=now - _dt.timedelta(days=10),
            end=now - _dt.timedelta(days=10) + _dt.timedelta(hours=1),
            status=Appointment.Status.COMPLETED,
        )
        rows = inactive_clients(salon=salon, now=now)
        self.assertEqual([r.client_id for r in rows], [never.pk])
        self.assertIsNone(rows[0].last_appointment)


# -- N-M8e: __date transform over joins (DYOR 9.1) --------------------
#
# Census on nedbd-v2 12.15.16 (nedb-date-probe-2026-10-31.md): the
# __date transform's stock expression "(start AT TIME ZONE %s)::date"
# routes any statement off NEDB's SQL evaluator -- over the bookings
# search joins it fails verbatim with "JOIN is not supported -- NQL
# is single-collection" (bookings.test_search: the plain-date range
# test and the combined-filters test). The ::date cast alone is
# transparent on NEDB, DATE()/DATE_TRUNC()/LEFT() are refused by
# name, and EXTRACT(YEAR/MONTH/DAY ...) is answered correctly. The
# guard is Django's per-backend ops hook: datetime_cast_date_sql
# returns temporal.date_part_sql's padded EXTRACT composite, so no
# AT TIME ZONE and no ::date cast ever reach nedbd. This is the
# semantics layer (DYOR 9.1), not statement-text rewriting: other
# backends supply their own cast-date expression through the same
# hook (MySQL DATE(...), Oracle TRUNC(...)).

import datetime as _dt_mod

_DATE_DAY = _dt_mod.date(2026, 11, 2)


def _search_date_sql():
    """Compile the bookings-search __date shape offline."""
    from bookings.models import Appointment

    wrapper = _wrapper()
    qs = Appointment.objects.filter(
        client__salon_id=1, staff_member__salon_id=1,
        start__date__gte=_DATE_DAY, start__date__lte=_DATE_DAY,
    )
    sql, _params = qs.query.get_compiler(connection=wrapper).as_sql()
    return sql


class DateCastSqlTests(SimpleTestCase):
    def test_cast_date_sql_has_no_at_time_zone_or_date_cast(self):
        wrapper = _wrapper()
        sql, params = wrapper.ops.datetime_cast_date_sql(
            '"bookings_appointment"."start"', (), "UTC"
        )
        self.assertNotIn("AT TIME ZONE", sql)
        self.assertNotIn("::date", sql)
        self.assertEqual(params, ())

    def test_cast_date_sql_is_padded_extract_composite(self):
        wrapper = _wrapper()
        sql, _params = wrapper.ops.datetime_cast_date_sql(
            '"bookings_appointment"."start"', (), "UTC"
        )
        self.assertIn('EXTRACT(YEAR FROM "bookings_appointment"."start")', sql)
        self.assertIn('EXTRACT(MONTH FROM "bookings_appointment"."start")', sql)
        self.assertIn('EXTRACT(DAY FROM "bookings_appointment"."start")', sql)
        self.assertIn("CASE WHEN", sql)
        self.assertTrue(sql.startswith("(") and sql.endswith(")"))

    def test_cast_date_sql_with_params_keeps_stock_shape(self):
        # A parameterised LHS would duplicate its placeholders in the
        # composite; the fallback keeps the stock (refused) shape
        # rather than silently mismatching parameters.
        wrapper = _wrapper()
        sql, params = wrapper.ops.datetime_cast_date_sql(
            "some_expr(%s)", (7,), "UTC"
        )
        self.assertIn("AT TIME ZONE", sql)
        self.assertIn("::date", sql)
        self.assertEqual(params, (7, "UTC"))

    def test_search_date_shape_compiles_without_at_time_zone(self):
        sql = _search_date_sql()
        self.assertIn("INNER JOIN", sql)
        self.assertNotIn("AT TIME ZONE", sql)
        self.assertNotIn("::date", sql)
        self.assertIn("EXTRACT(YEAR FROM", sql)


@unittest.skipUnless(
    os.environ.get("OPENSALON_NEDB_LIVE_TEST") == "1",
    "live nedbd __date test: set OPENSALON_NEDB_LIVE_TEST=1 with "
    "the default connection on the NEDB backend (nedbd running)",
)
class NedbDateTransformLiveTests(SimpleTestCase):
    """N-M8e acceptance against a real nedbd (guarded, never offline).

    Before the fix both shapes failed live with:
    NotSupportedError: JOIN is not supported -- NQL is
    single-collection; join in your client or model the relation
    with LINK/TRAVERSE.
    """

    databases = {"default"}

    def _seed(self):
        from bookings.models import Appointment
        from clients.models import Client
        from saloncore.models import Salon, Service, ServiceCategory
        from team.models import StaffMember

        salon = Salon.objects.create(name="Date Probe Salon", timezone="UTC")
        staff = StaffMember.objects.create(
            salon=salon, display_name="Date Stylist"
        )
        client = Client.objects.create(
            salon=salon, first_name="Dana", last_name="Probe"
        )
        category = ServiceCategory.objects.create(salon=salon, name="Hair")
        service = Service.objects.create(
            category=category, name="Cut", service_minutes=60
        )

        def appt(day, hour, status):
            start = _dt_mod.datetime.combine(
                day, _dt_mod.time(hour), tzinfo=_dt_mod.timezone.utc
            )
            return Appointment.objects.create(
                client=client, staff_member=staff, service=service,
                start=start, end=start + _dt_mod.timedelta(hours=1),
                status=status,
            )

        early = appt(_DATE_DAY, 9, Appointment.Status.CONFIRMED)
        late = appt(_DATE_DAY, 14, Appointment.Status.BOOKED)
        nxt = appt(
            _DATE_DAY + _dt_mod.timedelta(days=1), 9,
            Appointment.Status.BOOKED,
        )
        return salon, staff, early, late, nxt

    def test_plain_date_range_covers_whole_day_on_live_nedb(self):
        from django.db import connection

        self.assertEqual(connection.display_name, "NEDB (PostgreSQL pgwire)")
        from bookings.search import search_appointments

        salon, _staff, early, late, nxt = self._seed()
        rows = list(
            search_appointments(salon, date_from=_DATE_DAY, date_to=_DATE_DAY)
        )
        self.assertEqual(rows, [early, late])
        rows = list(
            search_appointments(
                salon, date_from=_DATE_DAY + _dt_mod.timedelta(days=1)
            )
        )
        self.assertEqual(rows, [nxt])

    def test_combined_filters_with_plain_dates_on_live_nedb(self):
        from django.db import connection

        self.assertEqual(connection.display_name, "NEDB (PostgreSQL pgwire)")
        from bookings.search import search_appointments

        salon, staff, _early, late, _nxt = self._seed()
        rows = list(
            search_appointments(
                salon, query="dana", staff_member=staff, status="booked",
                date_from=_DATE_DAY, date_to=_DATE_DAY,
            )
        )
        self.assertEqual(rows, [late])


# -- N-M8f: HAVING re-expression as derived-table WHERE (DYOR 9.1) ---
#
# Live probe (nedb-having-probe-2026-10-31.md): a HAVING clause that
# filters out the FIRST group makes nedbd-v2 12.15.16 emit every
# surviving row as a zero-column row, which Django's apply_converters
# dies on (IndexError). The NEDB SELECT compiler therefore compiles
# the grouped annotate query without HAVING as a derived table and
# applies the HAVING condition as an outer WHERE on the annotation
# columns -- the equivalent the evaluator answers correctly.

import datetime as _dt_f

_HAVING_NOW = _dt_f.datetime(2026, 11, 2, 12, 0, tzinfo=_dt_f.timezone.utc)


def _inactive_shape_sql(**qs_kwargs):
    """Compile the clients.inactive annotate+filter shape offline."""
    from django.db.models import Max, Q

    from bookings.models import Appointment
    from clients.models import Client

    wrapper = _wrapper()
    # Compile against the never-connected NEDB wrapper directly.
    query = (
        Client.objects.filter(salon_id=1)
        .annotate(
            _last_visit=Max(
                "appointments__start",
                filter=Q(appointments__start__lte=_HAVING_NOW)
                & ~Q(appointments__status=Appointment.Status.CANCELLED),
            )
        )
        .filter(
            Q(_last_visit__isnull=True)
            | Q(_last_visit__lt=_HAVING_NOW - _dt_f.timedelta(days=90))
        )
    )
    if qs_kwargs.get("sliced"):
        query = query[:5]
    if qs_kwargs.get("distinct"):
        query = query.distinct()
    compiler = query.query.get_compiler(connection=wrapper)
    return compiler.as_sql()


class HavingWrapCompilerTests(SimpleTestCase):
    def test_annotation_filter_compiles_without_having(self):
        sql, params = _inactive_shape_sql()
        self.assertNotIn("HAVING", sql)
        self.assertIn('FROM (SELECT', sql)
        self.assertIn('AS "nedb_having_sub"', sql)
        self.assertIn('"nedb_having_sub"."_last_visit"', sql)
        # The annotation keeps its CASE WHEN form (N-M8d) inside.
        self.assertIn("MAX(CASE WHEN", sql)

    def test_outer_where_params_follow_inner_params(self):
        sql, params = _inactive_shape_sql()
        # Inner: annotation filter (now, cancelled) + salon id;
        # outer: the cutoff, adapted to an ISO string by the
        # temporal write path (operations.py), never a cast.
        self.assertEqual(len(params), 4)
        self.assertEqual(params[-1], "2026-08-04T12:00:00+00:00")
        self.assertNotIn("::", sql)

    def test_meta_ordering_moves_to_outer_query(self):
        sql, _params = _inactive_shape_sql()
        outer = sql.rsplit(")", 1)[-1]
        self.assertIn('ORDER BY "nedb_having_sub"."last_name" ASC', outer)

    def test_sliced_query_keeps_stock_having(self):
        sql, _params = _inactive_shape_sql(sliced=True)
        self.assertIn("HAVING", sql)
        self.assertNotIn("nedb_having_sub", sql)

    def test_distinct_query_keeps_stock_having(self):
        sql, _params = _inactive_shape_sql(distinct=True)
        self.assertIn("HAVING", sql)
        self.assertNotIn("nedb_having_sub", sql)

    def test_wrapper_loads_nedb_select_compiler(self):
        from opensalon.backends.nedb.compiler import (
            SQLCompiler as NedbSQLCompiler,
        )

        wrapper = _wrapper()
        self.assertIs(
            wrapper.ops.compiler("SQLCompiler"), NedbSQLCompiler
        )


@unittest.skipUnless(
    os.environ.get("OPENSALON_NEDB_LIVE_TEST") == "1",
    "live nedbd HAVING test: set OPENSALON_NEDB_LIVE_TEST=1 with "
    "the default connection on the NEDB backend (nedbd running)",
)
class NedbHavingLiveTests(SimpleTestCase):
    """N-M8f acceptance against a real nedbd (guarded, never offline).

    The first-created client is the recent one, so HAVING filters
    out the first group -- the exact shape that returned
    zero-column rows before the compiler re-expression.
    """

    databases = {"default"}

    def test_inactive_clients_first_group_filtered_out(self):
        from django.db import connection

        self.assertEqual(connection.display_name, "NEDB (PostgreSQL pgwire)")
        from clients.inactive import inactive_clients
        from clients.models import Client
        from saloncore.models import Salon, Service, ServiceCategory
        from team.models import StaffMember
        from bookings.models import Appointment

        salon = Salon.objects.create(name="Having Probe Salon", timezone="UTC")
        staff = StaffMember.objects.create(
            salon=salon, display_name="Having Stylist"
        )
        category = ServiceCategory.objects.create(salon=salon, name="Hair")
        service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        recent = Client.objects.create(
            salon=salon, first_name="Recent", last_name="Aaa"
        )
        stale = Client.objects.create(
            salon=salon, first_name="Stale", last_name="Zzz"
        )
        for client, offset in ((recent, -89), (stale, -91)):
            start = _HAVING_NOW + _dt_f.timedelta(days=offset)
            Appointment.objects.create(
                client=client, staff_member=staff, service=service,
                start=start, end=start + _dt_f.timedelta(minutes=45),
            )
        rows = inactive_clients(salon=salon, now=_HAVING_NOW)
        self.assertEqual([row.client_id for row in rows], [stale.pk])
        self.assertEqual(rows[0].days_since_last_visit, 91)


# -- N-M10: server-side cursors / DECLARE (DYOR 5, 9.1, 9.9) ----------


class ChunkedCursorTests(SimpleTestCase):
    """chunked_cursor() must never produce a named (DECLARE) cursor."""

    def test_chunked_cursor_returns_the_plain_cursor(self):
        wrapper = _wrapper()
        sentinel = mock.Mock(name="plain-cursor")
        with mock.patch.object(wrapper, "cursor", return_value=sentinel) as cur:
            self.assertIs(wrapper.chunked_cursor(), sentinel)
        cur.assert_called_once_with()

    def test_chunked_cursor_never_names_a_cursor(self):
        wrapper = _wrapper()
        sentinel = mock.Mock(name="plain-cursor")
        with mock.patch.object(wrapper, "_cursor", return_value=sentinel) as cur:
            self.assertIs(wrapper.chunked_cursor(), sentinel)
        # _cursor() reached with no name argument: no DECLARE can follow.
        cur.assert_called_once_with()
        self.assertEqual(wrapper._named_cursor_idx, 0)


import datetime as _dt10

from django.test import TestCase as _TestCase10


@unittest.skipUnless(
    os.environ.get("OPENSALON_NEDB_LIVE_TEST") == "1",
    "live nedbd DECLARE test: set OPENSALON_NEDB_LIVE_TEST=1 with the "
    "default connection on the NEDB backend (nedbd running, test "
    "database pre-created over HTTP)",
)
class NedbDeclareCursorLiveTests(_TestCase10):
    """iterator() paths execute on live NEDB with no DECLARE (N-M10).

    Census signature 1 (nedb-live-census-2026-10-31.md): 24 live
    errors, 23 in messaging, from QuerySet.iterator() routing through
    the PostgreSQL named cursor. Probe: nedb-declare-probe-2026-10-31.md.
    """

    def setUp(self):
        from bookings.models import Appointment
        from clients.models import Client
        from messaging.models import ReminderSend
        from saloncore.models import Salon, Service, ServiceCategory
        from team.models import StaffMember

        self.ReminderSend = ReminderSend
        self.salon = Salon.objects.create(name="Declare Probe Salon", timezone="UTC")
        staff = StaffMember.objects.create(
            salon=self.salon, display_name="Declare Stylist"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )
        client = Client.objects.create(
            salon=self.salon, first_name="Declare", last_name="Client",
            email="declare@example.com", phone="555-0100",
            sms_opt_in=True, email_opt_in=True,
        )
        start = dj_timezone.now() + _dt10.timedelta(days=1)
        appt = Appointment.objects.create(
            client=client, staff_member=staff, service=service,
            start=start, end=start + _dt10.timedelta(minutes=45),
            status=Appointment.Status.BOOKED,
        )
        utc = datetime.timezone.utc
        for channel, day in (("email", 2), ("sms", 3)):
            ReminderSend.objects.create(
                appointment=appt, client=client, channel=channel,
                status=ReminderSend.Status.SENT,
                sent_at=datetime.datetime(2026, 3, day, 12, tzinfo=utc),
            )
        self.first = datetime.date(2026, 3, 1)
        self.last = datetime.date(2026, 3, 4)

    def test_plain_iterator_queryset_executes(self):
        rows = list(
            self.ReminderSend.objects.order_by("sent_at")
            .values_list("channel", flat=True)
            .iterator()
        )
        self.assertEqual(rows, ["email", "sms"])
        chunked = list(
            self.ReminderSend.objects.order_by("sent_at")
            .values_list("channel", flat=True)
            .iterator(chunk_size=1)
        )
        self.assertEqual(chunked, ["email", "sms"])

    def test_messaging_history_summary_executes(self):
        from messaging.history import reminder_history_summary

        summary = reminder_history_summary(self.first, self.last)
        self.assertEqual(summary.total, 2)
        self.assertEqual(summary.by_channel, {"email": 1, "sms": 1})

    def test_messaging_send_totals_executes(self):
        from messaging.send_totals import send_totals

        totals = send_totals(self.salon, self.first, self.last)
        self.assertEqual(totals.total, 2)
        self.assertEqual(totals.by_channel, {"email": 1, "sms": 1})


# -- N-M11: GROUP BY expressions expand to determined columns -------
#
# DYOR 9.1/9.9; probe nedb-groupby2-probe-2026-10-31.md, census
# signature 2. NEDB's evaluator checks GROUP BY at constituent-column
# level: SaleSearch's Concat(client__first_name, " ", last_name)
# annotation fails live whether GROUP BY carries its select ordinal
# or the full expression; grouping by the constituent columns (which
# the grouped client_id FK determines) is measured correct.

def _sale_search_sql():
    """Compile the SaleSearch name+total shape offline (NEDB wrapper)."""
    from decimal import Decimal as _Dec

    from django.db.models import F, Q, Sum, Value
    from django.db.models.functions import Coalesce, Concat

    from checkout.models import Sale

    wrapper = _wrapper()
    qs = (
        Sale.objects.filter(salon_id=1)
        .exclude(status="voided")
        .annotate(
            _full_name=Concat(
                F("client__first_name"), Value(" "),
                F("client__last_name"),
            )
        )
        .filter(
            Q(client__first_name__icontains="ana")
            | Q(_full_name__icontains="ana")
        )
        .annotate(
            search_total=Coalesce(
                Sum(F("items__unit_price") * F("items__quantity")),
                _Dec("0.00"),
            )
        )
        .order_by("-created_at", "-id")
    )
    sql, _params = qs.query.get_compiler(connection=wrapper).as_sql()
    return sql


def _group_by_of(sql):
    return sql.split("GROUP BY", 1)[1].split(" ORDER BY", 1)[0]


class GroupByExpressionExpansionTests(SimpleTestCase):
    def test_concat_annotation_groups_by_constituent_client_columns(self):
        group_by = _group_by_of(_sale_search_sql())
        self.assertIn('"clients_client"."first_name"', group_by)
        self.assertIn('"clients_client"."last_name"', group_by)
        # The select ordinal for _full_name (position 10) is gone.
        self.assertNotIn(", 10", group_by)

    def test_reverse_relation_expression_is_not_expanded(self):
        # items is a reverse FK (one-to-many): its rows are NOT
        # determined by the grouped keys, so expansion would not be
        # provably equivalent -- stock grouping (ordinal) must stay.
        from decimal import Decimal as _Dec

        from django.db.models import F, Sum, Value
        from django.db.models.functions import Coalesce, Concat

        from checkout.models import Sale

        wrapper = _wrapper()
        qs = Sale.objects.filter(salon_id=1).annotate(
            _x=Concat(F("items__description"), Value("!"))
        ).annotate(
            search_total=Coalesce(
                Sum(F("items__unit_price") * F("items__quantity")),
                _Dec("0.00"),
            )
        )
        sql, _params = qs.query.get_compiler(connection=wrapper).as_sql()
        group_by = _group_by_of(sql)
        self.assertNotIn('"checkout_saleitem"."description"', group_by)
        self.assertIn(", 10", group_by)

    def test_undetermined_fk_expression_is_not_expanded(self):
        # values("status") grouping: neither the Sale PK nor the
        # client_id FK is a group key, so client columns are not
        # determined and the Concat keeps its stock ordinal grouping.
        from django.db.models import Count, F, Value
        from django.db.models.functions import Concat

        from checkout.models import Sale

        wrapper = _wrapper()
        qs = Sale.objects.values("status").annotate(
            _full_name=Concat(
                F("client__first_name"), Value(" "),
                F("client__last_name"),
            )
        ).annotate(n=Count("id"))
        sql, _params = qs.query.get_compiler(connection=wrapper).as_sql()
        group_by = _group_by_of(sql)
        self.assertNotIn('"clients_client"."first_name"', group_by)
        self.assertEqual(group_by.strip(), "1, 2")


class HavingWrapOuterProjectionTests(SimpleTestCase):
    def test_wrap_names_outer_columns_in_inner_order(self):
        # N-M11 addendum: with a min_total-style filter the query goes
        # through the N-M8f HAVING wrap; NEDB reorders SELECT * on a
        # derived table, so the wrap must project _full_name before
        # search_total explicitly, in the inner select's order.
        from decimal import Decimal as _Dec

        from django.db.models import F, Sum, Value
        from django.db.models.functions import Coalesce, Concat

        from checkout.models import Sale

        wrapper = _wrapper()
        qs = (
            Sale.objects.filter(salon_id=1)
            .annotate(
                _full_name=Concat(
                    F("client__first_name"), Value(" "),
                    F("client__last_name"),
                )
            )
            .annotate(
                search_total=Coalesce(
                    Sum(F("items__unit_price") * F("items__quantity")),
                    _Dec("0.00"),
                )
            )
            .filter(search_total__gte=_Dec("50.00"))
            .order_by("-created_at", "-id")
        )
        sql, _params = qs.query.get_compiler(connection=wrapper).as_sql()
        self.assertTrue(
            sql.startswith('SELECT "nedb_having_sub"."id", ')
        )
        self.assertNotIn("SELECT * FROM", sql)
        outer = sql.split(" FROM (", 1)[0]
        self.assertLess(
            outer.index('"_full_name"'), outer.index('"search_total"')
        )


@unittest.skipUnless(
    os.environ.get("OPENSALON_NEDB_LIVE_TEST") == "1",
    "live nedbd GROUP BY expression test: set OPENSALON_NEDB_LIVE_TEST=1 "
    "with the default connection on the NEDB backend (nedbd running)",
)
class NedbGroupByExpressionLiveTests(SimpleTestCase):
    """N-M11 acceptance against a real nedbd (guarded, never offline).

    Before the fix every name search failed live with: column
    "clients_client.first_name" must appear in the GROUP BY clause
    or be used in an aggregate function (census signature 2, x4).
    """

    databases = {"default"}

    def test_sale_search_by_name_passes_on_live_nedb(self):
        from django.db import connection

        self.assertEqual(connection.display_name, "NEDB (PostgreSQL pgwire)")
        from checkout.models import Sale, SaleItem
        from checkout.search import search_sales
        from clients.models import Client
        from saloncore.models import Salon

        salon = Salon.objects.create(name="GroupBy2 Probe Salon", timezone="UTC")
        ana = Client.objects.create(
            salon=salon, first_name="Ana", last_name="Lopez"
        )
        sale = Sale.objects.create(salon=salon, client=ana)
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=decimal.Decimal("85.00"),
        )
        by_last = search_sales(salon, client_name="lopez")
        self.assertEqual([s.pk for s in by_last], [sale.pk])
        self.assertEqual(by_last[0].search_total, decimal.Decimal("85.00"))
        # Full-name fragment exercises the Concat annotation itself.
        by_full = search_sales(salon, client_name="ana lo")
        self.assertEqual([s.pk for s in by_full], [sale.pk])
        self.assertEqual(search_sales(salon, client_name="zzz"), [])


# -- N-M14: DISTINCT guard + Trunc composite (DYOR 5, 9.1, 9.9) -------
# Probe: nedb-distinct-probe-2026-10-31.md; census signature 6.
# Plain-column DISTINCT compiles as GROUP BY; expression/sliced
# shapes keep stock. Trunc compiles to the EXTRACT composite.

import datetime as _dt14


def _distinct_sql(qs):
    wrapper = _wrapper()
    sql, params = qs.query.get_compiler(connection=wrapper).as_sql()
    return sql, params


class DistinctGroupByCompilerTests(SimpleTestCase):
    def test_plain_distinct_compiles_as_group_by_with_ordering(self):
        from clients.models import Client

        sql, _params = _distinct_sql(Client.objects.distinct())
        self.assertNotIn("DISTINCT", sql)
        self.assertIn("GROUP BY", sql)
        self.assertIn('"clients_client"."id"', sql.split("GROUP BY", 1)[1])
        # Meta ordering survives the grouped compile (explicit form).
        self.assertIn(
            'ORDER BY "clients_client"."last_name" ASC', sql
        )

    def test_values_distinct_groups_by_projection_and_ordering(self):
        from clients.models import Client

        sql, _params = _distinct_sql(
            Client.objects.distinct().values_list("salon_id", flat=True)
        )
        self.assertNotIn("DISTINCT", sql)
        self.assertIn("GROUP BY 1", sql)
        self.assertIn('"clients_client"."last_name"', sql)

    def test_expression_distinct_keeps_stock(self):
        from django.db.models.functions import Upper

        from clients.models import Client

        sql, _params = _distinct_sql(
            Client.objects.distinct()
            .annotate(u=Upper("first_name"))
            .values_list("u", flat=True)
        )
        self.assertIn("DISTINCT", sql)
        self.assertNotIn("GROUP BY", sql)

    def test_sliced_distinct_keeps_stock(self):
        from clients.models import Client

        sql, _params = _distinct_sql(Client.objects.distinct()[:5])
        self.assertIn("DISTINCT", sql)
        self.assertNotIn("GROUP BY", sql)

    def test_query_state_restored_after_group_by_compile(self):
        from clients.models import Client

        qs = Client.objects.distinct()
        _distinct_sql(qs)
        self.assertTrue(qs.query.distinct)
        self.assertIsNone(qs.query.group_by)
        self.assertEqual(qs.query.order_by, ())


class TruncCompositeTests(SimpleTestCase):
    def test_date_trunc_sql_is_extract_composite(self):
        wrapper = _wrapper()
        sql, params = wrapper.ops.date_trunc_sql(
            "year", '"clients_clientnote"."created_at"', (), "UTC"
        )
        self.assertNotIn("DATE_TRUNC", sql)
        self.assertNotIn("AT TIME ZONE", sql)
        self.assertIn("EXTRACT(YEAR FROM", sql)
        self.assertEqual(params, ())

    def test_datetime_trunc_sql_appends_zeroed_time(self):
        wrapper = _wrapper()
        sql, _params = wrapper.ops.datetime_trunc_sql(
            "month", '"t"."created_at"', (), "UTC"
        )
        self.assertIn("'T00:00:00+00:00'", sql)
        self.assertIn("EXTRACT(MONTH FROM", sql)

    def test_trunc_fallbacks_keep_stock_shape(self):
        wrapper = _wrapper()
        # Non-UTC tzname: no silent UTC buckets.
        sql, _params = wrapper.ops.date_trunc_sql(
            "year", '"t"."created_at"', (), "America/New_York"
        )
        self.assertIn("DATE_TRUNC", sql)
        # Unsupported kind (week needs date arithmetic).
        sql, _params = wrapper.ops.date_trunc_sql(
            "week", '"t"."created_at"', (), "UTC"
        )
        self.assertIn("DATE_TRUNC", sql)
        # Parameterised LHS: composite would duplicate placeholders.
        sql, params = wrapper.ops.date_trunc_sql(
            "year", "some_expr(%s)", (7,), "UTC"
        )
        self.assertIn("DATE_TRUNC", sql)
        self.assertEqual(params[0], "year")

    def test_dates_shapes_compile_without_date_trunc(self):
        from clients.models import ClientNote

        for qs in (
            ClientNote.objects.all().dates("created_at", "year"),
            ClientNote.objects.all().datetimes("created_at", "year"),
        ):
            sql, _params = _distinct_sql(qs)
            self.assertNotIn("DATE_TRUNC", sql)
            self.assertNotIn("AT TIME ZONE", sql)
            self.assertIn("DISTINCT", sql)  # stock distinct, composite
            self.assertIn("EXTRACT(YEAR FROM", sql)


@unittest.skipUnless(
    os.environ.get("OPENSALON_NEDB_LIVE_TEST") == "1",
    "live nedbd DISTINCT test: set OPENSALON_NEDB_LIVE_TEST=1 with "
    "the default connection on the NEDB backend (nedbd running)",
)
class NedbDistinctLiveTests(SimpleTestCase):
    """N-M14 acceptance against a real nedbd (guarded, never offline).

    Before the fix the clients admin note changelist failed live
    with: DISTINCT is not supported -- GROUP BY <col> gives the
    distinct values with counts (census signature 6).
    """

    databases = {"default"}

    def test_distinct_shapes_and_date_hierarchy_on_live_nedb(self):
        from django.db import connection

        self.assertEqual(connection.display_name, "NEDB (PostgreSQL pgwire)")
        from clients.models import Client, ClientNote
        from saloncore.models import Salon

        salon = Salon.objects.create(name="Distinct Probe Salon", timezone="UTC")
        amy = Client.objects.create(
            salon=salon, first_name="Amy", last_name="Probe"
        )
        bob = Client.objects.create(
            salon=salon, first_name="Bob", last_name="Probe"
        )
        for client, when in (
            (amy, _dt14.datetime(2026, 1, 5, 10, tzinfo=_dt14.timezone.utc)),
            (amy, _dt14.datetime(2026, 3, 5, 10, tzinfo=_dt14.timezone.utc)),
            (bob, _dt14.datetime(2027, 1, 6, 10, tzinfo=_dt14.timezone.utc)),
        ):
            note = ClientNote.objects.create(
                client=client, body="probe", author_name="Probe"
            )
            ClientNote.objects.filter(pk=note.pk).update(created_at=when)
        # Plain-column DISTINCT (GROUP BY re-expression). Scoped
        # by salon: the shared live test DB holds other live tests'
        # rows (SimpleTestCase isolation is the HTTP flush between
        # TestCases, not between these probes).
        rows = list(Client.objects.filter(salon=salon).distinct())
        self.assertEqual({r.pk for r in rows}, {amy.pk, bob.pk})
        salon_ids = list(
            ClientNote.objects.filter(client__salon=salon)
            .distinct()
            .values_list("client__salon__pk", flat=True)
        )
        self.assertEqual(set(salon_ids), {salon.pk})
        # Date hierarchy shapes (Trunc composite under DISTINCT).
        notes = ClientNote.objects.filter(client__salon=salon)
        years = list(notes.dates("created_at", "year"))
        self.assertEqual(
            years, [_dt14.date(2026, 1, 1), _dt14.date(2027, 1, 1)]
        )
        dt_years = list(notes.datetimes("created_at", "year"))
        self.assertEqual([d.year for d in dt_years], [2026, 2027])
