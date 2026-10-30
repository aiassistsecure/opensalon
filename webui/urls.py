from django.urls import path

from . import interactions, views

app_name = "webui"

urlpatterns = [
    path("", views.day_book, name="daybook"),
    path("appointment/new/", interactions.appointment_new, name="appointment_new"),
    path("appointment/copy/", interactions.appointment_copy, name="appointment_copy"),
    path("appointment/<int:appointment_id>/", interactions.breakdown, name="breakdown"),
    path(
        "appointment/<int:appointment_id>/action/<slug:action>/",
        interactions.appointment_action,
        name="appointment_action",
    ),
    path(
        "appointment/<int:appointment_id>/add-service/",
        interactions.add_service,
        name="add_service",
    ),
    path(
        "appointment/<int:appointment_id>/close-out/",
        interactions.close_out,
        name="close_out",
    ),
    path("break/new/", interactions.break_new, name="break_new"),
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
            "title": "Reports",
            "lane_note": "Revenue, future-appointment value and busiest days arrive with the reports lane.",
        },
        name="insights",
    ),
]
