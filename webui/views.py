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
renders by. A service with no price-book row at that level renders
no price at all; nothing is invented. Projected revenue is the sum
of those resolved prices over the day's records, and the count of
unpriced records travels with it so the figure is never mistaken
for complete when it is not.
"""

import datetime
from decimal import Decimal

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone
from django.utils.text import slugify

from bookings.availability import _tz
from bookings.daybook import blocks_for_day as feed_blocks_for_day
from bookings.models import Appointment, AppointmentNote
from clients.models import Client, ClientNote
from saloncore.models import Salon, ServiceCategory, ServicePrice, StaffLevel
from team.models import StaffMember

# The day book window: 8:00 to 20:00 salon-local.
DAY_START_HOUR = 8
DAY_END_HOUR = 20

_STATUS_LABELS = dict(Appointment.Status.choices)

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


def day_book(request):
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
    default_rail = None
    overview = {
        "appointments": 0,
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
        members = list(
            StaffMember.objects.filter(salon=salon, active=True)
            .select_related("staff_level")
            .prefetch_related("roster_patterns")
        )
        feed = {c.staff_member_id: c for c in feed_blocks_for_day(salon, day)}
        prices = {
            (p.service_id, p.staff_level_id): p.amount
            for p in ServicePrice.objects.filter(
                active=True, service__category__salon=salon
            )
        }
        day_appts = list(
            Appointment.objects.filter(
                staff_member__in=members, start__lt=day_end, end__gt=day_start
            )
            .exclude(status=Appointment.Status.CANCELLED)
            .select_related("client", "staff_member", "service", "service__category")
            .order_by("start")
        )
        appt_by_id = {a.pk: a for a in day_appts}

        def amount_for(appt):
            return prices.get((appt.service_id, appt.staff_member.staff_level_id))

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
        visit_counts = {
            row["client_id"]: row["n"]
            for row in Appointment.objects.filter(client_id__in=client_ids)
            .values("client_id")
            .annotate(n=Count("id"))
        }
        client_notes = {}
        for note in ClientNote.objects.filter(client_id__in=client_ids).order_by(
            "-created_at"
        ):
            client_notes.setdefault(note.client_id, []).append(note.body)
        appt_notes = {}
        for note in AppointmentNote.objects.filter(
            appointment_id__in=appt_by_id
        ).order_by("-created_at"):
            appt_notes.setdefault(note.appointment_id, []).append(note.body)
        history = {}
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
                        "service": item.service.name if item.service else item.service_name,
                        "duration_label": _duration_label(minutes),
                        "price_label": _price_label(amount),
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
                rail_payloads[raw.appointment_id] = rail_payload(appt)
                blocks.append(
                    {
                        "appointment_id": raw.appointment_id,
                        "client_name": raw.client_display_name,
                        "client_initials": _initials(raw.client_display_name),
                        "service_name": raw.service_name,
                        "category_name": raw.service_category_name,
                        "cat_key": slugify(raw.service_category_name) or "misc",
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
                _assign_lanes(display_blocks)
            else:
                _assign_lanes(display_blocks)
            width_factor = min(
                3,
                max((b.get("overlap", 1) for b in display_blocks), default=1),
            )
            staff.append(
                {
                    "member": member,
                    "on_duty": bool(bands),
                    "bands": bands,
                    "shift_label": ", ".join(b["label"] for b in bands),
                    "blocks": display_blocks,
                    "booked_pct": booked_pct,
                    "initials": _initials(member.display_name),
                    "width_factor": width_factor,
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
        if day_appts:
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
    return render(request, "webui/daybook.html", context)


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


def placeholder(request, nav_key, title, lane_note):
    return render(
        request,
        "webui/placeholder.html",
        {"nav_key": nav_key, "title": title, "lane_note": lane_note},
    )
