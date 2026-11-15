"""Demo-mode seed: a fully populated, wholly invented salon.

Backend only -- no views, templates, or UI.

Demo mode exists so a stranger who clones OpenSalon can be
clicking around a busy salon within minutes. EVERY record here
is invented in code: a fictional salon, fictional people,
plausible invented prices. Nothing is read from any real
salon's data, and no real business or person is named.

The seed is deterministic (a fixed ``random.seed``) and every
date is computed relative to the salon-local today at seed
time, so the demo always opens on a busy day: today's book is
full, the last 30 days carry sales, and tomorrow already has
bookings (so future-value figures have something to count).

Re-running rebuilds cleanly: the demo salon is keyed on its
name, deleted (which cascades to everything it owns), and
recreated from scratch, so counts after any run are identical.
Only the salon named ``Demo Salon`` is ever touched.

Sale totals are consistent by construction: each sale's single
payment equals the sale total (line subtotals less recorded
line discounts; there are no sale-level discounts).
"""
import random
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from bookings.models import Appointment
from catalog.models import Product
from checkout.models import Payment, Refund, Sale, SaleItem
from clients.models import Client
from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import RosterPattern, StaffMember

DEMO_SALON_NAME = "Demo Salon"
DEMO_TIMEZONE = "America/New_York"
_SEED = 20261114
_SALES_DAYS = 30
_SALES_PER_DAY = 15

LEVELS = [("Stylist", "1"), ("Senior Stylist", "1.15"), ("Master Stylist", "1.3")]

STAFF = [  # (display name, level index, worked weekdays Mon=0)
    ("Alex Rivers", 2, (1, 2, 3, 4, 5)),
    ("Jordan Blake", 1, (0, 1, 2, 3, 4)),
    ("Taylor Quinn", 0, (0, 1, 3, 4, 5)),
    ("Casey Lane", 1, (0, 2, 3, 4, 5)),
    ("Riley Brooks", 0, (1, 2, 4, 5, 6)),
    ("Jamie Fox", 2, (0, 1, 2, 3, 5)),
]

# (category, [(service, minutes, base price)])
PRICE_BOOK = [
    ("Haircuts", [
        ("Women's Haircut", 60, "65"), ("Men's Haircut", 45, "40"),
        ("Kids Haircut", 30, "30"), ("Blowout & Style", 45, "55"),
        ("Special Occasion Style", 60, "75"),
    ]),
    ("Color", [
        ("Single Process Color", 90, "85"), ("Partial Foil", 120, "120"),
        ("Full Foil", 150, "160"), ("Balayage", 150, "175"),
        ("Gloss & Tone", 45, "50"), ("Color Correction", 180, "250"),
        ("Root Touch-Up", 75, "70"),
    ]),
    ("Texture & Treatments", [
        ("Keratin Treatment", 150, "225"),
        ("Deep Conditioning Treatment", 30, "35"),
        ("Scalp Treatment", 30, "40"), ("Perm", 120, "110"),
        ("Relaxer", 90, "95"),
    ]),
    ("Nails & More", [
        ("Manicure", 45, "35"), ("Pedicure", 60, "55"),
        ("Gel Manicure", 60, "50"), ("Wax — Brow", 15, "20"),
        ("Wax — Lip", 10, "15"), ("Makeup Application", 45, "60"),
        ("Bridal Trial", 75, "85"),
    ]),
]

PRODUCTS = [  # (name, price)
    ("Daily Shampoo 250ml", "24"), ("Daily Conditioner 250ml", "24"),
    ("Repair Mask 200ml", "32"), ("Argan Hair Oil 100ml", "28"),
    ("Sea Salt Spray 150ml", "22"), ("Strong Hold Gel 150ml", "18"),
    ("Heat Protectant Spray", "21"), ("Dry Shampoo 200ml", "19"),
    ("Curl Cream 150ml", "23"), ("Shine Serum 50ml", "26"),
]

