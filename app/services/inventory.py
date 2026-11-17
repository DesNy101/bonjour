from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import InventoryBalance, StockMovement, Product, Branch
from app.utils.common import bad, dec, num
from app.services import settings_service, notify

SIGNED_IN = {"addition", "transfer_in", "production_in", "purchase_in", "opening"}
SIGNED_OUT = {"deduction", "damaged", "expired", "wastage", "transfer_out", "production_out", "sale_out"}


def _lock_balance(db: Session, product_id: int, branch_id: int) -> InventoryBalance:
    bal = db.execute(select(InventoryBalance).where(InventoryBalance.product_id == product_id, InventoryBalance.branch_id == branch_id).with_for_update()).scalar_one_or_none()
    if bal is None:
        bal = InventoryBalance(product_id=product_id, branch_id=branch_id, quantity=Decimal(0))
        db.add(bal)
        db.flush()
        bal = db.execute(select(InventoryBalance).where(InventoryBalance.id == bal.id).with_for_update()).scalar_one()
    return bal


def balance(db: Session, product_id: int, branch_id: int) -> Decimal:
    b = db.execute(select(InventoryBalance.quantity).where(InventoryBalance.product_id == product_id, InventoryBalance.branch_id == branch_id)).scalar_one_or_none()
    return Decimal(b or 0)


def move(db: Session, product_id: int, branch_id: int, qty, mtype: str, user_id: int | None, reason: str = "", ref_type: str = "", ref_id="") -> StockMovement:
    """The ONLY way stock changes. Row-locked, never negative, always logged."""
    qty = dec(qty)
    if mtype in SIGNED_OUT:
        signed = -abs(qty)
    elif mtype in SIGNED_IN:
        signed = abs(qty)
    elif mtype == "adjustment":
        signed = qty
    else:
        bad("Unknown movement type.")
    if signed == 0:
        bad("Quantity must not be zero.")
    product = db.get(Product, product_id)
    if not product:
        bad("Product not found.", 404)
    bal = _lock_balance(db, product_id, branch_id)
    new = Decimal(bal.quantity) + signed
    if new < 0:
        bad(f"Insufficient stock for {product.name}: have {num(bal.quantity)}, need {num(-signed)}.")
    bal.quantity = new
    mv = StockMovement(product_id=product_id, branch_id=branch_id, movement_type=mtype, quantity=signed, balance_after=new, reason=reason,
                       reference_type=ref_type, reference_id=str(ref_id), user_id=user_id, is_demo=settings_service.is_demo_mode(db))
    db.add(mv)
    db.flush()
    if signed < 0 and product.reorder_level and new <= product.reorder_level and settings_service.get(db, "low_stock_alerts"):
        branch = db.get(Branch, branch_id)
        notify.notify_permission(db, "inventory.view", f"Low stock: {product.name}",
                                 f"{num(new)} {product.unit} left at {branch.name if branch else ''} (reorder level {num(product.reorder_level)}).", "#/inventory", "stock", branch_id)
    return mv


def transfer(db: Session, product_id: int, from_branch: int, to_branch: int, qty, user_id: int, number: str, note: str = ""):
    from app.models import StockTransfer
    if from_branch == to_branch:
        bad("Source and destination branches must differ.")
    qty = dec(qty)
    if qty <= 0:
        bad("Quantity must be greater than zero.")
    move(db, product_id, from_branch, qty, "transfer_out", user_id, f"Transfer {number}: {note}", "transfer", number)
    move(db, product_id, to_branch, qty, "transfer_in", user_id, f"Transfer {number}: {note}", "transfer", number)
    t = StockTransfer(number=number, product_id=product_id, from_branch_id=from_branch, to_branch_id=to_branch, quantity=qty, note=note, user_id=user_id)
    db.add(t)
    return t
