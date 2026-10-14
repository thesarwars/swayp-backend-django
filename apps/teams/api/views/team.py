"""Team and entity endpoints (E10-S1 … E10-S3)."""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status

from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse
from apps.teams.api.serializers.team import (
    MyRoleSerializer,
    AcceptInviteSerializer,
    ChangeRoleSerializer,
    EntitySerializer,
    EntityWriteSerializer,
    InviteSerializer,
    TeamMemberSerializer,
)
from apps.teams.permissions import capabilities_for
from apps.teams.services.entity_service import EntityService
from apps.teams.services.team_service import TeamService


class TeamContextMixin:
    """Resolves which account the caller is acting on.

    A user who was invited into someone else's account acts on *that* account,
    not their own. Getting this wrong would silently give every invited member
    a private empty account of their own instead of access to the team's.
    """

    def account_for(self, request):
        membership = TeamService().membership_for(request.user)

        if membership is not None:
            return membership.account

        return request.user


@extend_schema(
    tags=["Teams"],
    summary="Team members",
    description=(
        "Everyone on the account, including the owner. A pending invitation "
        "occupies a seat."
    ),
    responses={200: TeamMemberSerializer(many=True)},
)
class TeamMemberListAPIView(TeamContextMixin, BaseAPIView):

    service_class = TeamService

    def get(self, request):
        account = self.account_for(request)
        self.service.ensure_owner_seat(account)

        members = self.service.members(account).select_related("user")

        return ApiResponse.success(
            data=TeamMemberSerializer(members, many=True).data,
            message="Team members fetched successfully.",
        )


@extend_schema(
    tags=["Teams"],
    summary="My role",
    description=(
        "The caller's role on the account and the capabilities it grants. "
        "Use it to hide what the user cannot do — the API enforces it too."
    ),
    responses={200: MyRoleSerializer},
)
class MyRoleAPIView(TeamContextMixin, BaseAPIView):

    service_class = TeamService

    def get(self, request):
        account = self.account_for(request)
        self.service.ensure_owner_seat(account)

        role = self.service.role_for(request.user, account)

        return ApiResponse.success(
            data={
                "account_id": account.id,
                "is_owner": account == request.user,
                "role": role,
                "capabilities": capabilities_for(role),
            },
            message="Role fetched successfully.",
        )


@extend_schema(
    tags=["Teams"],
    summary="Invite a team member",
    description=(
        "Sends an invitation email and takes a seat immediately. Returns 402 "
        "when the plan's seat limit is reached."
    ),
    request=InviteSerializer,
    responses={
        201: TeamMemberSerializer,
        402: OpenApiResponse(description="Seat limit reached (code plan_limit, limit SEATS)."),
        403: OpenApiResponse(description="Role may not manage the team (code role_forbidden)."),
    },
)
class TeamInviteAPIView(TeamContextMixin, BaseAPIView):

    service_class = TeamService

    def post(self, request):
        serializer = InviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        member = self.service.invite(
            account=self.account_for(request),
            inviter=request.user,
            email=serializer.validated_data["email"],
            role=serializer.validated_data.get("role"),
        )

        return ApiResponse.success(
            data=TeamMemberSerializer(member).data,
            message="Invitation sent.",
            status_code=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Teams"],
    summary="Accept an invitation",
    description=(
        "Links the signed-in user to the invitation. The token is single-use "
        "and expires after 14 days."
    ),
    request=AcceptInviteSerializer,
    responses={200: TeamMemberSerializer},
)
class TeamInviteAcceptAPIView(BaseAPIView):

    service_class = TeamService

    def post(self, request):
        serializer = AcceptInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        member = self.service.accept(
            token=serializer.validated_data["token"], user=request.user
        )

        return ApiResponse.success(
            data=TeamMemberSerializer(member).data,
            message="Invitation accepted.",
        )


