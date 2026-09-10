"""Routes for the four-screen CompetitorScope PoC frontend."""

from __future__ import annotations

from django.urls import path

from . import views


urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("competitors/create/", views.create_competitor, name="create_competitor"),
    path("competitors/<str:competitor_id>/", views.competitor_detail, name="competitor_detail"),
    path("competitors/<str:competitor_id>/edit/", views.update_competitor, name="update_competitor"),
    path("competitors/<str:competitor_id>/delete/", views.delete_competitor, name="delete_competitor"),
    path("competitors/<str:competitor_id>/discover/", views.run_discovery, name="run_discovery"),
    path(
        "competitors/<str:competitor_id>/candidates/<str:candidate_id>/activate/",
        views.activate_candidate,
        name="activate_candidate",
    ),
    path(
        "competitors/<str:competitor_id>/candidates/<str:candidate_id>/discard/",
        views.discard_candidate,
        name="discard_candidate",
    ),
    path(
        "competitors/<str:competitor_id>/candidates/<str:candidate_id>/edit/",
        views.edit_candidate,
        name="edit_candidate",
    ),
    path(
        "competitors/<str:competitor_id>/candidates/<str:candidate_id>/delete/",
        views.delete_candidate,
        name="delete_candidate",
    ),
    path(
        "competitors/<str:competitor_id>/targets/add/",
        views.add_manual_target,
        name="add_manual_target",
    ),
    path(
        "competitors/<str:competitor_id>/targets/<str:target_id>/deactivate/",
        views.deactivate_target,
        name="deactivate_target",
    ),
    path(
        "competitors/<str:competitor_id>/targets/<str:target_id>/delete/",
        views.delete_target,
        name="delete_target",
    ),
    path("changes/", views.changes_feed, name="changes_feed"),
]
