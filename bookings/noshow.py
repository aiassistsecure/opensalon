"""Read-only no-show report service for a date range.

Backend only — no views, templates, or UI. Pure service: derived
only from existing ``Appointment`` records (one source of truth);
nothing is created, edited, or deleted.

For one salon and an inclusive local-date range the report is::

    NoShowReport(
        salon, start_date, end_date, now,
        no_show_count,  # numerator (see below)
        denominator,    # denominator (see below)
        rate,           # no_show_count / denominator, or 0.0
        by_staff,       # tuple of StaffNoShow, worst first
        by_client,      # tuple of ClientNoShow, worst first
    )

Denominator — the exact definition (deliberate, documented here):

    The denominator is the number of appointments for the salon
    whose ``start`` falls in the range (by salon-local date, as in
    :mod:`bookings.export` / :mod:`bookings.status_counts`) AND
    whose ``start`` is in the past relative to ``now``
    (``start < now``; an appointment starting exactly at ``now``
    is not yet past) AND whose status is not ``cancelled``.

    The numerator is the number of those denominator appointments
    whose status is ``no_show``. The numerator is therefore always
    a subset of the denominator, so ``rate`` lies in [0, 1].
    Future appointments never count (a future booking cannot yet
    be a no-show), cancelled appointments never count (a cancelled
    booking was never expected), and a future-dated or cancelled
    record anomalously marked ``no_show`` does not inflate the
    numerator. When the denominator is 0, ``rate`` is ``0.0``.

Grouping: ``by_staff`` / ``by_client`` carry the same count,
denominator, and rate computed per staff member / per client,
including only entries with at least one no-show, ordered by
``no_show_count`` descending, then name, then id. Staff entries
carry ``staff_member_id`` + ``staff_name`` (``display_name``);
client entries carry ``client_id`` + ``client_name`` (the name
already on the client record). No client contact details (email,
phone, address) are included anywhere in the output.

Scoping follows :mod:`bookings.export`: appointments belong to
the salon via both the client and the staff member
(``client__salon`` and ``staff_member__salon``), never via the
service, so snapshot-only appointments (``service=None``) count.

Listing: :func:`noshow_appointments` (alias
:func:`list_noshows`) returns the no-show appointments themselves
(the numerator set), most-recent first (``-start``, then ``-id``),
as plain JSON-serializable dicts.
"""
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from django.utils import timezone

from bookings.availability import _tz
from bookings.models import Appointment

__all__ = [
    "ClientNoShow",
    "NoShowReport",
    "StaffNoShow",
    "list_noshows",
    "no_show_report",
    "noshow_appointments",
    "noshow_report",
]


@dataclass(frozen=True)
class StaffNoShow:
    staff_member_id: int = None
    staff_name: str = ""
    no_show_count: int = 0
    denominator: int = 0
    rate: float = 0.0


@dataclass(frozen=True)
class ClientNoShow:
    client_id: int = None
    client_name: str = ""
    no_show_count: int = 0
    denominator: int = 0
    rate: float = 0.0


@dataclass(frozen=True)
class NoShowReport:
    salon: object = None
    start_date: object = None
    end_date: object = None
    now: object = None
    no_show_count: int = 0
    denominator: int = 0
    rate: float = 0.0
    by_staff: tuple = field(default_factory=tuple)
    by_client: tuple = field(default_factory=tuple)

    @property
    def count(self):
        return self.no_show_count

    def as_dict(self):
        return {
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "no_show_count": self.no_show_count,
            "denominator": self.denominator,
            "rate": self.rate,
            "by_staff": [
                {"staff_member_id": s.staff_member_id,
                 "staff_name": s.staff_name,
                 "no_show_count": s.no_show_count,
                 "denominator": s.denominator, "rate": s.rate}
                for s in self.by_staff
            ],
            "by_client": [
                {"client_id": c.client_id, "client_name": c.client_name,
                 "no_show_count": c.no_show_count,
                 "denominator": c.denominator, "rate": c.rate}
                for c in self.by_client
            ],
        }


def _as_local_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    return value


def _rate(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def _window(salon, date_from, date_to):
    tz = _tz(salon)
    first = _as_local_date(date_from, tz)
    last = _as_local_date(date_to, tz) if date_to is not None else first
    if last < first:
        return first, last, None, None
    start = datetime.combine(first, time.min, tzinfo=tz)
    end = datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz)
    return first, last, start, end


