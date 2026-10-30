"""Day book interactions: breakdown, booking, copy, breaks, close-out.

THE CLICK MODEL (founder's words): clicking an appointment opens its
breakdown, where services can be added and the visit closed out;
clicking empty column space sets a new appointment; a Copy toggle
arms pick-up-and-place copying, and every block and breakdown also
carries explicit Copy and Pay actions.

Everything renders through the contract functions below. They are
written against the bookings lane's Appointment model exactly as
proposed in its PR (one service per Appointment; a *visit* is the
contiguous chain of same-client, same-stylist appointments where each
starts when the previous ends; prices live in the price book and are
read at the stylist's level, never stored on the appointment). The
imports are lazy: while bookings is not on main the contracts resolve
to "not wired" and the pages say so plainly — no fake saves, no fake
payments. The moment the bookings app lands, the same views go live
with no template changes. webui/README.md documents every shape.
"""

import datetime
from decimal import Decimal

from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from clients.models import Client
from saloncore.models import Salon, Service
from team.models import StaffMember

from . import forms as webui_forms
from .views import STATUS_LABELS, _duration_label, _fmt_time


def _appointment_model():
    """The bookings Appointment model, or None while Lane 3 is not on
    main. Lazy so webui imports cleanly either way."""
    try:
        from bookings.models import Appointment
    except ImportError:
        return None
    return Appointment


def _price_for(service, staff_member):
    """The price-book price of a service for a stylist: their own
    level's price first, any active price as fallback, else None."""
    level = getattr(staff_member, "staff_level", None)
    if level is not None:
        price = service.prices.filter(staff_level=level, active=True).first()
        if price is not None:
            return price
    return service.prices.filter(active=True).first()


def _visit_chain(appointment):
    """The visit containing `appointment`: the maximal run of
    contiguous, non-cancelled appointments for the same client and
    stylist on the same day, each starting when the previous ends."""
    Appointment = _appointment_model()
    siblings = list(
        Appointment.objects.filter(
            client=appointment.client,
            staff_member=appointment.staff_member,
            start__date=appointment.start.date(),
        )
        .exclude(status=Appointment.Status.CANCELLED)
        .select_related("service")
        .order_by("start")
    )
    chain = [appointment]
    idx = next(i for i, a in enumerate(siblings) if a.pk == appointment.pk)
    cursor = idx
    while cursor + 1 < len(siblings) and siblings[cursor + 1].start == siblings[cursor].end:
        cursor += 1
        chain.append(siblings[cursor])
    cursor = idx
    while cursor - 1 >= 0 and siblings[cursor - 1].end == siblings[cursor].start:
        cursor -= 1
        chain.insert(0, siblings[cursor])
    return chain


# ---------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------

def breakdown_for_appointment(salon, appointment_id):
    """One visit, priced — THE CONTRACT.

    Returns None when the visit cannot be resolved (bookings lane not
    landed, or no such appointment at this salon). Otherwise:

        {
            "id": int,                # the clicked appointment
            "client_id": int, "client_name": str,
            "staff_id": int, "staff_name": str,
            "date": date, "start": time, "end": time,   # visit span
            "status": str,            # the clicked appointment's
            "lines": [{"appointment_id": int, "service_name": str,
                       "duration_label": str,
                       "price": Decimal | None,
                       "price_is_from": bool}],
            "total": Decimal,         # sum of priced lines
            "appointment_notes": [{"body", "author_name",
                                   "created_at"}],   # this visit only
            "record_notes": [ClientNote...],  # the client's
                              # persistent record — a different kind
                              # of note, never merged with the above
        }
    """
    Appointment = _appointment_model()
    if Appointment is None:
        return None
    appt = (
        Appointment.objects.filter(pk=appointment_id, client__salon=salon)
        .select_related("client", "staff_member")
        .first()
    )
    if appt is None:
        return None
    chain = _visit_chain(appt)
    lines = []
    total = Decimal("0")
    for link in chain:
        price = _price_for(link.service, appt.staff_member)
        if price is not None:
            total += price.amount
        lines.append(
            {
                "appointment_id": link.pk,
                "service_name": link.service.name,
                "duration_label": _duration_label(link.service.total_minutes),
                "price": price.amount if price else None,
                "price_is_from": bool(price.is_from) if price else False,
            }
        )
    notes = []
    for link in chain:
        notes.extend(link.notes.all())
    return {
        "id": appt.pk,
        "client_id": appt.client_id,
        "client_name": str(appt.client),
        "staff_id": appt.staff_member_id,
        "staff_name": appt.staff_member.display_name,
        "date": appt.start.date(),
        "start": chain[0].start.time(),
        "end": chain[-1].end.time(),
        "status": appt.status,
        "lines": lines,
        "total": total,
        "appointment_notes": notes,
        "record_notes": list(appt.client.notes.all()),
    }


