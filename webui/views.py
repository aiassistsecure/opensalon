"""Server-rendered pages for the salon floor.

Every page reads real rows through the existing apps' models. Where a
backend lane has not landed yet (appointments, breaks), the page
renders from documented view-context contracts instead of inventing
data — see ``blocks_for_day`` and ``breaks_for_day`` below and
webui/README.md.
"""

import datetime

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory, StaffLevel
from team.models import StaffMember

# The day book window: 8:00 to 20:00 salon-local.
DAY_START_HOUR = 8
DAY_END_HOUR = 20

# Appointment statuses the day book understands, in display order —
# the bookings model's own vocabulary (booked → confirmed → arrived
# → in_service → completed, with no_show / cancelled off the path).
APPOINTMENT_STATUSES = [
    ("booked", "Booked"),
    ("confirmed", "Confirmed"),
    ("arrived", "Arrived"),
    ("in_service", "In service"),
    ("completed", "Done"),
    ("no_show", "No-show"),
    ("cancelled", "Cancelled"),
]
STATUS_LABELS = dict(APPOINTMENT_STATUSES)

# Block colourways, keyed by service category in the salon's own
# category order (first category gets colourway 0, and so on). Each is
# (wash, deep ink) — soft enough for a bright room, distinct at a
# glance across the desk.
CATEGORY_PALETTE = [
    ("#dce8d2", "#2e4b34"),  # sage / forest
    ("#f3dcd2", "#7c3f2c"),  # terracotta rose
    ("#d7e5ee", "#2c4a63"),  # harbour blue
    ("#e4ddf0", "#4a3a6b"),  # violet
    ("#f7e7c3", "#7a5510"),  # marigold
    ("#d2e8e2", "#1f5546"),  # eucalyptus teal
    ("#f6dde4", "#74384c"),  # peony
    ("#dde3e6", "#3d4c55"),  # stone blue
]

# A soft signature wash per staff column, by column position.
STAFF_TINTS = ["#eef3e2", "#fbf0e2", "#e9f0f4", "#f3ecf6", "#e8f3ee", "#fbeeee"]
STAFF_ACCENTS = ["#7a9a5b", "#c08a3e", "#5b84a3", "#8a6bb5", "#4f9a7d", "#b56b7d"]


def blocks_for_day(salon, day):
    """Appointment blocks for the day book — THE CONTRACT.

    Returns a list of plain dicts, one per appointment block:

        {
            "staff_id":    int,             # StaffMember.pk the block sits under
            "client_name": str,
            "service_name": str,
            "start":       datetime.time,   # salon-local
            "end":         datetime.time,   # salon-local, after start
            "status":      "booked" | "confirmed" | "arrived"
                           | "in_service" | "completed" | "no_show"
                           | "cancelled",
            "note":        str,             # optional appointment-only note
            "category":    str,             # optional service-category
                                            # name (block colourway)
            "category_id": int,             # optional ServiceCategory.pk
                                            # (category filter)
            "appointment_id": int,          # optional Appointment.pk —
                                            # makes the block a link to
                                            # its breakdown view
        }

    The bookings lane (Lane 3) feeds this from real Appointment rows:
    the read below activates automatically the moment the bookings
    app is installed (lazy import — while it isn't, there are no
    Appointment rows to read and this returns []). The template and
    its positioning math consume only this shape either way.
    """
    try:
        from bookings.models import Appointment
    except ImportError:
        return []
    appointments = (
        Appointment.objects.filter(client__salon=salon, start__date=day)
        .select_related("client", "staff_member", "service__category")
        .prefetch_related("notes")
        .order_by("start")
    )
    return [_block_from_appointment(a) for a in appointments]


def _block_from_appointment(appointment):
    """Map one bookings Appointment row onto the block contract."""
    notes = list(appointment.notes.all())
    return {
        "staff_id": appointment.staff_member_id,
        "client_name": str(appointment.client),
        "service_name": appointment.service.name,
        "start": timezone.localtime(appointment.start).time(),
        "end": timezone.localtime(appointment.end).time(),
        "status": appointment.status,
        "note": notes[0].body if notes else "",
        "category": appointment.service.category.name,
        "category_id": appointment.service.category_id,
        "appointment_id": appointment.pk,
    }


def breaks_for_day(salon, day):
    """Staff breaks for the day book — THE CONTRACT.

    Returns a list of plain dicts, one per break:

        {
            "staff_id": int,             # StaffMember.pk
            "start":    datetime.time,   # salon-local
            "end":      datetime.time,   # salon-local, after start
            "paid":     bool,            # PAID vs UNPAID — payroll-
                                         # relevant, always shown
            "label":    str,             # optional, e.g. "Lunch"
        }

    A break removes its span from the stylist's availability. Breaks
    get a backend home in the bookings lane (blocked-time records);
    until that model lands there are no break rows to read, so this
    returns []. Breaks render hatched and muted — never confusable
    with an appointment.
    """
    return []


