"""NEDB test-database creation: never create or drop via SQL.

DYOR implication 8: NEDB has no ``postgres`` maintenance database and
refuses ``CREATE DATABASE`` (DDL is refused by design; collections and
databases are not created by SQL). Databases — including test
databases — are pre-created over nedbd's HTTP API
(``POST /v1/databases``) before Django connects.

This class therefore gives the backend ``TEST = {"CREATE_DB": False}``
semantics unconditionally: creating a test database issues no SQL and
assumes the (test) database already exists, and destroying one issues
no ``DROP DATABASE`` either (teardown via HTTP is a later microtask;
DYOR implications 4 and 5).
"""

from django.db.backends.postgresql.creation import (
    DatabaseCreation as PostgresDatabaseCreation,
)


class DatabaseCreation(PostgresDatabaseCreation):
    def _execute_create_test_db(self, cursor, parameters, keepdb=False):
        # No-op: never send CREATE DATABASE to NEDB. The database must
        # have been pre-created over the HTTP API.
        self.log(
            "NEDB backend: skipping CREATE DATABASE; the test database "
            "must be pre-created via POST /v1/databases."
        )

    def _create_test_db(self, verbosity, autoclobber, keepdb=False):
        # Bypass the PostgreSQL flow entirely: it opens a cursor against
        # a maintenance ("postgres") database that NEDB does not have.
        return self._get_test_db_name()

    def _destroy_test_db(self, test_database_name, verbosity):
        # No-op: never send DROP DATABASE to NEDB.
        self.log(
            "NEDB backend: skipping DROP DATABASE for %s; teardown is "
            "handled outside SQL." % test_database_name
        )
        return test_database_name
