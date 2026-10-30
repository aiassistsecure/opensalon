# Contributing to OpenSalon

Thanks for helping build salon software that salons actually own.

## License of contributions

Contributions are accepted under the MIT license (inbound = outbound).
There is no CLA. By submitting a contribution you agree it is licensed
under the repository's [LICENSE](LICENSE).

## Principles that govern what lands

1. **One source of truth.** Every fact (a price, a client, a transaction)
   lives in exactly one place. Features that copy facts around get fixed,
   not merged.
2. **Provider-agnostic payments.** Core code never speaks a payment
   provider's dialect. Provider behavior belongs in an adapter behind
   [the payments interface](docs/architecture/payments-interface.md).
3. **Extension points before add-ons.** If an add-on (ours included)
   needs a capability the core doesn't expose, the *extension point*
   goes into the core. Private hooks for Interchained's own add-ons are
   not accepted.
4. **Export is a feature, not a favor.** Anything a salon can enter,
   a salon can export, in an open format, without asking anyone.
5. **Boring at the till.** The transactional core favors proven
   technology and explicit behavior over cleverness. Money-handling
   code is reviewed for correctness before elegance.

## Workflow

- Work happens on branches with pull requests. Keep a PR to one
  coherent change.
- Add or update tests for behavior you change.
- Update the decision records in `docs/decisions/` when a change
  settles an architectural question, and say so in the PR.

## Development

```bash
cp .env.example .env
docker compose up
```

Or locally, in a virtual environment:

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py check
```
