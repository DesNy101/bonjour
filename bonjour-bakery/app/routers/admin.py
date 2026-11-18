from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies.auth import require, current_principal, staff_principal
from app.models import (Branch, User, AuditLog, Notification, Setting, Product, InventoryBalance, Order, Expense, ProductionBatch,
                        ExpenseCategory, ProductCategory)
from app.schemas.common import BranchIn, SettingsIn, ExpenseCategoryIn, CategoryIn
from app.serializers import branch_out
from app.services import audit, settings_service, analytics
from app.utils import common
from app.utils.common import bad

router = APIRouter(prefix="/api", tags=["Administration"])


# ------------------------ branches ------------------------
@router.get("/branches")
def list_branches(p=Depends(staff_principal), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    qs = db.query(Branch).filter(Branch.is_demo == demo)
    if p.branch_ids is not None:
        qs = qs.filter(Branch.id.in_(p.branch_ids or {-1}))
    mgrs = {u.id: u for u in db.query(User).all()}
    return [branch_out(b, mgrs.get(b.manager_id)) for b in qs.order_by(Branch.name)]


def _validate_manager(db, manager_id):
    if manager_id:
        m = db.get(User, manager_id)
        if not m or not m.role.is_staff or not m.is_active:
            bad("Selected manager is not an active staff member.")


@router.post("/branches", status_code=201)
def create_branch(body: BranchIn, request: Request, p=Depends(require("branches.manage")), db: Session = Depends(get_db)):
    if db.query(Branch).filter(func.lower(Branch.code) == body.code.lower()).first():
        bad("Branch code already exists.", 409)
    _validate_manager(db, body.manager_id)
    b = Branch(**body.model_dump(), is_demo=settings_service.is_demo_mode(db))
    b.code = b.code.upper()
    db.add(b)
    db.flush()
    audit.log(db, p.user, "branch_created", "branch", b.id, {"code": b.code}, request)
    db.commit()
    return branch_out(b)


@router.put("/branches/{bid}")
def update_branch(bid: int, body: BranchIn, request: Request, p=Depends(require("branches.manage")), db: Session = Depends(get_db)):
    b = db.get(Branch, bid)
    if not b:
        raise HTTPException(404, "Branch not found.")
    if db.query(Branch).filter(func.lower(Branch.code) == body.code.lower(), Branch.id != bid).first():
        bad("Branch code already exists.", 409)
    _validate_manager(db, body.manager_id)
    for k, v in body.model_dump().items():
        setattr(b, k, v)
    b.code = b.code.upper()
    audit.log(db, p.user, "branch_updated", "branch", b.id, body.model_dump(mode="json"), request)
    db.commit()
    return branch_out(b)


@router.get("/branches/compare")
def compare_branches(date_from: date | None = None, date_to: date | None = None, p=Depends(require("branches.view")), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    t = common.today()
    start = date_from if date_from else t.replace(day=1)
    end = date_to if date_to else t
    out = []
    for b in db.query(Branch).filter(Branch.is_demo == demo, Branch.is_active == True).order_by(Branch.name):  # noqa
        if not p.can_branch(b.id):
            continue
        ov = analytics.overview(db, p, b.id, start, end)["stats"]
        prod = db.execute(select(func.coalesce(func.sum(ProductionBatch.actual_qty), 0)).where(
            ProductionBatch.branch_id == b.id, ProductionBatch.is_demo == demo, ProductionBatch.status == "completed",
            analytics.ldate(ProductionBatch.created_at) >= start, analytics.ldate(ProductionBatch.created_at) <= end)).scalar()
        out.append({"branch_id": b.id, "name": b.name, "code": b.code, "revenue_kobo": ov["total_revenue_kobo"], "orders": ov["total_orders"],
                    "expenses_kobo": ov["total_expenses_kobo"], "gross_profit_kobo": ov["estimated_gross_profit_kobo"],
                    "stock_value_kobo": ov["stock_value_kobo"], "low_stock": ov["low_stock_count"], "units_produced": common.num(prod)})
    return out


@router.get("/branches/{bid}/performance")
def branch_performance(bid: int, date_from: date | None = None, date_to: date | None = None, p=Depends(require("branches.view")), db: Session = Depends(get_db)):
    if not p.can_branch(bid):
        raise HTTPException(403, "You do not have access to that branch.")
    b = db.get(Branch, bid)
    if not b:
        raise HTTPException(404, "Branch not found.")
    return analytics.overview(db, p, bid, date_from if date_from else None, date_to if date_to else None)


# ------------------------ settings ------------------------
@router.get("/settings")
def get_settings_all(p=Depends(require("settings.view")), db: Session = Depends(get_db)):
    s = settings_service.all_settings(db)
    return {"settings": s, "expense_categories": [{"id": c.id, "name": c.name, "counts_in_cogs": c.counts_in_cogs, "is_active": c.is_active}
                                                   for c in db.query(ExpenseCategory).order_by(ExpenseCategory.name)],
            "product_categories": [{"id": c.id, "name": c.name, "kind": c.kind} for c in db.query(ProductCategory).order_by(ProductCategory.name)]}


@router.put("/settings")
def put_settings(body: SettingsIn, request: Request, p=Depends(require("settings.manage")), db: Session = Depends(get_db)):
    defaults = settings_service.DEFAULTS
    changed = {}
    for k, v in body.values.items():
        if k not in defaults:
            bad(f"Unknown setting '{k}'.")
        d = defaults[k]
        if isinstance(d, bool) and not isinstance(v, bool):
            bad(f"'{k}' must be true or false.")
        if isinstance(d, int) and not isinstance(d, bool):
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
                bad(f"'{k}' must be a non-negative number.")
            v = int(v)
        if isinstance(d, float) and not isinstance(v, (int, float)):
            bad(f"'{k}' must be a number.")
        if isinstance(d, list) and not isinstance(v, list):
            bad(f"'{k}' must be a list.")
        if k == "timezone":
            from zoneinfo import ZoneInfo
            try:
                ZoneInfo(v)
            except Exception:
                bad("Unknown time zone.")
        if k == "data_mode" and v not in ("live", "demo"):
            bad("data_mode must be 'live' or 'demo'.")
        if k == "data_mode" and v == "demo" and p.role_key != "super_admin":
            bad("Only the Super Administrator can switch data mode.", 403)
        settings_service.set_value(db, k, v)
        changed[k] = v
    audit.log(db, p.user, "settings_changed", "settings", "", changed, request)
    db.commit()
    return {"settings": settings_service.all_settings(db)}


@router.post("/settings/expense-categories", status_code=201)
def add_expense_category(body: ExpenseCategoryIn, p=Depends(require("settings.manage")), db: Session = Depends(get_db)):
    if db.query(ExpenseCategory).filter(func.lower(ExpenseCategory.name) == body.name.lower()).first():
        bad("Category already exists.", 409)
    c = ExpenseCategory(name=body.name, counts_in_cogs=body.counts_in_cogs, is_active=body.is_active)
    db.add(c)
    db.commit()
    return {"id": c.id, "name": c.name}


@router.put("/settings/expense-categories/{cid}")
def edit_expense_category(cid: int, body: ExpenseCategoryIn, p=Depends(require("settings.manage")), db: Session = Depends(get_db)):
    c = db.get(ExpenseCategory, cid)
    if not c:
        raise HTTPException(404, "Category not found.")
    c.name, c.counts_in_cogs, c.is_active = body.name, body.counts_in_cogs, body.is_active
    db.commit()
    return {"id": c.id}


# ------------------------ audit & notifications ------------------------
@router.get("/audit-logs")
def audit_logs(q: str = "", action: str = "", page: int = 1, size: int = 50, p=Depends(require("audit.view")), db: Session = Depends(get_db)):
    qs = db.query(AuditLog)
    if q:
        qs = qs.filter(or_(AuditLog.user_label.ilike(f"%{q}%"), AuditLog.entity.ilike(f"%{q}%"), AuditLog.entity_id.ilike(f"%{q}%")))
    if action:
        qs = qs.filter(AuditLog.action == action)
    total = qs.count()
    rows = qs.order_by(AuditLog.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "items": [{"id": a.id, "user": a.user_label, "action": a.action, "entity": a.entity, "entity_id": a.entity_id,
                                       "details": a.details, "ip": a.ip, "at": a.created_at.isoformat()} for a in rows]}


@router.get("/notifications")
def notifications(unread: bool = False, p=Depends(current_principal), db: Session = Depends(get_db)):
    qs = db.query(Notification).filter(Notification.user_id == p.id, Notification.channel == "in_app")
    unread_count = qs.filter(Notification.is_read == False).count()  # noqa
    if unread:
        qs = qs.filter(Notification.is_read == False)  # noqa
    rows = qs.order_by(Notification.id.desc()).limit(60).all()
    return {"unread": unread_count, "items": [{"id": n.id, "title": n.title, "body": n.body, "link": n.link, "kind": n.kind,
                                               "is_read": n.is_read, "created_at": n.created_at.isoformat()} for n in rows]}


@router.post("/notifications/read")
def mark_read(ids: list[int] | None = None, p=Depends(current_principal), db: Session = Depends(get_db)):
    q = db.query(Notification).filter(Notification.user_id == p.id, Notification.is_read == False)  # noqa
    if ids:
        q = q.filter(Notification.id.in_(ids))
    q.update({"is_read": True}, synchronize_session=False)
    db.commit()
    return {"ok": True}
