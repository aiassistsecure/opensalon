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
compilation unchanged. (N-M11 addendum: the wrap's outer projection
is now the subquery's columns named explicitly in inner order --
NEDB reorders derived-table columns under ``SELECT *``, measured in
the N-M11 probe addendum; shapes whose columns lack unique names
keep ``SELECT *``.)

GROUP BY expressions (N-M11, DYOR 9.1/9.9; probe
``nedb-groupby2-probe-2026-10-31.md``, census signature 2): NEDB's
evaluator checks GROUP BY at constituent-column level. A selected
non-aggregate expression (live shape: checkout SaleSearch's
``Concat(client__first_name, " ", client__last_name)`` annotation
next to a ``Sum`` annotation) fails verbatim --
``column "clients_client.first_name" must appear in the GROUP BY
clause or be used in an aggregate function`` -- whether Django
groups by the expression's select ordinal (its default, via
``allows_group_by_select_index``) or by the full expression text
(both measured live on nedbd-v2 12.15.16). Grouping by the
expression's constituent columns is measured correct.
:class:`SQLCompiler` therefore expands such an expression's GROUP
BY entry into its constituent columns at the expression-tree layer
(``collapse_group_by``, the hook stock Django uses for its PK
collapse; no statement text is rewritten, per DYOR 9.1), ONLY where
the finer grouping is provably equivalent: every constituent column
must already be functionally determined by the existing GROUP BY
keys -- the column itself is grouped, its table's PK is grouped, or
its table is joined many-to-one / one-to-one on a grouped
parent-side column, so the joined row, hence the column, is
constant within each existing group and grouping by it can split
no group. Non-deterministic or unsupported expression shapes, and
columns reached over reverse (one-to-many) relations, keep the
stock compilation unchanged.

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

