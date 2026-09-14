"""Staff role group names and helpers.

ISO 9001 segregation of duties: Procurement evaluates; Director approves.
A user may belong to multiple groups, but workflows still require both steps.
"""

from __future__ import annotations

from django.contrib.auth.models import Group, User

# Canonical Django Group names (seeded by `seed_roles` management command)
SYSTEM_ADMIN = "System Admin"
PROCUREMENT = "Procurement"
DIRECTOR = "Director"
VIEWER = "Viewer"

STAFF_GROUP_NAMES: tuple[str, ...] = (
    SYSTEM_ADMIN,
    PROCUREMENT,
    DIRECTOR,
    VIEWER,
)


def user_in_group(user: User, group_name: str) -> bool:
    """Return True if the user is authenticated and in the named group."""
    if not user.is_authenticated:
        return False
    return user.groups.filter(name=group_name).exists()


def is_staff_user(user: User) -> bool:
    """True when the user holds any staff VMS role (or Django is_staff)."""
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(name__in=STAFF_GROUP_NAMES).exists()


def is_vendor_user(user: User) -> bool:
    """Vendors are authenticated users who are not in staff role groups."""
    if not user.is_authenticated:
        return False
    return not is_staff_user(user)


def ensure_role_groups() -> list[Group]:
    """Create missing role groups; return all staff groups."""
    groups: list[Group] = []
    for name in STAFF_GROUP_NAMES:
        group, _created = Group.objects.get_or_create(name=name)
        groups.append(group)
    return groups
