from django.urls import path

from . import views

app_name = "webui"

urlpatterns = [
    path(
        "home/",
        views.placeholder,
        {
            "nav_key": "home",
            "title": "Home",
            "lane_note": "The salon home screen arrives with a later lane.",
        },
        name="home",
    ),
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
    path(
        "pos/",
        views.placeholder,
        {
            "nav_key": "pos",
            "title": "POS",
            "lane_note": "Checkout and cashup arrive with the payments lane.",
        },
        name="pos",
    ),
    path(
        "automations/",
        views.placeholder,
        {
            "nav_key": "automations",
            "title": "Automations",
            "lane_note": "Reminders and campaigns arrive with the messaging lane.",
        },
        name="automations",
    ),
    path(
        "settings/",
        views.placeholder,
        {
            "nav_key": "settings",
            "title": "Settings",
            "lane_note": "Salon settings arrive with a later lane.",
        },
        name="settings",
    ),
]
