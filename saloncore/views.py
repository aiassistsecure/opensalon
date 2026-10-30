from django.http import JsonResponse
from django.views.decorators.http import require_GET

from saloncore.models import ServicePrice


@require_GET
def price_feed(request):
    """Public read-only JSON feed of the active price book.

    Prices are public by design (price transparency). Only current
    prices are exposed: a category, service, staff level, and price
    must all be ``active`` to appear. No client data is included.
    """
    prices = (
        ServicePrice.objects.filter(
            active=True,
            service__active=True,
            service__category__active=True,
            staff_level__active=True,
        )
        .select_related("service", "service__category", "staff_level")
        .order_by(
            "service__category__sort_order",
            "service__category__name",
            "service__name",
            "staff_level__sort_order",
            "staff_level__name",
        )
    )
    categories = {}
    for price in prices:
        category = price.service.category
        cat_entry = categories.setdefault(
            category.pk, {"name": category.name, "services": {}}
        )
        svc_entry = cat_entry["services"].setdefault(
            price.service.pk,
            {
                "name": price.service.name,
                "description": price.service.description,
                "total_minutes": price.service.total_minutes,
                "prices": [],
            },
        )
        svc_entry["prices"].append(
            {
                "staff_level": price.staff_level.name,
                "amount": str(price.amount),
                "is_from": price.is_from,
            }
        )
    payload = {
        "categories": [
            {
                "name": cat["name"],
                "services": list(cat["services"].values()),
            }
            for cat in categories.values()
        ]
    }
    return JsonResponse(payload)
