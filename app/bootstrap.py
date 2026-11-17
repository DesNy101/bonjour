"""Idempotent first-run initialisation: permissions, roles, reference data, first Super Administrator."""
import logging
from datetime import date
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import (Permission, Role, RolePermission, ProductionStage, ExpenseCategory, ProductCategory, Branch, User, Setting)
from app import permissions as P
from app.security import hash_password, password_problem
from app.services import settings_service

log = logging.getLogger("bonjour")


def sync_permissions_and_roles(db: Session):
    existing = {p.key: p for p in db.query(Permission)}
    for key, (desc, module) in P.PERMISSIONS.items():
        if key not in existing:
            existing[key] = Permission(key=key, description=desc, module=module)
            db.add(existing[key])
        else:
            existing[key].description, existing[key].module = desc, module
    db.flush()
    roles = {r.key: r for r in db.query(Role)}
    for key, (name, desc, all_br, is_staff, perms) in P.ROLES.items():
        r = roles.get(key)
        if r is None:
            r = Role(key=key, name=name, description=desc, all_branches=all_br, is_staff=is_staff, is_system=True)
            db.add(r)
            db.flush()
            for pk in perms:
                db.add(RolePermission(role_id=r.id, permission_id=existing[pk].id))
        elif key == "super_admin":  # owner always holds every permission, including future ones
            have = {x.permission_id for x in db.query(RolePermission).filter(RolePermission.role_id == r.id)}
            for pk in perms:
                if existing[pk].id not in have:
                    db.add(RolePermission(role_id=r.id, permission_id=existing[pk].id))


def seed_reference_data(db: Session):
    if db.query(ProductionStage).count() == 0:
        for i, (n, d) in enumerate(P.DEFAULT_PRODUCTION_STAGES, 1):
            db.add(ProductionStage(name=n, sequence=i, department=d))
    if db.query(ExpenseCategory).count() == 0:
        for n, cogs in P.DEFAULT_EXPENSE_CATEGORIES:
            db.add(ExpenseCategory(name=n, counts_in_cogs=cogs))
    if db.query(ProductCategory).count() == 0:
        for n, k in P.DEFAULT_PRODUCT_CATEGORIES:
            db.add(ProductCategory(name=n, kind=k))
    if db.get(Setting, "timezone") is None:
        settings_service.set_value(db, "timezone", "Africa/Lagos")
    if db.query(Branch).filter(Branch.is_demo == False).count() == 0:  # noqa
        db.add(Branch(code="YNG", name="Yenagoa (Main)", address="Yenagoa", state="Bayelsa", lga="Yenagoa", opened_on=date.today()))


def ensure_admin(db: Session):
    cfg = get_settings()
    if db.query(User).count() > 0:
        return
    if not cfg.admin_email or not cfg.admin_password:
        log.warning("No users exist. Set ADMIN_EMAIL and ADMIN_PASSWORD, or run: python -m app.create_admin")
        return
    problem = password_problem(cfg.admin_password)
    if problem:
        log.error("ADMIN_PASSWORD rejected: %s", problem)
        return
    role = db.query(Role).filter(Role.key == "super_admin").one()
    db.add(User(email=cfg.admin_email.lower(), full_name=cfg.admin_name, password_hash=hash_password(cfg.admin_password), role_id=role.id,
                employee_id="OWNER-001", job_title="Owner"))
    log.info("Created first Super Administrator %s", cfg.admin_email)


def init(db: Session):
    sync_permissions_and_roles(db)
    seed_reference_data(db)
    ensure_admin(db)
    db.commit()
    from app.utils import common
    common.set_tz(settings_service.get(db, "timezone") or "Africa/Lagos")
