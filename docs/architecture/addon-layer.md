# The add-on layer

Status: design, decided 2026-10-30 (see
`docs/decisions/0003-addon-layer.md`). The extension API itself is
designed alongside the first feature lanes, not before them.

## Shape

OpenSalon is a free MIT core plus an add-on layer:

- The **core** (this repository) runs a salon end to end for a single
  location.
- **Add-ons** are separately packaged modules that extend the core
  through a versioned extension API:
  - **Events** the core emits (appointment booked, ticket closed,
    price changed, …) that add-ons can react to.
  - **Hooks** where add-ons can contribute behavior (a checkout step,
    a report, a booking rule).
  - **Namespaced data**: an add-on stores its own data in its own
    tables and reaches core data through the core's services, never
    by patching core tables.
  - **Provider interfaces** like the payments interface, which are
    the plugin shape in its purest form.

## Who builds add-ons

- **Interchained** builds the hosted-service add-ons it sells
  (managed hosting tooling, hosted booking platform, message
  delivery, migration tooling) and custom features for individual
  salons.
- **Anyone else** can build add-ons on exactly the same extension
  points, free or paid, open or closed — that is their business
  decision, the same freedom MIT gives with the core itself.

## The upstream-hook rule

If an add-on needs a capability the core doesn't expose, the
extension point is contributed to the core under MIT, and the
add-on's implementation stays in the add-on. This keeps the core's
public surface honest: Interchained's commercial add-ons are proof
the extension API is sufficient, never evidence of a private one.

## The boundary test

When a feature could live in either place, apply Slice 1's rule:

- A generally useful feature a salon can run itself → **core**.
- Bespoke to one salon, operated by someone else, or costing the
  operator real money per use (hosting, SMS, payment onboarding,
  support) → **add-on**.
