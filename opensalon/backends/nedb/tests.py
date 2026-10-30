"""Unit tests for the NEDB backend (mock-level, no nedbd).

Run with: python manage.py test opensalon.backends.nedb
These tests pin: no session-setup SQL, no SQL test-database creation,
and the schema editor's catalog-validating no-op DDL handling (N-M3d).
"""

from unittest import mock

from django.db.backends.postgresql.base import (
    DatabaseWrapper as PostgresDatabaseWrapper,
)
from django.test import SimpleTestCase

from opensalon.backends.nedb.base import DatabaseWrapper
from opensalon.backends.nedb.creation import DatabaseCreation
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