def create_appointment(salon, *, client, staff, service, day, start, note):
    """Persist a new appointment — THE CONTRACT.

    Returns the new appointment's id, or None while the bookings lane
    hasn't landed (the caller must then say plainly that nothing was
    booked). The appointment-only note, when given, is stored as an
    AppointmentNote — never on the client record.
    """
    Appointment = _appointment_model()
    if Appointment is None:
        return None
    from bookings.models import AppointmentNote

    starts_at = timezone.make_aware(datetime.datetime.combine(day, start))
    appt = Appointment.objects.create(
        client=client, staff_member=staff, service=service,
        start=starts_at,
        end=starts_at + datetime.timedelta(minutes=service.total_minutes),
    )
    if note:
        AppointmentNote.objects.create(appointment=appt, body=note)
    return appt.pk


def copy_appointment(salon, appointment_id, *, staff, day, start):
    """Place a copy of a whole visit — THE CONTRACT.

    Every appointment in the source visit's chain is copied to the
    target stylist/day, keeping the chain's relative timing, with the
    first appointment at `start`. Returns the first copy's id, or
    None when not wired / unresolvable. Status resets to booked.
    """
    Appointment = _appointment_model()
    if Appointment is None:
        return None
    source = Appointment.objects.filter(pk=appointment_id, client__salon=salon).first()
    if source is None:
        return None
    chain = _visit_chain(source)
    origin = chain[0].start
    target = timezone.make_aware(datetime.datetime.combine(day, start))
    first_id = None
    for link in chain:
        offset = link.start - origin
        clone = Appointment.objects.create(
            client=source.client, staff_member=staff, service=link.service,
            start=target + offset,
            end=target + offset + (link.end - link.start),
            status=Appointment.Status.BOOKED,
        )
        if first_id is None:
            first_id = clone.pk
    return first_id


def add_service_to_visit(salon, appointment_id, service):
    """Attach one more service to a visit — THE CONTRACT.

    With one service per Appointment, adding a service books it as
    the next appointment in the visit's chain: same client and
    stylist, starting when the visit currently ends. Returns True
    when added, False when not wired / unresolvable. The breakdown
    then shows it as another priced line.
    """
    Appointment = _appointment_model()
    if Appointment is None:
        return False
    appt = Appointment.objects.filter(pk=appointment_id, client__salon=salon).first()
    if appt is None:
        return False
    chain = _visit_chain(appt)
    starts_at = chain[-1].end
    Appointment.objects.create(
        client=appt.client, staff_member=appt.staff_member, service=service,
        start=starts_at,
        end=starts_at + datetime.timedelta(minutes=service.total_minutes),
    )
    return True


def create_break(salon, *, staff, day, start, minutes, paid, label):
    """Persist a staff break — THE CONTRACT.

    Breaks get their backend home as blocked-time records in the
    bookings lane; that model does not exist yet (not even in the
    bookings lane's first PR), so this returns False for now and the
    caller says plainly that nothing was saved. ``paid`` will be
    stored verbatim — it is payroll data.
    """
    try:
        from bookings.models import StaffBreak
    except ImportError:
        return False
    StaffBreak.objects.create(
        salon=salon, staff_member=staff, date=day, start_time=start,
        end_time=(datetime.datetime.combine(day, start) + datetime.timedelta(minutes=minutes)).time(),
        paid=paid, label=label,
    )
    return True


def close_out_visit(salon, appointment_id):
    """Hand a visit to checkout — THE CONTRACT.

    Checkout is Lane 4. Until it lands there is no payment to take and
    this returns None; the close-out page must never pretend a payment
    happened. When wired it returns the checkout handoff dict
    {"sale_id": int, "total": Decimal}.
    """
    return None


# ---------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------

def _salon():
    return Salon.objects.order_by("id").first()


def breakdown(request, appointment_id):
    salon = _salon()
    data = breakdown_for_appointment(salon, appointment_id) if salon else None
    context = {"nav_key": "daybook", "appointment_id": appointment_id, "visit": data}
    if data is not None:
        context.update(
            status_label=STATUS_LABELS.get(data["status"], data["status"]),
            time_label=f"{_fmt_time(data['start'])} – {_fmt_time(data['end'])}",
            day_url=f"{reverse('webui:daybook')}?date={data['date'].isoformat()}",
        )
    return render(request, "webui/breakdown.html", context)


