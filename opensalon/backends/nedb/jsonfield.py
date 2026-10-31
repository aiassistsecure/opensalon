"""JSON values for NEDB: JSON text as a plain string literal.

Per the NEDB DYOR note (2026-10-30), implication 7 (expression and
cast VALUES are refused on the pgwire write path by design,
pgwire.rs:1246-1255) and implication 9 (nested data is stored
verbatim -- the SI document mapping's JSON column; here the JSON
document itself is the stored string scalar).

Measured against nedbd-v2 12.15.16 (N-M8a probe; evidence file cited
in the PR):

* Django's PostgreSQL backend binds parameters client-side -- its
  cursor class is a psycopg ``ClientCursor`` -- so a parameter's
  text dumper decides the SQL text Django sends. The stock
  PostgreSQL operations return ``psycopg.types.json.Jsonb`` from
  ``adapt_json_value``, and psycopg's Jsonb text dumper renders the
  value as a quoted literal *with a ``::jsonb`` cast suffix*:
  ``'{"cash": "85.00"}'::jsonb``. NEDB refuses that verbatim --
  ``cannot use "'{...}'::jsonb" as a value -- this endpoint accepts
  string literals, numbers, TRUE/FALSE and NULL`` -- the live-suite
  signature behind ~40 errors, mostly checkout JSON writes
  (``Cashup.tender_totals``, ``Receipt.lines`` / ``Receipt.tender``).
* The same ``Jsonb`` sent through psycopg's server-binding cursor
  travels as a typed bind parameter, never becomes SQL text, and
  NEDB accepts it -- which is why raw-psycopg probes pass while
  every Django JSONField write fails. The cast exists only in the
  client-side rendering, so the fix belongs to what this backend
  hands the dumper, not to SQL text rewriting (implication 1).
* A plain string parameter interpolates as a plain string literal,
  which NEDB accepts and stores verbatim; SELECT hands the identical
  JSON text back as a Python ``str``.

So ``adapt_json_value`` below returns the JSON text itself -- exactly
what Django's base operations class returns for the non-PostgreSQL
backends -- honouring the field's encoder. The read path needs no
converter: ``JSONField.from_db_value`` already parses string values
with ``json.loads``, and an operations converter that parsed first
would feed it a dict and break it. ``None`` passes through so it
stays SQL NULL, never the JSON text ``"null"``.

The ``::json`` sibling (N-M8b probe; evidence file cited in the PR):
no Django path emits it -- the only ``::json`` string in Django is
the psycopg2 fallback's ``::jsonb`` suffix, no Django code constructs
psycopg's ``Json`` wrapper, and a live 16-shape compile/run battery
(exact, contains, has_key(s), key transforms, ordering, ``Value``,
``Cast`` -- which emits ``::jsonb`` only, SELECT-side) sent no
``::json`` token to nedbd. Raw psycopg proves the hazard is real if a
wrapper ever became a VALUE: ``Json`` mogrifies to ``'...'::json``
and NEDB refuses it on INSERT with the same verbatim refusal as
``::jsonb`` (DYOR 9.7). So the guard below unwraps a ``Json`` /
``Jsonb`` wrapper a caller supplies as a JSONField value to its
plain JSON text (honouring the wrapper's own ``dumps``) -- through
Django's sole adaptation entry a wrapper can never be the vehicle
for a cast VALUE, and it no longer dies in ``json.dumps`` either.
Raw cursors bypass adaptation entirely; that is the caller's SQL,
not rewritten here (DYOR 9.1).
"""

import json

try:
    from psycopg.types.json import Json, Jsonb
except ImportError:  # pragma: no cover - psycopg is a PG dependency
    Json = Jsonb = None

_JSON_WRAPPERS = tuple(t for t in (Json, Jsonb) if t is not None)


def adapt_json_value(value, encoder):
    """JSON value -> JSON text (None and expressions pass through)."""
    if value is None:
        return value
    if hasattr(value, "resolve_expression"):
        # Query expressions are not values; Django expects adaptation
        # hooks to pass them through untouched (cf. temporal.py).
        return value
    if _JSON_WRAPPERS and isinstance(value, _JSON_WRAPPERS):
        # N-M8b guard: unwrap psycopg's Json/Jsonb to plain text so
        # its cast-rendering dumper never sees it (module docstring).
        if value.dumps is not None:
            text = value.dumps(value.obj)
            return text.decode() if isinstance(text, bytes) else text
        return json.dumps(value.obj, cls=encoder)
    return json.dumps(value, cls=encoder)
