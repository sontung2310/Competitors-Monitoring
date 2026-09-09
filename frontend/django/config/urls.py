"""URL configuration for the Django frontend."""

from __future__ import annotations

from django.urls import include, path


urlpatterns = [
    path("", include("monitoring.urls")),
]
