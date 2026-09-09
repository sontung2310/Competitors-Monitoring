"""Minimal Django settings for the server-rendered CompetitorScope PoC."""

from __future__ import annotations

import os
from pathlib import Path


FRONTEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_DIR = FRONTEND_DIR.parents[1]

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "competitorscope-development-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [host.strip() for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if host.strip()]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "monitoring",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [FRONTEND_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.static",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": REPOSITORY_DIR / "frontend.sqlite3",
    },
}

LANGUAGE_CODE = "en-au"
TIME_ZONE = "Australia/Melbourne"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [FRONTEND_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

FLASK_API_BASE_URL = os.environ.get("FLASK_API_BASE_URL", "http://localhost:5000/api")
FLASK_API_TIMEOUT_SECONDS = float(os.environ.get("FLASK_API_TIMEOUT_SECONDS", "60"))
