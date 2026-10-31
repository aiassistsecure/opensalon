"""Server-rendered pages for the salon floor.

Every page reads real rows through the existing apps' models. The
day book consumes the bookings lane's feed
(:mod:`bookings.daybook`) — the view-context contract that lane
publishes for this track — and enriches it with presentation math
(position, overlap lanes, utilization, prices) here, so the feed
itself stays UI-free.

Prices: the Appointment record carries no price of its own in the
current model, so a block's price is the price-book price for that
service at that stylist's level — the same rule the price book page
renders by. When no row exists at the stylist's own level (imported
books can carry split level identities), the price falls back to
the service's Base (menu) row — a real price for that service,
never an invented one. A service with no price-book row at all
renders no price; nothing is invented. Projected revenue is the sum
of those resolved prices over the day's records, and the count of
unpriced records travels with it so the figure is never mistaken
for complete when it is not.
"""

import datetime
from types import SimpleNamespace
import json
from decimal import Decimal, InvalidOperation

from django.core.paginator import Paginator
from django.db.models import Count, Max, Min, Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from bookings.availability import _tz
from bookings.daybook import blocks_for_day as feed_blocks_for_day
from bookings.models import Appointment, AppointmentNote, Break
from clients.models import Client, ClientNote
from saloncore.models import Salon, Service, ServiceCategory, ServicePrice, StaffLevel
from team.models import AttendanceRecord, RosterPattern, StaffMember, ShiftOverride
from team.roster_week import roster_week as build_roster_week

# The day book window: 8:00 to 20:00 salon-local.
DAY_START_HOUR = 8
DAY_END_HOUR = 20

_STATUS_LABELS = dict(Appointment.Status.choices)

# The desk's status flow, in order. Each entry: the status it
# sets, the button label, and whether it is the primary action.
# The rail renders these for the selected appointment; the status
# endpoint accepts exactly these transitions.
_STATUS_ACTIONS = {
    Appointment.Status.BOOKED: [
        (Appointment.Status.ARRIVED, "Check In", True),
        (Appointment.Status.NO_SHOW, "No-show", False),
        (Appointment.Status.CANCELLED, "Cancel", False),
    ],
    Appointment.Status.CONFIRMED: [
        (Appointment.Status.ARRIVED, "Check In", True),
        (Appointment.Status.NO_SHOW, "No-show", False),
        (Appointment.Status.CANCELLED, "Cancel", False),
    ],
    Appointment.Status.ARRIVED: [
        (Appointment.Status.IN_SERVICE, "Start Service", True),
        (Appointment.Status.BOOKED, "Undo Check In", False),
        (Appointment.Status.CANCELLED, "Cancel", False),
    ],
    Appointment.Status.IN_SERVICE: [
        (Appointment.Status.COMPLETED, "Complete", True),
    ],
    Appointment.Status.NO_SHOW: [
        (Appointment.Status.BOOKED, "Undo No-show", True),
    ],
}


def _status_toggles(status):
    """Check-in and no-show as full toggles, not one-way trips.

    Each toggle carries its current state and the target a flip
    posts; the transition table above governs legality, so a
    toggle is just the honest switch for moves the table already
    allows both ways. A toggle the appointment has outgrown —
    checked in, then the service started — still shows its
    state, disabled: history is not rewritten by flipping a
    switch.
    """
    S = Appointment.Status
    pre_arrival = status in (S.BOOKED, S.CONFIRMED)
    return [
        {
            "key": "checkin",
            "label": "Checked in",
            "on": status in (S.ARRIVED, S.IN_SERVICE, S.COMPLETED),
            "enabled": pre_arrival or status == S.ARRIVED,
            "target": S.BOOKED if status == S.ARRIVED else S.ARRIVED,
        },
        {
            "key": "noshow",
            "label": "No-show",
            "on": status == S.NO_SHOW,
            "enabled": pre_arrival or status == S.NO_SHOW,
            "target": S.BOOKED if status == S.NO_SHOW else S.NO_SHOW,
        },
    ]


# Targets the toggles own; the button row keeps the rest.
_TOGGLE_TARGETS = {
    Appointment.Status.ARRIVED,
    Appointment.Status.NO_SHOW,
    Appointment.Status.BOOKED,
}

# A follow-on service starting within this gap of the previous one's
# end belongs to the same visit (the detail rail's Service Stack).
VISIT_GAP = datetime.timedelta(minutes=15)

# An in-span gap at least this long counts as an opening.
OPENING_MIN_MINUTES = 30


def _assign_lanes(blocks):
    """Overlap lanes for one column's blocks (in start order).

    Chained overlaps form a cluster; inside a cluster each block
    takes the first lane free at its start. Sets ``lane``/``lanes``
    (and the derived ``left``/``width`` percentages) on each block
    dict, so back-to-back services render side by side at their true
    times instead of stacking — no time is ever shifted.
    """
    clusters, current, current_end = [], [], None
    for block in blocks:
        if current and block["_start"] >= current_end:
            clusters.append(current)
            current, current_end = [], None
        current.append(block)
        current_end = max(current_end or block["_end"], block["_end"])
    if current:
        clusters.append(current)
    for cluster in clusters:
        lane_ends = []
        for block in cluster:
            for lane, end in enumerate(lane_ends):
                if block["_start"] >= end:
                    lane_ends[lane] = block["_end"]
                    block["lane"] = lane
                    break
            else:
                lane_ends.append(block["_end"])
                block["lane"] = len(lane_ends) - 1
        width = 100.0 / len(lane_ends)
        for block in cluster:
            block["lanes"] = len(lane_ends)
            block["left"] = round(block["lane"] * width, 2)
            block["width"] = round(width, 2)
            # How many blocks are live at the busiest instant of this
            # block's own span — its personal crowding, which (with its
            # duration) drives both the degradation flags below and
            # the column's width ask: a crowded column widens instead
            # of squeezing its blocks unreadable.
            probes = {block["_start"]}
            probes.update(
                b["_start"]
                for b in cluster
                if block["_start"] < b["_start"] < block["_end"]
            )
            block["overlap"] = max(
                sum(1 for b in cluster if b["_start"] <= t < b["_end"])
                for t in probes
            )
            duration = block["_end"] - block["_start"]
            # Degradation order as a block narrows: the service line
            # yields first (mini); the price goes only when the block
            # is too short to hold its rows at all (micro). A block
            # keeps its service unless it is brief, or crowded AND
            # brief — a long appointment keeps its name even inside a
            # three-lane cluster.
            block["mini"] = duration < datetime.timedelta(minutes=45) or (
                block["overlap"] >= 3
                and duration < datetime.timedelta(minutes=90)
            )
            block["micro"] = duration < datetime.timedelta(minutes=30)


def _union_minutes(intervals):
    """Total minutes covered by a set of (start, end) datetimes."""
    total, covered_until = 0.0, None
    for start, end in sorted(intervals):
        if covered_until is None or start > covered_until:
            total += (end - start).total_seconds() / 60
            covered_until = end
        elif end > covered_until:
            total += (end - covered_until).total_seconds() / 60
            covered_until = end
    return total


def _gap_count(intervals, span_start, span_end):
    """Count uncovered gaps >= OPENING_MIN_MINUTES inside a span."""
    gaps, covered_until = 0, span_start
    for start, end in sorted(intervals):
        if start > covered_until:
            if (start - covered_until).total_seconds() / 60 >= OPENING_MIN_MINUTES:
                gaps += 1
        covered_until = max(covered_until, end)
    if (span_end - covered_until).total_seconds() / 60 >= OPENING_MIN_MINUTES:
        gaps += 1
    return gaps


def _pct(moment, day_start, day_end):
    """Position of a time as a % of the day window (for CSS top/height)."""
    span = (day_end - day_start).total_seconds()
    return round((moment - day_start).total_seconds() / span * 100, 2)


def _fmt_time(t):
    # Portable 12-hour label ("9 AM", "9:30 AM", "12 PM"). Built
    # with an f-string because the "%-I" strftime flag is glibc-only
    # and raises ValueError on Windows — the pilot install's first
    # page load found it (2026-10-31). Never use "%-" flags here.
    hour = t.hour % 12 or 12
    suffix = "AM" if t.hour < 12 else "PM"
    if t.minute:
        return f"{hour}:{t.minute:02d} {suffix}"
    return f"{hour} {suffix}"


def _fmt_date_label(d, with_year=False):
    # "Sat, Oct 3" (+ ", 2026" with_year). "%-d" is glibc-only too;
    # same Windows lesson as _fmt_time.
    label = f"{d.strftime('%a, %b')} {d.day}"
    return f"{label}, {d.year}" if with_year else label


def _initials(name):
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _price_label(amount):
    """Book price label: whole dollars stay whole; None stays blank."""
    if amount is None:
        return ""
    if amount == amount.to_integral_value():
        return f"${amount:.0f}"
    return f"${amount:.2f}"


def _money_label(amount):
    return f"${amount:,.0f}" if amount == amount.to_integral_value() else f"${amount:,.2f}"


