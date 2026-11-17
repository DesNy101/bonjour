from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies.auth import require, scope_branch, branch_filter
from app.models import (Expense, ExpenseCategory, FinancialTransaction, CashRegisterClose, Order, OrderItem, SupplierInvoice, User, Branch)
from app.schemas.common import ExpenseIn, AdjustmentIn, RegisterCloseIn, DecisionIn
from app.serializers import expense_out
from app.services import audit, finance as svc, numbering, settings_service, analytics
from app.utils import common
from app.utils.common import bad
from app.utils.uploads import save_image

router = APIRouter(prefix="/api", tags=["Finance"])
CASH_METHODS = ("cash", "cash_on_delivery", "cash_at_pickup")


@router.get("/expense-categories")
def expense_categories(p=Depends(require("expenses.record", "finance.view", "settings.view", any_of=True)), db: Session = Depends(get_db)):
    return [{"id": c.id, "name": c.name, "counts_in_cogs": c.counts_in_cogs} for c in db.query(ExpenseCategory).filter(ExpenseCategory.is_active == True).order_by(ExpenseCategory.name)]  # noqa


@router.get("/expenses")
def list_expenses(status: str = "", branch_id: int | None = None, category_id: int | None = None, date_from: date | None = None, date_to: date | None = None,
                  page: int = 1, size: int = 50, p=Depends(require("finance.view", "expenses.record", any_of=True)), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    qs = db.query(Expense).filter(Expense.is_demo == demo, branch_filter(p, Expense.branch_id, branch_id))
    if not p.can("finance.view"):
        qs = qs.filter(Expense.recorded_by == p.id)  # recorders see only their own entries
    if status:
        qs = qs.filter(Expense.status == status)
    if category_id:
        qs = qs.filter(Expense.category_id == category_id)
    if date_from:
        qs = qs.filter(Expense.expense_date >= date_from)
    if date_to:
        qs = qs.filter(Expense.expense_date <= date_to)
    total = qs.count()
    sum_ = qs.filter(Expense.status == "approved").with_entities(func.coalesce(func.sum(Expense.amount_kobo), 0)).scalar()
    rows = qs.order_by(Expense.id.desc()).offset((page - 1) * size).limit(size).all()
    names = {u.id: u.full_name for u in db.query(User).all()}
    return {"total": total, "approved_total_kobo": int(sum_), "items": [expense_out(e) | {"recorded_by_name": names.get(e.recorded_by)} for e in rows]}


@router.post("/expenses", status_code=201)
def create_expense(body: ExpenseIn, request: Request, p=Depends(require("expenses.record")), db: Session = Depends(get_db)):
    scope_branch(p, body.branch_id)
    cat = db.get(ExpenseCategory, body.category_id)
    if not cat or not cat.is_active:
        bad("Unknown expense category.")
    br = db.get(Branch, body.branch_id)
    if not br or not br.is_active:
        bad("Branch not available.")
    d = body.expense_date or common.today()
    if d > common.today():
        bad("Expense date cannot be in the future.")
    e = svc.create_expense(db, p, cat, body.description, body.amount_kobo, body.branch_id, d, body.supporting_ref)
    audit.log(db, p.user, "expense_recorded", "expense", e.reference, {"amount": e.amount_kobo, "status": e.status}, request)
    db.commit()
    return expense_out(e)


@router.post("/expenses/{eid}/attachment")
async def expense_attachment(eid: int, file: UploadFile = File(...), p=Depends(require("expenses.record")), db: Session = Depends(get_db)):
    e = db.get(Expense, eid)
    if not e or not p.can_branch(e.branch_id):
        raise HTTPException(404, "Expense not found.")
    e.attachment_path = await save_image(file, "expenses")
    db.commit()
    return {"attachment": e.attachment_path}


@router.post("/expenses/{eid}/decide")
def decide_expense(eid: int, body: DecisionIn, request: Request, p=Depends(require("expenses.approve")), db: Session = Depends(get_db)):
    e = db.get(Expense, eid)
    if not e or not p.can_branch(e.branch_id):
        raise HTTPException(404, "Expense not found.")
    svc.decide_expense(db, e, p, body.approve, body.note)
    audit.log(db, p.user, "expense_" + e.status, "expense", e.reference, {"note": body.note}, request)
    db.commit()
    return expense_out(e)


@router.get("/finance/transactions")
def transactions(kind: str = "", branch_id: int | None = None, verification: str = "", date_from: date | None = None, date_to: date | None = None,
                 page: int = 1, size: int = 50, p=Depends(require("finance.view")), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    qs = db.query(FinancialTransaction).filter(FinancialTransaction.is_demo == demo, branch_filter(p, FinancialTransaction.branch_id, branch_id))
    if kind:
        qs = qs.filter(FinancialTransaction.kind == kind)
    if verification:
        qs = qs.filter(FinancialTransaction.verification_status == verification)
    if date_from:
        qs = qs.filter(FinancialTransaction.txn_date >= date_from)
    if date_to:
        qs = qs.filter(FinancialTransaction.txn_date <= date_to)
    total = qs.count()
    rows = qs.order_by(FinancialTransaction.id.desc()).offset((page - 1) * size).limit(size).all()
    names = {u.id: u.full_name for u in db.query(User).all()}
    br = {b.id: b.name for b in db.query(Branch).all()}
    return {"total": total, "items": [{"id": t.id, "reference": t.reference, "kind": t.kind, "direction": t.direction, "amount_kobo": t.amount_kobo,
                                       "method": t.method, "branch": br.get(t.branch_id), "date": t.txn_date.isoformat(), "description": t.description,
                                       "order_id": t.order_id, "by": names.get(t.recorded_by, "System"), "verification": t.verification_status,
                                       "reason": t.adjustment_reason} for t in rows]}


@router.post("/finance/adjustments", status_code=201)
def adjustment(body: AdjustmentIn, request: Request, p=Depends(require("finance.manage")), db: Session = Depends(get_db)):
    scope_branch(p, body.branch_id)
    t = FinancialTransaction(reference=numbering.number(db, "txn", "TXN"), kind="adjustment_" + body.direction, direction=body.direction,
                             amount_kobo=body.amount_kobo, method="adjustment", branch_id=body.branch_id, txn_date=common.today(),
                             description="Financial adjustment", adjustment_reason=body.reason, recorded_by=p.id, verification_status="verified",
                             is_demo=settings_service.is_demo_mode(db))
    db.add(t)
    audit.log(db, p.user, "financial_adjustment", "transaction", t.reference, {"direction": body.direction, "amount": body.amount_kobo, "reason": body.reason}, request)
    db.commit()
    return {"reference": t.reference}


@router.post("/finance/reconcile")
def reconcile(ids: list[int], p=Depends(require("finance.manage")), db: Session = Depends(get_db)):
    n = 0
    for t in db.query(FinancialTransaction).filter(FinancialTransaction.id.in_(ids or [-1])):
        if p.can_branch(t.branch_id) and t.verification_status == "verified":
            t.verification_status = "reconciled"
            n += 1
    db.commit()
    return {"reconciled": n}


def _cash_figures(db, demo, branch_id, d):
    base = [FinancialTransaction.is_demo == demo, FinancialTransaction.branch_id == branch_id, FinancialTransaction.txn_date == d]
    cin = db.execute(select(func.coalesce(func.sum(FinancialTransaction.amount_kobo), 0)).where(*base, FinancialTransaction.direction == "in",
                     FinancialTransaction.method.in_(CASH_METHODS + ("adjustment",)))).scalar()
    cout = db.execute(select(func.coalesce(func.sum(FinancialTransaction.amount_kobo), 0)).where(*base, FinancialTransaction.direction == "out",
                      FinancialTransaction.method.in_(CASH_METHODS + ("adjustment",)))).scalar()
    by_method = {m: int(v) for m, v in db.execute(select(FinancialTransaction.method, func.sum(FinancialTransaction.amount_kobo)).where(
        *base, FinancialTransaction.direction == "in").group_by(FinancialTransaction.method))}
    return int(cin), int(cout), by_method


@router.get("/finance/daily-cash")
def daily_cash(branch_id: int, day: date | None = None, p=Depends(require("finance.view")), db: Session = Depends(get_db)):
    scope_branch(p, branch_id)
    d = day or common.today()
    demo = settings_service.is_demo_mode(db)
    cin, cout, by_method = _cash_figures(db, demo, branch_id, d)
    closed = db.query(CashRegisterClose).filter(CashRegisterClose.branch_id == branch_id, CashRegisterClose.close_date == d, CashRegisterClose.is_demo == demo).first()
    unverified = db.query(func.count()).select_from(FinancialTransaction).filter(FinancialTransaction.branch_id == branch_id, FinancialTransaction.txn_date == d,
                                                                              FinancialTransaction.verification_status == "unverified").scalar()
    return {"date": d.isoformat(), "cash_in_kobo": cin, "cash_out_kobo": cout, "received_by_method": by_method, "unverified": unverified,
            "closed": None if not closed else {"counted_kobo": closed.counted_kobo, "expected_kobo": closed.expected_kobo, "variance_kobo": closed.variance_kobo}}


@router.post("/finance/register-close", status_code=201)
def close_register(body: RegisterCloseIn, request: Request, p=Depends(require("finance.manage")), db: Session = Depends(get_db)):
    scope_branch(p, body.branch_id)
    d = body.close_date or common.today()
    demo = settings_service.is_demo_mode(db)
    if db.query(CashRegisterClose).filter(CashRegisterClose.branch_id == body.branch_id, CashRegisterClose.close_date == d, CashRegisterClose.is_demo == demo).first():
        bad("The register for that day is already closed.", 409)
    cin, cout, _ = _cash_figures(db, demo, body.branch_id, d)
    expected = body.opening_kobo + cin - cout
    c = CashRegisterClose(branch_id=body.branch_id, close_date=d, opening_kobo=body.opening_kobo, cash_in_kobo=cin, cash_out_kobo=cout,
                          expected_kobo=expected, counted_kobo=body.counted_kobo, variance_kobo=body.counted_kobo - expected, notes=body.notes,
                          closed_by=p.id, is_demo=demo)
    db.add(c)
    audit.log(db, p.user, "register_closed", "branch", body.branch_id, {"expected": expected, "counted": body.counted_kobo, "variance": c.variance_kobo}, request)
    db.commit()
    return {"expected_kobo": expected, "counted_kobo": c.counted_kobo, "variance_kobo": c.variance_kobo}


@router.get("/finance/register-closes")
def register_closes(p=Depends(require("finance.view")), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    br = {b.id: b.name for b in db.query(Branch).all()}
    rows = db.query(CashRegisterClose).filter(CashRegisterClose.is_demo == demo, branch_filter(p, CashRegisterClose.branch_id)).order_by(CashRegisterClose.id.desc()).limit(60).all()
    return [{"branch": br.get(r.branch_id), "date": r.close_date.isoformat(), "opening_kobo": r.opening_kobo, "cash_in_kobo": r.cash_in_kobo,
             "cash_out_kobo": r.cash_out_kobo, "expected_kobo": r.expected_kobo, "counted_kobo": r.counted_kobo, "variance_kobo": r.variance_kobo, "notes": r.notes} for r in rows]


def pnl(db, p, branch_id, start, end):
    demo = settings_service.is_demo_mode(db)
    ids = analytics.scope_ids(p, branch_id)
    ov = analytics.overview(db, p, branch_id, start, end)["stats"]
    opex = analytics._opex(db, demo, ids, start, end)
    payables = int(db.execute(select(func.coalesce(func.sum(SupplierInvoice.amount_kobo - SupplierInvoice.paid_kobo), 0)).where(SupplierInvoice.is_demo == demo)).scalar())
    return {"revenue_kobo": ov["total_revenue_kobo"], "cost_of_goods_kobo": ov["estimated_cogs_kobo"], "gross_profit_kobo": ov["estimated_gross_profit_kobo"],
            "operating_expenses_kobo": opex, "net_profit_kobo": ov["estimated_gross_profit_kobo"] - opex, "cash_received_kobo": ov["cash_received_kobo"],
            "outstanding_receivables_kobo": ov["outstanding_payments_kobo"], "total_expenses_kobo": ov["total_expenses_kobo"], "supplier_payables_kobo": payables,
            "note": "Gross profit = billed revenue minus standard recipe cost (incl. configured overhead) of goods sold. Raw-material and packaging purchases are "
                    "excluded from operating expenses because their cost flows through recipe costing."}


@router.get("/finance/summary")
def summary(branch_id: int | None = None, date_from: date | None = None, date_to: date | None = None, p=Depends(require("finance.view")), db: Session = Depends(get_db)):
    scope_branch(p, branch_id)
    t = common.today()
    start, end = date_from or t.replace(day=1), date_to or t
    demo = settings_service.is_demo_mode(db)
    ids = analytics.scope_ids(p, branch_id)
    by_method = db.execute(select(FinancialTransaction.method, func.sum(FinancialTransaction.amount_kobo)).where(
        FinancialTransaction.is_demo == demo, analytics._branch_cond(FinancialTransaction.branch_id, ids), FinancialTransaction.kind == "revenue",
        FinancialTransaction.txn_date.between(start, end)).group_by(FinancialTransaction.method)).all()
    pending_ver = db.execute(select(func.count()).select_from(FinancialTransaction).where(FinancialTransaction.is_demo == demo,
                             analytics._branch_cond(FinancialTransaction.branch_id, ids), FinancialTransaction.verification_status == "unverified")).scalar()
    from app.models import Payment
    awaiting = db.execute(select(func.count(), func.coalesce(func.sum(Payment.amount_kobo), 0)).where(Payment.is_demo == demo, analytics._branch_cond(Payment.branch_id, ids),
                          Payment.status == "awaiting_verification")).one()
    pend_exp = db.execute(select(func.count()).select_from(Expense).where(Expense.is_demo == demo, analytics._branch_cond(Expense.branch_id, ids), Expense.status == "pending_approval")).scalar()
    return {"range": {"from": start.isoformat(), "to": end.isoformat()}, "pnl": pnl(db, p, branch_id, start, end),
            "cash_by_method": [{"method": m, "amount_kobo": int(v)} for m, v in by_method], "payments_awaiting_verification": {"count": awaiting[0], "amount_kobo": int(awaiting[1])},
            "expenses_pending_approval": pend_exp, "unverified_transactions": pending_ver}
