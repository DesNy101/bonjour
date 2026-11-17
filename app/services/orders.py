import secrets
from sqlalchemy.orm import Session
from app.models import (Order, OrderItem, OrderStatusHistory, Product, Branch, Customer, CustomerAddress)
from app.services import inventory, notify, numbering, settings_service, payments as pay_svc
from app.utils.common import bad

STATUSES = ["pending", "confirmed", "awaiting_payment", "paid", "queued_for_production", "in_production", "ready_for_collection", "ready_for_dispatch",
            "assigned_to_driver", "out_for_delivery", "delivered", "completed", "cancelled"]
LABELS = {s: s.replace("_", " ").title() for s in STATUSES}

TRANSITIONS = {
    "pending": {"confirmed", "awaiting_payment", "paid", "cancelled"},
    "confirmed": {"awaiting_payment", "paid", "queued_for_production", "ready_for_collection", "ready_for_dispatch", "cancelled"},
    "awaiting_payment": {"paid", "confirmed", "cancelled"},
    "paid": {"queued_for_production", "ready_for_collection", "ready_for_dispatch", "cancelled"},
    "queued_for_production": {"in_production", "cancelled"},
    "in_production": {"ready_for_collection", "ready_for_dispatch", "cancelled"},
    "ready_for_collection": {"completed", "cancelled"},
    "ready_for_dispatch": {"assigned_to_driver", "cancelled"},
    "assigned_to_driver": {"out_for_delivery", "ready_for_dispatch"},
    "out_for_delivery": {"delivered", "ready_for_dispatch"},
    "delivered": {"completed"},
    "completed": set(),
    "cancelled": set(),
}
READY = {"ready_for_collection", "ready_for_dispatch"}
DISPATCH_ONLY = {"assigned_to_driver", "out_for_delivery", "delivered"}


def _record(db, order, frm, to, user, note):
    db.add(OrderStatusHistory(order_id=order.id, from_status=frm or "", to_status=to, user_id=getattr(user, "id", None),
                              user_label=(getattr(user, "full_name", None) or "System") if user else "Customer", note=note[:300]))


def deduct_stock(db: Session, order: Order, user):
    if order.stock_deducted:
        return
    for it in order.items:
        inventory.move(db, it.product_id, order.branch_id, it.quantity, "sale_out", getattr(user, "id", None), f"Order {order.order_number}", "order", order.order_number)
    order.stock_deducted = True


def restore_stock(db: Session, order: Order, user):
    if not order.stock_deducted:
        return
    for it in order.items:
        inventory.move(db, it.product_id, order.branch_id, it.quantity, "addition", getattr(user, "id", None), f"Order {order.order_number} cancelled - stock returned", "order", order.order_number)
    order.stock_deducted = False


def change_status(db: Session, order: Order, to: str, user, note: str = "", force: bool = False):
    frm = order.status
    if to not in STATUSES:
        bad("Unknown status.")
    if frm == to:
        return order
    if to not in TRANSITIONS.get(frm, set()):
        bad(f"Cannot move an order from '{LABELS[frm]}' to '{LABELS[to]}'.", 409)
    if to in DISPATCH_ONLY and not force:
        bad("This step is performed through the Dispatch module.", 409)
    if to == "cancelled" and not note.strip():
        bad("A reason is required to cancel an order.")
    if to == "ready_for_dispatch" and order.order_type != "delivery":
        bad("Pickup orders cannot be dispatched. Use 'Ready for Collection'.")
    if to == "ready_for_collection" and order.order_type != "pickup":
        bad("Delivery orders go to 'Ready for Dispatch'.")
    if to in READY:
        deduct_stock(db, order, user)
    if to == "cancelled":
        if order.paid_kobo > 0:
            note += " (NOTE: payment already received - refund required)"
        restore_stock(db, order, user)
        order.cancel_reason = note[:300]
    order.status = to
    _record(db, order, frm, to, user, note)
    cust = db.get(Customer, order.customer_id) if order.customer_id else None
    msg = {"confirmed": "Your order has been confirmed.", "ready_for_collection": "Your order is ready for collection.", "out_for_delivery": "Your order is on its way.",
           "delivered": "Your order has been delivered. Enjoy!", "cancelled": "Your order was cancelled.", "in_production": "Your bread is being baked."}.get(to)
    if msg:
        notify.notify_customer(db, cust, f"Order {order.order_number}: {LABELS[to]}", msg, f"#/track/{order.order_number}")
    if to == "confirmed":
        notify.notify_permission(db, "orders.view", f"Order {order.order_number} confirmed", "", "#/orders", "order", order.branch_id, getattr(user, "id", None))
    if to == "cancelled":
        notify.notify_permission(db, "orders.view", f"Order {order.order_number} cancelled", note, "#/orders", "order", order.branch_id, getattr(user, "id", None))
    if to == "delivered" and order.payment_status == "paid":
        order.status = "completed"
        _record(db, order, "delivered", "completed", user, "Auto-completed: delivered and fully paid")
    return order


