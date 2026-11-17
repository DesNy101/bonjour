from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import or_, func
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies.auth import require, scope_branch, branch_filter
from app.models import (Order, Payment, Branch, ProductionBatch, Recipe, Customer, PaymentVerification, OrderStatusHistory, Product)
from app.schemas.common import StaffOrderIn, StatusIn, OrderEditIn, PaymentIn, VerifyIn
from app.serializers import order_out, payment_out
from app.services import orders as osvc, payments as psvc, production as prodsvc, settings_service, audit, numbering
from app.utils import common
from app.utils.common import bad
from app.utils.pdf import document_pdf

router = APIRouter(prefix="/api", tags=["Orders & Payments"])


def _get_order(db, p, oid) -> Order:
    o = db.get(Order, oid)
    if not o or not p.can_branch(o.branch_id):
        raise HTTPException(404, "Order not found.")
    return o


@router.get("/orders/meta")
def order_meta(p=Depends(require("orders.view"))):
    return {"statuses": [{"key": s, "label": osvc.LABELS[s]} for s in osvc.STATUSES],
            "transitions": {k: sorted(v) for k, v in osvc.TRANSITIONS.items()}}


@router.get("/orders")
def list_orders(q: str = "", branch_id: int | None = None, customer_id: int | None = None, status: str = "", payment_status: str = "",
                channel: str = "", order_type: str = "", date_from: date | None = None, date_to: date | None = None,
                page: int = 1, size: int = 25, p=Depends(require("orders.view")), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    qs = db.query(Order).filter(Order.is_demo == demo, branch_filter(p, Order.branch_id, branch_id))
    if q:
        qs = qs.filter(or_(Order.order_number.ilike(f"%{q}%"), Order.contact_name.ilike(f"%{q}%"), Order.contact_phone.ilike(f"%{q}%")))
    if customer_id:
        qs = qs.filter(Order.customer_id == customer_id)
    if status:
        qs = qs.filter(Order.status.in_(status.split(",")))
    if payment_status:
        qs = qs.filter(Order.payment_status == payment_status)
    if channel:
        qs = qs.filter(Order.channel == channel)
    if order_type:
        qs = qs.filter(Order.order_type == order_type)
    if date_from:
        qs = qs.filter(Order.created_at >= common.day_start(date_from))
    if date_to:
        qs = qs.filter(Order.created_at < common.day_end(date_to))
    total = qs.count()
    rows = qs.order_by(Order.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "page": page, "size": size, "items": [order_out(o, internal=False) | {"customer_id": o.customer_id} for o in rows]}


@router.get("/orders/{oid}")
def get_order(oid: int, p=Depends(require("orders.view")), db: Session = Depends(get_db)):
    o = _get_order(db, p, oid)
    d = order_out(o)
    b = db.get(Branch, o.branch_id)
    d["branch_name"] = b.name if b else ""
    return d


@router.post("/orders", status_code=201)
def create_staff_order(body: StaffOrderIn, request: Request, p=Depends(require("orders.create")), db: Session = Depends(get_db)):
    scope_branch(p, body.branch_id)
    channel = body.channel
    if channel == "walk_in":
        body.order_type = "pickup"
    if channel in ("walk_in",) and body.payment_method in ("cash_on_delivery", "cash_at_pickup", "paystack"):
        body.payment_method = "cash"
    order = osvc.create_order(db, body, user=None, channel=channel, staff=p.user)
    pay = order.payments[0] if order.payments else None
    if channel == "walk_in":
        # counter sale: goods handed over now -> stock out, completed
        paid_amt = body.amount_paid_kobo if body.amount_paid_kobo else order.total_kobo
        paid_amt = min(paid_amt, order.total_kobo)
        osvc.deduct_stock(db, order, p.user)
        if pay:
            pay.amount_kobo, pay.method = paid_amt, (body.payment_method if body.payment_method in ("cash", "pos", "bank_transfer") else "cash")
            if p.can("payments.verify"):
                psvc.verify(db, pay, p.user, True, "Counter sale")
            else:
                pay.status = "awaiting_verification"
        prev = order.status
        order.status = "completed"
        osvc._record(db, order, prev, "completed", p.user, "Walk-in sale completed")
        db.flush()
    elif body.amount_paid_kobo and pay:
        pay.amount_kobo = min(body.amount_paid_kobo, order.total_kobo)
        pay.method = body.payment_method
        if body.payment_method in ("cash", "pos"):
            if p.can("payments.verify"):
                psvc.verify(db, pay, p.user, True, "Recorded at order creation")
            else:
                pay.status = "awaiting_verification"
    db.refresh(order)
    psvc.recompute_order_payment(order)
    audit.log(db, p.user, "order_created_staff", "order", order.order_number, {"channel": channel, "total": order.total_kobo}, request)
    db.commit()
    return order_out(order)


@router.patch("/orders/{oid}")
def edit_order(oid: int, body: OrderEditIn, request: Request, p=Depends(require("orders.manage")), db: Session = Depends(get_db)):
    o = _get_order(db, p, oid)
    if o.status not in ("pending", "confirmed", "awaiting_payment", "paid", "queued_for_production"):
        bad("This order can no longer be edited.", 409)
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "delivery_address" in changes and o.order_type != "delivery":
        bad("Pickup orders have no delivery address.")
    for k, v in changes.items():
        setattr(o, k, v)
    osvc._record(db, o, o.status, o.status, p.user, "Order details edited: " + ", ".join(changes))
    audit.log(db, p.user, "order_edited", "order", o.order_number, {k: str(v) for k, v in changes.items()}, request)
    db.commit()
    return order_out(o)


@router.post("/orders/{oid}/status")
def set_status(oid: int, body: StatusIn, request: Request, p=Depends(require("orders.manage", "orders.cancel", any_of=True)), db: Session = Depends(get_db)):
    o = _get_order(db, p, oid)
    if body.status == "cancelled" and not p.can("orders.cancel"):
        bad("You do not have permission to cancel orders.", 403)
    if body.status != "cancelled" and not p.can("orders.manage"):
        bad("You do not have permission to update orders.", 403)
    old = o.status
    osvc.change_status(db, o, body.status, p.user, body.note)
    audit.log(db, p.user, "order_status", "order", o.order_number, {"from": old, "to": body.status, "note": body.note}, request)
    db.commit()
    return order_out(o)


@router.post("/orders/{oid}/assign-production")
def assign_production(oid: int, request: Request, p=Depends(require("orders.manage", "production.manage")), db: Session = Depends(get_db)):
    """Queue the order for production: creates one planned batch per line, linked to the order."""
    o = _get_order(db, p, oid)
    if o.status not in ("confirmed", "paid"):
        bad("Only confirmed or paid orders can be queued for production.", 409)
    created = []
    for it in o.items:
        recipe = db.query(Recipe).filter(Recipe.product_id == it.product_id, Recipe.is_active == True).first()  # noqa
        b = ProductionBatch(batch_number=numbering.number(db, "batch", "BAT"), branch_id=o.branch_id, product_id=it.product_id,
                            recipe_id=recipe.id if recipe else None, planned_qty=it.quantity, order_id=o.id, created_by=p.id,
                            is_demo=o.is_demo, notes=f"For order {o.order_number}")
        db.add(b)
        db.flush()
        prodsvc.init_batch(db, b)
        created.append(b.batch_number)
    osvc.change_status(db, o, "queued_for_production", p.user, "Queued: " + ", ".join(created))
    from app.services import notify
    notify.notify_permission(db, "production.view", f"New batch(es) for order {o.order_number}", ", ".join(created), "#/production", "production", o.branch_id)
    audit.log(db, p.user, "order_to_production", "order", o.order_number, {"batches": created}, request)
    db.commit()
    return {"batches": created, "order": order_out(o)}


@router.post("/orders/{oid}/payments", status_code=201)
def add_payment(oid: int, body: PaymentIn, request: Request, p=Depends(require("orders.manage", "payments.verify", any_of=True)), db: Session = Depends(get_db)):
    o = _get_order(db, p, oid)
    if o.status == "cancelled":
        bad("Order is cancelled.", 409)
    if body.method not in psvc.METHODS:
        bad("Unsupported payment method.")
    if body.amount_kobo > o.total_kobo - o.paid_kobo - sum(x.amount_kobo for x in o.payments if x.status == "awaiting_verification"):
        bad("Amount exceeds the outstanding balance of this order.")
    pay = psvc.create(db, o, body.method, body.amount_kobo, p.id, "awaiting_verification", body.reference_note)
    if p.can("payments.verify") and body.method in ("cash", "pos", "cash_at_pickup", "cash_on_delivery"):
        psvc.verify(db, pay, p.user, True, body.reference_note or "Recorded by staff")
    psvc.recompute_order_payment(o)
    audit.log(db, p.user, "payment_recorded", "payment", pay.reference, {"order": o.order_number, "amount": body.amount_kobo}, request)
    db.commit()
    return payment_out(pay)


@router.get("/orders/{oid}/document.pdf")
def order_pdf(oid: int, kind: str = "receipt", p=Depends(require("orders.view")), db: Session = Depends(get_db)):
    if kind not in ("receipt", "invoice"):
        bad("kind must be receipt or invoice")
    o = _get_order(db, p, oid)
    s = settings_service.all_settings(db)
    d = order_out(o)
    d["branch"] = db.get(Branch, o.branch_id).name
    pdf = document_pdf(kind, {"name": s["business_name"], "address": s["contact_address"], "phone": s["contact_phone"], "email": s["contact_email"],
                              "bank_name": s["bank_name"], "bank_account_number": s["bank_account_number"], "bank_account_name": s["bank_account_name"]}, d)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{kind}-{o.order_number}.pdf"'})


# ---------------- payments ----------------
@router.get("/payments")
def list_payments(status: str = "", method: str = "", branch_id: int | None = None, q: str = "", page: int = 1, size: int = 30,
                  p=Depends(require("payments.view")), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    qs = db.query(Payment, Order).join(Order, Order.id == Payment.order_id).filter(Payment.is_demo == demo, branch_filter(p, Payment.branch_id, branch_id))
    if status:
        qs = qs.filter(Payment.status == status)
    if method:
        qs = qs.filter(Payment.method == method)
    if q:
        qs = qs.filter(or_(Payment.reference.ilike(f"%{q}%"), Order.order_number.ilike(f"%{q}%"), Order.contact_name.ilike(f"%{q}%")))
    total = qs.count()
    rows = qs.order_by(Payment.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "items": [payment_out(pay) | {"order_number": o.order_number, "customer": o.contact_name} for pay, o in rows]}


@router.post("/payments/{pid}/verify")
def verify_payment(pid: int, body: VerifyIn, request: Request, p=Depends(require("payments.verify")), db: Session = Depends(get_db)):
    pay = db.get(Payment, pid)
    if not pay or not p.can_branch(pay.branch_id):
        raise HTTPException(404, "Payment not found.")
    if pay.method == "bank_transfer" and pay.status == "pending":
        bad("The customer has not yet submitted transfer details for this payment.", 409)
    if pay.method == "paystack" and body.approve:
        bad("Online (Paystack) payments are confirmed automatically by the gateway.", 409)
    psvc.verify(db, pay, p.user, body.approve, body.note)
    audit.log(db, p.user, "payment_verified" if body.approve else "payment_rejected", "payment", pay.reference, {"note": body.note}, request)
    db.commit()
    return payment_out(pay)
