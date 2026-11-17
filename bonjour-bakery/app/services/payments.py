from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models import Payment, PaymentVerification, Order, FinancialTransaction, Customer
from app.services import notify, numbering
from app.utils import common
from app.utils.common import bad

METHODS = {"cash_on_delivery", "cash_at_pickup", "bank_transfer", "paystack", "cash", "pos"}


def new_reference(db: Session) -> str:
    return numbering.number(db, "pay", "PAY")


def create(db: Session, order: Order, method: str, amount_kobo: int, user_id: int | None, status: str = "pending", proof_reference: str = "") -> Payment:
    if method not in METHODS:
        bad("Unsupported payment method.")
    if amount_kobo <= 0:
        bad("Payment amount must be greater than zero.")
    pay = Payment(reference=new_reference(db), order_id=order.id, branch_id=order.branch_id, amount_kobo=amount_kobo, method=method, status=status,
                  proof_reference=proof_reference, recorded_by=user_id, is_demo=order.is_demo)
    db.add(pay)
    db.flush()
    db.add(PaymentVerification(payment_id=pay.id, action="submitted" if status != "pending" else "created", user_id=user_id, note=proof_reference))
    return pay


def recompute_order_payment(order: Order):
    paid = sum(p.amount_kobo for p in order.payments if p.status == "verified")
    order.paid_kobo = paid
    pending = any(p.status == "awaiting_verification" for p in order.payments)
    if paid >= order.total_kobo and order.total_kobo > 0:
        order.payment_status = "paid"
    elif paid > 0:
        order.payment_status = "partially_paid"
    elif pending:
        order.payment_status = "pending_verification"
    else:
        order.payment_status = "unpaid"


def verify(db: Session, pay: Payment, user, approve: bool, note: str = ""):
    """Staff verification. Posts to the ledger only on approval."""
    from app.services import orders as order_svc
    if pay.status in ("verified", "rejected"):
        bad(f"Payment already {pay.status}.", 409)
    order = db.get(Order, pay.order_id)
    pay.verified_by = user.id
    pay.verified_at = datetime.now(timezone.utc)
    if approve:
        pay.status = "verified"
        db.add(FinancialTransaction(
            reference=numbering.number(db, "txn", "TXN"), kind="revenue", direction="in", amount_kobo=pay.amount_kobo, method=pay.method, branch_id=pay.branch_id,
            txn_date=common.today(), description=f"Payment {pay.reference} for order {order.order_number}",
            sales_channel={"online": "online", "walk_in": "walk_in", "wholesale": "wholesale", "bulk": "bulk"}.get(order.channel, "online"),
            order_id=order.id, payment_id=pay.id, recorded_by=user.id, verification_status="verified", is_demo=pay.is_demo))
    else:
        pay.status = "rejected"
    db.add(PaymentVerification(payment_id=pay.id, action="verified" if approve else "rejected", user_id=user.id, note=note))
    db.flush()
    db.refresh(order)
    recompute_order_payment(order)
    if approve and order.payment_status == "paid" and order.status in ("pending", "confirmed", "awaiting_payment"):
        order_svc.change_status(db, order, "paid", user, "Payment verified", force=True)
    cust = db.get(Customer, order.customer_id) if order.customer_id else None
    notify.notify_customer(db, cust, f"Payment {'confirmed' if approve else 'rejected'} for {order.order_number}",
                           note or ("Thank you. Your payment has been verified." if approve else "We could not verify your payment. Please contact us."), f"#/track/{order.order_number}")
    return pay
