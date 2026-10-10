from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.teams.models import Entity, TeamMember, TeamRole
from apps.teams.permissions import capabilities_for


class TeamMemberSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    capabilities = serializers.SerializerMethodField()
    invite_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = TeamMember
        # invite_token is deliberately absent: it is a bearer credential and
        # belongs only in the invitee's email, never in a list any teammate
        # can read.
        fields = (
            "id",
            "email",
            "name",
            "role",
            "status",
            "capabilities",
            "invite_expired",
            "invite_expires_at",
            "accepted_at",
            "created_at",
        )

    @extend_schema_field(
        serializers.CharField(
            allow_null=True, help_text="null until the invite is accepted."
        )
    )
    def get_name(self, member):
        if member.user is None:
            return None

        full = f"{member.user.first_name} {member.user.last_name}".strip()

        return full or None

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_capabilities(self, member):
        return capabilities_for(member.role)


class InviteSerializer(serializers.Serializer):
    email = serializers.EmailField()
    # No default. A default would make "resend this invitation" — which sends
    # no role — indistinguishable from "invite them as a member", silently
    # demoting a pending admin. The service decides: new invite defaults to
    # MEMBER, resend keeps the role already chosen.
    role = serializers.ChoiceField(
        choices=[
            (TeamRole.ADMIN, TeamRole.ADMIN.label),
            (TeamRole.MEMBER, TeamRole.MEMBER.label),
        ],
        required=False,
    )


class AcceptInviteSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=64)


class ChangeRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(
        choices=[
            (TeamRole.ADMIN, TeamRole.ADMIN.label),
            (TeamRole.MEMBER, TeamRole.MEMBER.label),
        ]
    )


class EntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Entity
        fields = ("id", "legal_name", "ein", "status", "created_at")


class EntityWriteSerializer(serializers.Serializer):
    legal_name = serializers.CharField(max_length=150)
    ein = serializers.CharField(
        max_length=20, required=False, allow_blank=True, default=""
    )


class MyRoleSerializer(serializers.Serializer):
    account_id = serializers.UUIDField(help_text="The account acted on.")
    is_owner = serializers.BooleanField()
    role = serializers.ChoiceField(choices=TeamRole.choices)
    capabilities = serializers.ListField(
        child=serializers.CharField(),
        help_text="e.g. manage_billing, send_money: what this role may do.",
    )