def _duration_label(minutes):
    hours, mins = divmod(int(minutes), 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    return f"{hours}h" if hours else f"{mins}m"


def _day_book_context(request, *, light=False, kit=None):
    """Build one day's book.

    ``kit`` lets a caller that already holds shared facts hand
    them down (members, prices, the day's rows, client
    aggregates) instead of every day re-scanning for them — on
    a scan-priced store each avoided pass is real time. ``light``
    skips the rail-only reads (notes, history, payloads) for
    callers that need blocks and facts, not cards: the week
    pack's non-anchor days.
    """
    kit = kit or {}
    salon = kit.get("salon") or Salon.objects.order_by("id").first()
    tz = _tz(salon) if salon is not None else timezone.get_current_timezone()
    # "Today" is the salon's today. The server clock (UTC) rolls into
    # tomorrow while the salon is still in its evening; a book that
    # opens on the wrong day — and never draws its now-line — is
    # worse than useless at the front desk.
    today = timezone.now().astimezone(tz).date()
    try:
        day = datetime.date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        day = today
    weekday = day.weekday()  # Monday = 0; RosterPattern.Weekday matches.
    day_start = datetime.datetime.combine(day, datetime.time(DAY_START_HOUR), tzinfo=tz)
    day_end = datetime.datetime.combine(day, datetime.time(DAY_END_HOUR), tzinfo=tz)
    hours = [
        {
            "label": _fmt_time(datetime.time(h)),
            "top": _pct(
                datetime.datetime.combine(day, datetime.time(h), tzinfo=tz),
                day_start,
                day_end,
            ),
        }
        for h in range(DAY_START_HOUR, DAY_END_HOUR + 1)
    ]
    monday = day - datetime.timedelta(days=weekday)
    week_days = [monday + datetime.timedelta(days=i) for i in range(7)]

    cat_filter = request.GET.get("cat", "")
    status_filter = request.GET.get("status", "")

    staff = []
    rail_payloads = {}
    member_spans = {}
    agenda_pool = []
    default_rail = None
    kpi = {"avg_ticket_label": "—", "new_clients": 0}
    intel = {
        "next_label": "No 45+ min opening",
        "next_sub": "",
        "top_label": "—",
        "completed": 0,
        "remaining": 0,
    }
    agenda = []
    agenda_now_index = None
    overview = {
        "appointments": 0,
        "visits": 0,
        "revenue": Decimal("0"),
        "revenue_label": "$0",
        "unpriced": 0,
        "utilization": None,
        "openings": 0,
    }
    categories = []
    if salon is not None:
        categories = kit.get("categories") or list(
            ServiceCategory.objects.filter(salon=salon, active=True).order_by(
                "sort_order", "name"
            )
        )
        members = (
            kit["members"]
            if "members" in kit
            else list(
                StaffMember.objects.filter(salon=salon, active=True)
                .select_related("staff_level")
                .prefetch_related("roster_patterns")
            )
        )
        prices, base_level_id = (
            kit["prices"] if "prices" in kit else _price_lookup(salon)
        )
        if "day_appts" in kit:
            day_appts = list(kit["day_appts"])
        else:
            # Midnight bounds — the feed's own. The day's rows
            # are fetched once and shared by the grid, the rail
            # and the pack; the visible 8–20 window stays a
            # rendering choice, and an appointment outside it is
            # still a real appointment with a real card (before
            # this, one at 7am had a block but no payload and
            # priced as unpriced).
            midnight = datetime.datetime.combine(
                day, datetime.time.min, tzinfo=tz
            )
            day_appts = list(
                Appointment.objects.filter(
                    staff_member__in=members,
                    start__lt=midnight + datetime.timedelta(days=1),
                    end__gt=midnight,
                )
                .exclude(status=Appointment.Status.CANCELLED)
                .select_related(
                    "client", "staff_member", "staff_member__staff_level",
                    "service", "service__category"
                )
                .order_by("start")
            )
        # The feed renders the SAME rows: hand them over instead
        # of letting it scan the appointments table a second time.
        feed = {
            c.staff_member_id: c
            for c in feed_blocks_for_day(salon, day, appointments=day_appts)
        }
        appt_by_id = {a.pk: a for a in day_appts}

        def amount_for(appt):
            return _amount_for(appt, prices, base_level_id)

        # ---- visits: same client + stylist, chained by VISIT_GAP ----
        visits = {}
        grouped = {}
        for appt in day_appts:
            grouped.setdefault((appt.client_id, appt.staff_member_id), []).append(appt)
        for group in grouped.values():
            visit, visit_end = [], None
            for appt in group:
                if visit and appt.start > visit_end + VISIT_GAP:
                    for member_appt in visit:
                        visits[member_appt.pk] = visit
                    visit, visit_end = [], None
                visit.append(appt)
                visit_end = max(visit_end or appt.end, appt.end)
            for member_appt in visit:
                visits[member_appt.pk] = visit

        # ---- per-client facts for the rail (record only) ----
        client_ids = {a.client_id for a in day_appts}
        # One aggregate pass over the day's clients, not three:
        # visit counts and first-visit days come from the same
        # grouped scan. First-visit days follow one rule shared
        # by the ribbon's new count and the blocks' new-guest
        # highlight: a client is new on the day of their
        # first-ever appointment.
        aggregates = (
            kit["aggregates"]
            if "aggregates" in kit
            else {
                row["client_id"]: row
                for row in Appointment.objects.filter(client_id__in=client_ids)
                .values("client_id")
                .annotate(n=Count("id"), first=Min("start"))
            }
        )
        visit_counts = {cid: row["n"] for cid, row in aggregates.items()}
        first_days = {
            cid: row["first"].astimezone(tz).date()
            for cid, row in aggregates.items()
        }
        # Rail-only reads: light callers (the pack's non-anchor
        # days) never render a card, so they never pay for them.
        client_notes = {}
        appt_notes = {}
        history = {}
        if not light:
            for note in ClientNote.objects.filter(
                client_id__in=client_ids
            ).order_by("-created_at"):
                client_notes.setdefault(note.client_id, []).append(
                    {"id": note.pk, "body": note.body}
                )
            for note in AppointmentNote.objects.filter(
                appointment_id__in=appt_by_id
            ).order_by("-created_at"):
                appt_notes.setdefault(note.appointment_id, []).append(
                    {"id": note.pk, "body": note.body}
                )
            for appt in (
                Appointment.objects.filter(client_id__in=client_ids)
                .select_related("staff_member", "service")
                .order_by("-start")
            ):
                history.setdefault(appt.client_id, []).append(appt)

        def rail_payload(appt):
            visit = visits[appt.pk]
            stack, stack_minutes, stack_total = [], 0, Decimal("0")
            for item in visit:
                amount = amount_for(item)
                minutes = int((item.end - item.start).total_seconds() // 60)
                stack_minutes += minutes
                if amount is not None:
                    stack_total += amount
                stack.append(
                    {
                        "id": item.pk,
                        "service": item.service.name if item.service else item.service_name,
                        "duration_label": _duration_label(minutes),
                        "price_label": _price_label(amount),
                        "price": str(amount) if amount is not None else "",
                        "price_overridden": item.price_override is not None,
                        "current": item.pk == appt.pk,
                    }
                )
            client = appt.client
            return {
                "id": appt.pk,
                "time_label": (
                    f"{_fmt_time(appt.start.astimezone(tz).time())} – "
                    f"{_fmt_time(appt.end.astimezone(tz).time())}"
                ),
                "date_label": _fmt_date_label(day, with_year=True),
                "status": appt.status,
                "status_label": _STATUS_LABELS.get(appt.status, appt.status),
                "actions": [
                    {"status": s, "label": label, "primary": primary}
                    for s, label, primary in _STATUS_ACTIONS.get(appt.status, [])
                    if s not in _TOGGLE_TARGETS
                ],
                "toggles": _status_toggles(appt.status),
                "client_name": client.display_name
                if hasattr(client, "display_name")
                else f"{client.first_name} {client.last_name}".strip(),
                "client_initials": _initials(
                    f"{client.first_name} {client.last_name}"
                ),
                "client_email": client.email,
                "client_phone": client.phone,
                "client_sms": client.sms_opt_in,
                "client_email_opt": client.email_opt_in,
                "client_visits": visit_counts.get(client.pk, 0),
                "stack": stack,
                "stack_total_label": _duration_label(stack_minutes),
                "stack_price_label": _price_label(stack_total) if stack_total else "",
                "stylist_name": appt.staff_member.display_name,
                "stylist_initials": _initials(appt.staff_member.display_name),
                "stylist_level": appt.staff_member.staff_level.name
                if appt.staff_member.staff_level_id
                else "",
                "price_label": _price_label(amount_for(appt)),
                "price": (
                    str(amount_for(appt))
                    if amount_for(appt) is not None
                    else ""
                ),
                "price_overridden": appt.price_override is not None,
                "salon_name": salon.name,
                "appt_notes": appt_notes.get(appt.pk, []),
                "client_notes": client_notes.get(client.pk, []),
                "history": [
                    {
                        "date_label": _fmt_date_label(h.start.astimezone(tz)),
                        "time_label": _fmt_time(h.start.astimezone(tz).time()),
                        "service": h.service.name if h.service else h.service_name,
                        "stylist": h.staff_member.display_name,
                        "status_label": _STATUS_LABELS.get(h.status, h.status),
                    }
                    for h in history.get(client.pk, [])[:6]
                ],
            }

        # The roster book's instance layer: an override rules its
        # date in this book too (bands, minutes, openings follow).
        # The pack's kit carries the whole week's overrides and
        # breaks from two range queries; a lone day queries its
        # own, exactly as before.
        if "overrides" in kit:
            day_overrides = kit["overrides"].get(day, {})
        else:
            day_overrides = {
                o.staff_member_id: o
                for o in ShiftOverride.objects.filter(
                    staff_member__in=members, date=day
                )
            }
        block_index = 0
        # The day's breaks, grouped by stylist: drawn as their
        # own blocks and counted as busy time in the openings
        # math below — never as booked work.
        if "breaks_week" in kit:
            day_break_rows = [
                br
                for br in kit["breaks_week"]
                if br.start < day_end and br.end > day_start
            ]
        else:
            day_break_rows = Break.objects.filter(
                staff_member__in=members, start__lt=day_end, end__gt=day_start
            )
        day_breaks = {}
        for br in day_break_rows:
            day_breaks.setdefault(br.staff_member_id, []).append(br)
        total_booked, total_roster, total_openings = 0.0, 0.0, 0
        revenue, unpriced = Decimal("0"), 0
        for member in members:
            ov = day_overrides.get(member.pk)
            if ov is not None:
                patterns = [] if ov.is_off else [
                    SimpleNamespace(start_time=ov.start_time, end_time=ov.end_time)
                ]
            else:
                patterns = [
                    p for p in member.roster_patterns.all() if p.active and p.weekday == weekday
                ]
            bands = []
            roster_minutes = 0.0
            for p in patterns:
                band_start = datetime.datetime.combine(day, p.start_time, tzinfo=tz)
                band_end = datetime.datetime.combine(day, p.end_time, tzinfo=tz)
                roster_minutes += (band_end - band_start).total_seconds() / 60
                bands.append(
                    {
                        "top": _pct(band_start, day_start, day_end),
                        "height": _pct(band_end, day_start, day_end)
                        - _pct(band_start, day_start, day_end),
                        "label": f"{_fmt_time(p.start_time)} – {_fmt_time(p.end_time)}",
                        "_start": band_start,
                        "_end": band_end,
                    }
                )
            blocks = []
            column = feed.get(member.pk)
            for raw in column.blocks if column else ():
                start = raw.start.astimezone(tz)
                end = raw.end.astimezone(tz)
                appt = appt_by_id.get(raw.appointment_id)
                amount = amount_for(appt) if appt is not None else None
                if amount is None:
                    unpriced += 1
                else:
                    revenue += amount
                if not light and appt is not None:
                    rail_payloads[raw.appointment_id] = rail_payload(appt)
                blocks.append(
                    {
                        "appointment_id": raw.appointment_id,
                        "client_name": raw.client_display_name,
                        "client_initials": _initials(raw.client_display_name),
                        "service_name": raw.service_name,
                        "category_name": raw.service_category_name,
                        "cat_key": slugify(raw.service_category_name) or "misc",
                        "is_new": (
                            appt is not None
                            and first_days.get(appt.client_id) == day
                        ),
                        "status": raw.status,
                        "status_label": _STATUS_LABELS.get(raw.status, raw.status),
                        "top": _pct(start, day_start, day_end),
                        "height": max(
                            _pct(end, day_start, day_end)
                            - _pct(start, day_start, day_end),
                            4.0,
                        ),
                        "time_label": f"{_fmt_time(start.time())} – {_fmt_time(end.time())}",
                        "price_label": _price_label(amount),
                        "_amount": amount,
                        "index": block_index,
                        "_start": start,
                        "_end": end,
                    }
                )
                block_index += 1
            clipped = [
                (max(b["_start"], day_start), min(b["_end"], day_end))
                for b in blocks
                if b["_end"] > day_start and b["_start"] < day_end
            ]
            member_spans[member.pk] = clipped
            break_tiles = []
            break_spans = []
            for br in day_breaks.get(member.pk, []):
                b_start = br.start.astimezone(tz)
                b_end = br.end.astimezone(tz)
                b_top = _pct(b_start, day_start, day_end)
                break_tiles.append(
                    {
                        "break_id": br.pk,
                        "top": b_top,
                        "height": max(
                            _pct(b_end, day_start, day_end) - b_top, 4.0
                        ),
                        "time_label": (
                            f"{_fmt_time(b_start.time())} – "
                            f"{_fmt_time(b_end.time())}"
                        ),
                        "paid": br.paid,
                        "label": "Paid break" if br.paid else "Break",
                        "start_minutes": int(
                            (b_start - day_start).total_seconds() // 60
                        )
                        + DAY_START_HOUR * 60,
                        "minutes": int(
                            (b_end - b_start).total_seconds() // 60
                        ),
                    }
                )
                if b_end > day_start and b_start < day_end:
                    break_spans.append(
                        (max(b_start, day_start), min(b_end, day_end))
                    )
            booked_minutes = _union_minutes(clipped)
            booked_pct = None
            if roster_minutes:
                booked_pct = min(100, int(booked_minutes / roster_minutes * 100 + 0.5))
                total_booked += booked_minutes
                total_roster += roster_minutes
                # Openings close around breaks as well as bookings:
                # busy spans include both, booked minutes stay
                # appointments only — a break is not work sold.
                busy_spans = clipped + break_spans
                for band in bands:
                    in_span = [
                        (max(s, band["_start"]), min(e, band["_end"]))
                        for s, e in busy_spans
                        if e > band["_start"] and s < band["_end"]
                    ]
                    total_openings += _gap_count(in_span, band["_start"], band["_end"])
            overview["appointments"] += len(blocks)
            display_blocks = blocks
            if cat_filter or status_filter:
                display_blocks = [
                    b
                    for b in blocks
                    if (not cat_filter or b["cat_key"] == cat_filter)
                    and (not status_filter or b["status"] == status_filter)
                ]
            # ---- one block per service, Phorest-style ----
            # The grid unit is the appointment: each service is
            # its own block, and blocks that share a row split the
            # column into lanes — services and clients stack side
            # by side, the way the desk is used to seeing the day.
            # The visit still exists where it belongs: in the
            # rail, where a guest's whole stack reads as one.
            tiles = []
            for b in display_blocks:
                tile = dict(b)
                tile["_total"] = b["_amount"]
                tile["top"] = _pct(tile["_start"], day_start, day_end)
                tile["height"] = max(
                    _pct(tile["_end"], day_start, day_end) - tile["top"], 4.0
                )
                tile["time_label"] = (
                    f"{_fmt_time(tile['_start'].astimezone(tz).time())} – "
                    f"{_fmt_time(tile['_end'].astimezone(tz).time())}"
                )
                tile["price_label"] = (
                    _price_label(tile["_total"]) if tile["_total"] is not None else ""
                )
                tile["start_minutes"] = int(
                    (tile["_start"] - day_start).total_seconds() // 60
                )
                tiles.append(tile)
            _assign_lanes(tiles)
            width_factor = min(
                3,
                max((b.get("overlap", 1) for b in tiles), default=1),
            )
            col_total = sum(
                (t["_total"] for t in tiles if t["_total"] is not None),
                Decimal("0"),
            )
            # The agenda still speaks in visits: one entry per
            # chained stack, however many blocks it renders as.
            seen_visits = set()
            for tile in tiles:
                v = visits.get(tile["appointment_id"])
                if v is None or id(v) in seen_visits:
                    continue
                seen_visits.add(id(v))
                v_start = min(a.start for a in v)
                v_end = max(a.end for a in v)
                amounts = [amount_for(a) for a in v]
                priced = [x for x in amounts if x is not None]
                agenda_pool.append(
                    (
                        {
                            "appointment_id": min(v, key=lambda a: a.start).pk,
                            "_start": v_start,
                            "_end": v_end,
                            "time_label": (
                                f"{_fmt_time(v_start.astimezone(tz).time())} – "
                                f"{_fmt_time(v_end.astimezone(tz).time())}"
                            ),
                            "client_name": tile["client_name"],
                            "services": [
                                (a.service.name if a.service else a.service_name)
                                for a in v
                            ],
                            "price_label": (
                                _price_label(sum(priced, Decimal("0")))
                                if priced
                                else ""
                            ),
                        },
                        member,
                    )
                )
            staff.append(
                {
                    "member": member,
                    "on_duty": bool(bands),
                    "bands": bands,
                    "shift_label": ", ".join(b["label"] for b in bands),
                    "blocks": tiles,
                    "breaks": break_tiles,
                    "booked_pct": booked_pct,
                    "initials": _initials(member.display_name),
                    "width_factor": width_factor,
                    "level_name": member.staff_level.name
                    if member.staff_level_id
                    else "",
                    "day_total_label": _money_label(col_total),
                    "day_total": col_total,
                    "visits_count": len(seen_visits),
                    "booked_minutes": booked_minutes,
                }
            )
        overview["revenue"] = revenue
        overview["revenue_label"] = _money_label(revenue)
        overview["unpriced"] = unpriced
        overview["openings"] = total_openings
        if total_roster:
            overview["utilization"] = min(
                100, int(total_booked / total_roster * 100 + 0.5)
            )

        # ---- the working book: a column exists only for a stylist
        # who is rostered today or holds appointments. An off, empty
        # chair is not a column; the desk's screen belongs to the
        # day that is actually happening.
        staff = [c for c in staff if c["on_duty"] or c["blocks"]]
        visits_count = sum(c["visits_count"] for c in staff)
        overview["visits"] = visits_count
        if overview["utilization"] is None and staff:
            # No roster to measure against: utilization is booked
            # time across the working chairs over the day window.
            window_minutes = (day_end - day_start).total_seconds() / 60
            booked_all = sum(c["booked_minutes"] for c in staff)
            overview["utilization"] = min(
                100, int(booked_all / (len(staff) * window_minutes) * 100 + 0.5)
            )

        # ---- KPI ribbon facts: each one computed, never styled in
        kpi = {
            "avg_ticket_label": _money_label(revenue / visits_count)
            if visits_count
            else "—",
            # The shared first-days map from the one aggregate
            # pass — the ribbon and the block glow can never
            # disagree about who is new.
            "new_clients": sum(1 for d in first_days.values() if d == day),
        }

        # ---- intelligence strip: real answers from the day itself
        now_moment = timezone.now().astimezone(tz)
        cursor = now_moment if day == today else day_start
        candidates = []
        for col in staff:
            spans = sorted(member_spans.get(col["member"].pk, []))
            probe = max(cursor, day_start)
            found = None
            for span_start, span_end in spans:
                if (
                    span_start > probe
                    and (span_start - probe).total_seconds() / 60 >= 45
                ):
                    found = (probe, col["member"].display_name, span_start)
                    break
                probe = max(probe, span_end)
            if found is None and (day_end - probe).total_seconds() / 60 >= 45:
                found = (probe, col["member"].display_name, day_end)
            if found is not None:
                candidates.append(found)
        if candidates:
            candidates.sort(key=lambda c: c[0])
            o_start, o_name, o_end = candidates[0]
            intel["next_label"] = (
                f"{o_name} — open from {_fmt_time(o_start.astimezone(tz).time())}"
            )
            intel["next_sub"] = (
                f"{_duration_label(int((o_end - o_start).total_seconds() // 60))}"
                " free · first chair open for a 45+ min service"
            )
        top_col = max(staff, key=lambda c: c["day_total"], default=None)
        if top_col is not None:
            intel["top_label"] = (
                f"{top_col['member'].display_name} · {top_col['day_total_label']}"
            )
        intel["completed"] = sum(
            1 for a in day_appts if a.status == Appointment.Status.COMPLETED
        )
        intel["remaining"] = (
            sum(1 for tile, _m in agenda_pool if tile["_end"] > cursor)
            if day == today
            else visits_count
        )

        # ---- the phone agenda: the same visits, chronological
        staff_index = {c["member"].pk: i for i, c in enumerate(staff)}
        ordered = sorted(agenda_pool, key=lambda pair: pair[0]["_start"])
        if day == today:
            for i, (tile, _member) in enumerate(ordered):
                if tile["_end"] > now_moment:
                    agenda_now_index = i
                    break
        agenda = [
            {
                "appointment_id": tile["appointment_id"],
                "time_label": tile["time_label"],
                "client_name": tile["client_name"],
                "services_label": " + ".join(tile["services"]),
                "total_label": tile["price_label"],
                "staff_name": member.display_name,
                "staff_index": staff_index.get(member.pk, 0),
            }
            for tile, member in ordered
        ]

        if day_appts and day_appts[0].pk in rail_payloads:
            default_rail = rail_payloads[day_appts[0].pk]

    now_top = None
    now_label = ""
    if day == today:
        now = timezone.now().astimezone(tz)
        if day_start <= now <= day_end:
            now_top = _pct(now, day_start, day_end)
            now_label = _fmt_time(now.time())

    grid_tracks = ""
    if staff:
        grid_tracks = "var(--gutter) " + " ".join(
            "minmax(calc(var(--colunit) * {0}), {0}fr)".format(c["width_factor"])
            for c in staff
        )

    context = {
        "nav_key": "daybook",
        "day": day,
        "prev_day": day - datetime.timedelta(days=1),
        "next_day": day + datetime.timedelta(days=1),
        "today": today,
        "grid_tracks": grid_tracks,
        "day_start_hour": DAY_START_HOUR,
        "day_end_hour": DAY_END_HOUR,
        "hours": hours,
        "week_days": week_days,
        "staff_columns": staff,
        "has_blocks": any(c["blocks"] for c in staff),
        "overview": overview,
        "kpi": kpi,
        "intel": intel,
        "agenda": agenda,
        "agenda_now_index": agenda_now_index,
        "rail": default_rail,
        "rail_data": rail_payloads,
        "categories": categories,
        "cat_filter": cat_filter,
        "status_filter": status_filter,
        "status_choices": Appointment.Status.choices,
        "now_top": now_top,
        "now_label": now_label,
        "tz_label": tz.tzname(day_start) if hasattr(tz, "tzname") else "",
    }
    return context


def day_book(request):
    return render(request, "webui/daybook.html", _day_book_context(request))


def day_book_fragment(request):
    """The day book's content without the app chrome.

    The client's hot range fetches one of these per date and caches
    it, so moving between days renders from memory — no server
    round-trip stands between a tap and the paint.
    """
    return render(request, "webui/_daybook_main.html", _day_book_context(request))


@require_POST
def day_book_move(request):
    """Persist a drag on the day book.

    The dragged unit is the block the hand grabbed: one
    appointment (one service), exactly as the grid renders it.
    The start snaps to 5 minutes. Overlaps are allowed — the
    book renders stacked blocks in lanes rather than pretending
    they cannot happen — so a drop always saves; the client
    re-reads the day fragment and shows the truth.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
        anchor_id = int(payload["appointment_id"])
        member_id = int(payload["staff_member_id"])
        start_minutes = int(payload["start_minutes"])
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "bad payload"}, status=400)
    anchor = (
        Appointment.objects.select_related("staff_member", "client")
        .filter(pk=anchor_id)
        .first()
    )
    if anchor is None:
        return JsonResponse({"ok": False, "error": "no such appointment"}, status=404)
    salon = anchor.staff_member.salon
    member = StaffMember.objects.filter(pk=member_id, salon=salon, active=True).first()
    if member is None:
        return JsonResponse({"ok": False, "error": "no such stylist"}, status=404)
    snapped = _do_move(anchor, member, start_minutes, _tz(salon))
    return JsonResponse({"ok": True, "moved": 1, "start_minutes": snapped})


def _do_move(anchor, member, start_minutes, tz):
    """The move itself, shared by the single-op endpoint and the
    batch drain: snap to 5 minutes, clamp inside the day, keep
    the duration, save. Returns the snapped start minute."""
    local_day = anchor.start.astimezone(tz).date()
    duration_minutes = (anchor.end - anchor.start).total_seconds() / 60
    snapped = int(round(start_minutes / 5.0)) * 5
    snapped = max(0, min(snapped, int(24 * 60 - duration_minutes)))
    new_start = datetime.datetime.combine(local_day, datetime.time(0), tzinfo=tz) + (
        datetime.timedelta(minutes=snapped)
    )
    delta = new_start - anchor.start
    anchor.start += delta
    anchor.end += delta
    anchor.staff_member = member
    # Every desk write stamps itself: the pack version is
    # (count, max updated_at), and a save that leaves updated_at
    # untouched leaves the version standing still — clients
    # polling with their stamp are told "nothing changed" and
    # the mirror never converges on the write. update_fields
    # saves do not move auto_now on their own; the write must.
    anchor.updated_at = timezone.now()
    anchor.save(update_fields=["start", "end", "staff_member", "updated_at"])
    return snapped


def _do_status(appt, target):
    """The status transition itself, shared by the single-op
    endpoint and the batch drain. The transition table is the
    only law: returns an error string, or None after saving."""
    allowed = {s for s, _label, _p in _STATUS_ACTIONS.get(appt.status, [])}
    if target not in allowed:
        return f"cannot move {appt.status} to {target}"
    appt.status = target
    appt.updated_at = timezone.now()
    appt.save(update_fields=["status", "updated_at"])
    return None


def _do_price(appt, raw):
    """Set (or clear) an appointment's own price from the card.

    The card's word becomes ``price_override`` — the book row is
    never touched. An empty value clears the override and the
    book speaks again. Money is validated as money: finite,
    non-negative, cent-quantized, never via float.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        appt.price_override = None
        appt.updated_at = timezone.now()
        appt.save(update_fields=["price_override", "updated_at"])
        return None
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        return "price is not a number"
    if not value.is_finite():
        return "price is not a number"
    if value < 0:
        return "price cannot be negative"
    if value > Decimal("99999.99"):
        return "price is too large"
    appt.price_override = value.quantize(Decimal("0.01"))
    appt.updated_at = timezone.now()
    appt.save(update_fields=["price_override", "updated_at"])
    return None


def _do_note(appt, op):
    """Create or edit a note from the client card.

    Two kinds, never blurred: scope ``appt`` writes an
    appointment-only note on this appointment; scope ``client``
    writes the persistent client record note. An edit must name
    a note that belongs to its target — the card can never reach
    another visit's or another client's words.
    """
    scope = str(op.get("scope") or "")
    body = str(op.get("body") or "").strip()
    if scope not in ("appt", "client"):
        return "unknown note scope"
    if not body:
        return "note cannot be empty"
    if len(body) > 2000:
        return "note is too long"
    note_id = op.get("note_id")
    if scope == "appt":
        model, owner = AppointmentNote, {"appointment": appt}
    else:
        model, owner = ClientNote, {"client": appt.client}
    if note_id in (None, ""):
        # Replay guard: the tab's durable queue can re-send an
        # add whose ack died with the tab. An identical note on
        # the same target written moments ago IS that add — not
        # a second note the desk meant to write twice.
        recent = timezone.now() - datetime.timedelta(minutes=15)
        if not model.objects.filter(
            body=body, created_at__gte=recent, **owner
        ).exists():
            model.objects.create(body=body, **owner)
        return None
    note = model.objects.filter(pk=int(note_id), **owner).first()
    if note is None:
        return "no such note"
    note.body = body
    note.save(update_fields=["body"])
    return None


def _chain_echo(data):
    """The drain's chain stamp, echoed back: the client
    store's journal chain — its engine's sequence and head
    hash — as it stood when the batch was built. The node
    attests receipt: ``chain_ok`` says the stamp arrived
    whole and well-formed. Continuity across drains is the
    client's chain to prove; this echo is its receipt, and
    a stamp that returns different is a broken word, treated
    like any other. A drain from an older client carries no
    stamp and gets ``(None, False)`` — received, not
    attested."""
    chain = data.get("chain") if isinstance(data, dict) else None
    if not isinstance(chain, dict):
        return None, False
    seq, head = chain.get("seq"), chain.get("head")
    ok = (
        isinstance(seq, int)
        and not isinstance(seq, bool)
        and seq >= 0
        and isinstance(head, str)
        and bool(head)
    )
    return ({"seq": seq, "head": head} if ok else None), ok


@require_POST
def day_book_apply(request):
    """The drain: a batch of ops from a client's embedded store.

    The founder's two-stage design — the tab's in-memory NEDB
    holds the app and plays instantly; this endpoint is the
    persistence stage the op queue drains into, in bulk. Each op
    is applied under exactly the single-op rules (same snap, same
    transition table) and reported individually: one bad op never
    poisons the batch, and the client learns per-op truth so it
    can converge — acked ops are provenance, failed ops are
    re-read from the server's book.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
        ops = payload["ops"]
        if not isinstance(ops, list) or len(ops) > 100:
            raise ValueError("ops must be a list of at most 100")
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "bad payload"}, status=400)
    results = []
    for index, op in enumerate(ops):
        result = {"i": index, "ok": False}
        try:
            kind = str(op["kind"])
            if kind == "create":
                # A birth, not a play on an existing row: the
                # store created the doc under a temporary ref
                # and the drain carries the booking itself. The
                # answer names the real id and carries the true
                # pack entry, so the store renames its doc and
                # every later play rides on the real id.
                error, created, _day = _do_create(op)
                if error:
                    result["error"] = error
                else:
                    salon = created.staff_member.salon
                    result["ok"] = True
                    result["id"] = created.pk
                    result["entry"] = _pack_entry_for(
                        salon, created, _tz(salon)
                    )
                results.append(result)
                continue
            appt = Appointment.objects.select_related("staff_member").filter(
                pk=int(op["id"])
            ).first()
            if appt is None:
                result["error"] = "no such appointment"
            elif kind == "move":
                salon = appt.staff_member.salon
                member = StaffMember.objects.filter(
                    pk=int(op["staff_member_id"]), salon=salon, active=True
                ).first()
                if member is None:
                    result["error"] = "no such stylist"
                else:
                    result["start_minutes"] = _do_move(
                        appt, member, int(op["start_minutes"]), _tz(salon)
                    )
                    result["ok"] = True
            elif kind == "status":
                error = _do_status(appt, str(op["status"]))
                if error:
                    result["error"] = error
                else:
                    result["ok"] = True
            elif kind == "price":
                error = _do_price(appt, op.get("price"))
                if error:
                    result["error"] = error
                else:
                    result["ok"] = True
            elif kind == "note":
                error = _do_note(appt, op)
                if error:
                    result["error"] = error
                else:
                    result["ok"] = True
            else:
                result["error"] = f"unknown op kind {kind}"
        except (ValueError, KeyError, TypeError) as exc:
            result["error"] = f"bad op: {exc}"
        results.append(result)
    return JsonResponse(
        {
            "ok": all(r["ok"] for r in results),
            "results": results,
            "chain": _chain_echo(payload)[0],
            "chain_ok": _chain_echo(payload)[1],
        }
    )


@require_POST
def day_book_status(request):
    """Move an appointment along the desk's status flow.

    Check In is the first step: booked/confirmed -> arrived ->
    in_service -> completed, with no-show and cancel offered
    where the desk needs them. Only the transitions the rail
    offers are accepted; anything else is a 400, because a status
    the desk cannot explain should never land silently.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
        appt_id = int(payload["appointment_id"])
        target = str(payload["status"])
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "bad payload"}, status=400)
    appt = Appointment.objects.filter(pk=appt_id).first()
    if appt is None:
        return JsonResponse({"ok": False, "error": "no such appointment"}, status=404)
    error = _do_status(appt, target)
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)
    return JsonResponse(
        {"ok": True, "status": target, "status_label": _STATUS_LABELS.get(target, target)}
    )


