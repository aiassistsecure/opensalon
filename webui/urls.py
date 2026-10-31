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
    path("daybook/fragment/", views.day_book_fragment, name="daybook_fragment"),
    path("daybook/move/", views.day_book_move, name="daybook_move"),
    path("daybook/status/", views.day_book_status, name="daybook_status"),
    path("daybook/book/", views.day_book_book, name="daybook_book"),
    path("daybook/book/options/", views.day_book_book_options, name="daybook_book_options"),
    path("daybook/clients/search/", views.day_book_client_search, name="daybook_client_search"),
    path("daybook/pack/", views.day_book_pack, name="daybook_pack"),
    path("daybook/apply/", views.day_book_apply, name="daybook_apply"),
    path("daybook/price/", views.day_book_price, name="daybook_price"),
    path("daybook/checkout/", views.day_book_checkout, name="daybook_checkout"),
    path("daybook/products/", views.day_book_products, name="daybook_products"),
    path("daybook/note/", views.day_book_note, name="daybook_note"),
    path("price-book/", views.price_book, name="pricebook"),
    path("clients/", views.clients, name="clients"),
    path("team/", views.team, name="team"),
    path("roster/", views.roster_book, name="roster"),
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
    path("pos/", views.pos, name="pos"),
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