DISTINCT (N-M14, DYOR 5 / 9.1 / 9.9; probe
``nedb-distinct-probe-2026-10-31.md``, census signature 6): DYOR
section 5 records DISTINCT as refused by design -- "GROUP BY
<col> gives the distinct values with counts" -- and that is the
verbatim error the clients admin changelist raises live. The
probe refines it: nedbd-v2 12.15.16's SQL evaluator answers plain
DISTINCT, but a statement routed off the evaluator (an
``AT TIME ZONE`` clause does that) hits the refusal, and
expression projections cannot be grouped by their expression
(the evaluator checks constituent columns, the N-M11 signature).
:class:`SQLCompiler` therefore re-expresses exactly the
provably-equivalent shape at the expression-tree layer (no
statement text is rewritten, per DYOR 9.1): a DISTINCT query
whose compiled projection -- selected columns plus the extra
ordering columns Django adds to a DISTINCT select -- is entirely
plain columns, with no pre-existing grouping, HAVING, aggregate,
combinator, slice, subquery, extra or locking, compiles with
``distinct`` cleared and ``group_by = True``, i.e. GROUP BY over
exactly the columns DISTINCT would dedupe (extra ordering
columns included; Django trims them from results in both
shapes, and NULLs group together under both semantics).
Ordering must likewise be by selected columns or plain columns;
simple Meta ordering is re-applied as explicit ordering for the
compile, because a grouped compile would otherwise drop it (a
Meta ordering that cannot be made explicit, with a column
outside the projection, keeps stock). Every other DISTINCT
shape keeps the stock compilation unchanged. The changelist's
other stacked refusal -- ``DATE_TRUNC(... AT TIME ZONE ...)``
from its date hierarchy -- is re-expressed separately in
``operations.py`` / ``temporal.trunc_sql`` (N-M8e family).

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
from django.db.models.expressions import (
    BaseExpression,
    Col,
    CombinedExpression,
    F,
    Func,
    RawSQL,
    Value,
)
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

    # -- GROUP BY: expand determined expressions to columns (N-M11) --
    # Node types a grouping expansion may walk through: deterministic
    # combinations of columns and constants only. Anything else
    # (subqueries, aggregates, random/now functions, lookups) keeps
    # the stock grouping for that expression.
    # Case/When are deliberately absent: a When's condition is not a
    # plain source expression, so its columns cannot be collected
    # exhaustively here -- such shapes keep the stock grouping.
    _GROUP_BY_EXPANDABLE = (Col, Value, Func, CombinedExpression)
    _GROUP_BY_NEVER_EXPAND = {"Now", "Random"}

    def collapse_group_by(self, expressions, having):
        expressions = self._expand_group_by_expressions(list(expressions))
        return super().collapse_group_by(expressions, having)

    def _expand_group_by_expressions(self, expressions):
        # Iterate to a fixpoint: each expansion replaces a key by
        # columns already determined by the keys before it, so the
        # group partition is invariant at every single step.
        for _ in range(len(expressions) + 1):
            grouped, determined = self._group_determination(expressions)
            changed = False
            expanded = []
            for expr in expressions:
                cols = self._expansion_columns(expr, grouped, determined)
                if cols is None:
                    expanded.append(expr)
                else:
                    changed = True
                    for col in cols:
                        if col not in expanded:
                            expanded.append(col)
            expressions = expanded
            if not changed:
                break
        return expressions

    def _alias_pk_column(self, alias):
        query = self.query
        try:
            if alias == query.get_initial_alias():
                return query.model._meta.pk.column
            join = query.alias_map.get(alias)
            target = getattr(getattr(join, "join_field", None), "target_field", None)
            if target is not None and target.primary_key:
                return target.column
        except Exception:
            return None
        return None

    def _group_determination(self, expressions):
        """(grouped (alias, column) set, determined alias set).

        An alias is determined when its row is constant within any
        group of the current keys: its PK is grouped, or it is joined
        many-to-one / one-to-one on parent columns that are grouped
        or themselves determined (DYOR 9.9 join semantics).
        """
        grouped = {
            (expr.alias, expr.target.column)
            for expr in expressions
            if isinstance(expr, Col)
        }
        determined = {
            alias
            for alias in {a for a, _ in grouped}
            if (alias, self._alias_pk_column(alias)) in grouped
        }

        def constant(alias, column):
            return (alias, column) in grouped or alias in determined

        alias_map = getattr(self.query, "alias_map", {})
        for _ in range(len(alias_map) + 1):
            grew = False
            for alias, join in alias_map.items():
                if alias in determined:
                    continue
                field = getattr(join, "join_field", None)
                parent = getattr(join, "parent_alias", None)
                if field is None or parent is None:
                    continue
                rel = getattr(field, "rel", field)
                if not (
                    getattr(rel, "many_to_one", False)
                    or getattr(rel, "one_to_one", False)
                ):
                    continue
                try:
                    pairs = field.get_joining_fields()
                except Exception:
                    continue
                if pairs and all(
                    joined.primary_key and constant(parent, source.column)
                    for source, joined in pairs
                ):
                    determined.add(alias)
                    grew = True
            if not grew:
                break
        return grouped, determined

    def _expansion_columns(self, expr, grouped, determined):
        """Constituent Cols for expr, or None if not provably safe."""
        if isinstance(expr, Col) or not isinstance(expr, BaseExpression):
            return None
        if expr.contains_aggregate or getattr(expr, "contains_over_clause", False):
            return None
        try:
            if expr.get_group_by_cols() != [expr]:
                return None
        except Exception:
            return None
        cols = []
        stack = [expr]
        while stack:
            node = stack.pop()
            if isinstance(node, Col):
                if node not in cols:
                    cols.append(node)
                continue
            if isinstance(node, Value):
                continue
            if type(node).__name__ in self._GROUP_BY_NEVER_EXPAND:
                return None
            if not isinstance(node, self._GROUP_BY_EXPANDABLE):
                return None
            sources = [
                source
                for source in node.get_source_expressions()
                if isinstance(source, BaseExpression)
            ]
            if not sources:
                return None
            stack.extend(sources)
        if not cols:
            return None
        if all(
            (col.alias, col.target.column) in grouped or col.alias in determined
            for col in cols
        ):
            return cols
        return None

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

    # -- DISTINCT: re-express plain-column shapes as GROUP BY -------
    def _distinct_group_by_plan(self, with_col_aliases=False):
        """None if stock, else Meta-ordering terms to make explicit.

        A grouped compile drops Meta ordering (stock aggregate
        behaviour), which would silently lose the DISTINCT query's
        ordering; simple Meta ordering (plain field names) is
        therefore re-applied as explicit ordering for the compile
        -- the same terms, so the same ordering, and the ordering
        columns join the GROUP BY exactly as stock DISTINCT joins
        them to its select as extra columns. An empty return means
        no conversion is needed.
        """
        query = self.query
        if (
            not query.distinct
            or query.distinct_fields
            or query.group_by is not None
            or query.combinator
            or query.is_sliced
            or query.extra
            or query.subquery
            or query.explain_info
            or getattr(query, "select_for_update", False)
        ):
            return None
        try:
            _where, having, qualify = query.where.split_having_qualify()
        except Exception:
            return None
        if having is not None or qualify is not None:
            return None
        for expr in query.annotations.values():
            if expr.contains_aggregate or getattr(
                expr, "contains_over_clause", False
            ):
                return None
        # Inspect the compiled projection exactly as pre_sql_setup
        # will build it: selected expressions plus the extra
        # ordering columns a DISTINCT select carries.
        try:
            self.setup_query(with_col_aliases=with_col_aliases)
            order_by = self.get_order_by()
            extra_select = self.get_extra_select(order_by, self.select)
        except Exception:
            return None
        if not self.select:
            return None
        def _is_plain_col(expr):
            # Extra-select entries carry the ordering expression,
            # which may still be wrapped in OrderBy.
            return isinstance(getattr(expr, "expression", expr), Col)

        if any(
            not _is_plain_col(expr)
            for expr, _sql_params, _alias in (*self.select, *extra_select)
        ):
            return None
        conversion = ()
        if self._meta_ordering:
            terms = list(query.get_meta().ordering or ())
            if all(
                isinstance(term, str)
                and "__" not in term.lstrip("-")
                and term.lstrip("-") != "?"
                for term in terms
            ):
                conversion = tuple(terms)
            elif extra_select:
                # A Meta-ordering column outside the projection
                # that cannot be made explicit: stock DISTINCT
                # selects it (extra) and dedupes over it; a GROUP
                # BY compiler would not group it. Keep stock.
                return None
        for expr, (_sql, _params, is_ref) in order_by:
            if is_ref:
                continue
            inner = getattr(expr, "expression", expr)
            if not isinstance(inner, Col):
                return None
        return conversion

    # -- compilation --------------------------------------------------
    def as_sql(self, with_limits=True, with_col_aliases=False):
        plan = self._having_wrap_plan()
        if plan is None:
            conversion = self._distinct_group_by_plan(
                with_col_aliases=with_col_aliases
            )
            if conversion is not None:
                query = self.query
                original_group_by = query.group_by
                original_order_by = query.order_by
                original_default_ordering = query.default_ordering
                query.distinct = False
                query.group_by = True
                if conversion:
                    query.order_by = conversion
                    query.default_ordering = False
                # The plan's inspection calls set _meta_ordering for
                # the unconverted query; the real compile must
                # recompute it for the converted state (a stale flag
                # would make the grouped compile drop the ordering).
                self._meta_ordering = None
                try:
                    return super().as_sql(
                        with_limits=with_limits,
                        with_col_aliases=with_col_aliases,
                    )
                finally:
                    query.distinct = True
                    query.group_by = original_group_by
                    query.order_by = original_order_by
                    query.default_ordering = original_default_ordering
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
        # Outer projection (N-M11, DYOR 9.1/9.9; probe
        # nedb-groupby2-probe-2026-10-31.md addendum): NEDB's derived
        # table does not preserve inner column order under SELECT *
        # (measured: aggregates are returned before other annotation
        # columns), which misaligns Django's positional converters.
        # Name the subquery's columns explicitly, in the inner
        # select's own order (from self.select, set by the inner
        # compilation), whenever every column has a unique name;
        # otherwise keep the stock SELECT * wrap.
        outer_cols = "*"
        if not with_col_aliases and self.select:
            names = []
            for expr, _sql_params, alias in self.select:
                name = alias or (
                    expr.target.column if isinstance(expr, Col) else None
                )
                if name is None:
                    names = None
                    break
                names.append(name)
            if names is not None and len(set(names)) == len(names):
                outer_cols = ", ".join(
                    "%s.%s" % (quote(_HAVING_SUBQUERY_ALIAS), quote(name))
                    for name in names
                )
        sql = "SELECT %s FROM (%s) AS %s WHERE %s" % (
            outer_cols,
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
