"""factory_boy factories for teams (E10)."""

import factory

from apps.teams.models import (
    Entity,
    EntityStatus,
    TeamMember,
    TeamMemberStatus,
    TeamRole,
    default_invite_expiry,
    new_invite_token,
)
from apps.vendors.factories import UserFactory


class TeamMemberFactory(factory.django.DjangoModelFactory):
    """Defaults to a pending invitation, which is the state that occupies a
    seat without a linked user — the case most worth exercising."""

    class Meta:
        model = TeamMember

    account = factory.SubFactory(UserFactory)
    user = None
    email = factory.Sequence(lambda n: f"member{n}@example.com")
    role = TeamRole.MEMBER
    status = TeamMemberStatus.INVITED
    invite_token = factory.LazyFunction(new_invite_token)
    invite_expires_at = factory.LazyFunction(default_invite_expiry)


class ActiveMemberFactory(TeamMemberFactory):
    status = TeamMemberStatus.ACTIVE
    user = factory.SubFactory(UserFactory)
    invite_token = ""
    invite_expires_at = None


class EntityFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Entity

    account = factory.SubFactory(UserFactory)
    legal_name = factory.Sequence(lambda n: f"Acme Holdings {n} LLC")
    ein = "12-3456789"
    status = EntityStatus.ACTIVE
