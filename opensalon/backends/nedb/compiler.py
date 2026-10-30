"""NEDB compilers: client-assigned PKs on insert, no UNNEST (9.6).

DYOR implication 1 / section 9.1: work at the execution/semantics
layer only. Two insert semantics of the stock PostgreSQL compiler
break on NEDB's pgwire, both by design (DYOR section 5):

* It omits the auto PK column and relies on the database to assign
  it. NEDB assigns a string ``_id`` and RETURNING yields NULL, so
  Django objects come back with ``pk = None`` and any later use of
  a read-back string PK as an integer crashes (see
  ``identity.py``). Here the insert compiler assigns a
  client-generated integer PK (``identity.assign_pk_if_missing``)
  and prepends the PK field to the insert field list whenever the
  PK is an auto field that the caller left out, so the INSERT
  carries ``id`` explicitly and RETURNING yields that integer
  (verified live on nedbd-v2 12.15.16).

* For multi-row inserts it assembles values through ``UNNEST``
  arrays, which NEDB's write path refuses (its evaluator reports
  the shape as an unsupported ``INSERT ... SELECT``). Inheriting
  Django's base insert compiler instead of PostgreSQL's keeps
  ordinary multi-row ``VALUES (...), (...)`` placeholders, which
  NEDB accepts, including with RETURNING.

All other compilers are PostgreSQL's, unchanged.
"""

from django.db.backends.postgresql.compiler import (  # noqa: F401
    SQLAggregateCompiler,
    SQLCompiler,
    SQLDeleteCompiler,
    SQLUpdateCompiler,
)
from django.db.models.fields import AutoFieldMixin
from django.db.models.sql.compiler import (
    SQLInsertCompiler as BaseSQLInsertCompiler,
)

from . import identity

__all__ = [
    "SQLAggregateCompiler",
    "SQLCompiler",
    "SQLDeleteCompiler",
    "SQLInsertCompiler",
    "SQLUpdateCompiler",
]


class SQLInsertCompiler(BaseSQLInsertCompiler):
    def as_sql(self):
        query = self.query
        opts = query.get_meta()
        pk = opts.pk
        fields = query.fields
        # Inject the PK only for the shape that needs it: an auto PK
        # the caller excluded (single save() with pk unset, and
        # bulk_create's without-pk partition), with real objects to
        # assign to, and a non-empty field list (the empty-object
        # DEFAULT VALUES shape has no value row to extend).
        if (
            fields
            and pk is not None
            and isinstance(pk, AutoFieldMixin)
            and pk not in fields
            and query.objs
        ):
            for obj in query.objs:
                identity.assign_pk_if_missing(obj, pk)
            query.fields = [pk, *fields]
        return super().as_sql()
