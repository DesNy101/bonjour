from datetime import date
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import get_db
from app.dependencies.auth import optional_principal, current_principal
from app.middleware.security import limiter
from app.models import (Branch, Product, InventoryBalance, Order, Customer, Payment, Notification, ProductCategory)
from app.schemas.common import OrderIn, ProofIn
from app.serializers import customer_view_order, product_out
from app.services import orders as order_svc, settings_service, payments as pay_svc, paystack, audit
from app.utils.common import bad

router = APIRouter(prefix="/api", tags=["Customer Portal"])


def _ip(request):
    return (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip()


@router.get("/public/config")
def public_config(db: Session = Depends(get_db)):
    s = settings_service.all_settings(db)
    out = {k: s[k] for k in settings_service.PUBLIC_KEYS}
    out["paystack_available"] = bool(s["pay_online"]) and paystack.configured()
    out["paystack_public_key"] = get_settings().paystack_public_key if paystack.configured() else ""
    out["demo_mode"] = s["data_mode"] == "demo"
    return out


@router.get("/public/branches")
def public_branches(db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    rows = db.query(Branch).filter(Branch.is_active == True, Branch.accepts_online_orders == True, Branch.is_demo == demo).order_by(Branch.name)  # noqa
    return [{"id": b.id, "code": b.code, "name": b.name, "address": b.address, "lga": b.lga, "state": b.state, "phone": b.phone} for b in rows]


@router.get("/public/products")
def public_products(branch_id: int | None = None, db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    prods = db.query(Product).filter(Product.is_active == True, Product.is_sellable == True, Product.kind == "finished",  # noqa
                                     Product.is_demo == demo).order_by(Product.name, Product.price_kobo).all()
    stock = {}
    if branch_id:
        for pid, q in db.execute(select(InventoryBalance.product_id, InventoryBalance.quantity).where(InventoryBalance.branch_id == branch_id)):
            stock[pid] = q
    out = []
    for p in prods:
        d = product_out(p)
        d.pop("cost_kobo"), d.pop("wholesale_price_kobo"), d.pop("sku")
        q = stock.get(p.id, 0) if branch_id else None
        d["availability"] = "available" if (q is None or q > (p.reorder_level or 0)) and (q is None or q > 0) else ("limited" if q and q > 0 else "made_to_order")
        d["reorder_level"] = None
        out.append(d)
    return out


@router.post("/public/orders", status_code=201)
def place_order(body: OrderIn, request: Request, p=Depends(optional_principal), db: Session = Depends(get_db)):
    if not limiter.check(f"order:{_ip(request)}", 20, 3600):
        raise HTTPException(429, "Too many orders from this address. Please try again later.")
    s = settings_service.all_settings(db)
    gate = {"cash_on_delivery": "pay_cash_on_delivery", "cash_at_pickup": "pay_cash_at_pickup",
            "bank_transfer": "pay_bank_transfer", "paystack": "pay_online"}[body.payment_method]
    if not s[gate]:
        bad("That payment method is currently unavailable.")
    if body.payment_method == "cash_on_delivery" and body.order_type != "delivery":
        bad("Cash on delivery is only available for delivery orders.")
    if body.payment_method == "cash_at_pickup" and body.order_type != "pickup":
        bad("Cash at pickup is only available for pickup orders.")
    if body.payment_method == "paystack" and not paystack.configured():
        bad("Online payment is not configured yet. Please choose another payment method.")
    if body.preferred_date and body.preferred_date < date.today():
        bad("Preferred date cannot be in the past.")
    user = p.user if p else None
    if user and user.role.is_staff:
        user = None  # staff must use the staff order screen
    order = order_svc.create_order(db, body, user=user, channel="online")
    audit.log(db, user, "order_placed_online", "order", order.order_number, request=request)
    db.commit()
    pay = order.payments[0] if order.payments else None
    return {"order_number": order.order_number, "tracking_token": order.tracking_token, "total_kobo": order.total_kobo,
            "status": order.status, "payment": {"reference": pay.reference, "method": pay.method, "status": pay.status} if pay else None,
            "bank": {"bank_name": s["bank_name"], "account_number": s["bank_account_number"], "account_name": s["bank_account_name"]}
            if body.payment_method == "bank_transfer" else None}


def _find_guest_order(db, number, phone=None, token=None):
    o = db.query(Order).filter(Order.order_number == number.strip().upper()).first()
    if not o:
        return None
    if token and o.tracking_token == token:
        return o
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    stored = "".join(ch for ch in o.contact_phone if ch.isdigit())
    if digits and len(digits) >= 6 and stored.endswith(digits[-9:]):
        return o
    return None


@router.get("/public/track")
def track(request: Request, number: str, phone: str = "", token: str = "", p=Depends(optional_principal), db: Session = Depends(get_db)):
    if not limiter.check(f"track:{_ip(request)}", 40, 600):
        raise HTTPException(429, "Too many tracking attempts. Please wait.")
    o = _find_guest_order(db, number, phone, token)
    if not o and p and not p.user.role.is_staff:
        c = db.query(Customer).filter(Customer.user_id == p.user.id).first()
        cand = db.query(Order).filter(Order.order_number == number.strip().upper()).first()
        if c and cand and cand.customer_id == c.id:
            o = cand
    if not o:
        raise HTTPException(404, "We could not find that order. Check the order number and phone number.")
    return customer_view_order(o)


@router.post("/public/orders/{number}/payment-proof")
def submit_proof(number: str, body: ProofIn, request: Request, phone: str = "", token: str = "",
                 p=Depends(optional_principal), db: Session = Depends(get_db)):
    """Customer reports a bank transfer. This only moves the payment to 'awaiting verification' - never to paid."""
    o = _find_guest_order(db, number, phone, token)
    if not o and p and not p.user.role.is_staff:
        c = db.query(Customer).filter(Customer.user_id == p.user.id).first()
        cand = db.query(Order).filter(Order.order_number == number.upper()).first()
        o = cand if (c and cand and cand.customer_id == c.id) else None
    if not o:
        raise HTTPException(404, "Order not found.")
    pay = next((x for x in o.payments if x.method == "bank_transfer" and x.status in ("pending", "rejected")), None)
    if not pay:
        bad("There is no bank-transfer payment waiting for confirmation on this order.", 409)
    pay.status = "awaiting_verification"
    pay.proof_reference = f"{body.transfer_reference} {body.note}".strip()[:120]
    from app.models import PaymentVerification
    db.add(PaymentVerification(payment_id=pay.id, action="submitted", note=pay.proof_reference))
    pay_svc.recompute_order_payment(o)
    from app.services import notify
    notify.notify_permission(db, "payments.verify", f"Transfer to verify: {o.order_number}",
                             f"Reference: {body.transfer_reference} - ₦{pay.amount_kobo / 100:,.2f}", "#/payments", "payment", o.branch_id)
    db.commit()
    return {"ok": True, "message": "Thank you. Our team will verify your transfer and confirm your order.", "payment_status": pay.status}


@router.post("/public/orders/{number}/paystack")
def paystack_init(number: str, token: str = "", phone: str = "", db: Session = Depends(get_db)):
    o = _find_guest_order(db, number, phone, token)
    if not o:
        raise HTTPException(404, "Order not found.")
    pay = next((x for x in o.payments if x.method == "paystack" and x.status in ("pending", "failed")), None)
    if not pay:
        bad("No online payment is pending for this order.", 409)
    data = paystack.initialize(db, pay, o, f"{get_settings().public_base_url}/#/track/{o.order_number}?paid=1&token={o.tracking_token}")
    return {"authorization_url": data["authorization_url"], "reference": pay.reference}


@router.post("/public/payments/{reference}/confirm")
def paystack_confirm(reference: str, db: Session = Depends(get_db)):
    pay = db.query(Payment).filter(Payment.reference == reference, Payment.method == "paystack").first()
    if not pay:
        raise HTTPException(404, "Payment not found.")
    ok = paystack.verify_with_gateway(db, pay)
    db.commit()
    return {"verified": ok}


@router.post("/webhooks/paystack")
async def paystack_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if not paystack.valid_signature(raw, request.headers.get("x-paystack-signature", "")):
        raise HTTPException(401, "Invalid signature.")
    import json
    event = json.loads(raw)
    if event.get("event") == "charge.success":
        ref = (event.get("data") or {}).get("reference")
        pay = db.query(Payment).filter(Payment.reference == ref, Payment.method == "paystack").first()
        if pay and pay.status not in ("verified",):
            paystack.verify_with_gateway(db, pay)
            db.commit()
    return {"ok": True}


# ---------------- signed-in customer ----------------
def _customer(db, p):
    if p.user.role.is_staff:
        raise HTTPException(403, "This endpoint is for customer accounts.")
    c = db.query(Customer).filter(Customer.user_id == p.user.id).first()
    if not c:
        raise HTTPException(404, "Customer profile not found.")
    return c


@router.get("/me/orders")
def my_orders(page: int = 1, p=Depends(current_principal), db: Session = Depends(get_db)):
    c = _customer(db, p)
    rows = db.query(Order).filter(Order.customer_id == c.id).order_by(Order.id.desc()).offset((page - 1) * 20).limit(20).all()
    return [customer_view_order(o) for o in rows]


@router.post("/me/orders/{number}/reorder")
def reorder(number: str, p=Depends(current_principal), db: Session = Depends(get_db)):
    c = _customer(db, p)
    o = db.query(Order).filter(Order.order_number == number, Order.customer_id == c.id).first()
    if not o:
        raise HTTPException(404, "Order not found.")
    lines, skipped = [], []
    for i in o.items:
        pr = db.get(Product, i.product_id)
        if pr and pr.is_active and pr.is_sellable:
            lines.append({"product_id": pr.id, "quantity": i.quantity})
        else:
            skipped.append(i.name)
    return {"items": lines, "unavailable": skipped, "branch_id": o.branch_id, "order_type": o.order_type}


@router.get("/me/notifications")
def my_notifications(p=Depends(current_principal), db: Session = Depends(get_db)):
    rows = db.query(Notification).filter(Notification.user_id == p.user.id, Notification.channel == "in_app") \
        .order_by(Notification.id.desc()).limit(50).all()
    return [{"id": n.id, "title": n.title, "body": n.body, "link": n.link, "is_read": n.is_read, "created_at": n.created_at.isoformat()} for n in rows]