@require_POST
def day_book_price(request):
    """Single-op price write (the batch drain's twin).

    Same law as the apply endpoint's price kind: the value lands
    as the appointment's own override, or clears it when empty.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
        appt_id = int(payload["appointment_id"])
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "bad payload"}, status=400)
    appt = Appointment.objects.filter(pk=appt_id).first()
    if appt is None:
        return JsonResponse({"ok": False, "error": "no such appointment"}, status=404)
    error = _do_price(appt, payload.get("price"))
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)
    return JsonResponse(
        {"ok": True, "price": str(appt.price_override) if appt.price_override is not None else ""}
    )


def _visit_for(appt):
    """The visit a checkout settles: the appointment's own chain
    under the day book's rule (same client + stylist, chained
    while the gap stays within VISIT_GAP)."""
    salon = appt.staff_member.salon
    tz = _tz(salon)
    day = appt.start.astimezone(tz).date()
    midnight = datetime.datetime.combine(day, datetime.time.min, tzinfo=tz)
    rows = list(
        Appointment.objects.filter(
            client_id=appt.client_id,
            staff_member_id=appt.staff_member_id,
            start__lt=midnight + datetime.timedelta(days=1),
            end__gt=midnight,
        )
        .exclude(status=Appointment.Status.CANCELLED)
        .select_related("service", "staff_member")
        .order_by("start")
    )
    visit, visit_end = [], None
    for row in rows:
        if visit and row.start > visit_end + VISIT_GAP:
            if any(a.pk == appt.pk for a in visit):
                return visit
            visit, visit_end = [], None
        visit.append(row)
        visit_end = max(visit_end or row.end, row.end)
    return visit if any(a.pk == appt.pk for a in visit) else [appt]


def _do_checkout(appt, payload):
    """Settle a visit: sale + items + tender + stock + receipt.

    The one checkout law for the day book (and any future POS
    surface): services price through the day book's own lookup
    — a card price override wins — products snapshot the
    catalogue price, tender runs through the provider-agnostic
    interface (cash at the till, or an external tender the
    salon settles on its own terminal; core moves no money and
    names no vendor), stock leaves the shelf as SALE movements,
    the receipt snapshots at issue, and the visit's
    appointments complete carrying the write stamp every other
    write carries. Returns (error, sale).
    """
    from catalog.models import Product, StockMovement
    from checkout.models import Payment, Sale, SaleItem
    from checkout.payments import CashProvider, ExternalTenderProvider
    from checkout.receipts import build_receipt

    salon = appt.staff_member.salon
    method = str(payload.get("method") or "cash")
    providers = {
        "cash": (CashProvider, Payment.Method.CASH),
        "external": (ExternalTenderProvider, Payment.Method.EXTERNAL),
    }
    if method not in providers:
        return "unknown tender", None
    visit = _visit_for(appt)
    if any(a.status == Appointment.Status.COMPLETED for a in visit):
        return "visit already completed", None
    if any(a.status == Appointment.Status.NO_SHOW for a in visit):
        return "visit has a no-show", None
    prices, base_level_id = _price_lookup(salon)
    service_lines = []
    for a in visit:
        amount = _amount_for(a, prices, base_level_id)
        if amount is None:
            return (
                f"unpriced service on the visit: "
                f"{a.service_name or 'service'}",
                None,
            )
        service_lines.append((a, amount))
    product_lines = []
    for raw in payload.get("products") or []:
        try:
            product_id, qty = int(raw["product_id"]), int(raw["qty"])
        except (KeyError, TypeError, ValueError):
            return "bad product line", None
        if qty < 1 or qty > 99:
            return "bad quantity", None
        product = Product.objects.filter(
            pk=product_id, salon=salon, active=True
        ).first()
        if product is None:
            return "no such product", None
        product_lines.append((product, qty))
    sale = Sale.objects.create(salon=salon, client=appt.client)
    for a, amount in service_lines:
        SaleItem.objects.create(
            sale=sale,
            kind=SaleItem.Kind.SERVICE,
            service=a.service,
            description=a.service.name if a.service else a.service_name,
            unit_price=amount,
            quantity=1,
        )
    for product, qty in product_lines:
        SaleItem.objects.create(
            sale=sale,
            kind=SaleItem.Kind.PRODUCT,
            product=product,
            description=product.name,
            unit_price=product.price,
            quantity=qty,
        )
    provider_cls, method_enum = providers[method]
    result = provider_cls().charge(sale.total, reference=f"sale-{sale.pk}")
    if not result.success:
        sale.delete()
        return "tender failed", None
    Payment.objects.create(
        sale=sale,
        method=method_enum,
        amount=sale.total,
        status=result.status,
        provider_reference=result.reference,
    )
    sale.status = Sale.Status.COMPLETED
    sale.completed_at = timezone.now()
    sale.save(update_fields=["status", "completed_at"])
    now = timezone.now()
    for a in visit:
        a.status = Appointment.Status.COMPLETED
        a.updated_at = now
        a.save(update_fields=["status", "updated_at"])
    for product, qty in product_lines:
        StockMovement.objects.create(
            product=product,
            kind=StockMovement.Kind.SALE,
            quantity_delta=-qty,
            note=f"Sale #{sale.pk}",
        )
    build_receipt(sale)
    return None, sale


@require_POST
def day_book_checkout(request):
    """Checkout for a visit, from its client card."""
    from checkout.receipts import render_receipt_text

    try:
        payload = json.loads(request.body.decode("utf-8"))
        appt_id = int(payload["appointment_id"])
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "bad payload"}, status=400)
    appt = (
        Appointment.objects.select_related("staff_member", "client")
        .filter(pk=appt_id)
        .first()
    )
    if appt is None:
        return JsonResponse(
            {"ok": False, "error": "no such appointment"}, status=404
        )
    error, sale = _do_checkout(appt, payload)
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)
    receipt = getattr(sale, "receipt", None)
    return JsonResponse(
        {
            "ok": True,
            "sale_id": sale.pk,
            "total": str(sale.total),
            "total_label": _price_label(sale.total),
            "receipt_text": render_receipt_text(receipt) if receipt else "",
            "client_email": sale.client.email if sale.client_id else "",
        }
    )


def day_book_products(request):
    """Till search over the salon's retail shelf: name, brand or
    barcode, with the live stock count for each match."""
    from catalog.models import Product

    salon = _first_salon()
    if salon is None:
        return JsonResponse({"products": []})
    q = (request.GET.get("q") or "").strip()
    qs = Product.objects.filter(salon=salon, active=True).order_by("name")
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(brand_name__icontains=q) | Q(barcode__icontains=q)
        )
    products = [
        {
            "id": p.pk,
            "name": p.name,
            "brand": p.brand_name,
            "price": str(p.price),
            "price_label": _price_label(p.price),
            "stock": p.current_stock,
            "retail": p.product_type == "RETAIL",
        }
        for p in qs[:60]
    ]
    # The till sells from the retail shelf first; other stock
    # stays findable below it rather than hidden.
    products.sort(key=lambda row: (not row["retail"], row["name"]))
    return JsonResponse({"products": products[:12]})


@require_POST
def day_book_note(request):
    """Single-op note write (the batch drain's twin).

    Same law as the apply endpoint's note kind: appointment
    notes stay on the appointment, client notes on the record.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
        appt_id = int(payload["appointment_id"])
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "bad payload"}, status=400)
    appt = Appointment.objects.filter(pk=appt_id).first()
    if appt is None:
        return JsonResponse({"ok": False, "error": "no such appointment"}, status=404)
    error = _do_note(appt, payload)
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)
    return JsonResponse({"ok": True})


