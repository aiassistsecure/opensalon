"""NEDB compilers: client-assigned PKs, no UNNEST, HAVING wrap (9.1).

HAVING (N-M8f, DYOR 9.1/9.9; probe
``nedb-having-probe-2026-10-31.md``): on nedbd-v2 12.15.16 a HAVING
clause filters groups correctly, but if the FIRST group is filtered
out, every surviving row is emitted as a zero-column row with no
result description -- Django's ``apply_converters`` then dies with
``IndexError`` (live signature: ``clients.test_inactive``
``test_default_threshold_is_90_days``, where the first-created
client is the recent one HAVING removes). No features flag makes
Django avoid HAVING for a filter on an aggregate annotation. The
measured equivalent the SQL evaluator answers correctly is a
derived table: the grouped annotate query without HAVING inside,
the HAVING condition as an outer WHERE on the annotation columns.
:class:`SQLCompiler` below performs exactly that re-expression at
the expression-tree layer (each aggregate in the HAVING tree that
is a selected annotation is replaced by a reference to the
subquery's column of the same name; no statement text is rewritten,
per DYOR 9.1). Shapes it cannot prove equivalent -- sliced,
distinct, combinator, qualify, subquery use, or a HAVING aggregate
that is not a selected annotation -- keep the stock HAVING
compilation unchanged.

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

import copy

from django.core.exceptions import EmptyResultSet
from django.db.backends.postgresql.compiler import (  # noqa: F401
    SQLAggregateCompiler,
    SQLDeleteCompiler,
    SQLUpdateCompiler,
)
from django.db.backends.postgresql.compiler import (
    SQLCompiler as PostgresSQLCompiler,
)
from django.db.models.expressions import BaseExpression, Col, F, RawSQL
from django.db.models.fields import AutoFieldMixin
from django.db.models.sql.compiler import (
    SQLInsertCompiler as BaseSQLInsertCompiler,
)
from django.db.models.sql.where import WhereNode

from . import identity

__all__ = [
    "SQLAggregateCompiler",
    "SQLCompiler",
    "SQLDeleteCompiler",
    "SQLInsertCompiler",
    "SQLUpdateCompiler",
]

_HAVING_SUBQUERY_ALIAS = "nedb_having_sub"


class SQLCompiler(PostgresSQLCompiler):
    """SELECT compiler with the N-M8f HAVING re-expression (above)."""

    # -- plan: decide whether the wrap is provably equivalent -------
    def _having_wrap_plan(self):
        query = self.query
        if (
            query.combinator
            or query.is_sliced
            or query.distinct
            or query.extra
            or query.subquery
            or query.explain_info
            or getattr(query, "select_for_update", False)
        ):
            return None
        try:
            where, having, qualify = query.where.split_having_qualify()
        except Exception:
            return None
        if qualify is not None or having is None or not having.children:
            return None
        mask = query.annotation_select_mask
        selected = {
            name: expr
            for name, expr in query.annotations.items()
            if mask is None or name in mask
        }
        if not selected:
            return None
        order_sql = self._outer_ordering_sql(selected)
        if order_sql is None:
            return None
        if not self._having_tree_supported(having, selected):
            return None
        return where, having, selected, order_sql

    def _having_tree_supported(self, node, selected):
        if isinstance(node, WhereNode):
            return all(
                self._having_tree_supported(child, selected)
                for child in node.children
            )
        # A lookup leaf: lhs may wrap a selected annotation in
        # transforms/functions; rhs must carry no aggregate at all.
        lhs_ok = self._expr_supported(node.lhs, selected)
        rhs = getattr(node, "rhs", None)
        rhs_ok = not isinstance(rhs, BaseExpression) or (
            not rhs.contains_aggregate and not self._contains_col(rhs)
        )
        return lhs_ok and rhs_ok

    def _expr_supported(self, expr, selected):
        if any(expr is ann for ann in selected.values()):
            return True
        if not isinstance(expr, BaseExpression):
            return False
        if isinstance(expr, Col) or expr.contains_aggregate:
            # A bare column, or an aggregate that is not itself a
            # selected annotation, has no subquery column to name.
            return False
        return all(
            self._expr_supported(source, selected)
            for source in expr.get_source_expressions()
            if isinstance(source, BaseExpression)
        )

    @staticmethod
    def _contains_col(expr):
        if isinstance(expr, Col):
            return True
        if isinstance(expr, BaseExpression):
            return any(
                SQLCompiler._contains_col(source)
                for source in expr.get_source_expressions()
                if isinstance(source, BaseExpression)
            )
        return False

    # -- ordering: re-express on the subquery's columns -------------
    def _outer_ordering_sql(self, selected):
        """Outer ORDER BY terms, or None if any term is unsupported.

        Supports plain field/annotation names (explicit or Meta
        ordering), as strings or ``F()`` objects. Ordering columns
        must be selected: model fields always are; annotations must
        be in ``selected``.
        """
        query = self.query
        terms = list(query.order_by) or list(
            query.get_meta().ordering or ()
        )
        if not terms:
            return ""
        quote = self.connection.ops.quote_name
        parts = []
        for term in terms:
            if isinstance(term, F):
                term = term.name
            if not isinstance(term, str) or term == "?" or "__" in term:
                return None
            descending = term.startswith("-")
            name = term.lstrip("-")
            if name in selected:
                column = name
            else:
                try:
                    field = query.get_meta().get_field(name)
                except Exception:
                    return None
                column = getattr(field, "column", None)
                if column is None:
                    return None
            parts.append(
                "%s.%s %s"
                % (
                    quote(_HAVING_SUBQUERY_ALIAS),
                    quote(column),
                    "DESC" if descending else "ASC",
                )
            )
        return ", ".join(parts)

    # -- transform: HAVING tree -> outer WHERE tree ------------------
    def _subquery_ref(self, name, output_field):
        quote = self.connection.ops.quote_name
        return RawSQL(
            "%s.%s" % (quote(_HAVING_SUBQUERY_ALIAS), quote(name)),
            [],
            output_field=output_field,
        )

    def _replace_expr(self, expr, refs):
        if id(expr) in refs:
            return refs[id(expr)]
        sources = expr.get_source_expressions()
        if not sources:
            return expr
        new_sources = [
            self._replace_expr(source, refs)
            if isinstance(source, BaseExpression)
            else source
            for source in sources
        ]
        if all(new is old for new, old in zip(new_sources, sources)):
            return expr
        replaced = copy.copy(expr)
        replaced.set_source_expressions(new_sources)
        return replaced

    def _replace_node(self, node, refs):
        if isinstance(node, WhereNode):
            replaced = copy.copy(node)
            replaced.children = [
                self._replace_node(child, refs) for child in node.children
            ]
            return replaced
        replaced = copy.copy(node)
        replaced.lhs = self._replace_expr(node.lhs, refs)
        return replaced

    # -- compilation --------------------------------------------------
    def as_sql(self, with_limits=True, with_col_aliases=False):
        plan = self._having_wrap_plan()
        if plan is None:
            return super().as_sql(
                with_limits=with_limits, with_col_aliases=with_col_aliases
            )
        where, having, selected, order_sql = plan
        query = self.query
        original_where = query.where
        original_order_by = query.order_by
        original_default_ordering = query.default_ordering
        # Inner: grouped annotate query, no HAVING part in its WHERE,
        # no ordering (ordering is re-applied outside, below). The
        # split yields None for the WHERE part when the query had no
        # non-aggregate condition at all; Django expects a node.
        query.where = where if where is not None else WhereNode()
        query.order_by = ()
        query.default_ordering = False
        try:
            inner_sql, inner_params = super().as_sql(
                with_limits=False, with_col_aliases=with_col_aliases
            )
        finally:
            query.where = original_where
            query.order_by = original_order_by
            query.default_ordering = original_default_ordering
        refs = {
            id(expr): self._subquery_ref(name, expr.output_field)
            for name, expr in selected.items()
        }
        outer_where = self._replace_node(having, refs)
        try:
            where_sql, where_params = self.compile(outer_where)
        except EmptyResultSet:
            where_sql, where_params = "0 = 1", []
        quote = self.connection.ops.quote_name
        sql = "SELECT * FROM (%s) AS %s WHERE %s" % (
            inner_sql,
            quote(_HAVING_SUBQUERY_ALIAS),
            where_sql,
        )
        if order_sql:
            sql += " ORDER BY %s" % order_sql
        return sql, [*inner_params, *where_params]


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
