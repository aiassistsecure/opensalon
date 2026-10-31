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

Working software, in daily use at the pilot salon on its real book.
Built and verified so far:

1. **Price book** — services, categories, staff levels, and prices in
   exactly one place, with full import and export.
2. **Day book** — one column per stylist, one block per service,
   drag to move, check-in / no-show toggles, breaks, and a booking
   flow that paints in the click's own frame (see
   [0006](docs/decisions/0006-the-book-lives-in-the-client.md)).
3. **Roster book** — perpetual scheduling patterns with per-date
   overrides; the roster controls both the day book and online
   booking availability.
4. **Clients** — the full client record: opt-ins for reminders,
   appointment notes and persistent record notes (never blurred),
   full import and export.
5. **Checkout & cashup** — sales and receipts (including emailed
   receipts) behind the provider-agnostic payments interface, and a
   cashup that closes the day's takings by tender — more than once
   a day is fine; a cashup never locks the day.
6. **Products & inventory** — the retail shelf with barcodes,
   receiving, and stock adjustments.
7. **Team** — staff records, levels, and a PIN time clock with
   attendance recorded against the schedule.
8. **Insights** — revenue splits, future-book value, busiest days.

Next lanes: the salon-branded online booking page, and automations
(appointment reminders first — marketing last).

The v1 test was simple: a real salon runs a full Saturday on
OpenSalon, and that night's numbers are queryable without an export
job. The pilot salon now does that as a matter of routine.

## Quick start

```bash
cp .env.example .env
docker compose up
```

Then open http://localhost:8000/health/ — a healthy install answers
`{"status": "ok"}`.

## Stack

- Python / Django, server-rendered templates, vanilla JavaScript —
  no build step
- NEDB is the database
  ([0005](docs/decisions/0005-nedb-is-the-database.md)): Django
  reaches it over its Postgres-compatible wire. A SQLite mode
  exists for development only
- The day book runs on an embedded NEDB store in the browser
  ([0006](docs/decisions/0006-the-book-lives-in-the-client.md)) —
  the same engine at both ends
- Docker Compose packaging (app + nedbd)
- Payments: one provider interface; the core names no vendor and
  never takes custody of money. The shipped proof tenders are cash
  and external tender (a card run on the salon's own terminal);
  vendor adapters live in the add-on layer. See
  [docs/architecture/payments-interface.md](docs/architecture/payments-interface.md)

Decision records live in [docs/decisions/](docs/decisions/).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Contributions are accepted under
the MIT license, no CLA.

## License and trademark

The code is MIT licensed — see [LICENSE](LICENSE).

The OpenSalon name and logo are not part of that grant. See
[TRADEMARK.md](TRADEMARK.md): you may fork the code freely, but a hosted
fork offered to the public must use its own name.