def _price_lookup(salon):
    """Every active price row for the salon, plus the Base level.

    One lookup shared by the day book and the client pack, so a
    price can never mean two things in two renderers.
    """
    prices = {
        (p.service_id, p.staff_level_id): p.amount
        for p in ServicePrice.objects.filter(
            active=True, service__category__salon=salon
        )
    }
    base_level = StaffLevel.objects.filter(salon=salon, name="Base").first()
    return prices, (base_level.pk if base_level is not None else None)


def _amount_for(appt, prices, base_level_id):
    if appt.price_override is not None:
        # The client card set this visit's price: it wins over
        # every book row, everywhere the amount is read.
        return appt.price_override
    amount = prices.get((appt.service_id, appt.staff_member.staff_level_id))
    if amount is None and base_level_id is not None:
        # No row at the stylist's own level: price at the service's
        # Base (menu) row rather than not at all.
        amount = prices.get((appt.service_id, base_level_id))
    return amount


def _first_salon():
    return Salon.objects.order_by("id").first()


def day_book_book_options(request):
    """The booking form's choices: stylists and the service menu."""
    salon = _first_salon()
    if salon is None:
        return JsonResponse({"members": [], "services": [], "today": ""})
    tz = _tz(salon)
    members = [
        {"id": m.pk, "name": m.display_name}
        for m in StaffMember.objects.filter(salon=salon, active=True).order_by(
            "display_name"
        )
    ]
    services = [
        {
            "id": s.pk,
            "name": s.name,
            "minutes": s.service_minutes,
            "category": s.category.name if s.category_id else "",
        }
        for s in Service.objects.filter(category__salon=salon)
        .select_related("category")
        .order_by("category__sort_order", "category__name", "name")
    ]
    return JsonResponse(
        {
            "members": members,
            "services": services,
            "today": timezone.now().astimezone(tz).date().isoformat(),
        }
    )


def day_book_client_search(request):
    """Find a client for the booking form: first, last, first + last,
    phone, or email — the ways the desk actually looks someone up."""
    salon = _first_salon()
    q = (request.GET.get("q") or "").strip()
    if salon is None or len(q) < 2:
        return JsonResponse({"clients": []})
    qs = Client.objects.filter(salon=salon)
    digits = "".join(ch for ch in q if ch.isdigit())
    cond = Q()
    for token in q.split():
        cond |= (
            Q(first_name__icontains=token)
            | Q(last_name__icontains=token)
            | Q(email__icontains=token)
        )
    rows = list(qs.filter(cond).order_by("first_name", "last_name")[:8])
    exact = []
    tokens = q.split()
    if len(tokens) >= 2:
        # "First Last" typed in full names ONE person. Rows matching
        # EVERY token are fetched separately and ranked first, so a
        # common surname can't push the exact person past the cap.
        exact_qs = qs
        for token in tokens:
            exact_qs = exact_qs.filter(
                Q(first_name__icontains=token)
                | Q(last_name__icontains=token)
                | Q(email__icontains=token)
            )
        exact = list(exact_qs.order_by("first_name", "last_name")[:8])
        if exact:
            exact_pks = {c.pk for c in exact}
            rows = (exact + [c for c in rows if c.pk not in exact_pks])[:8]
    if len(digits) >= 3:
        # Stored phones carry punctuation ("407-555-0100"), so a
        # digit query can never substring-match them directly:
        # narrow by the first digits, then compare digit-to-digit.
        seen = {c.pk for c in rows}
        candidates = qs.filter(phone__icontains=digits[:3]).order_by(
            "first_name", "last_name"
        )[:200]
        for c in candidates:
            phone_digits = "".join(ch for ch in (c.phone or "") if ch.isdigit())
            if digits in phone_digits and c.pk not in seen:
                rows.append(c)
                seen.add(c.pk)
        if not exact:
            rows.sort(key=lambda c: (c.first_name, c.last_name))
    return JsonResponse(
        {
            "clients": [
                {
                    "id": c.pk,
                    "name": f"{c.first_name} {c.last_name}".strip(),
                    "phone": c.phone,
                }
                for c in rows[:8]
            ]
        }
    )


def _create_twin(member, service, start, client, first, last, phone):
    """The replay guard for store-born bookings.

    A create play's ack can die with its tab; the durable queue
    then re-sends a birth the node already delivered. An
    appointment for the same stylist, service and start,
    created moments ago for the same client (or for a client
    created moments ago with the same name and phone), IS that
    birth — the drain is answered with the original, never a
    twin. The note ops' replay guard, carried to creates."""
    recent = timezone.now() - datetime.timedelta(minutes=15)
    qs = Appointment.objects.filter(
        staff_member=member, service=service, start=start,
        created_at__gte=recent,
    )
    if client is not None:
        return qs.filter(client=client).first()
    twin_client = Client.objects.filter(
        salon=member.salon, first_name=first, last_name=last,
        phone=phone, created_at__gte=recent,
    ).first()
    if twin_client is None:
        return None
    return qs.filter(client=twin_client).first()


def _do_create(payload):
    """The desk's booking, created once — shared by the book
    endpoint and the store's drain, so a booking is born under
    one law whichever door it arrives by.

    One service, one stylist, one client — an existing client
    by id, or a new client created from the name/phone the
    desk typed. The end is the start plus the service's own
    minutes; the name snapshot is stored verbatim, like an
    import's. The book allows overlaps (lanes render them),
    so no conflict can reject a booking the desk wants.

    Returns (error, appointment, day); error is None on a
    birth. A payload carrying a store `ref` is replay-guarded:
    a twin born moments ago answers instead of a duplicate."""
    try:
        member_id = int(payload["staff_member_id"])
        service_id = int(payload["service_id"])
        day = datetime.date.fromisoformat(str(payload["date"]))
        start_time = datetime.datetime.strptime(
            str(payload["time"]), "%H:%M"
        ).time()
    except (ValueError, KeyError, TypeError):
        return "bad payload", None, None
    member = StaffMember.objects.select_related("salon").filter(
        pk=member_id, active=True
    ).first()
    if member is None:
        return "no such stylist", None, None
    salon = member.salon
    service = Service.objects.filter(
        pk=service_id, category__salon=salon
    ).first()
    if service is None:
        return "no such service", None, None
    client = None
    if payload.get("client_id"):
        try:
            client = Client.objects.filter(
                pk=int(payload["client_id"]), salon=salon
            ).first()
        except (TypeError, ValueError):
            client = None
    new_client = payload.get("new_client") or {}
    first = str(new_client.get("first_name", "")).strip()
    last = str(new_client.get("last_name", "")).strip()
    phone = str(new_client.get("phone", "")).strip()
    if client is None and not first and not last:
        return "pick a client or enter a new client's name", None, None
    tz = _tz(salon)
    start = datetime.datetime.combine(day, start_time, tzinfo=tz)
    if payload.get("ref"):
        twin = _create_twin(
            member, service, start, client, first, last, phone
        )
        if twin is not None:
            return None, twin, day
    if client is None:
        client = Client.objects.create(
            salon=salon, first_name=first, last_name=last, phone=phone
        )
    minutes = service.service_minutes or 60
    appt = Appointment.objects.create(
        client=client,
        staff_member=member,
        service=service,
        service_name=service.name,
        start=start,
        end=start + datetime.timedelta(minutes=minutes),
        status=Appointment.Status.BOOKED,
    )
    return None, appt, day


