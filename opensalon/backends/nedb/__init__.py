"""NEDB database backend for Django (skeleton, N-M3b).

Selectable via ``ENGINE = "opensalon.backends.nedb"``. NEDB is reached
through its Postgres-compatible pgwire endpoint (psycopg), per ADR 0005
and the NEDB DYOR note (2026-10-30). This package is a skeleton: it
neutralizes connection setup and test-database creation only. Migration /
DDL handling, savepoints, and identity/RETURNING handling are later
microtasks (DYOR section 9, implications 3, 4, and 6).
"""
