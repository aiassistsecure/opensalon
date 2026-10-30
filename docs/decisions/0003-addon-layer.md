# 0003 — Custom features live in an add-on layer on the MIT core

Date: 2026-10-30. Status: decided.

One rule splits free from paid:

> If it runs on your box, it's MIT. If it runs on ours, it's paid.

Its architectural expression is an add-on layer:

- **Core (this repo, MIT):** everything a salon needs to run itself —
  price book, staff, clients, calendar, checkout, reporting, and a
  self-hosted booking page.
- **Add-on layer (on top):** hosted services Interchained operates,
  and custom features built for a specific salon or as paid offerings —
  bespoke workflows, salon-specific integrations, custom reporting,
  migration tooling.

Rules for the layer:

- Add-ons build **only** on documented extension points: a versioned
  extension API (events, hooks, namespaced add-on data). The payments
  provider interface is the first example of this plugin shape.
- If an add-on needs a capability the core doesn't expose, the
  **extension point** is added to the MIT core so anyone could build
  an equivalent add-on; the custom implementation stays in the add-on.
  Interchained gets no private back door into its own platform.
- Third parties build add-ons on the same points. The layer is how
  everyone extends OpenSalon without forking it.
- The core is never crippled to sell an add-on. Standing test: if a
  salon could plainly run a generally useful feature itself, it
  belongs in the core. Add-ons are for what is bespoke, operated, or
  costs the operator money to run (hosting, message delivery, payment
  onboarding, support).
