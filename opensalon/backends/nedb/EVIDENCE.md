# NEDB backend skeleton — evidence (N-M3b, 2026-10-30)

Backend under test: `ENGINE = "opensalon.backends.nedb"` (this package),
Django 5.2.18, psycopg 3, nedbd-v2 **12.15.16** (the pinned wheel binary
`nedb/nedbd-v2` in the si2 venv — same version as the N-M2 spike).

Daemon launch (verbatim):

```
nedbd-v2 --data /tmp/os-nedb-data --port 17070 --pg-port 5432
```

Database pre-created over HTTP before any Django connection
(DYOR implication 8):

```
POST /v1/databases {"name":"opensalon_probe"}
-> {"database":{"name":"opensalon_probe","seq":0,"head":""}}
```

Probe: `evidence_probe.py` in this package (plain ORM, no raw SQL except
one `SELECT version()` through the ORM connection). Full probe output
was captured during the run; the load-bearing lines, verbatim:

## What worked

Connection itself — the spike's gate blocker is gone. With the stock
PostgreSQL backend every connection died on
`SELECT set_config('TimeZone', 'UTC', false)`; through this backend the
connection opens and serves queries:

```
ENGINE: opensalon.backends.nedb
vendor/display: postgresql / NEDB (PostgreSQL pgwire)
SELECT version() -> PostgreSQL 15.0 (NEDB 12.15.16) — tamper-evident, append-only, permanent history. SELECT + INSERT/UPDATE/DELETE; an UPDATE is a new version, so prior values stay readable with AS OF SYSTEM TIME.
```

Insert/select round-trip on an existing model with plain literal
columns (`team.StaffMember`: str/int/bool + FK ids; NEDB is schemaless,
so no table was created first):

```
ORM StaffMember read-back rows: [{'display_name': 'Evidence Stylist', 'online_bookable': True, 'salon_id': 1}]
```

Select on a model whose insert failed also worked (empty result, no
error — consistent with the spike's schemaless empty-collection read):

```
ORM Salon filter read-back rows: []
```

## What failed (verbatim)

1. ORM insert of `saloncore.Salon` (has `auto_now_add`/`auto_now`
   DateTimeFields). Django's PostgreSQL compiler renders datetime
   parameters as a `::timestamptz` cast expression, which NEDB refuses
   by design (expression values on the write path; DYOR section 5):

   ```
   django.db.utils.NotSupportedError: cannot use "'2026-10-30 20:23:22.939249+00:00'::timestamptz" as a value — this endpoint accepts string literals, numbers, TRUE/FALSE and NULL. Expressions, casts and function calls are not evaluated, because storing an unevaluated expression as text would be worse than refusing it
   ```

   This is a new, adapter-side finding for the N-M3 queue: datetime
   parameter adaptation needs handling in a later microtask (alongside
   implication 7's ban on expression-valued writes).

2. Identity/RETURNING mismatch, now confirmed through the ORM
   (DYOR implication 6; spike saw it in raw SQL): the StaffMember row
   above **was** inserted and read back, but Django received no pk:

   ```
   ORM StaffMember create returned, pk: None
   ```

## Regression check (SQLite, no nedbd)

```
OPENSALON_USE_SQLITE=1 python manage.py test opensalon.backends.nedb
-> Ran 9 tests — OK
OPENSALON_USE_SQLITE=1 python manage.py test
-> Ran 72 tests — OK
```

## Scope reminder

Skeleton only: no migration/DDL handling, no savepoint mapping, no
identity adaptation, no datetime-cast adaptation — each is its own
later microtask in the N-M3 track. Settings defaults are unchanged;
this backend is opt-in via the ENGINE string until the settings flip.
