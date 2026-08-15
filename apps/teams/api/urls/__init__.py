from django.urls import path

from apps.teams.api.views.team import (
    EntityDetailAPIView,
    EntityListAPIView,
    MyRoleAPIView,
    TeamInviteAcceptAPIView,
    TeamInviteAPIView,
    TeamMemberDetailAPIView,
    TeamMemberListAPIView,
)

urlpatterns = [
    path("/members", TeamMemberListAPIView.as_view(), name="team-members"),
    path(
        "/members/<uuid:member_id>",
        TeamMemberDetailAPIView.as_view(),
        name="team-member-detail",
    ),
    path("/me", MyRoleAPIView.as_view(), name="team-my-role"),
    path("/invite", TeamInviteAPIView.as_view(), name="team-invite"),
    path(
        "/invite/accept",
        TeamInviteAcceptAPIView.as_view(),
        name="team-invite-accept",
    ),
    path("/entities", EntityListAPIView.as_view(), name="team-entities"),
    path(
        "/entities/<uuid:entity_id>",
        EntityDetailAPIView.as_view(),
        name="team-entity-detail",
    ),
]
