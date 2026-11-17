from datetime import date, datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies.auth import require, scope_branch, branch_filter
from app.models import (Supplier, PurchaseRequest, PurchaseRequestItem, PurchaseOrder, PurchaseOrderItem, GoodsReceipt, GoodsReceiptItem,
                        SupplierInvoice, SupplierPayment, Product, FinancialTransaction, Branch, User)
from app.schemas.common import (SupplierIn, PurchaseRequestIn, DecisionIn, PurchaseOrderIn, ReceiptIn, SupplierInvoiceIn, SupplierPaymentIn)
from app.services import audit, inventory, numbering, settings_service, notify
from app.utils import common
from app.utils.common import bad, num

router = APIRouter(prefix="/api", tags=["Suppliers & Purchasing"])


def _sup(s, balance=0):
    return {"id": s.id, "name": s.name, "contact_person": s.contact_person, "phone": s.phone, "email": s.email, "address": s.address,
            "materials_supplied": s.materials_supplied, "is_active": s.is_active, "outstanding_kobo": balance, "is_demo": s.is_demo}


def _balances(db, ids=None):
    q = select(SupplierInvoice.supplier_id, func.sum(SupplierInvoice.amount_kobo - SupplierInvoice.paid_kobo)).group_by(SupplierInvoice.supplier_id)
    return {k: int(v or 0) for k, v in db.execute(q)}


