"""Salon identity + theme for every webui page.

The shell is branded BY THE SALON, never hard-branded to OpenSalon:
the salon's name comes from its Salon record, and theme values are
plain data (CSS custom properties) so a salon's own logo and colours
can drop in later without template changes. Until Salon carries
branding fields, DEFAULT_THEME supplies the house palette.
"""

from saloncore.models import Salon

DEFAULT_THEME = {
    "primary": "#2e4b34",  # deep forest
    "accent": "#b8862f",  # embossed gold
    "ground": "#f7f2e7",  # creme
}


def salon_context(request):
    salon = Salon.objects.order_by("id").first()
    return {"salon": salon, "salon_theme": DEFAULT_THEME}