FIRST_NAMES = [
    "Ava", "Liam", "Mia", "Noah", "Zoe", "Eli", "Ivy", "Owen", "Ruby",
    "Leo", "Nora", "Hugo", "Lila", "Ezra", "Cleo", "Amos", "Fern",
    "Silas", "Opal", "Dario",
]
LAST_NAMES = [
    "Ashford", "Bexley", "Calloway", "Dunmore", "Ellery", "Fenwick",
    "Garland", "Holloway", "Ingram", "Juniper", "Kestrel", "Larkspur",
    "Marlowe", "Netherby", "Oakes", "Pemberton", "Quill", "Ravenshaw",
    "Sorrel", "Thistledown",
]

SERIES_PRICES = ["240", "300", "360"]
REFUND_REASONS = [
    "Service rebooked as a courtesy", "Product returned unopened",
    "Guest charged twice at the till", "Appointment shortened on the day",
]


def _at(day, hour, minute, tz):
    return datetime.combine(day, time(hour, minute), tzinfo=tz)


def _round5(amount):
    return (amount / 5).quantize(Decimal("1")) * 5


def seed_demo_salon():
    """Rebuild the demo salon and return a dict of created counts."""
    rng = random.Random(_SEED)
    tz = ZoneInfo(DEMO_TIMEZONE)
    today = datetime.now(tz).date()

    Salon.objects.filter(name=DEMO_SALON_NAME).delete()
    salon = Salon.objects.create(
        name=DEMO_SALON_NAME, timezone=DEMO_TIMEZONE,
        tagline="A fictional salon, seeded for demonstration",
    )
    levels = [
        StaffLevel.objects.create(salon=salon, name=name, sort_order=i)
        for i, (name, _mult) in enumerate(LEVELS)
    ]
    staff = []
    for name, level_idx, weekdays in STAFF:
        member = StaffMember.objects.create(
            salon=salon, display_name=name, staff_level=levels[level_idx],
            email=f"{name.split()[0].lower()}@example.com",
        )
        for weekday in weekdays:
            RosterPattern.objects.create(
                staff_member=member, weekday=weekday,
                start_time=time(9, 0), end_time=time(18, 0),
            )
        staff.append(member)

    services, price_by_service_level = [], {}
    for sort_order, (cat_name, rows) in enumerate(PRICE_BOOK):
        category = ServiceCategory.objects.create(
            salon=salon, name=cat_name, sort_order=sort_order)
        for svc_name, minutes, base in rows:
            service = Service.objects.create(
                category=category, name=svc_name,
                service_minutes=minutes)
            services.append(service)
            for level, (_lname, mult) in zip(levels, LEVELS):
                amount = _round5(Decimal(base) * Decimal(mult))
                ServicePrice.objects.create(
                    service=service, staff_level=level, amount=amount,
                    is_from=svc_name == "Color Correction")
                price_by_service_level[(service.pk, level.pk)] = amount

    products = [
        Product.objects.create(
            salon=salon, name=name, price=Decimal(price),
            sku=f"DEMO-{i + 1:03d}", category_name="Retail")
        for i, (name, price) in enumerate(PRODUCTS)
    ]
    clients = []
    for i in range(80):
        first = FIRST_NAMES[i % len(FIRST_NAMES)]
        last = LAST_NAMES[(i * 7 + 3) % len(LAST_NAMES)]
        clients.append(Client.objects.create(
            salon=salon, first_name=first, last_name=last,
            email=f"{first.lower()}.{last.lower()}{i}@example.com",
            phone=f"555-01{i:02d}",
            sms_opt_in=rng.random() < 0.6, email_opt_in=rng.random() < 0.7,
        ))

    counts = {"appointments": _seed_appointments(
        rng, tz, today, staff, services, clients)}
    counts.update(_seed_sales(
        rng, tz, today, salon, staff, services, products, clients,
        price_by_service_level))
    return {
        "salon": salon, "staff": len(staff), "services": len(services),
        "prices": ServicePrice.objects.filter(
            service__category__salon=salon).count(),
        "products": len(products), "clients": len(clients),
        **counts,
    }