@extend_schema(
    tags=["Teams"],
    summary="Change a role or remove a member",
    responses={200: TeamMemberSerializer},
)
class TeamMemberDetailAPIView(TeamContextMixin, BaseAPIView):

    service_class = TeamService

    @extend_schema(
        summary="Change a member's role",
        request=ChangeRoleSerializer,
        responses={200: TeamMemberSerializer},
    )
    def patch(self, request, member_id):
        serializer = ChangeRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        member = self.service.change_role(
            account=self.account_for(request),
            actor=request.user,
            member_id=member_id,
            # Required here, unlike invite: changing a role with no role is
            # meaningless, so the serializer rejects it before this runs.
            role=serializer.validated_data["role"],
        )

        return ApiResponse.success(
            data=TeamMemberSerializer(member).data,
            message="Role updated.",
        )

    @extend_schema(
        summary="Remove a member",
        description="Answers the removed member; their seat is freed.",
        request=None,
        responses={200: TeamMemberSerializer},
    )
    def delete(self, request, member_id):
        member = self.service.remove(
            account=self.account_for(request),
            actor=request.user,
            member_id=member_id,
        )

        return ApiResponse.success(
            data=TeamMemberSerializer(member).data,
            message="Team member removed.",
        )


# --- entities (E10-S3) -----------------------------------------------------


@extend_schema(
    tags=["Teams"],
    summary="Entities",
    description=(
        "Legal entities under the account. A second entity requires the "
        "Enterprise plan, and each one beyond the included three bills $79."
    ),
    responses={200: EntitySerializer(many=True)},
)
class EntityListAPIView(TeamContextMixin, BaseAPIView):

    service_class = EntityService

    def get(self, request):
        account = self.account_for(request)

        return ApiResponse.success(
            data=EntitySerializer(
                self.service.active(account), many=True
            ).data,
            message="Entities fetched successfully.",
        )

    @extend_schema(
        summary="Add an entity",
        description="Enterprise only (402 otherwise). 403 without manage_entities.",
        request=EntityWriteSerializer,
        responses={
            201: EntitySerializer,
            402: OpenApiResponse(description="Entities are Enterprise only (code plan_limit)."),
            403: OpenApiResponse(description="Role may not manage entities."),
        },
    )
    def post(self, request):
        account = self.account_for(request)

        TeamService().assert_can(
            user=request.user,
            account=account,
            capability="manage_entities",
        )

        serializer = EntityWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        entity = self.service.create(
            account=account,
            legal_name=serializer.validated_data["legal_name"],
            ein=serializer.validated_data.get("ein", ""),
        )

        return ApiResponse.success(
            data=EntitySerializer(entity).data,
            message="Entity created.",
            status_code=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Teams"],
    summary="Update or archive an entity",
    responses={200: EntitySerializer},
)
class EntityDetailAPIView(TeamContextMixin, BaseAPIView):

    service_class = EntityService

    @extend_schema(
        summary="Rename an entity",
        request=EntityWriteSerializer,
        responses={200: EntitySerializer},
    )
    def patch(self, request, entity_id):
        account = self.account_for(request)

        TeamService().assert_can(
            user=request.user,
            account=account,
            capability="manage_entities",
        )

        serializer = EntityWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        entity = self.service.update(
            account=account,
            entity_id=entity_id,
            legal_name=serializer.validated_data.get("legal_name"),
            ein=serializer.validated_data.get("ein"),
        )

        return ApiResponse.success(
            data=EntitySerializer(entity).data,
            message="Entity updated.",
        )

    @extend_schema(
        summary="Archive an entity",
        description="Answers the archived entity.",
        request=None,
        responses={200: EntitySerializer},
    )
    def delete(self, request, entity_id):
        """Archives rather than deletes — payments still reference it."""
        account = self.account_for(request)

        TeamService().assert_can(
            user=request.user,
            account=account,
            capability="manage_entities",
        )

        entity = self.service.archive(account=account, entity_id=entity_id)

        return ApiResponse.success(
            data=EntitySerializer(entity).data,
            message="Entity archived.",
        )
