from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import Session
from app.models import (ProductionBatch, BatchStageLog, BatchConsumption, ProductionStage, Recipe, Product, Order)
from app.services import inventory, notify, settings_service
from app.utils.common import bad, dec, num


def recipe_unit_cost(recipe: Recipe) -> int:
    total = sum(Decimal(i.quantity) * i.material.cost_kobo for i in recipe.ingredients)
    return int(round(total / Decimal(recipe.yield_qty))) if recipe.yield_qty else 0


def expected_consumption(recipe: Recipe, planned_qty) -> list[tuple[int, Decimal]]:
    factor = dec(planned_qty) / Decimal(recipe.yield_qty)
    return [(i.material_id, (Decimal(i.quantity) * factor).quantize(Decimal("0.0001"))) for i in recipe.ingredients]


def init_batch(db: Session, batch: ProductionBatch):
    recipe = db.get(Recipe, batch.recipe_id) if batch.recipe_id else None
    batch.consumption = []
    if recipe:
        for mid, q in expected_consumption(recipe, batch.planned_qty):
            batch.consumption.append(BatchConsumption(material_id=mid, expected_qty=q))
    stages = db.query(ProductionStage).filter(ProductionStage.is_active == True).order_by(ProductionStage.sequence).all()  # noqa
    batch.stage_logs = [BatchStageLog(stage_id=s.id) for s in stages]


def start(db: Session, batch: ProductionBatch, user):
    if batch.status != "planned":
        bad("Only planned batches can be started.", 409)
    short = []
    for c in batch.consumption:
        have = inventory.balance(db, c.material_id, batch.branch_id)
        if have < Decimal(c.expected_qty):
            short.append(f"{c.material.name}: need {num(c.expected_qty)}, have {num(have)}")
    if short:
        bad("Insufficient raw materials to start this batch - " + "; ".join(short))
    batch.status = "in_progress"
    batch.started_at = datetime.now(timezone.utc)
    if batch.stage_logs:
        first = batch.stage_logs[0]
        first.status = "active"
        first.started_at = batch.started_at
        batch.current_stage_id = first.stage_id
    if batch.plan and batch.plan.status == "planned":
        batch.plan.status = "in_progress"
    if batch.order_id:
        o = db.get(Order, batch.order_id)
        if o and o.status == "queued_for_production":
            from app.services import orders
            orders.change_status(db, o, "in_production", user, f"Batch {batch.batch_number} started")


def advance_stage(db: Session, batch: ProductionBatch, user, notes: str = ""):
    if batch.status != "in_progress":
        bad("Batch is not in progress.", 409)
    now = datetime.now(timezone.utc)
    logs = batch.stage_logs
    idx = next((i for i, l in enumerate(logs) if l.status == "active"), None)
    if idx is None:
        bad("No active stage.")
    logs[idx].status = "done"
    logs[idx].completed_at = now
    if notes:
        logs[idx].notes = notes
    if idx + 1 < len(logs):
        logs[idx + 1].status = "active"
        logs[idx + 1].started_at = now
        batch.current_stage_id = logs[idx + 1].stage_id
    else:
        batch.current_stage_id = None


def complete(db: Session, batch: ProductionBatch, user, actual_qty, rejected_qty=0, wastage_qty=0, actual_consumption=None, notes=""):
    if batch.status != "in_progress":
        bad("Only batches in progress can be completed.", 409)
    actual_qty, rejected_qty, wastage_qty = dec(actual_qty), dec(rejected_qty), dec(wastage_qty)
    if actual_qty < 0 or rejected_qty < 0 or wastage_qty < 0:
        bad("Quantities cannot be negative.")
    if rejected_qty > actual_qty:
        bad("Rejected quantity cannot exceed produced quantity.")
    overrides = {int(k): dec(v) for k, v in (actual_consumption or {}).items()}
    total_cost = 0
    for c in batch.consumption:
        used = overrides.get(c.material_id, Decimal(c.expected_qty))
        if used < 0:
            bad("Consumption cannot be negative.")
        c.actual_qty = used
        c.cost_kobo = int(round(used * c.material.cost_kobo))
        total_cost += c.cost_kobo
        if used > 0:
            inventory.move(db, c.material_id, batch.branch_id, used, "production_out", user.id,
                           f"Batch {batch.batch_number}", "production", batch.batch_number)
    overhead = int(settings_service.get(db, "overhead_percent_of_ingredient_cost") or 0)
    total_cost += int(round(total_cost * overhead / 100))
    good = actual_qty - rejected_qty
    if good > 0:
        inventory.move(db, batch.product_id, batch.branch_id, good, "production_in", user.id,
                       f"Batch {batch.batch_number}", "production", batch.batch_number)
    now = datetime.now(timezone.utc)
    for l in batch.stage_logs:
        if l.status != "done":
            l.status = "done"
            l.completed_at = now
    batch.actual_qty, batch.rejected_qty, batch.wastage_qty = actual_qty, rejected_qty, wastage_qty
    batch.total_cost_kobo = total_cost
    batch.status = "completed"
    batch.completed_at = now
    batch.current_stage_id = None
    if notes:
        batch.notes = (batch.notes + "\n" + notes).strip()
    if batch.plan:
        if all(b.status in ("completed", "cancelled") for b in batch.plan.batches):
            batch.plan.status = "completed"
    notify.notify_permission(db, "production.view", f"Production completed: {batch.batch_number}",
                             f"{batch.product.name}: {num(good)} good units", "#/production", "production", batch.branch_id)
    if batch.order_id:
        o = db.get(Order, batch.order_id)
        if o and o.status == "in_production":
            from app.services import orders
            orders.change_status(db, o, "ready_for_dispatch" if o.order_type == "delivery" else "ready_for_collection", user,
                                 f"Batch {batch.batch_number} completed")
