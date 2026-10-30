"""Server-rendered pages for the salon floor.

Every page reads real rows through the existing apps' models. Where a
backend lane has not landed yet (appointments), the page renders from
a documented view-context contract instead of inventing data.
"""

import datetime

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone

from clients.models import Client
from saloncore.models import Salon, ServiceCategory, StaffLevel
from team.models import StaffMember

# The day book window: 8:00 to 20:00 salon-local.
DAY_START_HOUR = 8
DAY_END_HOUR = 20


def blocks_for_day(salon, day):
    """Appointment blocks for the day book — THE CONTRACT.

    Returns a list of plain dicts, one per appointment block:

        {
            "staff_id":    int,             # StaffMember.pk the block sits under
            "client_name": str,
            "service_name": str,
            "start":       datetime.time,   # salon-local
            "end":         datetime.time,   # salon-local, after start
            "status":      "booked" | "confirmed" | "checked_in"
                           | "completed" | "no_show" | "cancelled",
            "note":        str,             # optional appointment-only note
        }

    The bookings lane (Lane 3) will feed this from real Appointment
    rows; the template and its positioning math consume only this
    shape, so no template change is needed when that lands. Until
    then there are no Appointment rows to read, so this returns [].
    """
    return []


def _pct(moment, day_start, day_end):
    """Position of a time as a % of the day window (for CSS top/height)."""
    span = (day_end - day_start).total_seconds()
    return round((moment - day_start).total_seconds() / span * 100, 2)


def _fmt_time(t):
    return t.strftime("%-I:%M %p").replace(":00 ", " ")


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

    staff = []
    if salon is not None:
        members = (
            StaffMember.objects.filter(salon=salon, active=True)
            .select_related("staff_level")
            .prefetch_related("roster_patterns")
        )
        blocks = {}
        for block in blocks_for_day(salon, day):
            start = datetime.datetime.combine(day, block["start"])
            end = datetime.datetime.combine(day, block["end"])
            block = {
                **block,
                "top": _pct(start, day_start, day_end),
                "height": max(_pct(end, day_start, day_end) - _pct(start, day_start, day_end), 4.0),
                "time_label": f"{_fmt_time(block['start'])} – {_fmt_time(block['end'])}",
            }
            blocks.setdefault(block["staff_id"], []).append(block)
        for member in members:
            patterns = [
                p for p in member.roster_patterns.all() if p.active and p.weekday == weekday
            ]
            bands = [
                {
                    "top": _pct(datetime.datetime.combine(day, p.start_time), day_start, day_end),
                    "height": _pct(datetime.datetime.combine(day, p.end_time), day_start, day_end)
                    - _pct(datetime.datetime.combine(day, p.start_time), day_start, day_end),
                    "label": f"{_fmt_time(p.start_time)} – {_fmt_time(p.end_time)}",
                }
                for p in patterns
            ]
            staff.append(
                {
                    "member": member,
                    "on_duty": bool(bands),
                    "bands": bands,
                    "shift_label": ", ".join(b["label"] for b in bands),
                    "blocks": blocks.get(member.pk, []),
                }
            )
    context = {
        "nav_key": "daybook",
        "day": day,
        "prev_day": day - datetime.timedelta(days=1),
        "next_day": day + datetime.timedelta(days=1),
        "today": timezone.localdate(),
        "hours": hours,
        "staff_columns": staff,
        "has_blocks": any(c["blocks"] for c in staff),
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