def _past_non_cancelled(salon, window_start, window_end, now):
    # Both upper bounds on start apply: in-window AND in the past.
    return Appointment.objects.filter(
        client__salon=salon, staff_member__salon=salon,
        start__gte=window_start, start__lt=min(window_end, now),
    ).exclude(status=Appointment.Status.CANCELLED)


def noshow_report(salon, date_from, date_to=None, *, now=None):
    """Return the no-show report for ``salon`` over a local range.

    Args:
        salon: ``saloncore.Salon`` instance; ``None`` returns a
            zero report.
        date_from: first local date, inclusive (date, or datetime
            reduced to its date in the salon's timezone).
        date_to: last local date, inclusive; defaults to
            ``date_from``.
        now: reference instant for "past"; defaults to
            ``timezone.now()``. Pass an aware datetime in tests.

    Returns:
        A :class:`NoShowReport`. A reversed range returns zeros.
    """
    now = now or timezone.now()
    if salon is None or date_from is None:
        return NoShowReport(salon=salon, now=now)
    first, last, ws, we = _window(salon, date_from, date_to)
    if ws is None:
        return NoShowReport(
            salon=salon, start_date=first, end_date=last, now=now)
    base = list(
        _past_non_cancelled(salon, ws, we, now)
        .select_related("client", "staff_member")
    )
    denominator = len(base)
    noshows = [a for a in base if a.status == Appointment.Status.NO_SHOW]
    staff, clients = {}, {}
    for appt in base:
        s = staff.setdefault(appt.staff_member_id, {
            "name": str(appt.staff_member), "n": 0, "d": 0})
        s["d"] += 1
        c = clients.setdefault(appt.client_id, {
            "name": str(appt.client), "n": 0, "d": 0})
        c["d"] += 1
        if appt.status == Appointment.Status.NO_SHOW:
            s["n"] += 1
            c["n"] += 1
    by_staff = tuple(sorted(
        (StaffNoShow(staff_member_id=k, staff_name=v["name"],
                     no_show_count=v["n"], denominator=v["d"],
                     rate=_rate(v["n"], v["d"]))
         for k, v in staff.items() if v["n"]),
        key=lambda r: (-r.no_show_count, r.staff_name, r.staff_member_id),
    ))
    by_client = tuple(sorted(
        (ClientNoShow(client_id=k, client_name=v["name"],
                      no_show_count=v["n"], denominator=v["d"],
                      rate=_rate(v["n"], v["d"]))
         for k, v in clients.items() if v["n"]),
        key=lambda r: (-r.no_show_count, r.client_name, r.client_id),
    ))
    return NoShowReport(
        salon=salon, start_date=first, end_date=last, now=now,
        no_show_count=len(noshows), denominator=denominator,
        rate=_rate(len(noshows), denominator),
        by_staff=by_staff, by_client=by_client,
    )


def no_show_report(salon, date_from, date_to=None, *, now=None):
    """Alias for :func:`noshow_report`."""
    return noshow_report(salon, date_from, date_to, now=now)


def noshow_appointments(salon, date_from, date_to=None, *, now=None):
    """List the numerator no-shows, most-recent first, as dicts.

    Each dict has exactly ``id``, ``client_id``, ``client_name``,
    ``staff_member_id``, ``staff_name``, ``service_id``,
    ``service_name``, ``start``, ``end``, ``status`` — ids/names
    only, no client contact details. ``start``/``end`` are
    ISO-8601 strings. Empty/reversed range or ``None`` salon: ``[]``.
    """
    now = now or timezone.now()
    if salon is None or date_from is None:
        return []
    _first, _last, ws, we = _window(salon, date_from, date_to)
    if ws is None:
        return []
    rows = (
        _past_non_cancelled(salon, ws, we, now)
        .filter(status=Appointment.Status.NO_SHOW)
        .select_related("client", "staff_member", "service")
        .order_by("-start", "-id")
    )
    return [{
        "id": a.pk, "client_id": a.client_id,
        "client_name": str(a.client),
        "staff_member_id": a.staff_member_id,
        "staff_name": str(a.staff_member),
        "service_id": a.service_id,
        "service_name": a.service.name if a.service else a.service_name,
        "start": a.start.isoformat() if a.start else None,
        "end": a.end.isoformat() if a.end else None,
        "status": a.status,
    } for a in rows]


def list_noshows(salon, date_from, date_to=None, *, now=None):
    """Alias for :func:`noshow_appointments`."""
    return noshow_appointments(salon, date_from, date_to, now=now)
