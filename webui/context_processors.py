"""Salon identity + theme for every webui page.

The shell is branded BY THE SALON, never hard-branded to OpenSalon:
the salon's name comes from its Salon record, and theme values are
plain data (CSS custom properties) so a salon's own logo and colours
can drop in later without template changes. Until Salon carries
branding fields, DEFAULT_THEME supplies the house palette.
"""

import hashlib
import os

from django.contrib.staticfiles.finders import find as _static_find

from saloncore.models import Salon

DEFAULT_THEME = {
    "primary": "#2f7bff",  # electric blue
    "accent": "#8b5cf6",  # violet
    "ground": "#050914",  # deep navy
}

_ASSET_FILES = ("webui/webui.css", "webui/webui.js", "webui/shadow.js")
_asset_cache = {}


def _asset_version():
    """A short hash of the shell assets' contents, for ?v= cache
    busting. A salon box that pulls new code must never keep
    running yesterday's JS from the browser cache — that skew has
    already impersonated three separate bugs. Recomputed only
    when a file's mtime/size moves; cheap per request."""
    digest = hashlib.sha256()
    for rel in _ASSET_FILES:
        path = _static_find(rel)
        if not path:
            continue
        try:
            stat = os.stat(path)
        except OSError:
            continue
        key = (stat.st_mtime_ns, stat.st_size)
        cached = _asset_cache.get(rel)
        if cached is None or cached[0] != key:
            try:
                with open(path, "rb") as handle:
                    file_hash = hashlib.sha256(handle.read()).hexdigest()[:10]
            except OSError:
                continue
            cached = (key, file_hash)
            _asset_cache[rel] = cached
        digest.update(cached[1].encode())
    return digest.hexdigest()[:12]


def salon_context(request):
    # UI theme (the deep-navy glass theme, approved 2026-10-30): the
    # theme is dark-born; there is no light variant in this build.
    salon = Salon.objects.order_by("id").first()
    return {
        "salon": salon,
        "salon_theme": DEFAULT_THEME,
        "asset_v": _asset_version(),
    }
