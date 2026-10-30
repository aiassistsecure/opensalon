"""Front-desk forms for the day book interactions.

Plain Django forms over the existing apps' models. They collect and
validate; persistence goes through the contract functions in
webui.views (create_appointment, copy_appointment, create_break,
add_service_to_visit), never through these forms directly.
"""

import datetime

from django import forms

from clients.models import Client
from saloncore.models import Service
from team.models import StaffMember


class BookingForm(forms.Form):
    """Set an appointment: client, service, stylist, day, start.

    The client is picked with a datalist (name search) backed by a
    hidden id field that webui.js fills in; without JS the typed name
    is matched exactly server-side. Services are labelled with their
    duration and price from the price book.
    """

    client_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    client_name = forms.CharField(label="Client", max_length=200)
    service = forms.ModelChoiceField(label="Service", queryset=Service.objects.none())
    staff = forms.ModelChoiceField(label="Stylist", queryset=StaffMember.objects.none())
    date = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}))
    start = forms.TimeField(label="Start", widget=forms.TimeInput(attrs={"type": "time"}))
    note = forms.CharField(
        label="Appointment note",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="This note belongs to this appointment only.",
    )

    def __init__(self, *args, salon=None, **kwargs):
        super().__init__(*args, **kwargs)
        if salon is not None:
            self.fields["service"].queryset = (
                Service.objects.filter(category__salon=salon, active=True)
                .select_related("category")
                .prefetch_related("prices")
                .order_by("category__sort_order", "category__name", "name")
            )
            self.fields["staff"].queryset = StaffMember.objects.filter(
                salon=salon, active=True
            )

    def clean(self):
        cleaned = super().clean()
        client = None
        if cleaned.get("client_id"):
            client = Client.objects.filter(pk=cleaned["client_id"], active=True).first()
        if client is None and cleaned.get("client_name"):
            first, _, last = cleaned["client_name"].strip().partition(" ")
            client = (
                Client.objects.filter(
                    first_name__iexact=first, last_name__iexact=last, active=True
                ).first()
                if last
                else None
            )
        if client is None:
            self.add_error("client_name", "Pick a client from the list.")
        else:
            cleaned["client"] = client
        return cleaned


class CopyForm(forms.Form):
    """Place a copy of an appointment: target stylist, day, start."""

    staff = forms.ModelChoiceField(label="Stylist", queryset=StaffMember.objects.none())
    date = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}))
    start = forms.TimeField(label="Start", widget=forms.TimeInput(attrs={"type": "time"}))

    def __init__(self, *args, salon=None, **kwargs):
        super().__init__(*args, **kwargs)
        if salon is not None:
            self.fields["staff"].queryset = StaffMember.objects.filter(
                salon=salon, active=True
            )


class BreakForm(forms.Form):
    """Add a break to a stylist's day.

    ``paid`` is payroll-relevant data, not decoration: True = paid
    break, False = unpaid. It is an explicit choice on the form.
    """

    staff = forms.ModelChoiceField(label="Stylist", queryset=StaffMember.objects.none())
    date = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}))
    start = forms.TimeField(label="Start", widget=forms.TimeInput(attrs={"type": "time"}))
    minutes = forms.TypedChoiceField(
        label="Length",
        choices=[(15, "15 min"), (30, "30 min"), (45, "45 min"), (60, "1 hour"), (90, "1½ hours")],
        coerce=int,
    )
    label = forms.CharField(label="Label", required=False, max_length=80)
    paid = forms.BooleanField(
        label="Paid break",
        required=False,
        help_text="Paid breaks count as paid time. Leave unticked for an unpaid break.",
    )

    def __init__(self, *args, salon=None, **kwargs):
        super().__init__(*args, **kwargs)
        if salon is not None:
            self.fields["staff"].queryset = StaffMember.objects.filter(
                salon=salon, active=True
            )


class AddServiceForm(forms.Form):
    """Attach one more service from the price book to a visit."""

    service = forms.ModelChoiceField(label="Service", queryset=Service.objects.none())

    def __init__(self, *args, salon=None, **kwargs):
        super().__init__(*args, **kwargs)
        if salon is not None:
            self.fields["service"].queryset = (
                Service.objects.filter(category__salon=salon, active=True)
                .select_related("category")
                .order_by("category__sort_order", "category__name", "name")
            )
