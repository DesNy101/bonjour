from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies.auth import require, staff_principal, current_principal
from app.models import (User, Role, Permission, UserPermission, UserBranch, AuthSession, Driver, Branch, RolePermission)
from app.permissions import PERMISSIONS
from app.schemas.common import StaffIn, StaffUpdate, RolePermsIn
from app.security import hash_password, password_problem, temp_password
from app.serializers import user_out
from app.services import audit, access, settings_service
from app.utils.common import bad

router = APIRouter(prefix="/api", tags=["Staff & Roles"])
PRIVILEGED = {"super_admin", "general_manager"}


def _staff_detail(db, u):
    pr = access.build_principal(db, u)
    d = user_out(u, pr.permissions)
    d["overrides"] = {o.permission.key: o.granted for o in db.query(UserPermission).filter(UserPermission.user_id == u.id)}
    d["extra_branch_ids"] = [r.branch_id for r in db.query(UserBranch).filter(UserBranch.user_id == u.id)]
    return d


@router.get("/staff")
def list_staff(q: str = "", role: str = "", branch_id: int | None = None, active: bool | None = None, page: int = 1, size: int = 50,
               p=Depends(require("staff.view")), db: Session = Depends(get_db)):
    qs = db.query(User).join(Role, Role.id == User.role_id).filter(Role.is_staff == True)  # noqa
    if q:
        qs = qs.filter(or_(User.full_name.ilike(f"%{q}%"), User.email.ilike(f"%{q}%"), User.employee_id.ilike(f"%{q}%")))
    if role:
        qs = qs.filter(Role.key == role)
    if branch_id:
        qs = qs.filter(User.branch_id == branch_id)
    if active is not None:
        qs = qs.filter(User.is_active == active)
    if p.branch_ids is not None:
        qs = qs.filter(User.branch_id.in_(p.branch_ids or {-1}))
    total = qs.count()
    rows = qs.order_by(User.full_name).offset((page - 1) * size).limit(size).all()
    return {"total": total, "items": [user_out(u) for u in rows]}