def _seed_appointments(rng, tz, today, staff, services, clients):
    now = datetime.now(tz)
    made = 0

    def book(member, start_dt, service, status):
        nonlocal made
        Appointment.objects.create(
            client=rng.choice(clients), staff_member=member,
            service=service, service_name=service.name,
            start=start_dt,
            end=start_dt + timedelta(minutes=service.total_minutes),
            status=status, origin=rng.choice(Appointment.Origin.values),
        )
        made += 1

    def run_day(member, day, status_for):
        cursor = rng.choice([0, 0, 30])
        while cursor < 480:
            service = rng.choice(services)
            start_dt = _at(day, 9, 0, tz) + timedelta(minutes=cursor)
            book(member, start_dt, service, status_for(start_dt, service))
            cursor += service.total_minutes + rng.choice([0, 15, 30])
            if status_for is not _today_status and rng.random() < 0.4:
                break

    def _today_status(start_dt, service):
        end_dt = start_dt + timedelta(minutes=service.total_minutes)
        if end_dt <= now:
            return Appointment.Status.COMPLETED
        if start_dt <= now:
            return Appointment.Status.IN_SERVICE
        if start_dt <= now + timedelta(minutes=45):
            return Appointment.Status.ARRIVED
        return Appointment.Status.BOOKED

    for member in staff:  # a busy today, judged against the clock
        run_day(member, today, _today_status)
    for member in staff:  # tomorrow: booked, so future value shows
        run_day(member, today + timedelta(days=1),
                lambda start_dt, service: Appointment.Status.BOOKED)
    for back in range(1, 8):  # a scattering over the past week
        day = today - timedelta(days=back)

        def past_status(start_dt, service):
            return rng.choices(
                [Appointment.Status.COMPLETED, Appointment.Status.CANCELLED,
                 Appointment.Status.NO_SHOW], weights=[8, 1, 1])[0]

        for member in rng.sample(staff, k=rng.randint(2, 4)):
            run_day(member, day, past_status)
    return made


def _seed_sales(rng, tz, today, salon, staff, services, products,
                clients, price_by_service_level):
    level_pks = [member.staff_level_id for member in staff]
    sales = refunds = 0
    refundable = []
    for back in range(_SALES_DAYS - 1, -1, -1):
        day = today - timedelta(days=back)
        for _ in range(_SALES_PER_DAY):
            stamp = _at(day, rng.randint(9, 18), rng.choice([0, 15, 30, 45]), tz)
            sale = Sale.objects.create(
                salon=salon, client=rng.choice(clients),
                status=Sale.Status.COMPLETED, completed_at=stamp)
            total = Decimal("0.00")
            for _ in range(rng.randint(1, 3)):
                kind = rng.choices(
                    [SaleItem.Kind.SERVICE, SaleItem.Kind.PRODUCT,
                     SaleItem.Kind.SERIES], weights=[65, 25, 10])[0]
                discount = Decimal("0.00")
                if kind == SaleItem.Kind.SERVICE:
                    service = rng.choice(services)
                    unit = price_by_service_level[
                        (service.pk, rng.choice(level_pks))]
                    if rng.random() < 0.1:
                        discount = Decimal("5.00")
                    item = SaleItem.objects.create(
                        sale=sale, kind=kind, service=service,
                        description=service.name, unit_price=unit,
                        discount_amount=discount)
                elif kind == SaleItem.Kind.PRODUCT:
                    product = rng.choice(products)
                    qty = rng.choice([1, 1, 2])
                    item = SaleItem.objects.create(
                        sale=sale, kind=kind, product=product,
                        description=product.name, quantity=qty,
                        unit_price=product.price)
                else:
                    service = rng.choice(services)
                    item = SaleItem.objects.create(
                        sale=sale, kind=kind, service=service,
                        description=f"Series — {service.name} (6 sessions)",
                        unit_price=Decimal(rng.choice(SERIES_PRICES)))
                total += item.line_total
            method = rng.choice(Payment.Method.values)
            Payment.objects.create(
                sale=sale, method=method, amount=total,
                status=Payment.Status.COMPLETED)
            Sale.objects.filter(pk=sale.pk).update(created_at=stamp)
            sales += 1
            if total >= Decimal("30"):
                refundable.append((sale, method, total))
    for sale, method, total in rng.sample(refundable, k=6):
        refund = Refund.objects.create(
            sale=sale, amount=min(Decimal("20.00"), total),
            tender=method, reason=rng.choice(REFUND_REASONS))
        Refund.objects.filter(pk=refund.pk).update(
            created_at=sale.completed_at + timedelta(days=1))
        refunds += 1
    return {"sales": sales, "refunds": refunds}
