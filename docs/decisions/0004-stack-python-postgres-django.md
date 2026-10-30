# 0004 — Stack: Python + Django + Postgres

Date: 2026-10-30. Status: decided.

- **Application:** one Python service. Python has the largest plausible
  contributor pool for a salon-adjacent open-source project after
  TypeScript, and it is where a small team iterates fastest on the
  CRUD + reporting surface a salon system mostly is.
- **Framework:** Django. The back office (services, staff, clients,
  price book) is CRUD-heavy; Django ships auth, admin, migrations,
  and forms rather than OpenSalon assembling and owning them. Pages
  are server-rendered with HTMX and light JavaScript.
- **Database:** Postgres, the transactional store. A point of sale is
  not a young database's shakedown cruise; Postgres is boring, proven,
  and what every hosting and contributor assumption in the ecosystem
  expects. (A SQLite fallback exists only so a first local look needs
  no database server.)
- **Packaging:** Docker Compose. Self-hosting is `docker compose up`,
  with automated backups the owner controls. That is the install bar
  for a non-technical salon owner.

Rust was considered for the application and rejected for it: compile-
time rigor pays in money-handling correctness, but a small team's
feature velocity is measurably lower, and the casual-contributor pool
for business software in Rust is small. Rust already exists in the
stack where it belongs (infrastructure); OpenSalon consumes that
work rather than duplicating its costs.
