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
        self.assertEqual(pairs[-1], ("POST", "/v1/databases"))
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
    """

    databases = {"default"}

    def test_salon_datetime_round_trip(self):
        from django.db import connection

        self.assertEqual(
            type(connection).__module__, "opensalon.backends.nedb.base"
        )
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
