from datetime import datetime, timezone
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import AuthSession, User
from app.security import token_hash
from app.services import access

COOKIE = "bj_session"
CSRF_COOKIE = "bj_csrf"
SAFE = {"GET", "HEAD", "OPTIONS"}


def _load(request: Request, db: Session):
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    s = db.query(AuthSession).filter(AuthSession.token_hash == token_hash(token)).first()
    if not s or s.revoked or s.expires_at < datetime.now(timezone.utc):
        return None
    if request.method not in SAFE:
        hdr = request.headers.get("x-csrf-token", "")
        if not hdr or hdr != s.csrf_token:
            raise HTTPException(403, "Security check failed (CSRF). Refresh the page and try again.")
    user = db.get(User, s.user_id)
    if not user or not user.is_active:
        return None
    return user


def optional_principal(request: Request, db: Session = Depends(get_db)):
    user = _load(request, db)
    return access.build_principal(db, user) if user else None


def current_principal(request: Request, db: Session = Depends(get_db)) -> access.Principal:
    user = _load(request, db)
    if not user:
        raise HTTPException(401, "Please sign in.")
    return access.build_principal(db, user)


def staff_principal(p: access.Principal = Depends(current_principal)) -> access.Principal:
    if not p.user.role.is_staff:
        raise HTTPException(403, "Staff access required.")
    return p


def require(*perms: str, any_of: bool = False):
    def dep(p: access.Principal = Depends(staff_principal)) -> access.Principal:
        ok = any(p.can(x) for x in perms) if any_of else all(p.can(x) for x in perms)
        if not ok:
            raise HTTPException(403, "You do not have permission for this action.")
        return p
    return dep


def scope_branch(p: access.Principal, branch_id: int | None, required: bool = False) -> int | None:
    if branch_id is None:
        if required:
            if p.branch_ids is not None and len(p.branch_ids) == 1:
                return next(iter(p.branch_ids))
            raise HTTPException(400, "Select a branch.")
        return None
    if not p.can_branch(branch_id):
        raise HTTPException(403, "You do not have access to that branch.")
    return branch_id


def branch_filter(p: access.Principal, col, requested: int | None = None):
    from sqlalchemy import and_, true
    conds = []
    if requested is not None:
        if not p.can_branch(requested):
            raise HTTPException(403, "You do not have access to that branch.")
        conds.append(col == requested)
    elif p.branch_ids is not None:
        conds.append(col.in_(p.branch_ids or {-1}))
    return and_(true(), *conds)