@require_POST
def day_book_book(request):
    """Create a booking from the desk — the direct door.

    The day book itself no longer books through here when its
    embedded store is live: the booking is a store play first
    and drains through the apply endpoint's create kind. This
    door remains for pages and tabs without a store, under the
    same creation core."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "bad payload"}, status=400)
    error, appt, day = _do_create(payload)
    if error:
        status = (
            404 if error in ("no such stylist", "no such service") else 400
        )
        return JsonResponse({"ok": False, "error": error}, status=status)
    salon = appt.staff_member.salon
    return JsonResponse(
        {
            "ok": True,
            "appointment_id": appt.pk,
            "date": day.isoformat(),
            # The created appointment's pack entry rides home with
            # the reply, so the client's embedded store adopts it
            # as a doc at once — the book never re-fetches a pack
            # to learn what it just created.
            "entry": _pack_entry_for(salon, appt, _tz(salon)),
        }
    )


@require_POST
def day_book_break(request):
    """Block off a span of one stylist's day as a break.

    The desk pressed empty space and chose Break: this stylist,
    starting at this time, for this many minutes, paid or unpaid.
    The reply carries everything the book needs to paint the
    break where it stands — the block exists on screen in the
    same breath as the answer, like every write on this desk."""
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "bad payload"}, status=400)
    member = StaffMember.objects.filter(
        pk=data.get("staff_member_id"), active=True
    ).first()
    if member is None:
        return JsonResponse(
            {"ok": False, "error": "unknown staff member"}, status=400
        )
    salon = member.salon
    tz = _tz(salon)
    try:
        day = datetime.date.fromisoformat(str(data.get("date", "")))
        hour, minute = (int(p) for p in str(data.get("time", "")).split(":"))
        minutes = int(data.get("minutes"))
    except (TypeError, ValueError):
        return JsonResponse(
            {"ok": False, "error": "bad date, time or length"}, status=400
        )
    if minutes < 5 or minutes > 720:
        return JsonResponse(
            {"ok": False, "error": "a break runs 5 minutes to 12 hours"},
            status=400,
        )
    start = datetime.datetime.combine(
        day, datetime.time(hour, minute), tzinfo=tz
    )
    br = Break.objects.create(
        staff_member=member,
        start=start,
        end=start + datetime.timedelta(minutes=minutes),
        paid=bool(data.get("paid")),
    )
    return JsonResponse(
        {
            "ok": True,
            "break": {
                "id": br.pk,
                "staff_id": member.pk,
                "date": day.isoformat(),
                "start_min": hour * 60 + minute,
                "minutes": minutes,
                "paid": br.paid,
                "label": "Paid break" if br.paid else "Break",
                "time_label": (
                    f"{_fmt_time(start.time())} – "
                    f"{_fmt_time(br.end.astimezone(tz).time())}"
                ),
            },
        }
    )


@require_POST
def day_book_break_remove(request):
    """Take a break back off the book."""
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "bad payload"}, status=400)
    br = Break.objects.filter(pk=data.get("break_id")).first()
    if br is None:
        return JsonResponse({"ok": False, "error": "unknown break"}, status=400)
    salon = _first_salon()
    if salon is not None and br.staff_member.salon_id != salon.pk:
        return JsonResponse({"ok": False, "error": "unknown break"}, status=400)
    br.delete()
    return JsonResponse({"ok": True})


def _visit_keys(tiles, client_ids):
    """Visit keys with the day book's own chaining rule: same
    client + stylist, chained while the gap stays within
    VISIT_GAP; the key is the visit's first appointment."""
    visit_of = {}
    grouped = {}
    for tile in tiles:
        grouped.setdefault(
            (client_ids.get(tile["appointment_id"]), tile["_staff_id"]), []
        ).append(tile)
    for group in grouped.values():
        visit, visit_end = [], None
        for tile in group:
            if visit and tile["_start"] > visit_end + VISIT_GAP:
                for member_tile in visit:
                    visit_of[member_tile["appointment_id"]] = visit[0][
                        "appointment_id"
                    ]
                visit, visit_end = [], None
            visit.append(tile)
            visit_end = max(visit_end or tile["_end"], tile["_end"])
        for member_tile in visit:
            visit_of[member_tile["appointment_id"]] = visit[0]["appointment_id"]
    return visit_of


def _tile_entry(tile, tz, visit_of):
    """One pack entry from a day-book tile — the shape the client
    model, the embedded store, and the pack all share."""
    start = tile["_start"].astimezone(tz)
    end = tile["_end"].astimezone(tz)
    return {
        "id": tile["appointment_id"],
        "staff_id": tile["_staff_id"],
        "client": tile["client_name"],
        "service": tile["service_name"],
        "cat": tile["cat_key"],
        "is_new": tile["is_new"],
        "start_min": start.hour * 60 + start.minute,
        "end_min": end.hour * 60 + end.minute,
        "status": tile["status"],
        "amount": str(tile["_amount"]) if tile["_amount"] is not None else None,
        "price_label": tile["price_label"],
        "time_label": tile["time_label"],
        "visit": visit_of.get(tile["appointment_id"]),
    }


def _pack_entry_for(salon, appt, tz):
    """The pack entry for ONE appointment, built from the row
    itself — never from a whole day context.

    The booking POST's reply rides on this entry. The first
    version rebuilt the entire day through the context builder
    to describe one block; on the pilot's NEDB that context is
    seconds of queries, and the desk waited all of them inside
    the POST — the ten-second appointment, again, wearing a
    different coat. Every field here is one of the row's own
    lookups: the shared price map for the amount, one existence
    check for the first-visit flag, and the visit rule run
    over the only appointments that can chain with this one
    (same client, same stylist, same day). The store-law test
    pins the result key-for-key against the pack's own entry
    for the same appointment, so the two can never drift."""
    day = appt.start.astimezone(tz).date()
    day_start = datetime.datetime.combine(day, datetime.time.min, tzinfo=tz)
    prices, base_level_id = _price_lookup(salon)
    amount = _amount_for(appt, prices, base_level_id)
    client = appt.client
    client_name = (
        client.display_name
        if hasattr(client, "display_name")
        else f"{client.first_name} {client.last_name}".strip()
    )
    is_new = not Appointment.objects.filter(
        client_id=appt.client_id, start__lt=day_start
    ).exists()
    siblings = list(
        Appointment.objects.filter(
            client_id=appt.client_id,
            staff_member_id=appt.staff_member_id,
            start__gte=day_start,
            start__lt=day_start + datetime.timedelta(days=1),
        )
        .exclude(status=Appointment.Status.CANCELLED)
        .order_by("start", "pk")
    )
    mini_tiles = [
        {
            "appointment_id": a.pk,
            "_staff_id": a.staff_member_id,
            "_start": a.start,
            "_end": a.end,
        }
        for a in siblings
    ]
    visit_of = _visit_keys(mini_tiles, {a.pk: a.client_id for a in siblings})
    start = appt.start.astimezone(tz)
    end = appt.end.astimezone(tz)
    category_name = (
        appt.service.category.name
        if appt.service is not None and appt.service.category_id
        else ""
    )
    return {
        "id": appt.pk,
        "staff_id": appt.staff_member_id,
        "client": client_name,
        "service": appt.service.name if appt.service else appt.service_name,
        "cat": slugify(category_name) or "misc",
        "is_new": is_new,
        "start_min": start.hour * 60 + start.minute,
        "end_min": end.hour * 60 + end.minute,
        "status": appt.status,
        "amount": str(amount) if amount is not None else None,
        "price_label": _price_label(amount) if amount is not None else "",
        "time_label": (
            f"{_fmt_time(start.time())} – {_fmt_time(end.time())}"
        ),
        "visit": visit_of.get(appt.pk, appt.pk),
    }


def day_book_pack(request):
    """The hot range as ONE packed asset for the client.

    The founder's shape: the client holds the week in memory and
    reacts eagerly — to touch, to keys, to other desks — without
    asking the server per gesture. So the range travels as a
    single pack (appointments as data, minutes-from-midnight in
    salon time, prices resolved through the same lookup the day
    book renders with), versioned by a stamp. A poll carrying the
    current stamp gets a one-line "unchanged" answer; anything
    else gets the fresh pack. The pack is a mirror: it can always
    be thrown away and re-fetched, because nedbv2 behind the
    server stays the only durable truth.
    """
    salon = _first_salon()
    if salon is None:
        return JsonResponse({"pack": 1, "version": "", "days": {}, "staff": []})
    tz = _tz(salon)
    try:
        anchor = datetime.date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        anchor = timezone.now().astimezone(tz).date()
    monday = anchor - datetime.timedelta(days=anchor.weekday())
    week = [monday + datetime.timedelta(days=i) for i in range(7)]
    range_start = datetime.datetime.combine(week[0], datetime.time.min, tzinfo=tz)
    range_end = datetime.datetime.combine(
        week[-1] + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz
    )
    # The kit's members are fetched first: filtering the range
    # by their ids (a narrow column predicate) instead of by
    # staff_member__salon (a join) is the difference between a
    # scan and a scan-with-a-join on the wire — and the pack
    # only ever carries these members' appointments anyway.
    members = list(
        StaffMember.objects.filter(salon=salon, active=True)
        .select_related("staff_level")
        .prefetch_related("roster_patterns")
    )
    in_range = Appointment.objects.filter(
        staff_member_id__in=[m.pk for m in members],
        start__lt=range_end,
        end__gt=range_start,
    ).exclude(status=Appointment.Status.CANCELLED)
    # One aggregate pass answers the stamp: how many rows the
    # pack would carry, and the freshest write among them. A
    # write outside the visible week cannot change this pack,
    # so it no longer invalidates it either.
    stats = in_range.aggregate(n=Count("id"), m=Max("updated_at"))
    version = f"{stats['n']}:{(stats['m'].isoformat() if stats['m'] else '')}"
    if request.GET.get("stamp") and request.GET.get("stamp") == version:
        return JsonResponse({"changed": False, "version": version})
    # Pack v2: every day's entries are lifted from the day book's
    # own context builder, so the pack can never disagree with the
    # page about a block, a price, or a visit — same function, same
    # numbers. The anchor day additionally carries its rendered
    # ribbon/intel/agenda facts, which lets the client reconcile
    # in place (update what changed, touch nothing else) instead
    # of rebuilding the page: the sturdy-composition contract.
    import types

    # The week's rows are fetched ONCE, with their joins, and
    # handed to each day: seven contexts used to mean seven
    # scans of the appointments table (plus seven of everything
    # else). Shared kit — members, prices, and one aggregate
    # pass over the week's clients — is computed here, once.
    week_appts = list(
        in_range.select_related(
            "client", "staff_member", "staff_member__staff_level",
            "service", "service__category"
        ).order_by("start")
    )
    client_ids = {row.pk: row.client_id for row in week_appts}
    week_client_ids = {row.client_id for row in week_appts}
    aggregates = (
        {
            row["client_id"]: row
            for row in Appointment.objects.filter(client_id__in=week_client_ids)
            .values("client_id")
            .annotate(n=Count("id"), first=Min("start"))
        }
        if week_client_ids
        else {}
    )
    week_overrides = {}
    for o in ShiftOverride.objects.filter(
        staff_member__in=members, date__gte=week[0], date__lte=week[-1]
    ):
        week_overrides.setdefault(o.date, {})[o.staff_member_id] = o
    week_breaks = list(
        Break.objects.filter(
            staff_member__in=members, start__lt=range_end, end__gt=range_start
        )
    )
    kit_base = {
        "members": members,
        "prices": _price_lookup(salon),
        "aggregates": aggregates,
        # Shared facts the per-day contexts used to re-query
        # seven times each: the salon itself, its categories,
        # the week's overrides and breaks. On a scan-priced
        # store every repeated round trip is real seconds.
        "salon": salon,
        "categories": list(
            ServiceCategory.objects.filter(salon=salon, active=True).order_by(
                "sort_order", "name"
            )
        ),
        "overrides": week_overrides,
        "breaks_week": week_breaks,
    }
    days = {}
    anchor_extra = {}
    for day in week:
        day_lo = datetime.datetime.combine(day, datetime.time.min, tzinfo=tz)
        day_hi = day_lo + datetime.timedelta(days=1)
        kit = dict(
            kit_base,
            day_appts=[
                a for a in week_appts if a.start < day_hi and a.end > day_lo
            ],
        )
        ctx = _day_book_context(
            types.SimpleNamespace(GET={"date": day.isoformat()}),
            light=(day != anchor),
            kit=kit,
        )
        tiles = []
        for col in ctx["staff_columns"]:
            for tile in col["blocks"]:
                tile["_staff_id"] = col["member"].pk
                tiles.append(tile)
        tiles.sort(key=lambda t: (t["_start"], t["appointment_id"]))
        visit_of = _visit_keys(tiles, client_ids)
        entries = [_tile_entry(tile, tz, visit_of) for tile in tiles]
        days[day.isoformat()] = entries
        if day == anchor:
            overview, intel, kpi = ctx["overview"], ctx["intel"], ctx["kpi"]
            anchor_extra = {
                "ribbon": {
                    "revenue_label": overview["revenue_label"],
                    "unpriced": overview["unpriced"],
                    "appointments": overview["appointments"],
                    "visits": overview["visits"],
                    "utilization": overview["utilization"],
                    "avg_ticket_label": kpi["avg_ticket_label"],
                    "new_clients": kpi["new_clients"],
                },
                "intel": {
                    "completed": intel["completed"],
                    "remaining": intel["remaining"],
                    "top_label": intel["top_label"],
                    "next_label": intel["next_label"],
                    "next_sub": intel["next_sub"],
                },
                "agenda": ctx["agenda"],
                "agenda_now_index": ctx["agenda_now_index"],
                "now_label": ctx["now_label"],
                "columns": [
                    {
                        "member": col["member"].pk,
                        "visits_count": col["visits_count"],
                        "day_total_label": col["day_total_label"],
                        "on_duty": col["on_duty"],
                    }
                    for col in ctx["staff_columns"]
                ],
            }
    staff = [
        {
            "id": m.pk,
            "name": m.display_name,
            "initials": _initials(m.display_name),
            "level": m.staff_level.name if m.staff_level_id else "",
        }
        for m in StaffMember.objects.filter(salon=salon, active=True)
        .select_related("staff_level")
        .order_by("display_name")
    ]
    return JsonResponse(
        {
            "pack": 2,
            "changed": True,
            "version": version,
            "week_of": monday.isoformat(),
            "days": days,
            "staff": staff,
            "anchor": anchor_extra,
        }
    )


