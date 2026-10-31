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
import json
from decimal import Decimal, InvalidOperation

from django.core.paginator import Paginator
from django.db.models import Count, Max, Min, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from bookings.availability import _tz
from bookings.daybook import blocks_for_day as feed_blocks_for_day
from bookings.models import Appointment, AppointmentNote
from clients.models import Client, ClientNote
from saloncore.models import Salon, Service, ServiceCategory, ServicePrice, StaffLevel
from team.models import RosterPattern, StaffMember
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
    salon = Salon.objects.order_by("id").first()
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
        categories = list(
            ServiceCategory.objects.filter(salon=salon, active=True).order_by(
                "sort_order", "name"
            )
        )
        kit = kit or {}
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
                    "client", "staff_member", "service", "service__category"
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

        block_index = 0
        total_booked, total_roster, total_openings = 0.0, 0.0, 0
        revenue, unpriced = Decimal("0"), 0
        for member in members:
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
            booked_minutes = _union_minutes(clipped)
            booked_pct = None
            if roster_minutes:
                booked_pct = min(100, int(booked_minutes / roster_minutes * 100 + 0.5))
                total_booked += booked_minutes
                total_roster += roster_minutes
                for band in bands:
                    in_span = [
                        (max(s, band["_start"]), min(e, band["_end"]))
                        for s, e in clipped
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
        {"ok": all(r["ok"] for r in results), "results": results}
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
    """Find a client for the booking form: name tokens or phone."""
    salon = _first_salon()
    q = (request.GET.get("q") or "").strip()
    if salon is None or len(q) < 2:
        return JsonResponse({"clients": []})
    qs = Client.objects.filter(salon=salon)
    digits = "".join(ch for ch in q if ch.isdigit())
    cond = Q()
    for token in q.split():
        cond |= Q(first_name__icontains=token) | Q(last_name__icontains=token)
    rows = list(qs.filter(cond).order_by("first_name", "last_name")[:8])
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


@require_POST
def day_book_book(request):
    """Create a booking from the desk.

    One service, one stylist, one client — an existing client by
    id, or a new client created from the name/phone the desk
    typed. The end is the start plus the service's own minutes;
    the name snapshot is stored verbatim, like an import's. The
    book allows overlaps (lanes render them), so no conflict can
    reject a booking the desk wants to make.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
        member_id = int(payload["staff_member_id"])
        service_id = int(payload["service_id"])
        day = datetime.date.fromisoformat(str(payload["date"]))
        start_time = datetime.datetime.strptime(str(payload["time"]), "%H:%M").time()
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "bad payload"}, status=400)
    member = StaffMember.objects.select_related("salon").filter(
        pk=member_id, active=True
    ).first()
    if member is None:
        return JsonResponse({"ok": False, "error": "no such stylist"}, status=404)
    salon = member.salon
    service = Service.objects.filter(pk=service_id, category__salon=salon).first()
    if service is None:
        return JsonResponse({"ok": False, "error": "no such service"}, status=404)
    client = None
    if payload.get("client_id"):
        try:
            client = Client.objects.filter(
                pk=int(payload["client_id"]), salon=salon
            ).first()
        except (TypeError, ValueError):
            client = None
    if client is None:
        new_client = payload.get("new_client") or {}
        first = str(new_client.get("first_name", "")).strip()
        last = str(new_client.get("last_name", "")).strip()
        phone = str(new_client.get("phone", "")).strip()
        if not first and not last:
            return JsonResponse(
                {"ok": False, "error": "pick a client or enter a new client's name"},
                status=400,
            )
        client = Client.objects.create(
            salon=salon, first_name=first, last_name=last, phone=phone
        )
    tz = _tz(salon)
    start = datetime.datetime.combine(day, start_time, tzinfo=tz)
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
    return JsonResponse({"ok": True, "appointment_id": appt.pk, "date": day.isoformat()})


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
            "client", "staff_member", "service", "service__category"
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
    kit_base = {
        "members": members,
        "prices": _price_lookup(salon),
        "aggregates": aggregates,
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
        # Visit keys with the day book's own chaining rule: same
        # client + stylist, chained while the gap stays within
        # VISIT_GAP; the key is the visit's first appointment.
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
        entries = []
        for tile in tiles:
            start = tile["_start"].astimezone(tz)
            end = tile["_end"].astimezone(tz)
            entries.append(
                {
                    "id": tile["appointment_id"],
                    "staff_id": tile["_staff_id"],
                    "client": tile["client_name"],
                    "service": tile["service_name"],
                    "cat": tile["cat_key"],
                    "is_new": tile["is_new"],
                    "start_min": start.hour * 60 + start.minute,
                    "end_min": end.hour * 60 + end.minute,
                    "status": tile["status"],
                    "amount": str(tile["_amount"])
                    if tile["_amount"] is not None
                    else None,
                    "price_label": tile["price_label"],
                    "time_label": tile["time_label"],
                    "visit": visit_of.get(tile["appointment_id"]),
                }
            )
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


def price_book(request):
    salon = Salon.objects.order_by("id").first()
    levels = list(StaffLevel.objects.filter(salon=salon, active=True)) if salon else []
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
                        "cells": [prices.get(level.pk) for level in levels],
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
            qs = qs.filter(
                Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(email__icontains=query)
                | Q(phone__icontains=query)
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


def placeholder(request, nav_key, title, lane_note):
    return render(
        request,
        "webui/placeholder.html",
        {"nav_key": nav_key, "title": title, "lane_note": lane_note},
    )