@router.get("/staff/{uid}")
def get_staff(uid: int, p=Depends(require("staff.view")), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or not u.role.is_staff or not p.can_branch(u.branch_id) and p.branch_ids is not None:
        raise HTTPException(404, "Staff member not found.")
    return _staff_detail(db, u)


def _check_role_assign(p, role: Role):
    if role.key == "customer":
        bad("Customers register themselves on the storefront.")
    if role.key in PRIVILEGED and p.role_key != "super_admin":
        bad("Only the Super Administrator can assign this role.", 403)


@router.post("/staff", status_code=201)
def create_staff(body: StaffIn, request: Request, p=Depends(require("staff.manage")), db: Session = Depends(get_db)):
    role = db.query(Role).filter(Role.key == body.role_key).first()
    if not role:
        bad("Unknown role.")
    _check_role_assign(p, role)
    email = body.email.lower()
    if db.query(User).filter(User.email == email).first():
        bad("A user with this email already exists.", 409)
    if body.employee_id and db.query(User).filter(User.employee_id == body.employee_id).first():
        bad("Employee ID is already in use.", 409)
    if body.branch_id and not p.can_branch(body.branch_id):
        bad("You cannot assign staff to that branch.", 403)
    pw = body.password or temp_password()
    problem = password_problem(pw)
    if problem:
        bad(problem)
    u = User(email=email, full_name=body.full_name, phone=body.phone, password_hash=hash_password(pw), role_id=role.id,
             branch_id=body.branch_id, employee_id=body.employee_id or None, department=body.department,
             job_title=body.job_title, must_change_password=True, work_schedule=body.work_schedule,
             is_demo=settings_service.is_demo_mode(db))
    db.add(u)
    db.flush()
    for bid in body.extra_branch_ids:
        db.add(UserBranch(user_id=u.id, branch_id=bid))
    if role.key == "driver":
        db.add(Driver(user_id=u.id, license_no=body.license_no, phone=body.phone, branch_id=body.branch_id, is_demo=u.is_demo))
    audit.log(db, p.user, "staff_created", "user", u.id, {"email": email, "role": role.key}, request)
    db.commit()
    db.refresh(u)
    out = _staff_detail(db, u)
    if not body.password:
        out["temporary_password"] = pw  # shown once to the administrator
    return out


@router.patch("/staff/{uid}")
def update_staff(uid: int, body: StaffUpdate, request: Request, p=Depends(require("staff.manage")), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or not u.role.is_staff:
        raise HTTPException(404, "Staff member not found.")
    if u.role.key in PRIVILEGED and p.role_key != "super_admin":
        bad("Only the Super Administrator can modify this account.", 403)
    changes = {}
    if body.role_key and body.role_key != u.role.key:
        role = db.query(Role).filter(Role.key == body.role_key).first()
        if not role:
            bad("Unknown role.")
        _check_role_assign(p, role)
        if u.id == p.id:
            bad("You cannot change your own role.")
        if u.role.key == "super_admin" and db.query(User).join(Role).filter(Role.key == "super_admin", User.is_active == True).count() <= 1:  # noqa
            bad("At least one active Super Administrator is required.")
        changes["role"] = [u.role.key, role.key]
        u.role_id = role.id
        db.flush()
        db.refresh(u)
        if role.key == "driver" and not db.query(Driver).filter(Driver.user_id == u.id).first():
            db.add(Driver(user_id=u.id, phone=u.phone, branch_id=u.branch_id, is_demo=u.is_demo))
        for s in db.query(AuthSession).filter(AuthSession.user_id == u.id):
            s.revoked = True  # force re-login with the new permissions
    if body.is_active is not None and body.is_active != u.is_active:
        if u.id == p.id:
            bad("You cannot deactivate your own account.")
        if not body.is_active and u.role.key == "super_admin" and db.query(User).join(Role).filter(Role.key == "super_admin", User.is_active == True).count() <= 1:  # noqa
            bad("At least one active Super Administrator is required.")
        u.is_active = body.is_active
        changes["is_active"] = body.is_active
        if not body.is_active:
            for s in db.query(AuthSession).filter(AuthSession.user_id == u.id):
                s.revoked = True
            drv = db.query(Driver).filter(Driver.user_id == u.id).first()
            if drv:
                drv.is_active = False
    for f in ("full_name", "phone", "department", "job_title", "work_schedule", "employee_id"):
        v = getattr(body, f)
        if v is not None:
            setattr(u, f, v or None if f == "employee_id" else v)
    if body.branch_id is not None:
        if not p.can_branch(body.branch_id):
            bad("You cannot assign staff to that branch.", 403)
        u.branch_id = body.branch_id
    if body.extra_branch_ids is not None:
        db.query(UserBranch).filter(UserBranch.user_id == u.id).delete()
        for bid in body.extra_branch_ids:
            db.add(UserBranch(user_id=u.id, branch_id=bid))
    if body.permission_overrides is not None:
        if p.role_key != "super_admin":
            bad("Only the Super Administrator can grant individual permissions.", 403)
        db.query(UserPermission).filter(UserPermission.user_id == u.id).delete()
        for key, granted in body.permission_overrides.items():
            perm = db.query(Permission).filter(Permission.key == key).first()
            if not perm:
                bad(f"Unknown permission {key}.")
            db.add(UserPermission(user_id=u.id, permission_id=perm.id, granted=bool(granted)))
        changes["permission_overrides"] = body.permission_overrides
        for s in db.query(AuthSession).filter(AuthSession.user_id == u.id):
            s.revoked = True
    audit.log(db, p.user, "staff_updated", "user", u.id, changes, request)
    db.commit()
    db.refresh(u)
    return _staff_detail(db, u)


@router.post("/staff/{uid}/reset-password")
def reset_staff_password(uid: int, request: Request, p=Depends(require("staff.manage")), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or not u.role.is_staff:
        raise HTTPException(404, "Staff member not found.")
    if u.role.key in PRIVILEGED and p.role_key != "super_admin":
        bad("Only the Super Administrator can reset this account.", 403)
    pw = temp_password()
    u.password_hash, u.must_change_password, u.failed_logins, u.locked_until = hash_password(pw), True, 0, None
    for s in db.query(AuthSession).filter(AuthSession.user_id == u.id):
        s.revoked = True
    audit.log(db, p.user, "staff_password_reset", "user", u.id, request=request)
    db.commit()
    return {"temporary_password": pw}


@router.post("/staff/{uid}/revoke-sessions")
def revoke_sessions(uid: int, request: Request, p=Depends(require("staff.manage")), db: Session = Depends(get_db)):
    n = 0
    for s in db.query(AuthSession).filter(AuthSession.user_id == uid, AuthSession.revoked == False):  # noqa
        s.revoked = True
        n += 1
    audit.log(db, p.user, "sessions_revoked", "user", uid, {"count": n}, request)
    db.commit()
    return {"revoked": n}


@router.get("/roles")
def list_roles(p=Depends(staff_principal), db: Session = Depends(get_db)):
    roles = db.query(Role).order_by(Role.id).all()
    return {"roles": [{"key": r.key, "name": r.name, "description": r.description, "all_branches": r.all_branches,
                       "is_staff": r.is_staff, "permissions": sorted(x.key for x in r.permissions)} for r in roles],
            "permissions": [{"key": k, "description": v[0], "module": v[1]} for k, v in PERMISSIONS.items()]}


@router.put("/roles/{key}/permissions")
def set_role_permissions(key: str, body: RolePermsIn, request: Request, p=Depends(require("roles.manage")), db: Session = Depends(get_db)):
    role = db.query(Role).filter(Role.key == key).first()
    if not role:
        raise HTTPException(404, "Role not found.")
    if role.key == "super_admin":
        bad("The Super Administrator role always has every permission.")
    if role.key == "customer":
        bad("Customers cannot be granted internal permissions.")
    perms = db.query(Permission).filter(Permission.key.in_(body.permissions)).all()
    if len(perms) != len(set(body.permissions)):
        bad("Unknown permission in list.")
    db.query(RolePermission).filter(RolePermission.role_id == role.id).delete()
    for pm in perms:
        db.add(RolePermission(role_id=role.id, permission_id=pm.id))
    for s in db.query(AuthSession).join(User, User.id == AuthSession.user_id).filter(User.role_id == role.id):
        s.revoked = True
    audit.log(db, p.user, "role_permissions_changed", "role", role.key, {"permissions": sorted(body.permissions)}, request)
    db.commit()
    return {"ok": True}
