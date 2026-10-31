"""OpenSalon project settings.

Foundation settings: deliberately minimal. Environment-driven secrets.
The database is NEDB, reached over its Postgres-compatible pgwire using
the custom NEDB backend (opensalon.backends.nedb, see ADR 0005), which
neutralizes set_config/session setup that nedbd refuses (DYOR §9.1-2).
Host, name, user, password and port are env-driven with NEDB-shaped
defaults. SQLite is available only behind the explicit
OPENSALON_USE_SQLITE=1 flag, as a dev fallback.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("OPENSALON_SECRET_KEY", "dev-only-change-me")
DEBUG = os.environ.get("OPENSALON_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("OPENSALON_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "saloncore",
    "clients",
    "team",
    "catalog",
    "bookings",
    "checkout",
    "insights",
    "messaging",
    "onlinebooking",
    "webui",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "opensalon.urls"
WSGI_APPLICATION = "opensalon.wsgi.application"
ASGI_APPLICATION = "opensalon.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "webui.context_processors.salon_context",
            ],
        },
    },
]

if os.environ.get("OPENSALON_USE_SQLITE") == "1":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "opensalon.backends.nedb",
            "HOST": os.environ.get("POSTGRES_HOST", "nedbd"),
            "NAME": os.environ.get("POSTGRES_DB", "opensalon"),
            "USER": os.environ.get("POSTGRES_USER", "opensalon"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "PORT": int(os.environ.get("POSTGRES_PORT", "5432")),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
# Deployment default timezone; a salon's own locale lives on
# Salon.timezone. Set OPENSALON_TIME_ZONE to the salon-local zone
# (e.g. America/New_York) for a single-salon deployment.
TIME_ZONE = os.environ.get("OPENSALON_TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

# Email: the salon's own mail server over standard SMTP settings.
# No vendor email API; core only uses django.core.mail.
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "1") == "1"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "salon@localhost")

# SMS: provider-agnostic. Core speaks only messaging.adapters.SmsAdapter;
# this setting is a dotted path to an adapter class. The default is the
# console/no-op development adapter; a real provider adapter lives
# outside core and is supplied by the salon/deployment.
MESSAGING_SMS_ADAPTER = os.environ.get(
    "MESSAGING_SMS_ADAPTER", "messaging.adapters.ConsoleSmsAdapter"
)

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
