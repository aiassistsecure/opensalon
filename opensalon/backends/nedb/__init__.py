"""NEDB database backend for Django (skeleton, N-M3b).

Selectable via ``ENGINE = "opensalon.backends.nedb"``. NEDB is reached
through its Postgres-compatible pgwire endpoint (psycopg), per ADR 0005
and the NEDB DYOR note (2026-10-30). This package neutralizes
connection setup and test-database creation, no-ops DDL after catalog
validation (``schema.py``), and no-ops savepoints (DYOR section 9.4:
``uses_savepoints = False`` plus inert ``_savepoint*`` hooks).
Identity/RETURNING (implication 6, N-M3g): ``identity.py`` +
``compiler.py`` -- the adapter assigns client-generated integer PKs
on insert and converts numeric-string PKs back to ints on read.
"""
