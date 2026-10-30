from django.urls import path

from . import views

app_name = "webui"

urlpatterns = [
    path("", views.day_book, name="daybook"),
    path("price-book/", views.price_book, name="pricebook"),
    path("clients/", views.clients, name="clients"),
    path(
        "team/",
        views.placeholder,
        {
            "nav_key": "team",
            "title": "Team & Roster",
            "lane_note": "Roster patterns and check-in/out arrive with the team lane.",
        },
        name="team",
    ),
    path(
        "products/",
        views.placeholder,
        {
            "nav_key": "products",
            "title": "Products",
            "lane_note": "Retail products and barcode stocktake arrive with the catalog lane.",
        },
        name="products",
    ),
    path(
        "insights/",
        views.placeholder,
        {
            "nav_key": "insights",
            "title": "Insights",
            "lane_note": "Revenue, future-appointment value and busiest days arrive with the insights lane.",
        },
        name="insights",
    ),
]
