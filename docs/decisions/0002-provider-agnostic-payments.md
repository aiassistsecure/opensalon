# 0002 — Payments are provider-agnostic from day one

Date: 2026-10-30. Status: decided. This is a founding principle,
not a feature.

Payment processing is where closed salon platforms lock salons in:
the real money of a salon (processing on every card it takes) flows
only on the vendor's rails, and leaving the software means leaving
the processor.

OpenSalon refuses that shape:

1. The core is written against one internal payments interface, never
   against a provider's API. See `docs/architecture/payments-interface.md`.
2. Every provider is an adapter implementing that interface. Adding a
   provider never touches checkout logic; removing one never breaks a
   salon's records.
3. The interface is not considered real until two materially different
   providers implement it. First adapters: Stripe (online-first) and
   Square (in-person-first).
4. The salon brings its own provider account and is the merchant.
   OpenSalon never takes custody of funds and never takes a cut of
   processing.
5. No provider-specific fields enter the core data model. Core records
   amount, currency, tender, status, provider id, and an opaque
   provider reference.
6. Raw card data never touches OpenSalon; adapters use each provider's
   hosted fields / terminal SDK.
7. Having no provider at all is a valid configuration. Cash, check,
   and external-terminal tenders are recorded natively, and the till
   is complete without a card integration.

Stripe-only was considered and rejected: one integration is faster,
and it recreates exactly the lock-in OpenSalon exists to remove.
