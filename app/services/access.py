"""Effective permission + branch-scope calculation."""
from dataclasses import dataclass, field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import User, UserPermission, UserBranch


@dataclass
class Principal:
    user: User
    permissions: set = field(default_factory=set)
    branch_ids: set | None = None  # None => all branches

    @property
    def id(self): return self.user.id
    @property
    def email(self): return self.user.email
    @property
    def role_key(self): return self.user.role.key

    def can(self, perm: str) -> bool:
        return perm in self.permissions

    def can_branch(self, branch_id) -> bool:
        return self.branch_ids is None or (branch_id is not None and branch_id in self.branch_ids)

    @property
    def sees_all(self) -> bool:
        return self.branch_ids is None


def effective_permissions(user, overrides) -> set:
    perms = {p.key for p in user.role.permissions}
    for o in overrides:
        if o.granted:
            perms.add(o.permission.key)
        else:
            perms.discard(o.permission.key)
    return perms


def branch_scope(db: Session, user: User):
    if user.role.all_branches:
        return None
    ids = {r for (r,) in db.execute(select(UserBranch.branch_id).where(UserBranch.user_id == user.id))}
    if user.branch_id:
        ids.add(user.branch_id)
    return ids


def build_principal(db: Session, user: User) -> Principal:
    overrides = db.query(UserPermission).filter(UserPermission.user_id == user.id).all()
    return Principal(user=user, permissions=effective_permissions(user, overrides), branch_ids=branch_scope(db, user))


def users_with_permission(db: Session, perm: str, branch_id: int | None = None) -> list[User]:
    out = []
    for u in db.query(User).filter(User.is_active == True).all():  # noqa: E712
        if not u.role.is_staff:
            continue
        pr = build_principal(db, u)
        if perm in pr.permissions and (branch_id is None or pr.can_branch(branch_id)):
            out.append(u)
    return out