def _level_rank(level):
    """Price-book column order: Base first, then the named ladder,
    then unassigned price sets, then any raw id a repair has not
    named yet — the page reads like the salon talks."""
    name = level.name or ""
    if name == "Base":
        return (0, "")
    if name.startswith("Unassigned"):
        return (2, name)
    if " " not in name and len(name) >= 16:
        return (3, name)
    return (1, name.lower())


def _level_label(level, seen):
    """The header a level earns on the page: its human name, or —
    for a level still named by a source id (a private key, not a
    public title) — an honest Unassigned label carrying only its
    last four characters. The repair command gives it a real name
    in the data; until then the page never prints the raw id."""
    name = level.name or ""
    if " " not in name and len(name) >= 16:
        label = f"Unassigned ····{name[-4:]}"
    else:
        label = name
    if label in seen:
        seen[label] += 1
        label = f"{label} ({seen[label]})"
    else:
        seen[label] = 1
    return label


def price_book(request):
    salon = Salon.objects.order_by("id").first()
    levels = list(StaffLevel.objects.filter(salon=salon, active=True)) if salon else []
    levels.sort(key=_level_rank)
    seen_labels = {}
    levels = [
        {"pk": level.pk, "label": _level_label(level, seen_labels)}
        for level in levels
    ]
    categories = []
    if salon is not None:
        cats = (
            ServiceCategory.objects.filter(salon=salon, active=True)
            .prefetch_related("services__prices")
            .order_by("sort_order", "name")
        )
        for cat in cats:
            rows = []
            for service in cat.services.all():
                if not service.active:
                    continue
                prices = {p.staff_level_id: p for p in service.prices.all() if p.active}
                rows.append(
                    {
                        "service": service,
                        "duration": _duration_label(service.total_minutes),
                        "cells": [prices.get(level["pk"]) for level in levels],
                    }
                )
            if rows:
                categories.append({"category": cat, "rows": rows})
    context = {"nav_key": "pricebook", "levels": levels, "categories": categories}
    return render(request, "webui/pricebook.html", context)


def clients(request):
    salon = Salon.objects.order_by("id").first()
    query = request.GET.get("q", "").strip()
    page = Paginator([], 1).get_page(1)
    total = 0
    if salon is not None:
        qs = (
            Client.objects.filter(salon=salon, active=True)
            .annotate(note_count=Count("notes"))
            .order_by("last_name", "first_name")
        )
        if query:
            # Every token must land somewhere: "Dawn Davalos" is
            # first AND last — no single field holds both. A token
            # may hit first name, last name, email, or phone.
            for token in query.split():
                qs = qs.filter(
                    Q(first_name__icontains=token)
                    | Q(last_name__icontains=token)
                    | Q(email__icontains=token)
                    | Q(phone__icontains=token)
                )
            digits = "".join(ch for ch in query if ch.isdigit())
            if len(digits) >= 3:
                # Stored phones carry punctuation ("407-555-0100"),
                # so a digit query compares digit-to-digit over a
                # narrowed candidate set — the booking search's rule.
                phone_pks = [
                    c.pk
                    for c in Client.objects.filter(
                        salon=salon, phone__icontains=digits[:3]
                    )[:500]
                    if digits
                    in "".join(ch for ch in (c.phone or "") if ch.isdigit())
                ]
                if phone_pks:
                    matched = {c.pk for c in qs} | set(phone_pks)
                    qs = (
                        Client.objects.filter(
                            salon=salon, active=True, pk__in=matched
                        )
                        .annotate(note_count=Count("notes"))
                        .order_by("last_name", "first_name")
                    )
        total = qs.count()
        page = Paginator(qs, 30).get_page(request.GET.get("page"))
    context = {"nav_key": "clients", "page": page, "query": query, "total": total}
    return render(request, "webui/clients.html", context)


def team(request):
    """Team & Roster: the week matrix the day book measures against.

    Patterns are the roster. The matrix renders the salon's real
    RosterPattern rows for the current week (via the team app's
    roster-week service); the editor below it adds and removes
    patterns, and every day-book number that depends on the
    roster — utilization, openings, on-duty columns — follows.
    """
    salon = Salon.objects.order_by("id").first()
    message = ""
    if request.method == "POST" and salon is not None:
        action = request.POST.get("action")
        if action == "add":
            member = StaffMember.objects.filter(
                pk=request.POST.get("member"), salon=salon, active=True
            ).first()
            try:
                weekday = int(request.POST.get("weekday", ""))
                start = datetime.datetime.strptime(
                    request.POST.get("start", ""), "%H:%M"
                ).time()
                end = datetime.datetime.strptime(
                    request.POST.get("end", ""), "%H:%M"
                ).time()
            except ValueError:
                member = None
            if member is not None and 0 <= weekday <= 6 and end > start:
                RosterPattern.objects.get_or_create(
                    staff_member=member,
                    weekday=weekday,
                    start_time=start,
                    end_time=end,
                )
                message = "Pattern added — the day book now measures against it."
            else:
                message = "Check the pattern: pick a stylist, a day, and an end after the start."
        elif action == "delete":
            RosterPattern.objects.filter(
                pk=request.POST.get("pattern"), staff_member__salon=salon
            ).delete()
            message = "Pattern removed."
        elif action == "set_pin":
            member = StaffMember.objects.filter(
                pk=request.POST.get("member"), salon=salon, active=True
            ).first()
            pin = (request.POST.get("pin") or "").strip()
            if member is None:
                message = "Pick a team member first."
            elif pin == "":
                member.pin = ""
                member.save(update_fields=["pin"])
                message = (
                    f"{member.display_name}'s PIN is cleared — they can't use "
                    "the time clock until a new one is set."
                )
            elif not pin.isdigit() or not 4 <= len(pin) <= 8:
                message = "A PIN is 4 to 8 digits — birthdays work well (day and year)."
            else:
                holder = (
                    StaffMember.objects.filter(salon=salon, pin=pin)
                    .exclude(pk=member.pk)
                    .first()
                )
                if holder is not None:
                    message = (
                        f"That PIN is already {holder.display_name}'s — every "
                        "PIN has to be unique, or the clock can't tell you apart."
                    )
                else:
                    member.pin = pin
                    member.save(update_fields=["pin"])
                    message = f"PIN set for {member.display_name}."
    rows, patterns, members = [], [], []
    week_label = ""
    if salon is not None:
        tz = _tz(salon)
        today = timezone.now().astimezone(tz).date()
        monday = today - datetime.timedelta(days=today.weekday())
        week = build_roster_week(salon, monday)
        week_label = (
            f"{_fmt_date_label(monday)} – {_fmt_date_label(monday + datetime.timedelta(days=6))}"
        )
        for entry in week.entries:
            cells = []
            for avail in entry.days:
                label = ", ".join(
                    f"{_fmt_time(iv.start.astimezone(tz).time())} – "
                    f"{_fmt_time(iv.end.astimezone(tz).time())}"
                    for iv in avail.intervals
                )
                cells.append(label)
            rows.append(
                {
                    "member": entry.staff_member,
                    "initials": _initials(entry.staff_member.display_name),
                    "level_name": entry.staff_member.staff_level.name
                    if entry.staff_member.staff_level_id
                    else "",
                    "cells": cells,
                    "hours_label": _duration_label(entry.total_minutes)
                    if entry.total_minutes
                    else "—",
                }
            )
        patterns = list(
            RosterPattern.objects.filter(staff_member__salon=salon)
            .select_related("staff_member")
            .order_by("staff_member__display_name", "weekday", "start_time")
        )
        members = list(
            StaffMember.objects.filter(salon=salon, active=True).order_by("display_name")
        )
    return render(
        request,
        "webui/roster.html",
        {
            "nav_key": "team",
            "salon": salon,
            "rows": rows,
            "patterns": patterns,
            "members": members,
            "weekday_choices": RosterPattern.Weekday.choices,
            "week_label": week_label,
            "message": message,
        },
    )


def _clock_member(salon, pin):
    """The one member a time-clock PIN names, or None.

    PINs are unique per salon among non-blank values, so a match is
    unambiguous. A blank PIN never matches: a member with no PIN set
    cannot use the clock.
    """
    pin = (pin or "").strip()
    if not pin or salon is None:
        return None
    return StaffMember.objects.filter(salon=salon, pin=pin, active=True).first()


def _clock_payload(member, tz):
    latest = member.attendance_records.first()
    clocked_in = (
        latest is not None
        and latest.event_type == AttendanceRecord.EventType.CHECK_IN
    )
    return {
        "ok": True,
        "member": member.display_name,
        "initials": _initials(member.display_name),
        "clocked_in": clocked_in,
        "since": (
            _fmt_time(latest.recorded_at.astimezone(tz).time())
            if clocked_in
            else None
        ),
        "action": "Clock out" if clocked_in else "Clock in",
    }