def _pct(moment, day_start, day_end):
    """Position of a time as a % of the day window (for CSS top/height)."""
    span = (day_end - day_start).total_seconds()
    return round((moment - day_start).total_seconds() / span * 100, 2)


def _fmt_time(t):
    return t.strftime("%-I:%M %p").replace(":00 ", " ")


def _params(request, **overrides):
    """Query string for day-book links: current GET params with
    overrides applied (a value of None removes the key)."""
    params = request.GET.copy()
    for key, value in overrides.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value
    return params.urlencode()


def day_book(request):
    salon = Salon.objects.order_by("id").first()
    try:
        day = datetime.date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        day = timezone.localdate()
    weekday = day.weekday()
    hours = [datetime.time(h) for h in range(DAY_START_HOUR, DAY_END_HOUR + 1)]
    day_start = datetime.datetime.combine(day, datetime.time(DAY_START_HOUR))
    day_end = datetime.datetime.combine(day, datetime.time(DAY_END_HOUR))
    today = timezone.localdate()

    # Filters (all GET-driven, all bookmarkable).
    hidden_ids = {
        int(x) for x in request.GET.get("off", "").split(",") if x.isdigit()
    }
    status_filter = request.GET.get("status", "")
    if status_filter not in STATUS_LABELS:
        status_filter = ""
    category_filter = request.GET.get("cat", "")
    category_filter = int(category_filter) if category_filter.isdigit() else ""

    # The week strip: Monday–Sunday of the displayed day's week.
    week_start = day - datetime.timedelta(days=weekday)
    week_days = []
    for offset in range(7):
        chip_day = week_start + datetime.timedelta(days=offset)
        week_days.append(
            {
                "date": chip_day,
                "dow": chip_day.strftime("%a"),
                "dom": chip_day.day,
                "is_today": chip_day == today,
                "is_selected": chip_day == day,
                "url": "?" + _params(request, date=chip_day.isoformat()),
            }
        )

    categories = []
    staff = []
    if salon is not None:
        categories = list(
            ServiceCategory.objects.filter(salon=salon, active=True).order_by(
                "sort_order", "name"
            )
        )
        palette_by_category = {cat.pk: i % len(CATEGORY_PALETTE) for i, cat in enumerate(categories)}

        members = list(
            StaffMember.objects.filter(salon=salon, active=True)
            .select_related("staff_level")
            .prefetch_related("roster_patterns")
        )

        blocks = {}
        for block in blocks_for_day(salon, day):
            if status_filter and block.get("status") != status_filter:
                continue
            if category_filter and block.get("category_id") != category_filter:
                continue
            start = datetime.datetime.combine(day, block["start"])
            end = datetime.datetime.combine(day, block["end"])
            wash, ink = CATEGORY_PALETTE[
                palette_by_category.get(block.get("category_id"), 0)
            ]
            block = {
                **block,
                "url": (
                    reverse("webui:breakdown", args=[block["appointment_id"]])
                    if block.get("appointment_id")
                    else ""
                ),
                "top": _pct(start, day_start, day_end),
                "height": max(_pct(end, day_start, day_end) - _pct(start, day_start, day_end), 4.0),
                "time_label": f"{_fmt_time(block['start'])} – {_fmt_time(block['end'])}",
                "status_label": STATUS_LABELS.get(block.get("status", ""), block.get("status", "")),
                "wash": wash,
                "ink": ink,
            }
            blocks.setdefault(block["staff_id"], []).append(block)

        breaks = {}
        for brk in breaks_for_day(salon, day):
            start = datetime.datetime.combine(day, brk["start"])
            end = datetime.datetime.combine(day, brk["end"])
            brk = {
                **brk,
                "top": _pct(start, day_start, day_end),
                "height": max(_pct(end, day_start, day_end) - _pct(start, day_start, day_end), 3.5),
                "time_label": f"{_fmt_time(brk['start'])} – {_fmt_time(brk['end'])}",
            }
            breaks.setdefault(brk["staff_id"], []).append(brk)

        for position, member in enumerate(members):
            patterns = [
                p for p in member.roster_patterns.all() if p.active and p.weekday == weekday
            ]
            bands = [
                {
                    "top": _pct(datetime.datetime.combine(day, p.start_time), day_start, day_end),
                    "height": _pct(datetime.datetime.combine(day, p.end_time), day_start, day_end)
                    - _pct(datetime.datetime.combine(day, p.start_time), day_start, day_end),
                    "label": f"{_fmt_time(p.start_time)} – {_fmt_time(p.end_time)}",
                    "tall": _pct(datetime.datetime.combine(day, p.end_time), day_start, day_end)
                    - _pct(datetime.datetime.combine(day, p.start_time), day_start, day_end)
                    > 9,
                }
                for p in patterns
            ]
            off_param = ",".join(
                str(x) for x in sorted(hidden_ids.symmetric_difference({member.pk}))
            )
            staff.append(
                {
                    "member": member,
                    "initials": "".join(
                        part[0] for part in member.display_name.split()[:2]
                    ).upper(),
                    "tint": STAFF_TINTS[position % len(STAFF_TINTS)],
                    "accent": STAFF_ACCENTS[position % len(STAFF_ACCENTS)],
                    "hidden": member.pk in hidden_ids,
                    "toggle_url": "?" + _params(request, off=off_param or None),
                    "on_duty": bool(bands),
                    "bands": bands,
                    "shift_label": ", ".join(b["label"] for b in bands),
                    "blocks": blocks.get(member.pk, []),
                    "breaks": breaks.get(member.pk, []),
                }
            )

    visible_staff = [c for c in staff if not c["hidden"]]
    context = {
        "nav_key": "daybook",
        "day": day,
        "prev_day": day - datetime.timedelta(days=1),
        "next_day": day + datetime.timedelta(days=1),
        "today": today,
        "hours": hours,
        "week_days": week_days,
        "staff_columns": visible_staff,
        "staff_chips": staff,
        "has_blocks": any(c["blocks"] for c in visible_staff),
        "status_filter": status_filter,
        "status_options": APPOINTMENT_STATUSES,
        "category_filter": category_filter,
        "category_options": categories,
        "prev_url": "?" + _params(request, date=(day - datetime.timedelta(days=1)).isoformat()),
        "next_url": "?" + _params(request, date=(day + datetime.timedelta(days=1)).isoformat()),
        "today_url": "?" + _params(request, date=today.isoformat()),
        "clear_url": "?" + _params(request, off=None, status=None, cat=None),
        "filters_active": bool(hidden_ids or status_filter or category_filter),
    }
    return render(request, "webui/daybook.html", context)