@router.get("/suppliers")
def suppliers(q: str = "", p=Depends(require("suppliers.view", "purchasing.view", any_of=True)), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    qs = db.query(Supplier).filter(Supplier.is_demo == demo)
    if q:
        qs = qs.filter(Supplier.name.ilike(f"%{q}%"))
    bal = _balances(db)
    return [_sup(s, bal.get(s.id, 0)) for s in qs.order_by(Supplier.name)]


@router.post("/suppliers", status_code=201)
def add_supplier(body: SupplierIn, request: Request, p=Depends(require("suppliers.manage")), db: Session = Depends(get_db)):
    s = Supplier(**body.model_dump(), is_demo=settings_service.is_demo_mode(db))
    db.add(s)
    db.flush()
    audit.log(db, p.user, "supplier_created", "supplier", s.id, request=request)
    db.commit()
    return _sup(s)


@router.put("/suppliers/{sid}")
def edit_supplier(sid: int, body: SupplierIn, p=Depends(require("suppliers.manage")), db: Session = Depends(get_db)):
    s = db.get(Supplier, sid)
    if not s:
        raise HTTPException(404, "Supplier not found.")
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    db.commit()
    return _sup(s)


@router.get("/suppliers/{sid}/statement")
def supplier_statement(sid: int, p=Depends(require("suppliers.view")), db: Session = Depends(get_db)):
    s = db.get(Supplier, sid)
    if not s:
        raise HTTPException(404, "Supplier not found.")
    inv = db.query(SupplierInvoice).filter(SupplierInvoice.supplier_id == sid).order_by(SupplierInvoice.id.desc()).all()
    pays = db.query(SupplierPayment).filter(SupplierPayment.supplier_id == sid).order_by(SupplierPayment.id.desc()).all()
    return {"supplier": _sup(s, sum(i.amount_kobo - i.paid_kobo for i in inv)),
            "invoices": [{"id": i.id, "invoice_number": i.invoice_number, "amount_kobo": i.amount_kobo, "paid_kobo": i.paid_kobo, "status": i.status,
                          "due_date": i.due_date.isoformat() if i.due_date else None, "po_id": i.po_id} for i in inv],
            "payments": [{"id": x.id, "invoice_id": x.invoice_id, "amount_kobo": x.amount_kobo, "method": x.method, "reference": x.reference,
                          "status": x.status, "at": x.created_at.isoformat()} for x in pays]}


# ---------------- purchase requests ----------------
def _pr(r: PurchaseRequest, names):
    return {"id": r.id, "number": r.number, "branch_id": r.branch_id, "status": r.status, "reason": r.reason,
            "requested_by": names.get(r.requested_by), "decision_note": r.decision_note, "created_at": r.created_at.isoformat(),
            "est_total_kobo": int(sum(Decimal(i.quantity) * i.est_unit_cost_kobo for i in r.items)),
            "items": [{"product_id": i.product_id, "name": i.product.name, "unit": i.product.unit, "quantity": num(i.quantity),
                       "est_unit_cost_kobo": i.est_unit_cost_kobo} for i in r.items]}


def _names(db):
    return {u.id: u.full_name for u in db.query(User).all()}


@router.get("/purchase-requests")
def list_prs(status: str = "", p=Depends(require("purchasing.view")), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    qs = db.query(PurchaseRequest).filter(PurchaseRequest.is_demo == demo, branch_filter(p, PurchaseRequest.branch_id))
    if status:
        qs = qs.filter(PurchaseRequest.status == status)
    n = _names(db)
    return [_pr(r, n) for r in qs.order_by(PurchaseRequest.id.desc()).limit(200)]


@router.post("/purchase-requests", status_code=201)
def create_pr(body: PurchaseRequestIn, request: Request, p=Depends(require("purchasing.request")), db: Session = Depends(get_db)):
    scope_branch(p, body.branch_id)
    if not body.items:
        bad("Add at least one item.")
    for it in body.items:
        pr = db.get(Product, it.product_id)
        if not pr or pr.kind == "finished":
            bad("Purchase requests are for raw materials and packaging only.")
    r = PurchaseRequest(number=numbering.number(db, "pr", "PR"), branch_id=body.branch_id, requested_by=p.id, reason=body.reason,
                        status="submitted" if body.submit else "draft", is_demo=settings_service.is_demo_mode(db))
    r.items = [PurchaseRequestItem(product_id=i.product_id, quantity=i.quantity, est_unit_cost_kobo=i.est_unit_cost_kobo) for i in body.items]
    db.add(r)
    db.flush()
    if body.submit:
        notify.notify_permission(db, "purchasing.approve", f"Purchase request {r.number} needs approval", body.reason, "#/purchasing", "approval", body.branch_id, p.id)
    audit.log(db, p.user, "purchase_request_created", "purchase_request", r.number, request=request)
    db.commit()
    return _pr(r, _names(db))


@router.post("/purchase-requests/{rid}/submit")
def submit_pr(rid: int, p=Depends(require("purchasing.request")), db: Session = Depends(get_db)):
    r = db.get(PurchaseRequest, rid)
    if not r or not p.can_branch(r.branch_id):
        raise HTTPException(404, "Request not found.")
    if r.status != "draft":
        bad("Only draft requests can be submitted.", 409)
    r.status = "submitted"
    notify.notify_permission(db, "purchasing.approve", f"Purchase request {r.number} needs approval", r.reason, "#/purchasing", "approval", r.branch_id, p.id)
    db.commit()
    return _pr(r, _names(db))


@router.post("/purchase-requests/{rid}/decide")
def decide_pr(rid: int, body: DecisionIn, request: Request, p=Depends(require("purchasing.approve")), db: Session = Depends(get_db)):
    r = db.get(PurchaseRequest, rid)
    if not r or not p.can_branch(r.branch_id):
        raise HTTPException(404, "Request not found.")
    if r.status != "submitted":
        bad("Request is not awaiting a decision.", 409)
    if r.requested_by == p.id and p.role_key != "super_admin":
        bad("You cannot approve your own request.", 403)
    r.status = "approved" if body.approve else "rejected"
    r.decided_by, r.decision_note = p.id, body.note
    r.decided_at = datetime.now(timezone.utc)
    notify.notify_user(db, r.requested_by, f"Purchase request {r.number} {r.status}", body.note, "#/purchasing", "approval")
    audit.log(db, p.user, "purchase_request_" + r.status, "purchase_request", r.number, {"note": body.note}, request)
    db.commit()
    return _pr(r, _names(db))


# ---------------- purchase orders ----------------
def _po(o: PurchaseOrder):
    return {"id": o.id, "number": o.number, "supplier_id": o.supplier_id, "supplier": o.supplier.name, "branch_id": o.branch_id,
            "status": o.status, "total_kobo": o.total_kobo, "notes": o.notes, "request_id": o.request_id, "created_at": o.created_at.isoformat(),
            "items": [{"product_id": i.product_id, "name": i.product.name, "unit": i.product.unit, "quantity": num(i.quantity),
                       "unit_cost_kobo": i.unit_cost_kobo, "received_qty": num(i.received_qty)} for i in o.items]}


@router.get("/purchase-orders")
def list_pos(status: str = "", p=Depends(require("purchasing.view")), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    qs = db.query(PurchaseOrder).filter(PurchaseOrder.is_demo == demo, branch_filter(p, PurchaseOrder.branch_id))
    if status:
        qs = qs.filter(PurchaseOrder.status == status)
    return [_po(o) for o in qs.order_by(PurchaseOrder.id.desc()).limit(200)]


@router.post("/purchase-orders", status_code=201)
def create_po(body: PurchaseOrderIn, request: Request, p=Depends(require("purchasing.request")), db: Session = Depends(get_db)):
    scope_branch(p, body.branch_id)
    if not db.get(Supplier, body.supplier_id):
        bad("Supplier not found.", 404)
    if not body.items:
        bad("Add at least one item.")
    if body.request_id:
        pr = db.get(PurchaseRequest, body.request_id)
        if not pr or pr.status != "approved":
            bad("A purchase order can only be raised from an approved purchase request.", 409)
    o = PurchaseOrder(number=numbering.number(db, "po", "PO"), supplier_id=body.supplier_id, branch_id=body.branch_id, request_id=body.request_id,
                      created_by=p.id, notes=body.notes, is_demo=settings_service.is_demo_mode(db))
    o.items = [PurchaseOrderItem(product_id=i.product_id, quantity=i.quantity, unit_cost_kobo=i.unit_cost_kobo) for i in body.items]
    o.total_kobo = int(sum(Decimal(str(i.quantity)) * i.unit_cost_kobo for i in body.items))
    db.add(o)
    db.flush()
    if body.request_id:
        db.get(PurchaseRequest, body.request_id).status = "ordered"
    notify.notify_permission(db, "purchasing.approve", f"Purchase order {o.number} needs approval", f"₦{o.total_kobo / 100:,.2f}", "#/purchasing", "approval", body.branch_id, p.id)
    audit.log(db, p.user, "purchase_order_created", "purchase_order", o.number, {"total": o.total_kobo}, request)
    db.commit()
    db.refresh(o)
    return _po(o)


@router.post("/purchase-orders/{oid}/decide")
def decide_po(oid: int, body: DecisionIn, request: Request, p=Depends(require("purchasing.approve")), db: Session = Depends(get_db)):
    o = db.get(PurchaseOrder, oid)
    if not o or not p.can_branch(o.branch_id):
        raise HTTPException(404, "Purchase order not found.")
    if o.status != "draft":
        bad("Purchase order is not awaiting approval.", 409)
    if o.created_by == p.id and p.role_key != "super_admin":
        bad("You cannot approve your own purchase order.", 403)
    o.status = "approved" if body.approve else "cancelled"
    o.approved_by = p.id if body.approve else None
    notify.notify_user(db, o.created_by, f"Purchase order {o.number} {'approved' if body.approve else 'rejected'}", body.note, "#/purchasing", "approval")
    audit.log(db, p.user, "purchase_order_" + o.status, "purchase_order", o.number, request=request)
    db.commit()
    return _po(o)


@router.post("/purchase-orders/{oid}/receive", status_code=201)
def receive_goods(oid: int, body: ReceiptIn, request: Request, p=Depends(require("purchasing.receive")), db: Session = Depends(get_db)):
    o = db.execute(select(PurchaseOrder).where(PurchaseOrder.id == oid).with_for_update()).scalar_one_or_none()
    if not o or not p.can_branch(o.branch_id):
        raise HTTPException(404, "Purchase order not found.")
    if o.status not in ("approved", "partially_received"):
        bad("Goods can only be received against an approved purchase order.", 409)
    gr = GoodsReceipt(number=numbering.number(db, "grn", "GRN"), po_id=o.id, branch_id=o.branch_id, received_by=p.id, delivery_note=body.delivery_note)
    lines = {i.product_id: i for i in o.items}
    for ln in body.items:
        it = lines.get(ln.product_id)
        if not it:
            bad("Item is not on this purchase order.")
        if Decimal(str(ln.quantity)) > Decimal(it.quantity) - Decimal(it.received_qty):
            bad(f"Cannot receive more {it.product.name} than ordered.")
        it.received_qty = Decimal(it.received_qty) + Decimal(str(ln.quantity))
        gr.items.append(GoodsReceiptItem(product_id=ln.product_id, quantity=ln.quantity))
        inventory.move(db, ln.product_id, o.branch_id, ln.quantity, "purchase_in", p.id, f"{gr.number} / {o.number}", "purchase_order", o.number)
        prod = db.get(Product, ln.product_id)
        if it.unit_cost_kobo and prod.cost_kobo != it.unit_cost_kobo:
            prod.cost_kobo = it.unit_cost_kobo  # latest purchase cost becomes the standard cost
    o.status = "received" if all(Decimal(i.received_qty) >= Decimal(i.quantity) for i in o.items) else "partially_received"
    db.add(gr)
    audit.log(db, p.user, "goods_received", "purchase_order", o.number, {"grn": gr.number}, request)
    db.commit()
    return {"receipt": gr.number, "status": o.status}


# ---------------- supplier invoices & payments ----------------
@router.post("/supplier-invoices", status_code=201)
def add_invoice(body: SupplierInvoiceIn, request: Request, p=Depends(require("finance.manage", "purchasing.receive", any_of=True)), db: Session = Depends(get_db)):
    if not db.get(Supplier, body.supplier_id):
        bad("Supplier not found.", 404)
    branch_id = None
    if body.po_id:
        po = db.get(PurchaseOrder, body.po_id)
        if not po or po.supplier_id != body.supplier_id:
            bad("Purchase order does not belong to that supplier.")
        branch_id = po.branch_id
    inv = SupplierInvoice(supplier_id=body.supplier_id, po_id=body.po_id, branch_id=branch_id, invoice_number=body.invoice_number,
                          amount_kobo=body.amount_kobo, due_date=body.due_date, recorded_by=p.id, is_demo=settings_service.is_demo_mode(db))
    db.add(inv)
    audit.log(db, p.user, "supplier_invoice_recorded", "supplier", body.supplier_id, {"invoice": body.invoice_number, "amount": body.amount_kobo}, request)
    db.commit()
    return {"id": inv.id}


@router.post("/supplier-payments", status_code=201)
def pay_supplier(body: SupplierPaymentIn, request: Request, p=Depends(require("finance.manage")), db: Session = Depends(get_db)):
    inv = db.execute(select(SupplierInvoice).where(SupplierInvoice.id == body.invoice_id).with_for_update()).scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Invoice not found.")
    if body.amount_kobo > inv.amount_kobo - inv.paid_kobo:
        bad("Payment exceeds the outstanding invoice balance.")
    threshold = int(settings_service.get(db, "expense_approval_threshold_kobo") or 0)
    pay = SupplierPayment(supplier_id=inv.supplier_id, invoice_id=inv.id, branch_id=inv.branch_id, amount_kobo=body.amount_kobo,
                          method=body.method, reference=body.reference, paid_by=p.id, is_demo=inv.is_demo)
    if threshold and body.amount_kobo >= threshold and p.role_key not in ("super_admin", "general_manager"):
        pay.status = "pending_approval"
        db.add(pay)
        db.flush()
        notify.notify_permission(db, "purchasing.approve", "Supplier payment needs approval", f"₦{body.amount_kobo / 100:,.2f} - {inv.supplier.name}", "#/suppliers", "approval")
        db.commit()
        return {"id": pay.id, "status": pay.status}
    db.add(pay)
    db.flush()
    _post_supplier_payment(db, inv, pay, p)
    audit.log(db, p.user, "supplier_payment", "supplier", inv.supplier_id, {"amount": body.amount_kobo, "invoice": inv.invoice_number}, request)
    db.commit()
    return {"id": pay.id, "status": pay.status}


def _post_supplier_payment(db, inv, pay, user):
    inv.paid_kobo += pay.amount_kobo
    inv.status = "paid" if inv.paid_kobo >= inv.amount_kobo else "part_paid"
    pay.status = "paid"
    pay.approved_by = user.id
    bid = inv.branch_id or pay.branch_id
    if bid is None:
        bid = db.query(Branch).filter(Branch.is_demo == inv.is_demo).order_by(Branch.id).first().id
    db.add(FinancialTransaction(reference=numbering.number(db, "txn", "TXN"), kind="supplier_payment", direction="out", amount_kobo=pay.amount_kobo,
                                method=pay.method, branch_id=bid, txn_date=common.today(), description=f"Supplier payment {inv.invoice_number}",
                                supplier_payment_id=pay.id, recorded_by=user.id, verification_status="verified", is_demo=inv.is_demo))


@router.post("/supplier-payments/{pid}/decide")
def decide_supplier_payment(pid: int, body: DecisionIn, p=Depends(require("purchasing.approve")), db: Session = Depends(get_db)):
    pay = db.get(SupplierPayment, pid)
    if not pay or pay.status != "pending_approval":
        raise HTTPException(404, "No pending payment found.")
    if pay.paid_by == p.id and p.role_key != "super_admin":
        bad("You cannot approve a payment you initiated.", 403)
    inv = db.execute(select(SupplierInvoice).where(SupplierInvoice.id == pay.invoice_id).with_for_update()).scalar_one()
    if body.approve:
        if pay.amount_kobo > inv.amount_kobo - inv.paid_kobo:
            bad("Payment now exceeds the outstanding balance.")
        _post_supplier_payment(db, inv, pay, p)
    else:
        pay.status = "rejected"
    db.commit()
    return {"status": pay.status}
