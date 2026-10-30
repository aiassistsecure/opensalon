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

# Block colourways — the founder-approved mock's palette, mapped onto
# service categories BY NAME (the design-token layer: a salon whose
# categories carry these words gets these colourways; anything else
# rotates through the same palette in the salon's category order).
# Colour is information: the category picks the saturated gradient,
# the status rides the block's top line and edge. Blocks wear white
# text on the gradient, exactly as the mock draws them.
CATEGORY_COLORWAYS = [
    (("color", "colour"), ("#177a68", "#0d4f43")),  # deep teal
    (("highlight", "balayage", "lighten", "blond"), ("#9c4066", "#74304e")),  # berry
    (("extension",), ("#c08c22", "#96690f")),  # amber
    (("texture", "perm", "keratin", "smoothing"), ("#6c5484", "#4c3a61")),  # plum
    (("treatment", "ritual", "care"), ("#77995f", "#55703f")),  # sage
    (("nail",), ("#b2546e", "#8a3c52")),  # rose
    (("consult",), ("#52769e", "#2c4a63")),  # harbour
    (("wax", "brow", "lash"), ("#7a6a9e", "#57497a")),  # violet
    (("hair", "cut", "style"), ("#39684a", "#254a33")),  # forest
]
COLORWAY_ROTATION = [
    ("#177a68", "#0d4f43"),
    ("#9c4066", "#74304e"),
    ("#39684a", "#254a33"),
    ("#c08c22", "#96690f"),
    ("#6c5484", "#4c3a61"),
    ("#77995f", "#55703f"),
    ("#b2546e", "#8a3c52"),
]


def _colorway_for(category_name, position):
    """The (start, end) gradient pair for a service category: the
    name-mapped colourway when the category carries a known word,
    else the rotation by the category's order in the price book."""
    name = (category_name or "").lower()
    for fragments, pair in CATEGORY_COLORWAYS:
        if any(fragment in name for fragment in fragments):
            return pair
    return COLORWAY_ROTATION[position % len(COLORWAY_ROTATION)]


def _gradient(pair):
    return f"linear-gradient(150deg,{pair[0]},{pair[1]})"


# Status glyphs for the block's top line — the mock's vocabulary:
# ○ booked, ✓ confirmed, ◉ arrived, ● in service, ✓ done.
STATUS_GLYPHS = {
    "booked": "○",
    "confirmed": "✓",
    "arrived": "◉",
    "in_service": "●",
    "completed": "✓",
    "no_show": "✕",
    "cancelled": "—",
}

# Staff signature bands — each column head wears one, by position,
# exactly the mock's device (forest, rust, olive gold, plum, sage,
# rose, bronze, then teal / harbour / berry for wider teams). The
# band's start colour doubles as the team chip's dot.
STAFF_BANDS = [
    ("#26503c", "#173327"),  # forest
    ("#c96a24", "#a34e12"),  # rust
    ("#a2932a", "#7d701a"),  # olive gold
    ("#77598f", "#543e68"),  # plum
    ("#84a668", "#5f7f47"),  # sage
    ("#bb5f78", "#93455c"),  # rose
    ("#a87c2a", "#7d5a14"),  # bronze
    ("#177a68", "#0d4f43"),  # teal
    ("#52769e", "#2c4a63"),  # harbour
    ("#9c4066", "#74304e"),  # berry
]


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
            "price":       Decimal,         # optional — the price-book
                                            # price at the stylist's
                                            # level, shown on the block
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
        .prefetch_related("notes", "service__prices")
        .order_by("start")
    )
    return [_block_from_appointment(a) for a in appointments]


def _price_label(amount):
    """A block's price tag, the mock's way: $215 when whole, $85.50
    when not, empty when the service carries no price."""
    if amount is None:
        return ""
    if amount == amount.to_integral_value():
        return f"${amount:,.0f}"
    return f"${amount:,.2f}"


def _block_from_appointment(appointment):
    """Map one bookings Appointment row onto the block contract."""
    notes = list(appointment.notes.all())
    # The block's price is read live from the price book at the
    # stylist's level (any active price as fallback) — the same rule
    # the breakdown totals use; never stored on the appointment.
    price = None
    prices = getattr(appointment.service, "prices", None)
    if prices is not None:
        try:
            active = [p for p in prices.all() if p.active]
        except TypeError:
            active = []
        level_id = getattr(appointment.staff_member, "staff_level_id", None)
        chosen = next((p for p in active if p.staff_level_id == level_id), None)
        if chosen is None and active:
            chosen = active[0]
        if chosen is not None:
            price = chosen.amount
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
        "price": price,
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
                "tag": "Today"
                if chip_day == today
                else "Tomorrow"
                if chip_day == today + datetime.timedelta(days=1)
                else "",
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
        colorway_by_category = {
            cat.pk: _colorway_for(cat.name, i) for i, cat in enumerate(categories)
        }
        colorway_by_name = {
            cat.name: _colorway_for(cat.name, i) for i, cat in enumerate(categories)
        }

        members = list(
            StaffMember.objects.filter(salon=salon, active=True)
            .select_related("staff_level")
            .prefetch_related("roster_patterns")
        )

        blocks = {}
        booked_minutes = {}
        for block in blocks_for_day(salon, day):
            start = datetime.datetime.combine(day, block["start"])
            end = datetime.datetime.combine(day, block["end"])
            # Booked time is the day's truth, counted before filters:
            # it feeds the staff head's booked-% (cancelled excluded).
            if block.get("status") != "cancelled":
                booked_minutes[block["staff_id"]] = booked_minutes.get(
                    block["staff_id"], 0
                ) + (end - start).total_seconds() / 60
            if status_filter and block.get("status") != status_filter:
                continue
            if category_filter and block.get("category_id") != category_filter:
                continue
            pair = colorway_by_category.get(block.get("category_id")) or (
                colorway_by_name.get(block.get("category"))
            )
            if pair is None:
                pair = COLORWAY_ROTATION[0]
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
                "status_glyph": STATUS_GLYPHS.get(block.get("status", ""), ""),
                "bg": _gradient(pair),
                "price_label": _price_label(block.get("price")),
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
            # Booked-% — the mock's staff-head figure: the day's real
            # blocks against the day's rostered time. Only stated when
            # a roster exists to measure against; never invented.
            roster_minutes = sum(
                (
                    datetime.datetime.combine(day, p.end_time)
                    - datetime.datetime.combine(day, p.start_time)
                ).total_seconds()
                / 60
                for p in patterns
            )
            booked_pct = None
            booked_label = ""
            if roster_minutes:
                booked_pct = round(
                    100 * booked_minutes.get(member.pk, 0) / roster_minutes
                )
                if booked_pct >= 100:
                    booked_label = "Full"
                elif booked_pct == 0:
                    booked_label = "Openings"
                else:
                    booked_label = f"Booked {booked_pct}%"
            band = STAFF_BANDS[position % len(STAFF_BANDS)]
            staff.append(
                {
                    "member": member,
                    "initials": "".join(
                        part[0] for part in member.display_name.split()[:2]
                    ).upper(),
                    "band": _gradient(band),
                    "accent": band[0],
                    "hidden": member.pk in hidden_ids,
                    "toggle_url": "?" + _params(request, off=off_param or None),
                    "on_duty": bool(bands),
                    "bands": bands,
                    "shift_label": ", ".join(b["label"] for b in bands),
                    "booked_pct": booked_pct,
                    "booked_label": booked_label,
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
                pair = _colorway_for(cat.name, all_categories.index(cat))
                categories.append(
                    {"category": cat, "rows": rows, "swatch": pair[0]}
                )
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