def add_service(request, appointment_id):
    salon = _salon()
    visit = breakdown_for_appointment(salon, appointment_id) if salon else None
    note = ""
    if request.method == "POST":
        form = webui_forms.AddServiceForm(request.POST, salon=salon)
        if form.is_valid():
            if add_service_to_visit(salon, appointment_id, form.cleaned_data["service"]):
                return redirect("webui:breakdown", appointment_id=appointment_id)
            note = (
                "Saving arrives with the bookings lane — "
                "nothing was added to this visit."
            )
    else:
        form = webui_forms.AddServiceForm(salon=salon)
    return render(
        request, "webui/add_service.html",
        {"nav_key": "daybook", "form": form, "visit": visit,
         "appointment_id": appointment_id, "form_note": note},
    )


def close_out(request, appointment_id):
    salon = _salon()
    visit = breakdown_for_appointment(salon, appointment_id) if salon else None
    note = ""
    if request.method == "POST":
        if close_out_visit(salon, appointment_id) is not None:
            return redirect("webui:daybook")
        note = (
            "Checkout hasn't landed yet (Lane 4) — no payment was taken. "
            "This screen is where the visit will be paid and closed."
        )
    return render(
        request, "webui/closeout.html",
        {"nav_key": "daybook", "visit": visit,
         "appointment_id": appointment_id, "form_note": note},
    )


def _prefill(request):
    initial = {}
    if request.GET.get("staff", "").isdigit():
        initial["staff"] = int(request.GET["staff"])
    try:
        initial["date"] = datetime.date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        initial["date"] = timezone.localdate()
    try:
        initial["start"] = datetime.time.fromisoformat(request.GET.get("start", ""))
    except ValueError:
        pass
    return initial


def appointment_new(request):
    salon = _salon()
    note = ""
    if request.method == "POST":
        form = webui_forms.BookingForm(request.POST, salon=salon)
        if form.is_valid():
            data = form.cleaned_data
            new_id = create_appointment(
                salon, client=data["client"], staff=data["staff"],
                service=data["service"], day=data["date"],
                start=data["start"], note=data["note"],
            )
            if new_id is not None:
                return redirect("webui:breakdown", appointment_id=new_id)
            note = (
                "Booking saving arrives with the bookings lane — "
                "nothing was booked. The details you entered are still "
                "here; nothing was lost or faked."
            )
    else:
        form = webui_forms.BookingForm(initial=_prefill(request), salon=salon)
    clients = (
        Client.objects.filter(salon=salon, active=True).order_by("first_name", "last_name")
        if salon else []
    )
    services = (
        Service.objects.filter(category__salon=salon, active=True)
        .select_related("category").prefetch_related("prices")
        .order_by("category__sort_order", "category__name", "name")
        if salon else []
    )
    return render(
        request, "webui/booking_form.html",
        {"nav_key": "daybook", "form": form, "form_note": note,
         "clients": clients, "service_options": services},
    )


def appointment_copy(request):
    salon = _salon()
    raw_source = request.POST.get("source", "") if request.method == "POST" else request.GET.get("source", "")
    source_id = int(raw_source) if str(raw_source).isdigit() else None
    source = (
        breakdown_for_appointment(salon, source_id)
        if salon and source_id is not None else None
    )
    note = ""
    if request.method == "POST":
        form = webui_forms.CopyForm(request.POST, salon=salon)
        if form.is_valid() and source_id is not None:
            data = form.cleaned_data
            new_id = copy_appointment(
                salon, source_id, staff=data["staff"],
                day=data["date"], start=data["start"],
            )
            if new_id is not None:
                return redirect("webui:breakdown", appointment_id=new_id)
            note = (
                "Copying arrives with the bookings lane — no copy was "
                "placed. The target you chose is still here."
            )
    else:
        form = webui_forms.CopyForm(initial=_prefill(request), salon=salon)
    return render(
        request, "webui/copy.html",
        {"nav_key": "daybook", "form": form, "form_note": note,
         "source": source, "source_id": source_id},
    )


def break_new(request):
    salon = _salon()
    note = ""
    if request.method == "POST":
        form = webui_forms.BreakForm(request.POST, salon=salon)
        if form.is_valid():
            data = form.cleaned_data
            if create_break(
                salon, staff=data["staff"], day=data["date"],
                start=data["start"], minutes=data["minutes"],
                paid=data["paid"], label=data["label"],
            ):
                return redirect(f"{reverse('webui:daybook')}?date={data['date'].isoformat()}")
            note = (
                "Break saving arrives with the bookings lane — no break "
                "was saved. Paid/unpaid is payroll data, so nothing is "
                "recorded until it can be recorded for real."
            )
    else:
        initial = {"minutes": 30, **_prefill(request)}
        form = webui_forms.BreakForm(initial=initial, salon=salon)
    return render(
        request, "webui/break_form.html",
        {"nav_key": "daybook", "form": form, "form_note": note},
    )