def compute_totals(db: Session, lines, order_type: str, branch_id: int, wholesale: bool = False):
    s = settings_service.all_settings(db)
    items, subtotal, merged = [], 0, {}
    for ln in lines:
        merged[ln.product_id] = merged.get(ln.product_id, 0) + ln.quantity
    if not merged:
        bad("Add at least one item.")
    for pid, qty in merged.items():
        p = db.get(Product, pid)
        if not p or not p.is_active or not p.is_sellable or p.kind != "finished":
            bad("One of the products is not available.")
        if qty <= 0 or qty > 100000:
            bad("Invalid quantity.")
        price = p.wholesale_price_kobo if (wholesale and p.wholesale_price_kobo) else p.price_kobo
        items.append(OrderItem(product_id=p.id, name=f"{p.name}{' (' + p.size_label + ')' if p.size_label else ''}", unit_price_kobo=price,
                               unit_cost_kobo=p.cost_kobo, quantity=qty, line_total_kobo=price * qty))
        subtotal += price * qty
    if subtotal < int(s.get("min_order_kobo") or 0):
        bad("Order is below the minimum order value.")
    fee = 0
    if order_type == "delivery":
        fee = int(s["delivery_fee_kobo"])
        free_above = int(s.get("free_delivery_above_kobo") or 0)
        if free_above and subtotal >= free_above:
            fee = 0
    tax = round(subtotal * float(s["tax_rate_percent"]) / 100) if s.get("tax_enabled") else 0
    return items, subtotal, fee, int(tax), subtotal + fee + int(tax)


def find_or_create_customer(db: Session, name, phone, email, user=None, address=None, lga="", branch_id=None, ctype="retail"):
    cust = None
    if user is not None and not user.role.is_staff:
        cust = db.query(Customer).filter(Customer.user_id == user.id).first()
    if cust is None and phone:
        cust = db.query(Customer).filter(Customer.phone == phone, Customer.is_demo == settings_service.is_demo_mode(db)).first()
    if cust is None:
        cust = Customer(name=name, phone=phone or "", email=(email or "").lower(), customer_type=ctype, preferred_branch_id=branch_id,
                        is_guest=user is None, is_demo=settings_service.is_demo_mode(db))
        db.add(cust)
        db.flush()
    if address and not any(a.address == address for a in cust.addresses):
        db.add(CustomerAddress(customer_id=cust.id, address=address, lga=lga, label="Delivery", is_default=not cust.addresses))
    return cust


def create_order(db: Session, data, user=None, channel: str = "online", staff=None) -> Order:
    branch = db.get(Branch, data.branch_id)
    if not branch or not branch.is_active:
        bad("Selected branch is not available.")
    if channel == "online" and not branch.accepts_online_orders:
        bad("This branch is not accepting online orders right now.")
    if data.order_type == "delivery" and not (data.delivery_address or "").strip():
        bad("Delivery address is required for delivery orders.")
    wholesale = channel in ("wholesale", "bulk")
    items, subtotal, fee, tax, total = compute_totals(db, data.items, data.order_type, branch.id, wholesale)
    cust = None
    if getattr(data, "customer_id", None):
        cust = db.get(Customer, data.customer_id)
        if not cust:
            bad("Customer not found.", 404)
    elif data.contact_phone or user is not None:
        cust = find_or_create_customer(db, data.contact_name, data.contact_phone, data.contact_email, user,
                                       data.delivery_address if data.order_type == "delivery" else None, getattr(data, "delivery_lga", ""), branch.id)
    method = data.payment_method
    order = Order(order_number=numbering.number(db, "order"), tracking_token=secrets.token_urlsafe(16), customer_id=cust.id if cust else None,
                  branch_id=branch.id, channel=channel, order_type=data.order_type, contact_name=data.contact_name, contact_phone=data.contact_phone or "",
                  contact_email=(data.contact_email or "").lower(), delivery_address=data.delivery_address or "", delivery_lga=getattr(data, "delivery_lga", "") or "",
                  delivery_instructions=getattr(data, "delivery_instructions", "") or "", preferred_date=data.preferred_date, preferred_time=data.preferred_time or "",
                  notes=data.notes or "", subtotal_kobo=subtotal, delivery_fee_kobo=fee, tax_kobo=tax, total_kobo=total,
                  created_by=getattr(staff, "id", None), is_demo=settings_service.is_demo_mode(db))
    order.items = items
    db.add(order)
    db.flush()
    initial = "awaiting_payment" if (method == "bank_transfer" and channel == "online") else "pending"
    _record(db, order, "", "pending", staff or user, f"Order placed via {channel}")
    order.status = "pending"
    if initial != "pending":
        order.status = initial
        _record(db, order, "pending", initial, None, "Waiting for bank transfer")
    if total > 0:
        pay_svc.create(db, order, method, total, getattr(staff, "id", None) or getattr(user, "id", None))
        db.flush()
        db.refresh(order)
    notify.notify_permission(db, "orders.view", f"New order {order.order_number}", f"{order.contact_name} - ₦{total / 100:,.2f} ({order.order_type})", "#/orders", "order", branch.id)
    notify.notify_customer(db, cust, f"Order {order.order_number} received", "Thank you! We have received your order and will confirm it shortly.", f"#/track/{order.order_number}")
    return order
