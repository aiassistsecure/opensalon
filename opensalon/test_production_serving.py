"""Production-serving pins: Waitress + WhiteNoise replace runserver.

Waitress serves the WSGI app as one process (the embedded NEDB store
allows a single opener), and WhiteNoise serves /static/ because under
WSGI nothing else does. These tests pin the settings shape that the
production run documented in README.md depends on.
"""
from django.conf import settings
from django.test import SimpleTestCase


class ProductionServingSettingsTests(SimpleTestCase):
    def test_whitenoise_immediately_after_security_middleware(self):
        middleware = list(settings.MIDDLEWARE)
        security = middleware.index(
            "django.middleware.security.SecurityMiddleware"
        )
        self.assertEqual(
            middleware[security + 1],
            "whitenoise.middleware.WhiteNoiseMiddleware",
        )

    def test_static_root_set(self):
        self.assertTrue(settings.STATIC_ROOT)
        self.assertEqual(
            settings.STATIC_ROOT, settings.BASE_DIR / "staticfiles"
        )

    def test_wsgi_application_importable(self):
        from opensalon.wsgi import application

        self.assertTrue(callable(application))

    def test_production_packages_declared(self):
        requirements = (
            settings.BASE_DIR / "requirements.txt"
        ).read_text()
        self.assertIn("waitress", requirements)
        self.assertIn("whitenoise", requirements)
