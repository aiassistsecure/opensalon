"""Salon identity + theme for every webui page.

The shell is branded BY THE SALON, never hard-branded to OpenSalon:
the salon's name comes from its Salon record, and theme values are
plain data (CSS custom properties) so a salon's own logo and colours
can drop in later without template changes. Until Salon carries
branding fields, DEFAULT_THEME supplies the house palette.
"""

from saloncore.models import Salon

DEFAULT_THEME = {
    "primary": "#2f7bff",  # electric blue
    "accent": "#8b5cf6",  # violet
    "ground": "#050914",  # deep navy
}


def salon_context(request):
    # UI theme (the deep-navy glass theme, approved 2026-10-30): the
    # theme is dark-born; there is no light variant in this build.
    salon = Salon.objects.order_by("id").first()
    return {
        "salon": salon,
        "salon_theme": DEFAULT_THEME,
    }
