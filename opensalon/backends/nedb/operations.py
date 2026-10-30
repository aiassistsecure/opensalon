"""NEDB operations: no session-setup SQL and no savepoint SQL, ever.

DYOR implication 2 / spike blocker 1: NEDB's pgwire refuses
``set_config()`` by design ("refused rather than answered with NULL,
because a NULL column reads as missing DATA rather than a missing
feature"). Django's PostgreSQL backend builds its timezone statement
from ``set_time_zone_sql()``, so that method is neutralized here. The
wrapper in ``base.py`` additionally never calls it: both layers are
kept so no future caller can reintroduce the statement by accident.
"""

from django.db.backends.postgresql.operations import (
    DatabaseOperations as PostgresDatabaseOperations,
)


class DatabaseOperations(PostgresDatabaseOperations):
    # -- savepoints: no SQL exists on this backend (DYOR 9.4) --------
    # NEDB refuses SAVEPOINT / RELEASE / ROLLBACK TO at execution, and
    # features.uses_savepoints is False, so Django never asks for this
    # SQL. Returning None (not a statement) keeps the builders inert
    # for any direct caller, mirroring set_time_zone_sql below.

    def savepoint_create_sql(self, sid):
        return None

    def savepoint_commit_sql(self, sid):
        return None

    def savepoint_rollback_sql(self, sid):
        return None

    def set_time_zone_sql(self):
        # Neutralized: NEDB refuses set_config() on pgwire, and the
        # wrapper never executes a timezone statement. Returning an
        # empty string (not a set_config statement) is the marker that
        # no session-setup SQL exists on this backend.
        return ""
