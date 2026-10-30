from django.urls import path

from saloncore.views import price_feed

app_name = "saloncore"

urlpatterns = [
    path("price-feed/", price_feed, name="price-feed"),
]
