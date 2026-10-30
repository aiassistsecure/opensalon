# 0005 — NEDB is the database

Date: 2026-10-30. Status: decided. Supersedes the database section
of 0004.

OpenSalon's database is NEDB — its primary and only store.

- **Shape:** Django connects to `nedbd` over NEDB's
  Postgres-compatible pgwire, using the standard Django postgresql
  backend (psycopg). Application code uses the Django ORM the way it
  would against any Postgres-shaped endpoint; the wire protocol is
  the integration point, not a custom driver.
- **No fallback:** there is no real-Postgres mode, and none will be
  added. A fallback would split testing, support, and contributor
  assumptions across two stores and quietly demote NEDB to an option.
  One store, one source of truth.
- **Packaging:** the Docker Compose target shape is `app + nedbd`.
  The `postgres:16` service in the current compose file is removed by
  a later switch change; this record decides the destination, not
  the mechanics of getting there.

Why NEDB, decided by Mark on 2026-10-30:

- **Dogfooding.** NEDB is Interchained's own database and already
  replaces Postgres across the rest of the stack. OpenSalon is the
  pilot product of that stack; running the salon's book on anything
  else would leave the flagship claim untested exactly where it
  matters most — a real business's daily transactions.
- **Provenance for free.** NEDB's time-travel and provenance are
  properties of the store itself. On NEDB, the salon's book —
  appointments, sales, price changes — is natively auditable and
  rollback-capable, rather than depending on every app remembering
  to write its own history.

0004's reasoning for Postgres was that a point of sale is not a young
database's shakedown cruise. The answer is deliberate: OpenSalon's
pilot salon is Interchained's own, the shakedown is the point, and
any incompatibility found is a bug to fix in NEDB or in OpenSalon's
use of it — never a reason to route around it. The rest of 0004
(application, framework, packaging) stands unchanged.
