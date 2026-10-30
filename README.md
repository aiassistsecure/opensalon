# OpenSalon

Free, open-source salon software. Own your book, your prices, your client
data, and your payment provider — because all of it was always yours.

OpenSalon is the salon platform built by [Interchained](https://github.com/aiassistsecure)
out of running a real salon on closed software. It is MIT licensed: download
it, self-host it, run your salon on it, never pay anyone for the software.

## Why OpenSalon exists

Closed salon platforms share a pattern:

- Your prices live in three places at once and drift apart.
- Getting your own transaction history out is an export job, a fee, or both.
- Payments only flow on the vendor's rails, at the vendor's rates.
- Growth is taxed: per seat, per calendar, per new client.
- Leaving means paying to take your own data with you — if they let you.

OpenSalon is built to be structurally incapable of all of that:

- **One price book.** Services, durations, and prices live in exactly one
  place. Your website, booking page, and front desk all read from it.
- **Your data, in and out.** Full import and full export, in open formats,
  at any time, free. You hold the database.
- **Provider-agnostic payments.** Payments sit behind one interface and
  every provider is an adapter. Bring your own provider account, switch
  providers without leaving OpenSalon, or run cash-only. OpenSalon never
  takes custody of your money and never takes a cut of your processing.
- **No per-seat tax, no marketplace commission.** Ever. There is no
  marketplace. Your clients are your clients.
- **Open core, honest paid services** (see below).

## Free core, paid services

One rule decides what is free and what is paid:

> **If it runs on your box, it's MIT. If it runs on ours, it's paid.**

The MIT core in this repository is a complete salon system: price book,
staff and levels, clients, appointment calendar, checkout and transactions,
reporting, and your own self-hosted online booking page.

Interchained sells what it *operates*: managed hosting, the hosted online
booking platform, payments onboarding and support through the platform,
message delivery (SMS/email reminders), and custom features built as an
**add-on layer** on top of the core. Add-ons — ours and third parties' —
are built only on documented extension points in the core, so anyone can
build the same kind of extension without forking. See
[docs/architecture/addon-layer.md](docs/architecture/addon-layer.md).

## Status

Foundation release. This repository currently contains the project
foundation: license, architecture decisions, a Django + Postgres skeleton,
and a one-command Docker Compose install. Feature work proceeds in lanes:

1. Price book & service truth
2. Day book & clients
3. Checkout, transactions & day close (with the payments interface)
4. Online booking & self-host release

The v1 test is simple: a real salon runs a full Saturday on OpenSalon,
and that night's numbers are queryable without an export job.

## Quick start

```bash
cp .env.example .env
docker compose up
```

Then open http://localhost:8000/health/ — a healthy install answers
`{"status": "ok"}`.

## Stack

- Python / Django, server-rendered with light JavaScript
- Postgres (SQLite fallback for a first local look)
- Docker Compose packaging
- Payments: provider interface first, adapters second. First adapters
  planned: Stripe (online-first) and Square (in-person-first), chosen so
  the interface has to survive two very different providers.
  See [docs/architecture/payments-interface.md](docs/architecture/payments-interface.md).

Decision records live in [docs/decisions/](docs/decisions/).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Contributions are accepted under
the MIT license, no CLA.

## License and trademark

The code is MIT licensed — see [LICENSE](LICENSE).

The OpenSalon name and logo are not part of that grant. See
[TRADEMARK.md](TRADEMARK.md): you may fork the code freely, but a hosted
fork offered to the public must use its own name.
