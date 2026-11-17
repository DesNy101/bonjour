from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models import Expense, ExpenseApproval, FinancialTransaction
from app.services import numbering, settings_service, notify
from app.utils.common import bad


def create_expense(db: Session, user, category, description, amount_kobo, branch_id, expense_date, supporting_ref="", attachment_path="") -> Expense:
    threshold = int(settings_service.get(db, "expense_approval_threshold_kobo") or 0)
    can_approve = "expenses.approve" in getattr(user, "permissions", set())
    needs = threshold and amount_kobo >= threshold and not can_approve
    e = Expense(reference=numbering.number(db, "exp", "EXP"), category_id=category.id, description=description, amount_kobo=amount_kobo, branch_id=branch_id,
                expense_date=expense_date, supporting_ref=supporting_ref, attachment_path=attachment_path, recorded_by=user.id,
                is_demo=settings_service.is_demo_mode(db), status="pending_approval" if needs else "approved")
    db.add(e)
    db.flush()
    if needs:
        notify.notify_permission(db, "expenses.approve", "Expense requires approval", f"{e.reference}: {description} (₦{amount_kobo / 100:,.2f})", "#/expenses", "approval", branch_id)
    else:
        e.decided_by = user.id
        e.decided_at = datetime.now(timezone.utc)
        post_expense(db, e, user)
    return e


def post_expense(db: Session, e: Expense, user):
    db.add(FinancialTransaction(reference=numbering.number(db, "txn", "TXN"), kind="expense", direction="out", amount_kobo=e.amount_kobo, method="cash",
                                branch_id=e.branch_id, txn_date=e.expense_date, description=f"{e.reference}: {e.description}", expense_id=e.id,
                                recorded_by=user.id, verification_status="verified", is_demo=e.is_demo))


def decide_expense(db: Session, e: Expense, user, approve: bool, note: str = ""):
    if e.status != "pending_approval":
        bad("Expense is not awaiting approval.", 409)
    if e.recorded_by == user.id and e.amount_kobo >= int(settings_service.get(db, "expense_approval_threshold_kobo") or 0) and user.role_key != "super_admin":
        bad("You cannot approve an expense you recorded yourself.", 403)
    e.status = "approved" if approve else "rejected"
    e.decided_by = user.id
    e.decided_at = datetime.now(timezone.utc)
    db.add(ExpenseApproval(expense_id=e.id, user_id=user.id, decision="approved" if approve else "rejected", note=note))
    if approve:
        post_expense(db, e, user)
    if e.recorded_by:
        notify.notify_user(db, e.recorded_by, f"Expense {e.reference} {e.status}", note, "#/expenses", "approval")
