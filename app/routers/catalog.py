from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Query
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies.auth import require, staff_principal, scope_branch
from app.models import (Product, ProductCategory, InventoryBalance, StockMovement, StockTransfer, Branch, Customer, CustomerAddress, Order)
from app.schemas.common import ProductIn, CategoryIn, StockMoveIn, TransferIn, CustomerIn
from app.serializers import product_out, customer_out, order_out
from app.services import audit, inventory, numbering, settings_service
from app.utils import common
from app.utils.common import bad, num
from app.utils.uploads import save_image

router = APIRouter(prefix="/api", tags=["Products & Inventory"])


# ---------------- products ----------------
@router.get("/product-categories")
def categories(p=Depends(staff_principal), db: Session = Depends(get_db)):
    return [{"id": c.id, "name": c.name, "kind": c.kind} for c in db.query(ProductCategory).order_by(ProductCategory.name)]


@router.post("/product-categories", status_code=201)
def add_category(body: CategoryIn, p=Depends(require("products.manage")), db: Session = Depends(get_db)):
    if body.kind not in ("finished", "raw", "packaging"):
        bad("Invalid category kind.")
    if db.query(ProductCategory).filter(func.lower(ProductCategory.name) == body.name.lower()).first():
        bad("Category already exists.", 409)
    c = ProductCategory(name=body.name, kind=body.kind)
    db.add(c)
    db.commit()
    return {"id": c.id, "name": c.name, "kind": c.kind}


def _qty_map(db, ids, product_ids=None):
    q = select(InventoryBalance.product_id, func.sum(InventoryBalance.quantity)).group_by(InventoryBalance.product_id)
    if ids is not None:
        q = q.where(InventoryBalance.branch_id.in_(ids or {-1}))
    return {pid: Decimal(v) for pid, v in db.execute(q)}