@require_POST
def clock_status(request):
    """Time clock, step one: a PIN names its owner and reports their
    standing — clocked in (and since when) or clocked out. A wrong
    PIN gets one generic answer; the clock never says who exists."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
        pin = str(payload["pin"])
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "bad payload"}, status=400)
    salon = Salon.objects.order_by("id").first()
    member = _clock_member(salon, pin)
    if member is None:
        return JsonResponse(
            {"ok": False, "error": "That PIN doesn't match anyone on the team."},
            status=400,
        )
    return JsonResponse(_clock_payload(member, _tz(salon)))


@require_POST
def clock_toggle(request):
    """Time clock, step two: record the one event opposite to the
    member's current standing, on the AttendanceRecord event log —
    the same log the rest of the app derives status from."""
    try:
        payload = json.loads(request.body.decode("utf-8"))
        pin = str(payload["pin"])
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "bad payload"}, status=400)
    salon = Salon.objects.order_by("id").first()
    member = _clock_member(salon, pin)
    if member is None:
        return JsonResponse(
            {"ok": False, "error": "That PIN doesn't match anyone on the team."},
            status=400,
        )
    event = (
        AttendanceRecord.EventType.CHECK_OUT
        if member.is_checked_in()
        else AttendanceRecord.EventType.CHECK_IN
    )
    AttendanceRecord.objects.create(staff_member=member, event_type=event)
    result = _clock_payload(member, _tz(salon))
    result["just"] = (
        "in" if event == AttendanceRecord.EventType.CHECK_IN else "out"
    )
    return JsonResponse(result)


def placeholder(request, nav_key, title, lane_note):
    return render(
        request,
        "webui/placeholder.html",
        {"nav_key": nav_key, "title": title, "lane_note": lane_note},
    )


def _rb_place(member, day, weekly, start, end):
    """One place play under the switch law: ON writes the
    perpetual pattern, OFF rules just this date. A weekly
    place returns the pattern's pk — the roster store chains
    later plays (a move, a removal) onto it by that id."""
    if weekly:
        pat, _created = RosterPattern.objects.get_or_create(
            staff_member=member, weekday=day.weekday(),
            start_time=start, end_time=end,
        )
        return pat.pk
    ShiftOverride.objects.update_or_create(
        staff_member=member, date=day,
        defaults={
            "is_off": False, "start_time": start, "end_time": end,
        },
    )
    return True


def _rb_move(member, day, weekly, pattern_pk, start, end):
    """One move play: a pattern retimed (weekly) or the date's
    override rewritten (instance)."""
    if weekly:
        pat = RosterPattern.objects.filter(
            pk=pattern_pk, staff_member=member
        ).first()
        if pat is None:
            return False
        pat.start_time, pat.end_time = start, end
        pat.save(update_fields=["start_time", "end_time"])
        return pat.pk
    ShiftOverride.objects.update_or_create(
        staff_member=member, date=day,
        defaults={"is_off": False, "start_time": start, "end_time": end},
    )
    return True


def _rb_off(member, day, weekly, pattern_pk):
    """One off play: the pattern deleted (weekly) or the date
    ruled off by an override (instance)."""
    if weekly:
        RosterPattern.objects.filter(
            pk=pattern_pk, staff_member=member
        ).delete()
    else:
        ShiftOverride.objects.update_or_create(
            staff_member=member, date=day,
            defaults={
                "is_off": True, "start_time": None, "end_time": None,
            },
        )
    return True


def _rb_clear(member, day):
    """One clear play: the date's override goes; the pattern
    speaks for the date again."""
    ShiftOverride.objects.filter(staff_member=member, date=day).delete()
    return True


def roster_book(request):
    """The Roster Book — the day book's perpetual controller.

    A day book clone perceived differently: the blocks are HOURS,
    not guests. The manager walks any week — patterns are perpetual,
    they project onto every future week until flipped — and places
    hours with a switch: ON writes the perpetual RosterPattern (every
    week, forever); OFF writes a ShiftOverride that rules just that
    one date. The day book and online booking read the same
    resolution (override first, pattern otherwise), so what is
    flipped here is what both books obey.
    """
    salon = Salon.objects.order_by("id").first()
    tz = _tz(salon) if salon is not None else timezone.get_current_timezone()
    today = timezone.now().astimezone(tz).date()

    if request.method == "POST" and salon is not None:
        try:
            day = datetime.date.fromisoformat(request.POST.get("date", ""))
        except ValueError:
            day = today
        member = StaffMember.objects.filter(
            pk=request.POST.get("member"), salon=salon, active=True
        ).first()
        weekly = request.POST.get("weekly") == "on"
        action = request.POST.get("action")
        if member is not None and action in ("place", "move"):
            try:
                start = datetime.datetime.strptime(
                    request.POST.get("start", ""), "%H:%M"
                ).time()
                end = datetime.datetime.strptime(
                    request.POST.get("end", ""), "%H:%M"
                ).time()
            except ValueError:
                start = end = None
            if start is not None and end > start:
                if action == "place":
                    _rb_place(member, day, weekly, start, end)
                else:
                    _rb_move(
                        member, day, weekly,
                        request.POST.get("pattern"), start, end,
                    )
        elif member is not None and action == "off":
            _rb_off(member, day, weekly, request.POST.get("pattern"))
        elif member is not None and action == "clear":
            _rb_clear(member, day)
        return redirect(f"{reverse('webui:roster')}?date={day.isoformat()}")

    try:
        day = datetime.date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        day = today
    monday = day - datetime.timedelta(days=day.weekday())
    week = [monday + datetime.timedelta(days=i) for i in range(7)]
    members = (
        list(salon.staff_members.filter(active=True).order_by("display_name"))
        if salon is not None else []
    )
    patterns = {}
    for pat in RosterPattern.objects.filter(
        staff_member__in=members, weekday=day.weekday(), active=True
    ):
        patterns.setdefault(pat.staff_member_id, []).append(pat)
    overrides = {
        o.staff_member_id: o
        for o in ShiftOverride.objects.filter(staff_member__in=members, date=day)
    }
    day_start = datetime.datetime.combine(
        day, datetime.time(DAY_START_HOUR), tzinfo=tz
    )
    day_end = datetime.datetime.combine(day, datetime.time(DAY_END_HOUR), tzinfo=tz)
    hours = [
        {
            "label": _fmt_time(datetime.time(h)),
            "top": _pct(
                datetime.datetime.combine(day, datetime.time(h), tzinfo=tz),
                day_start, day_end,
            ),
        }
        for h in range(DAY_START_HOUR, DAY_END_HOUR)
    ]

    def block(start_t, end_t, source, pattern_id=None):
        sdt = datetime.datetime.combine(day, start_t, tzinfo=tz)
        edt = datetime.datetime.combine(day, end_t, tzinfo=tz)
        top = _pct(sdt, day_start, day_end)
        return {
            "top": top,
            "height": _pct(edt, day_start, day_end) - top,
            "label": f"{_fmt_time(start_t)} – {_fmt_time(end_t)}",
            "source": source,
            "pattern_id": pattern_id,
            "start": start_t.strftime("%H:%M"),
            "end": end_t.strftime("%H:%M"),
        }

    avatar_pairs = [
        ("5eead4", "34d399"), ("c4b5fd", "f0abfc"), ("93c5fd", "818cf8"),
        ("fda4af", "fbbf24"), ("6ee7b7", "2dd4bf"), ("a5b4fc", "38bdf8"),
    ]
    columns = []
    for idx, member in enumerate(members):
        ov = overrides.get(member.pk)
        windows = []
        if ov is not None:
            if not ov.is_off:
                windows.append((ov.start_time, ov.end_time, "instance", None))
        else:
            windows = [
                (p.start_time, p.end_time, "weekly", p.pk)
                for p in patterns.get(member.pk, [])
            ]
        total_minutes = sum(
            int(
                (
                    datetime.datetime.combine(day, e)
                    - datetime.datetime.combine(day, s)
                ).total_seconds()
            )
            // 60
            for s, e, _src, _pid in windows
        )
        av1, av2 = avatar_pairs[idx % len(avatar_pairs)]
        columns.append(
            {
                "member": member,
                "blocks": [
                    block(s, e, src, pid) for s, e, src, pid in windows
                ],
                "is_off": ov is not None and ov.is_off,
                "has_override": ov is not None,
                "initials": _initials(member.display_name),
                "av_style": f"--av1:#{av1};--av2:#{av2}",
                "hours_label": _duration_label(total_minutes)
                if total_minutes
                else "",
            }
        )
    def _mins(t):
        return t.hour * 60 + t.minute if t is not None else None

    # The roster store's hydration seed: the same patterns and
    # overrides this page renders, in minutes — the embedded
    # store takes the book's state from here at boot (HTTP is
    # the recovery), and every gesture after that is a store
    # play that drains to the apply endpoint.
    roster_seed = {
        "date": day.isoformat(),
        "weekday": day.weekday(),
        "patterns": [
            {
                "id": p.pk,
                "member": p.staff_member_id,
                "start_min": _mins(p.start_time),
                "end_min": _mins(p.end_time),
            }
            for member_patterns in patterns.values()
            for p in member_patterns
        ],
        "overrides": {
            str(member_pk): {
                "is_off": o.is_off,
                "start_min": _mins(o.start_time),
                "end_min": _mins(o.end_time),
            }
            for member_pk, o in overrides.items()
        },
        "apply_url": reverse("webui:roster_apply"),
    }
    return render(
        request,
        "webui/roster_book.html",
        {
            "salon": salon,
            "nav_key": "roster",
            "day": day,
            "today": today,
            "week": [
                {"date": d, "current": d == day, "today": d == today}
                for d in week
            ],
            "prev_week": (day - datetime.timedelta(days=7)).isoformat(),
            "next_week": (day + datetime.timedelta(days=7)).isoformat(),
            "hours": hours,
            "columns": columns,
            "roster_seed": roster_seed,
        },
    )


def _rb_apply_one(salon, op):
    """One roster play from the bulk endpoint: validated,
    applied through the same cores the form posts use, and
    answered on its own — a bad play never poisons its batch."""
    if not isinstance(op, dict):
        return {"ok": False, "error": "bad op"}
    member = StaffMember.objects.filter(
        pk=op.get("member"), salon=salon, active=True
    ).first()
    if member is None:
        return {"ok": False, "error": "unknown staff member"}
    try:
        day = datetime.date.fromisoformat(str(op.get("date", "")))
    except ValueError:
        return {"ok": False, "error": "bad date"}
    weekly = bool(op.get("weekly"))
    kind = op.get("kind")
    if kind in ("place", "move"):
        try:
            start = datetime.datetime.strptime(
                str(op.get("start", "")), "%H:%M"
            ).time()
            end = datetime.datetime.strptime(
                str(op.get("end", "")), "%H:%M"
            ).time()
        except ValueError:
            return {"ok": False, "error": "bad times"}
        if end <= start:
            return {"ok": False, "error": "end must follow start"}
        applied = (
            _rb_place(member, day, weekly, start, end)
            if kind == "place"
            else _rb_move(member, day, weekly, op.get("pattern"), start, end)
        )
    elif kind == "off":
        applied = _rb_off(member, day, weekly, op.get("pattern"))
    elif kind == "clear":
        applied = _rb_clear(member, day)
    else:
        return {"ok": False, "error": "unknown kind"}
    if not applied:
        return {"ok": False, "error": "not applied"}
    result = {"ok": True}
    if isinstance(applied, int) and not isinstance(applied, bool):
        # A weekly place/move names its pattern, so the store
        # can chain the next play onto the real id at once.
        result["pattern"] = applied
    return result


@require_POST
def roster_apply(request):
    """Roster plays in bulk — the roster book's drain target,
    sibling to the day book's apply.

    The roster book's gestures will record their plays in the
    embedded store first and drain here on their own schedule,
    exactly as day-book plays drain to /daybook/apply/: this
    endpoint is the node's half of that chain, speaking the
    same per-op results so a rejected play converges the desk
    without taking its batch down with it. The switch law
    rides in every op (`weekly`): ON writes the perpetual
    pattern, OFF rules just the date."""
    salon = _first_salon()
    if salon is None:
        return JsonResponse({"results": []})
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "bad payload"}, status=400)
    ops = data.get("ops")
    if not isinstance(ops, list):
        return JsonResponse({"ok": False, "error": "bad payload"}, status=400)
    chain, chain_ok = _chain_echo(data)
    return JsonResponse(
        {
            "results": [_rb_apply_one(salon, op) for op in ops],
            "chain": chain,
            "chain_ok": chain_ok,
        }
    )


def pos(request):
    """Point of Sale — the till's home: today's takings and Cashup.

    The day book settles visits; this page counts the drawer. It
    reads the checkout lane's own law: compute_tender_totals for the
    live day-so-far, run_cashup for the snapshot. A cashup is a
    snapshot, not a lock — closing more than once a day is fine and
    later sales are simply counted by the next one.
    """
    from checkout.cashup import compute_tender_totals, run_cashup
    from checkout.models import Cashup, Payment, Sale

    salon = Salon.objects.order_by("id").first()
    tz = _tz(salon) if salon is not None else timezone.get_current_timezone()
    now = timezone.now().astimezone(tz)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if request.method == "POST" and salon is not None:
        if request.POST.get("action") == "cashup":
            run_cashup(salon, day_start, timezone.now())
        return redirect("webui:pos")

    tender_rows, day_total = [], Decimal("0")
    sales_rows, cashups = [], []
    if salon is not None:
        labels = dict(Payment.Method.choices)
        totals = compute_tender_totals(salon, day_start, timezone.now())
        for method, amount in totals.items():
            tender_rows.append(
                {"label": labels.get(method, method), "amount": amount}
            )
            day_total += amount
        sales = (
            Sale.objects.filter(
                salon=salon,
                status=Sale.Status.COMPLETED,
                completed_at__gte=day_start,
            )
            .select_related("client")
            .prefetch_related("items", "payments", "receipt")
            .order_by("-completed_at")
        )
        for sale in sales:
            tender = ", ".join(
                sorted(
                    {
                        labels.get(p.method, p.method)
                        for p in sale.payments.all()
                        if p.status == Payment.Status.COMPLETED
                    }
                )
            )
            receipt = getattr(sale, "receipt", None)
            sales_rows.append(
                {
                    "sale": sale,
                    "when": sale.completed_at.astimezone(tz) if sale.completed_at else None,
                    "client_name": str(sale.client) if sale.client_id else "",
                    "client_email": sale.client.email if sale.client_id else "",
                    "receipt_sent": bool(receipt and receipt.sent_at),
                    "tender": tender,
                    "total": sale.total,
                }
            )
        for cu in Cashup.objects.filter(salon=salon, created_at__gte=day_start):
            breakdown = ", ".join(
                f"{labels.get(m, m)} {_money_label(Decimal(v))}"
                for m, v in cu.tender_totals.items()
            )
            cashups.append(
                {
                    "cashup": cu,
                    "when": cu.created_at.astimezone(tz),
                    "breakdown": breakdown,
                }
            )
    return render(
        request,
        "webui/pos.html",
        {
            "salon": salon,
            "nav_key": "pos",
            "today": now.date(),
            "tender_rows": tender_rows,
            "day_total": day_total,
            "sales_rows": sales_rows,
            "cashups": cashups,
        },
    )


def products_page(request):
    """The Shelf — the salon's products, stock, and receiving.

    Reads the catalog lane's own law: search_products to find,
    stock derived from the movement log (one aggregate, never a
    stored counter), adjust_stock for corrections (its negative
    guard is the law). Receiving appends a RECEIVE movement — the
    same movement the importer and the till write. The search box
    is autofocused: a keyboard-wedge scanner types into it like a
    keyboard, so scan-to-find works with no special hardware path.
    """
    from django.db.models import Sum

    from catalog.adjust import adjust_stock
    from catalog.models import Product, StockMovement
    from catalog.search import search_products

    salon = Salon.objects.order_by("id").first()
    if request.method == "POST" and salon is not None:
        product = Product.objects.filter(
            pk=request.POST.get("product"), salon=salon
        ).first()
        if product is not None:
            action = request.POST.get("action")
            if action == "receive":
                try:
                    qty = int(request.POST.get("qty", "1"))
                except ValueError:
                    qty = 0
                if qty > 0:
                    StockMovement.objects.create(
                        product=product,
                        kind=StockMovement.Kind.RECEIVE,
                        quantity_delta=qty,
                        note="Received at the shelf",
                    )
            elif action == "adjust":
                try:
                    delta = int(request.POST.get("delta", "0"))
                except ValueError:
                    delta = 0
                reason = request.POST.get("reason", "").strip()
                if delta != 0 and reason:
                    try:
                        adjust_stock(product, delta, reason)
                    except ValueError:
                        pass  # the guard refused (would go negative)
        return redirect("webui:products")

    query = request.GET.get("q", "").strip()
    rows, total = [], 0
    if salon is not None:
        found = (
            search_products(salon, query)
            if query
            else Product.objects.filter(salon=salon, active=True).order_by("name")
        )
        found = list(found)
        total = len(found)
        page = found[:100]
        stock = {
            row["product_id"]: row["s"]
            for row in StockMovement.objects.filter(product__in=page)
            .values("product_id")
            .annotate(s=Sum("quantity_delta"))
        }
        for product in page:
            qty = stock.get(product.pk, 0)
            rows.append(
                {
                    "product": product,
                    "stock": qty,
                    "flag": "Out" if qty <= 0 else ("Low" if qty <= 2 else ""),
                }
            )
    return render(
        request,
        "webui/products.html",
        {
            "salon": salon,
            "nav_key": "products",
            "query": query,
            "rows": rows,
            "total": total,
            "shown": len(rows),
        },
    )


REPORT_PRESETS = [
    ("today", "Today"),
    ("7d", "Last 7 days"),
    ("30d", "Last 30 days"),
    ("month", "This month"),
    ("lastmonth", "Last month"),
    ("custom", "Custom range"),
]


def _report_range(request, today):
    """Resolve the reports' date range from the query string.

    Presets anchor on the salon's today; ``custom`` reads
    ``start``/``end`` ISO dates and falls back to the last 30
    days when they don't parse. The range is whole local days,
    inclusive at both ends, and capped at a year so a typo can't
    ask the till for a decade.
    """
    preset = request.GET.get("preset", "30d")
    if preset not in dict(REPORT_PRESETS):
        preset = "30d"
    if preset == "today":
        start = end = today
    elif preset == "7d":
        start, end = today - datetime.timedelta(days=6), today
    elif preset == "month":
        start = today.replace(day=1)
        end = today
    elif preset == "lastmonth":
        end = today.replace(day=1) - datetime.timedelta(days=1)
        start = end.replace(day=1)
    elif preset == "custom":
        try:
            start = datetime.date.fromisoformat(request.GET.get("start", ""))
            end = datetime.date.fromisoformat(request.GET.get("end", ""))
        except ValueError:
            start, end = today - datetime.timedelta(days=29), today
    else:  # 30d
        start, end = today - datetime.timedelta(days=29), today
    if end < start:
        start, end = end, start
    if (end - start).days > 365:
        start = end - datetime.timedelta(days=365)
    return start, end, preset


def _insights_report(salon, start, end):
    """Every figure on the Insights page for one date range.

    The accounting reads the checkout lane's own services — the
    same numbers the exports print, never a second arithmetic:
    the date-wise ledger sums ``daily_sales_summary`` day by day
    with ``refund_totals`` laid over it; tenders come from
    ``totals_by_tender``; staff from ``revenue_by_staff``;
    cashups from ``cashup_history``. The audit sections read the
    append-only records themselves: ``PriceChange`` rows and the
    ``ReminderSend`` log. One builder feeds the page and the CSV
    downloads, so the two can never disagree.
    """
    from checkout.cashup_history import cashup_history
    from checkout.models import Payment, Sale
    from checkout.refund_report import refund_totals
    from checkout.summary import daily_sales_summary
    from checkout.tender_totals import tender_totals
    from insights.services import busiest_days, future_appointments_value
    from insights.staff_revenue import revenue_by_staff
    from messaging.models import ReminderSend
    from saloncore.models import PriceChange

    tz = _tz(salon)
    refunds = refund_totals(salon, start, end)
    ledger = []
    day = start
    while day <= end:
        summary = daily_sales_summary(salon, day)
        refunded = refunds.by_day.get(day)
        refund_amount = refunded.total if refunded else Decimal("0")
        ledger.append(
            {
                "day": day,
                "count": summary.sales_count,
                "service": summary.service_total,
                "retail": summary.retail_total,
                "gross": summary.gross_total,
                "refunds": refund_amount,
                "net": summary.gross_total - refund_amount,
            }
        )
        day += datetime.timedelta(days=1)
    totals = {
        "count": sum(r["count"] for r in ledger),
        "service": sum((r["service"] for r in ledger), Decimal("0")),
        "retail": sum((r["retail"] for r in ledger), Decimal("0")),
        "gross": sum((r["gross"] for r in ledger), Decimal("0")),
        "refunds": sum((r["refunds"] for r in ledger), Decimal("0")),
        "net": sum((r["net"] for r in ledger), Decimal("0")),
    }
    totals["avg_ticket"] = (
        totals["gross"] / totals["count"] if totals["count"] else Decimal("0")
    )

    tenders = tender_totals(start, end, salon)
    method_labels = dict(Payment.Method.choices)
    tender_rows = [
        {
            "method": method,
            "label": method_labels.get(method, method),
            "amount": amount,
        }
        for method, amount in sorted(tenders.by_method.items())
    ]

    staff_rows = [
        {"display_name": r.display_name, "total": r.total}
        for r in revenue_by_staff(salon, start, end)
    ]

    history = cashup_history(salon, start, end)
    cashup_rows = [
        {
            "when": entry.cashup.created_at,
            "period_start": entry.cashup.period_start,
            "period_end": entry.cashup.period_end,
            "total": entry.total,
            "variance": entry.variance,
        }
        for entry in history.entries
    ]

    day_start = datetime.datetime.combine(start, datetime.time.min, tzinfo=tz)
    day_end = datetime.datetime.combine(
        end + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz
    )
    price_changes = list(
        PriceChange.objects.filter(
            service_price__service__category__salon=salon,
            changed_at__gte=day_start,
            changed_at__lt=day_end,
        )
        .select_related(
            "service_price__service", "service_price__staff_level"
        )
        .order_by("-changed_at", "-id")[:100]
    )
    sends = ReminderSend.objects.filter(
        appointment__staff_member__salon=salon,
        sent_at__gte=day_start,
        sent_at__lt=day_end,
    )
    send_counts = {
        row["channel"]: row["n"]
        for row in sends.values("channel").annotate(n=Count("id"))
    }
    send_rows = list(
        sends.select_related("client", "appointment")
        .order_by("-sent_at", "-id")[:20]
    )

    register = list(
        Sale.objects.filter(salon=salon)
        .exclude(status=Sale.Status.VOIDED)
        .filter(
            Q(completed_at__gte=day_start, completed_at__lt=day_end)
            | Q(
                completed_at__isnull=True,
                created_at__gte=day_start,
                created_at__lt=day_end,
            )
        )
        .select_related("client")
        .prefetch_related("items", "payments")
        .order_by("-id")
    )

    future = future_appointments_value(salon)
    busiest = sorted(
        busiest_days(salon, start, end),
        key=lambda b: (-b.count, b.weekday),
    )
    return {
        "ledger": ledger,
        "totals": totals,
        "refund_count": refunds.refund_count,
        "tender_rows": tender_rows,
        "tender_total": tenders.total,
        "tender_count": tenders.count,
        "staff_rows": staff_rows,
        "cashup_rows": cashup_rows,
        "cashup_summary": history.summary,
        "price_changes": price_changes,
        "send_counts": send_counts,
        "send_rows": send_rows,
        "register": register,
        "future": future,
        "busiest": busiest,
    }


def insights_page(request):
    """Insights — the salon's reports, date-wise.

    The founder's shape: professional insights AND reports, for
    auditing everything and accounting everything, kept date
    wise. One range drives the whole page: the accounting
    ledger by day, tenders, staff revenue, cashups, and the
    audit trails (price changes, reminder sends, the sales
    register) all read the same window, and each section's CSV
    download prints exactly what the section shows.
    """
    salon = Salon.objects.order_by("id").first()
    ctx = {"salon": salon, "nav_key": "insights"}
    if salon is not None:
        tz = _tz(salon)
        today = timezone.now().astimezone(tz).date()
        start, end, preset = _report_range(request, today)
        report = _insights_report(salon, start, end)
        future = report["future"]
        ctx.update(
            {
                "today": today,
                "range_start": start,
                "range_end": end,
                "preset": preset,
                "presets": REPORT_PRESETS,
                "ledger": [
                    dict(
                        row,
                        service_label=_money_label(row["service"]),
                        retail_label=_money_label(row["retail"]),
                        gross_label=_money_label(row["gross"]),
                        refunds_label=_money_label(row["refunds"]),
                        net_label=_money_label(row["net"]),
                    )
                    for row in reversed(report["ledger"])
                ],
                "totals": report["totals"],
                "total_service_label": _money_label(report["totals"]["service"]),
                "total_retail_label": _money_label(report["totals"]["retail"]),
                "total_gross_label": _money_label(report["totals"]["gross"]),
                "total_refunds_label": _money_label(report["totals"]["refunds"]),
                "total_net_label": _money_label(report["totals"]["net"]),
                "avg_ticket_label": _money_label(report["totals"]["avg_ticket"]),
                "refund_count": report["refund_count"],
                "tender_rows": [
                    dict(row, label_amount=_money_label(row["amount"]))
                    for row in report["tender_rows"]
                ],
                "tender_total_label": _money_label(report["tender_total"]),
                "tender_count": report["tender_count"],
                "staff_rows": [
                    dict(row, total_label=_money_label(row["total"]))
                    for row in report["staff_rows"]
                ],
                "cashup_rows": [
                    dict(
                        row,
                        total_label=_money_label(row["total"]),
                        variance_label=(
                            _money_label(row["variance"])
                            if row["variance"] is not None
                            else "—"
                        ),
                    )
                    for row in report["cashup_rows"]
                ],
                "cashup_count": report["cashup_summary"].count,
                "cashup_total_label": _money_label(report["cashup_summary"].total),
                "price_changes": report["price_changes"],
                "send_counts": report["send_counts"],
                "send_rows": report["send_rows"],
                "register": report["register"][:50],
                "register_count": len(report["register"]),
                "future_total_label": _money_label(future.total),
                "future": future,
                "future_days": [
                    {"day": d.day, "count": d.count,
                     "label": _money_label(d.value)}
                    for d in future.days
                ],
                "busiest": [
                    {
                        "weekday_name": b.weekday_name,
                        "count": b.count,
                        "revenue_label": _money_label(b.revenue),
                    }
                    for b in report["busiest"]
                ],
            }
        )
    return render(request, "webui/insights.html", ctx)


def insights_export(request, kind):
    """CSV twin of one Insights section, same range, same rows.

    The downloads read through the very builder the page uses,
    so a report handed to an accountant is the page's own
    numbers in a spreadsheet's shape — never a second query
    that could drift from what the desk saw.
    """
    import csv
    import io

    from django.http import HttpResponse

    salon = Salon.objects.order_by("id").first()
    if salon is None:
        return redirect("webui:insights")
    tz = _tz(salon)
    today = timezone.now().astimezone(tz).date()
    start, end, _preset = _report_range(request, today)
    report = _insights_report(salon, start, end)
    stamp = f"{start.isoformat()}_{end.isoformat()}"

    def money(value):
        return f"{value:.2f}" if value is not None else ""

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    if kind == "ledger":
        writer.writerow(["date", "sales", "services", "retail", "gross", "refunds", "net"])
        for row in report["ledger"]:
            writer.writerow([
                row["day"].isoformat(), row["count"], money(row["service"]),
                money(row["retail"]), money(row["gross"]),
                money(row["refunds"]), money(row["net"]),
            ])
    elif kind == "tenders":
        writer.writerow(["tender", "amount"])
        for row in report["tender_rows"]:
            writer.writerow([row["label"], money(row["amount"])])
    elif kind == "staff":
        writer.writerow(["staff", "revenue"])
        for row in report["staff_rows"]:
            writer.writerow([row["display_name"], money(row["total"])])
    elif kind == "register":
        writer.writerow(["sale", "when", "client", "status", "items", "total", "tenders"])
        for sale in report["register"]:
            when = sale.completed_at or sale.created_at
            writer.writerow([
                sale.pk,
                when.astimezone(tz).strftime("%Y-%m-%d %H:%M") if when else "",
                str(sale.client) if sale.client_id else "",
                sale.status,
                sale.items.count(),
                money(sale.total),
                ";".join(
                    f"{p.get_method_display()} {money(p.amount)}"
                    for p in sale.payments.all()
                ),
            ])
    elif kind == "prices":
        writer.writerow(["when", "service", "level", "old", "new", "changed_by", "note"])
        for change in report["price_changes"]:
            price = change.service_price
            writer.writerow([
                change.changed_at.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
                str(price.service), str(price.staff_level),
                money(change.old_amount), money(change.new_amount),
                change.changed_by, change.note,
            ])
    elif kind == "cashups":
        writer.writerow(["closed_at", "period_start", "period_end", "total", "variance"])
        for row in report["cashup_rows"]:
            writer.writerow([
                row["when"].astimezone(tz).strftime("%Y-%m-%d %H:%M"),
                row["period_start"].astimezone(tz).strftime("%Y-%m-%d %H:%M"),
                row["period_end"].astimezone(tz).strftime("%Y-%m-%d %H:%M"),
                money(row["total"]), money(row["variance"]),
            ])
    else:
        return redirect("webui:insights")
    response = HttpResponse(buffer.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="opensalon-{kind}-{stamp}.csv"'
    )
    return response


def day_book_receipt_email(request):
    """Email a settled sale's receipt to the client.

    The send itself is the checkout lane's law (send_receipt): the
    salon's own mail settings carry it, the recipient defaults to
    the client's email on record, and the receipt records who it
    went to and when. Two callers: the checkout modal (JSON, with an
    optional typed override address) and the POS page's per-sale
    form (plain POST, redirect back).
    """
    from checkout.models import Sale
    from checkout.receipts import build_receipt, send_receipt

    salon = Salon.objects.order_by("id").first()
    web = request.POST.get("web") == "pos"
    if web:
        sale_id = request.POST.get("sale_id")
        email = ""
    else:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return JsonResponse(
                {"ok": False, "error": "bad payload"}, status=400
            )
        sale_id = payload.get("sale_id")
        email = (payload.get("email") or "").strip()
    sale = (
        Sale.objects.select_related("client")
        .filter(pk=sale_id, salon=salon, status=Sale.Status.COMPLETED)
        .first()
    )
    if sale is None:
        if web:
            return redirect("webui:pos")
        return JsonResponse(
            {"ok": False, "error": "no such sale"}, status=404
        )
    receipt = getattr(sale, "receipt", None) or build_receipt(sale)
    try:
        send_receipt(receipt, email or None)
    except ValueError as exc:
        if web:
            return redirect("webui:pos")
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except Exception:
        if web:
            return redirect("webui:pos")
        return JsonResponse(
            {"ok": False, "error": "The mail server could not send it."},
            status=502,
        )
    if web:
        return redirect("webui:pos")
    return JsonResponse({"ok": True, "sent_to": receipt.recipient_email})
