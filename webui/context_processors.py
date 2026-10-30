"""Salon identity + theme for every webui page.

The shell is branded BY THE SALON, never hard-branded to OpenSalon:
the salon's name comes from its Salon record, and theme values are
plain data (CSS custom properties) so a salon's own logo and colours
can drop in later without template changes. Until Salon carries
branding fields, DEFAULT_THEME supplies the house palette.
"""

from saloncore.models import Salon

DEFAULT_THEME = {
    "primary": "#26503c",  # deep forest (the approved mock's band)
    "accent": "#c9a227",  # mock gold
    "ground": "#f4efe3",  # creme
}


def salon_context(request):
    salon = Salon.objects.order_by("id").first()
    from django.utils import timezone

    return {
        "salon": salon,
        "salon_theme": DEFAULT_THEME,
        "today": timezone.localdate(),
        # Sidebar width, persisted in a cookie by the toggle (see
        # views.sidebar_toggle). Read server-side so the first paint
        # is already the right width — no flash of the wrong state.
        "sidebar_rail": request.COOKIES.get("os_sidebar") == "rail",
    }
