"""Identity for NEDB: the adapter assigns integer PKs (DYOR 9.6).

Per the NEDB DYOR note (2026-10-30), implication 6 / section 9.6:
NEDB has no IDENTITY columns. An INSERT that omits ``id`` gets a
string ``_id`` assigned by the engine (``r1793...-0``; pgwire maps
bare ``id`` to ``_id``), and ``INSERT ... RETURNING`` for such an
insert yields NULL for the PK. A string ``_id`` then crashes Django
the moment it is used where an integer PK is expected -- verbatim,
from post-migrate ``create_permissions`` (N-M3c evidence):
``ValueError: Field 'id' expected a number but got
'r179339565244311531-0'.``

Strategy (client-generated ids, DYOR 9.6's first named option): the
adapter assigns the PK itself, in the insert compiler
(``compiler.py``), before the statement is built, and includes the
``id`` column explicitly in the INSERT. Verified against nedbd-v2
12.15.16: an INSERT with an explicit integer ``id`` stores ``_id``
as that integer's string form, ``RETURNING`` yields the integer
itself, and later reads hand the numeric string back, which the
read-path converter in ``operations.py`` turns into a real ``int``.

Allocator: one process-wide, lock-guarded, monotonic counter seeded
from wall-clock milliseconds. Ids are therefore positive, strictly
increasing within a process, and unique across tables (one counter
for every table -- per-table sequences do not exist on a schemaless
store, and ``MAX(id)`` is unusable as a seed: NEDB returns the
lexicographic maximum, which for legacy rows is an ``r...`` string).
Millisecond ids exceed the 32-bit range Django declares for
``AutoField`` PKs (auth/contenttypes/admin models), so
``operations.py`` reports a 64-bit range for auto fields (N-M6f);
without it, Django's lookup overflow check compiles PK filters and
updates for those models to ``EmptyResultSet`` (0 rows affected).

Known limits, stated plainly:

* Cross-process uniqueness rests on the millisecond seed plus
  monotonicity; two processes assigning in the same millisecond
  could collide. The pilot is one Django process per nedbd; a
  durable cross-process sequence is future work, not claimed here.
* Rows written BEFORE this adapter (or by non-ORM writers that omit
  ``id``) keep their engine string ``_id``. No integer can be
  recovered from them, so the read converter passes non-numeric
  strings through unchanged rather than inventing a value; using
  such a legacy row's PK as an integer FK filter still raises the
  ``ValueError`` above. Legacy rows must be rewritten with explicit
  integer ids to become usable PKs.
"""

import re
import threading
import time

_INT_LITERAL = re.compile(r"^-?\d+$")


def _clock_ms():
    return int(time.time() * 1000)


class ClientIdAllocator:
    """Monotonic client-side PK allocator (injectable clock)."""

    def __init__(self, clock_ms=None):
        self._clock_ms = clock_ms or _clock_ms
        self._lock = threading.Lock()
        self._last = 0

    def next_id(self):
        with self._lock:
            candidate = int(self._clock_ms())
            if candidate <= self._last:
                candidate = self._last + 1
            self._last = candidate
            return candidate


# The one process-wide allocator used by the insert compiler.
default_allocator = ClientIdAllocator()


def next_client_id():
    return default_allocator.next_id()


def assign_pk_if_missing(obj, pk_field):
    """Set ``obj``'s PK from the allocator if unset; return the PK."""
    value = getattr(obj, pk_field.attname)
    if value is None:
        value = next_client_id()
        setattr(obj, pk_field.attname, value)
    return value


def convert_integer_value(value):
    """Stored value -> int where lossless; pass everything else through.

    Numeric strings (``"101"`` -- the form NEDB returns for a
    document whose ``_id`` was assigned an integer) become ``int``.
    Non-numeric strings are legacy engine ids (see module docstring)
    and pass through unchanged: fabricating an integer for them
    would corrupt identity.
    """
    if value is None or isinstance(value, int):
        return value
    if isinstance(value, str) and _INT_LITERAL.match(value.strip()):
        return int(value)
    return value
