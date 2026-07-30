"""Entity scoping for account-owned data (E10-S3).

The rule is deliberately narrow: **filtering only happens when the account
actually has entities.** A single-entity account has none, every row's
``entity`` is null, and every query behaves exactly as it did before E10 —
which is what makes this safe to add to models that already hold live data.

Kept as one function so the rule lives in one place. Reimplementing
`if entity: filter(...)` at each call site is how one list view ends up
leaking another entity's bills.
"""

from apps.teams.models import Entity, EntityStatus


def has_entities(account):
    return Entity.objects.filter(
        account=account, status=EntityStatus.ACTIVE
    ).exists()


def scope_to_entity(queryset, account, entity_id=None):
    """Narrow ``queryset`` to one entity, when entities are in play.

    ``entity_id`` of None means "everything on this account", which is the
    right default: an owner looking at the account overview wants the whole
    picture, not an arbitrary entity's slice.

    An id that does not belong to this account matches nothing rather than
    raising — the queryset is already account-scoped by its caller, so a
    foreign id is simply not found.
    """
    if entity_id is None:
        return queryset

    if not has_entities(account):
        # Nothing is scoped yet, so an entity filter would silently return
        # empty. Ignoring it keeps a stale client parameter harmless.
        return queryset

    return queryset.filter(entity_id=entity_id)


def default_entity(account):
    """The entity to stamp on newly created data.

    None unless the account has exactly one, in which case that one is
    unambiguous. With several, the caller must say which — guessing would
    file a bill against the wrong company.
    """
    entities = list(
        Entity.objects.filter(
            account=account, status=EntityStatus.ACTIVE
        )[:2]
    )

    return entities[0] if len(entities) == 1 else None
