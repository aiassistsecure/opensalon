# Payments interface

Status: design, decided 2026-10-30 (see
`docs/decisions/0002-provider-agnostic-payments.md`). Not yet
implemented; it lands with the checkout lane, before any adapter.

## Purpose

All money movement in OpenSalon goes through one provider-neutral
interface. Core code (checkout, booking deposits, refunds, no-show
charges) depends only on this interface. Each payment provider is an
adapter implementing it.

## The interface (sketch)

An adapter provides some or all of these capabilities, and declares
which, so the UI can be honest about what a salon's provider supports:

- `authorize(amount, currency, payment_method_ref)` — reserve funds
  (e.g. a booking deposit hold).
- `capture(authorization_ref, amount)` — settle an authorization, in
  full or in part.
- `charge(amount, currency, payment_method_ref)` — authorize + capture
  in one step (the common online case).
- `refund(payment_ref, amount)` — full or partial refund.
- `void(authorization_ref)` — release an uncaptured hold.
- `terminal_charge(amount, currency, device_ref)` — in-person payment
  on a paired terminal, for providers that offer one.
- `save_payment_method(client_ref)` — card-on-file for deposits and
  no-show protection, tokenized by the provider.
- Webhook / event ingestion: the adapter translates provider events
  into normalized payment status changes
  (`pending → authorized → captured`, `→ refunded`, `→ failed`,
  `→ voided`).

## Data model rules

A core payment record contains exactly:

- amount (minor units), currency
- tender type (`card`, `cash`, `check`, `external`, …)
- status (the normalized set above)
- provider id (or none, for native tenders)
- provider reference (opaque string; core never parses it)
- links to the core objects it settles (ticket, appointment deposit)

Anything provider-specific — charge ids with semantics, payout ids,
provider fee breakdowns in the provider's own shape — lives inside
the adapter's own namespaced storage, per the add-on layer rules.

## Rules for adapters

1. The salon authenticates with **its own** provider account. Adapter
   configuration is per-salon credentials, never platform credentials.
   OpenSalon is never the merchant of record.
2. Raw card data never passes through OpenSalon. Adapters use the
   provider's hosted fields / terminal SDK.
3. An adapter must pass the shared conformance tests for every
   capability it declares.
4. Losing an adapter (provider discontinued, salon switches) must
   leave all core payment records readable and reportable. Historical
   records are OpenSalon's, in OpenSalon's shape.

## First adapters

- **Stripe** — online-first: booking deposits, card-on-file, no-show
  charges.
- **Square** — in-person-first: terminals, and the many salons already
  running Square hardware.

Chosen as a pair on purpose: if the interface survives both shapes,
it is probably the right interface.