def _duration_label(minutes):
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    return f"{hours}h" if hours else f"{mins}m"


def price_book(request):
    salon = Salon.objects.order_by("id").first()
    levels = list(StaffLevel.objects.filter(salon=salon, active=True)) if salon else []
    query = request.GET.get("q", "").strip()
    cat_filter = request.GET.get("cat", "")
    cat_filter = int(cat_filter) if cat_filter.isdigit() else ""
    all_categories = []
    categories = []
    if salon is not None:
        all_categories = list(
            ServiceCategory.objects.filter(salon=salon, active=True).order_by(
                "sort_order", "name"
            )
        )
        cats = (
            ServiceCategory.objects.filter(salon=salon, active=True)
            .prefetch_related("services__prices")
            .order_by("sort_order", "name")
        )
        if cat_filter:
            cats = cats.filter(pk=cat_filter)
        for cat in cats:
            rows = []
            for service in cat.services.all():
                if not service.active:
                    continue
                if query and query.lower() not in service.name.lower():
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
    context = {
        "nav_key": "pricebook",
        "levels": levels,
        "categories": categories,
        "all_categories": all_categories,
        "query": query,
        "cat_filter": cat_filter,
        "no_match": bool((query or cat_filter) and not categories),
    }
    return render(request, "webui/pricebook.html", context)


# Client list filters: key -> (label, queryset test). Opt-in state and
# record notes are the front desk's reminder-safety facts, so they
# filter first-class.
CLIENT_FILTERS = [
    ("sms", "SMS on"),
    ("email", "Email on"),
    ("notes", "Has notes"),
]


def clients(request):
    salon = Salon.objects.order_by("id").first()
    query = request.GET.get("q", "").strip()
    opt_filter = request.GET.get("opt", "")
    if opt_filter not in dict(CLIENT_FILTERS):
        opt_filter = ""
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
        if opt_filter == "sms":
            qs = qs.filter(sms_opt_in=True)
        elif opt_filter == "email":
            qs = qs.filter(email_opt_in=True)
        elif opt_filter == "notes":
            qs = qs.filter(note_count__gt=0)
        total = qs.count()
        page = Paginator(qs, 30).get_page(request.GET.get("page"))
    context = {
        "nav_key": "clients",
        "page": page,
        "query": query,
        "total": total,
        "opt_filter": opt_filter,
        "opt_options": CLIENT_FILTERS,
    }
    return render(request, "webui/clients.html", context)


def placeholder(request, nav_key, title, lane_note):
    return render(
        request,
        "webui/placeholder.html",
        {"nav_key": nav_key, "title": title, "lane_note": lane_note},
    )