@router.get("/products")
def list_products(q: str = "", kind: str = "", category_id: int | None = None, active: bool | None = None, branch_id: int | None = None,
                  page: int = 1, size: int = 100, p=Depends(require("products.view", "inventory.view", "production.view", "purchasing.view", "recipes.manage", any_of=True)),
                  db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    scope_branch(p, branch_id)
    qs = db.query(Product).filter(Product.is_demo == demo)
    if q:
        qs = qs.filter(or_(Product.name.ilike(f"%{q}%"), Product.sku.ilike(f"%{q}%")))
    if kind:
        qs = qs.filter(Product.kind == kind)
    if category_id:
        qs = qs.filter(Product.category_id == category_id)
    if active is not None:
        qs = qs.filter(Product.is_active == active)
    total = qs.count()
    rows = qs.order_by(Product.name, Product.id).offset((page - 1) * size).limit(size).all()
    qm = _qty_map(db, {branch_id} if branch_id else p.branch_ids)
    items = [product_out(r, qm.get(r.id, Decimal(0))) for r in rows]
    if not p.can("finance.view") and not p.can("products.manage"):
        for i in items:
            i.pop("cost_kobo", None)
    return {"total": total, "items": items}


def _unique_sku(db, sku, exclude=None):
    q = db.query(Product).filter(func.lower(Product.sku) == sku.lower())
    if exclude:
        q = q.filter(Product.id != exclude)
    if q.first():
        bad("SKU already exists.", 409)


@router.post("/products", status_code=201)
def create_product(body: ProductIn, request: Request, p=Depends(require("products.manage")), db: Session = Depends(get_db)):
    if body.kind not in ("finished", "raw", "packaging"):
        bad("Invalid product kind.")
    _unique_sku(db, body.sku)
    data = body.model_dump(exclude={"opening_stock", "opening_branch_id"})
    data["sku"] = data["sku"].upper()
    if data["is_sellable"] is None:
        data["is_sellable"] = body.kind == "finished"
    if body.kind != "finished":
        data["is_sellable"] = False
    if data["is_sellable"] and body.price_kobo <= 0:
        bad("A sellable product needs a price.")
    prod = Product(**data, is_demo=settings_service.is_demo_mode(db))
    db.add(prod)
    db.flush()
    if body.opening_stock > 0:
        bid = scope_branch(p, body.opening_branch_id, required=True)
        inventory.move(db, prod.id, bid, body.opening_stock, "opening", p.id, "Opening stock", "product", prod.sku)
    audit.log(db, p.user, "product_created", "product", prod.id, {"sku": prod.sku, "name": prod.name}, request)
    db.commit()
    db.refresh(prod)
    return product_out(prod)


@router.put("/products/{pid}")
def update_product(pid: int, body: ProductIn, request: Request, p=Depends(require("products.manage")), db: Session = Depends(get_db)):
    prod = db.get(Product, pid)
    if not prod:
        raise HTTPException(404, "Product not found.")
    _unique_sku(db, body.sku, pid)
    old_price = prod.price_kobo
    for k, v in body.model_dump(exclude={"opening_stock", "opening_branch_id", "kind"}).items():
        if k == "is_sellable" and v is None:
            continue
        setattr(prod, k, v.upper() if k == "sku" else v)
    if prod.kind != "finished":
        prod.is_sellable = False
    if prod.is_sellable and prod.price_kobo <= 0:
        bad("A sellable product needs a price.")
    audit.log(db, p.user, "product_updated", "product", prod.id, {"price_from": old_price, "price_to": prod.price_kobo}, request)
    db.commit()
    db.refresh(prod)
    return product_out(prod)


@router.post("/products/{pid}/image")
async def upload_product_image(pid: int, file: UploadFile = File(...), p=Depends(require("products.manage")), db: Session = Depends(get_db)):
    prod = db.get(Product, pid)
    if not prod:
        raise HTTPException(404, "Product not found.")
    prod.image_url = await save_image(file, "products")
    db.commit()
    return {"image_url": prod.image_url}


# ---------------- inventory ----------------
@router.get("/inventory/stock")
def stock(branch_id: int | None = None, kind: str = "", q: str = "", low: bool = False, page: int = 1, size: int = 100,
          p=Depends(require("inventory.view")), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    scope_branch(p, branch_id)
    ids = {branch_id} if branch_id else p.branch_ids
    qs = (select(InventoryBalance, Product, Branch).join(Product, Product.id == InventoryBalance.product_id)
          .join(Branch, Branch.id == InventoryBalance.branch_id).where(Product.is_demo == demo))
    if ids is not None:
        qs = qs.where(InventoryBalance.branch_id.in_(ids or {-1}))
    if kind:
        qs = qs.where(Product.kind == kind)
    if q:
        qs = qs.where(or_(Product.name.ilike(f"%{q}%"), Product.sku.ilike(f"%{q}%")))
    if low:
        qs = qs.where(Product.reorder_level > 0, InventoryBalance.quantity <= Product.reorder_level)
    total = db.execute(select(func.count()).select_from(qs.subquery())).scalar()
    rows = db.execute(qs.order_by(Product.name, Branch.name).offset((page - 1) * size).limit(size)).all()
    return {"total": total, "items": [{
        "product_id": pr.id, "sku": pr.sku, "name": pr.name, "kind": pr.kind, "unit": pr.unit, "branch_id": br.id, "branch": br.name,
        "quantity": num(b.quantity), "reorder_level": num(pr.reorder_level), "cost_kobo": pr.cost_kobo,
        "value_kobo": int(Decimal(b.quantity) * pr.cost_kobo), "low_stock": bool(pr.reorder_level) and b.quantity <= pr.reorder_level}
        for b, pr, br in rows]}


MOVE_TYPES = {"addition", "deduction", "damaged", "expired", "wastage"}


@router.post("/inventory/movements", status_code=201)
def record_movement(body: StockMoveIn, request: Request, p=Depends(require("inventory.adjust")), db: Session = Depends(get_db)):
    if body.movement_type not in MOVE_TYPES:
        bad("Movement type must be one of: " + ", ".join(sorted(MOVE_TYPES)))
    if body.quantity <= 0:
        bad("Quantity must be greater than zero.")
    scope_branch(p, body.branch_id, required=True)
    br = db.get(Branch, body.branch_id)
    if not br or not br.is_active:
        bad("Branch not available.")
    mv = inventory.move(db, body.product_id, body.branch_id, body.quantity, body.movement_type, p.id, body.reason, "manual")
    audit.log(db, p.user, "stock_" + body.movement_type, "product", body.product_id, {"qty": body.quantity, "branch": body.branch_id, "reason": body.reason}, request)
    db.commit()
    return {"id": mv.id, "balance_after": num(mv.balance_after)}


@router.get("/inventory/movements")
def movements(product_id: int | None = None, branch_id: int | None = None, movement_type: str = "", date_from: str = "", date_to: str = "",
              page: int = 1, size: int = 50, p=Depends(require("inventory.view")), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    scope_branch(p, branch_id)
    qs = db.query(StockMovement).filter(StockMovement.is_demo == demo)
    if p.branch_ids is not None:
        qs = qs.filter(StockMovement.branch_id.in_(p.branch_ids or {-1}))
    if branch_id:
        qs = qs.filter(StockMovement.branch_id == branch_id)
    if product_id:
        qs = qs.filter(StockMovement.product_id == product_id)
    if movement_type:
        qs = qs.filter(StockMovement.movement_type == movement_type)
    from datetime import date as _d
    if date_from:
        qs = qs.filter(StockMovement.created_at >= common.day_start(_d.fromisoformat(date_from)))
    if date_to:
        qs = qs.filter(StockMovement.created_at < common.day_end(_d.fromisoformat(date_to)))
    total = qs.count()
    rows = qs.order_by(StockMovement.id.desc()).offset((page - 1) * size).limit(size).all()
    names = {b.id: b.name for b in db.query(Branch).all()}
    from app.models import User
    users = {u.id: u.full_name for u in db.query(User).filter(User.id.in_({r.user_id for r in rows if r.user_id} or {-1}))}
    return {"total": total, "items": [{"id": m.id, "product": m.product.name, "product_id": m.product_id, "branch": names.get(m.branch_id),
                                       "type": m.movement_type, "quantity": num(m.quantity), "balance_after": num(m.balance_after),
                                       "reason": m.reason, "reference": f"{m.reference_type} {m.reference_id}".strip(),
                                       "by": users.get(m.user_id, "System"), "at": m.created_at.isoformat()} for m in rows]}


@router.post("/inventory/transfers", status_code=201)
def create_transfer(body: TransferIn, request: Request, p=Depends(require("inventory.transfer")), db: Session = Depends(get_db)):
    if not p.can_branch(body.from_branch_id) or not p.can_branch(body.to_branch_id):
        bad("You can only transfer between branches you are authorised for.", 403)
    for bid in (body.from_branch_id, body.to_branch_id):
        b = db.get(Branch, bid)
        if not b or not b.is_active:
            bad("Branch not available.")
    num_ = numbering.number(db, "trf", "TRF")
    inventory.transfer(db, body.product_id, body.from_branch_id, body.to_branch_id, body.quantity, p.id, num_, body.note)
    audit.log(db, p.user, "stock_transfer", "product", body.product_id, {"number": num_, "qty": body.quantity}, request)
    db.commit()
    return {"number": num_}


@router.get("/inventory/transfers")
def transfers(p=Depends(require("inventory.view")), db: Session = Depends(get_db)):
    names = {b.id: b.name for b in db.query(Branch).all()}
    qs = db.query(StockTransfer)
    if p.branch_ids is not None:
        qs = qs.filter(or_(StockTransfer.from_branch_id.in_(p.branch_ids or {-1}), StockTransfer.to_branch_id.in_(p.branch_ids or {-1})))
    rows = qs.order_by(StockTransfer.id.desc()).limit(100).all()
    pn = {x.id: x.name for x in db.query(Product).filter(Product.id.in_({r.product_id for r in rows} or {-1}))}
    return [{"number": t.number, "product": pn.get(t.product_id), "from": names.get(t.from_branch_id), "to": names.get(t.to_branch_id),
             "quantity": num(t.quantity), "note": t.note, "at": t.created_at.isoformat()} for t in rows]


# ---------------- customers ----------------
@router.get("/customers")
def list_customers(q: str = "", customer_type: str = "", page: int = 1, size: int = 50,
                   p=Depends(require("customers.view")), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    qs = db.query(Customer).filter(Customer.is_demo == demo)
    if q:
        qs = qs.filter(or_(Customer.name.ilike(f"%{q}%"), Customer.phone.ilike(f"%{q}%"), Customer.email.ilike(f"%{q}%")))
    if customer_type:
        qs = qs.filter(Customer.customer_type == customer_type)
    total = qs.count()
    rows = qs.order_by(Customer.name).offset((page - 1) * size).limit(size).all()
    ids = [c.id for c in rows] or [-1]
    agg = {r[0]: (r[1], int(r[2] or 0), int(r[3] or 0)) for r in db.execute(
        select(Order.customer_id, func.count(), func.sum(Order.total_kobo), func.sum(Order.total_kobo - Order.paid_kobo))
        .where(Order.customer_id.in_(ids), Order.status != "cancelled").group_by(Order.customer_id))}
    out = []
    for c in rows:
        d = customer_out(c, full=False)
        a = agg.get(c.id, (0, 0, 0))
        d.update({"orders": a[0], "total_purchases_kobo": a[1], "outstanding_kobo": a[2]})
        out.append(d)
    return {"total": total, "items": out}


@router.get("/customers/{cid}")
def get_customer(cid: int, p=Depends(require("customers.view")), db: Session = Depends(get_db)):
    c = db.get(Customer, cid)
    if not c:
        raise HTTPException(404, "Customer not found.")
    orders = db.query(Order).filter(Order.customer_id == cid)
    if p.branch_ids is not None:
        orders = orders.filter(Order.branch_id.in_(p.branch_ids or {-1}))
    orders = orders.order_by(Order.id.desc()).limit(50).all()
    d = customer_out(c)
    d["orders"] = [order_out(o, internal=False) for o in orders]
    live = [o for o in orders if o.status != "cancelled"]
    d["total_purchases_kobo"] = sum(o.total_kobo for o in live)
    d["outstanding_kobo"] = sum(o.total_kobo - o.paid_kobo for o in live)
    return d


@router.post("/customers", status_code=201)
def create_customer(body: CustomerIn, request: Request, p=Depends(require("customers.manage")), db: Session = Depends(get_db)):
    if body.customer_type not in ("retail", "wholesale", "bulk", "business"):
        bad("Invalid customer type.")
    c = Customer(name=body.name, phone=body.phone, email=body.email.lower(), customer_type=body.customer_type,
                 preferred_branch_id=body.preferred_branch_id, notes=body.notes, is_demo=settings_service.is_demo_mode(db))
    db.add(c)
    db.flush()
    if body.address:
        db.add(CustomerAddress(customer_id=c.id, address=body.address, is_default=True))
    audit.log(db, p.user, "customer_created", "customer", c.id, request=request)
    db.commit()
    db.refresh(c)
    return customer_out(c)


@router.put("/customers/{cid}")
def update_customer(cid: int, body: CustomerIn, p=Depends(require("customers.manage")), db: Session = Depends(get_db)):
    c = db.get(Customer, cid)
    if not c:
        raise HTTPException(404, "Customer not found.")
    if body.customer_type not in ("retail", "wholesale", "bulk", "business"):
        bad("Invalid customer type.")
    c.name, c.phone, c.email, c.customer_type = body.name, body.phone, body.email.lower(), body.customer_type
    c.preferred_branch_id, c.notes = body.preferred_branch_id, body.notes
    db.commit()
    return customer_out(c)
