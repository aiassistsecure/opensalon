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
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
