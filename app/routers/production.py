from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies.auth import require, scope_branch, branch_filter
from app.models import (Recipe, RecipeIngredient, Product, ProductionStage, ProductionPlan, ProductionBatch, BatchStageLog, User)
from app.schemas.common import RecipeIn, StageIn, PlanIn, StageAdvanceIn, StageAssignIn, BatchCompleteIn
from app.serializers import batch_out
from app.services import audit, numbering, production as svc, settings_service, notify
from app.utils import common
from app.utils.common import bad, num

router = APIRouter(prefix="/api/production", tags=["Production"])


def _recipe_out(r: Recipe):
    return {"id": r.id, "product_id": r.product_id, "product": r.product.name, "name": r.name, "yield_qty": num(r.yield_qty),
            "instructions": r.instructions, "is_active": r.is_active, "unit_cost_kobo": svc.recipe_unit_cost(r),
            "batch_cost_kobo": int(sum(Decimal(i.quantity) * i.material.cost_kobo for i in r.ingredients)),
            "ingredients": [{"material_id": i.material_id, "name": i.material.name, "unit": i.material.unit, "quantity": num(i.quantity),
                             "cost_kobo": int(Decimal(i.quantity) * i.material.cost_kobo)} for i in r.ingredients]}


# ---------------- recipes ----------------
@router.get("/recipes")
def recipes(p=Depends(require("production.view", "recipes.manage", any_of=True)), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    rows = db.query(Recipe).join(Product, Product.id == Recipe.product_id).filter(Product.is_demo == demo).order_by(Recipe.name).all()
    return [_recipe_out(r) for r in rows]


def _save_recipe(db, r: Recipe, body: RecipeIn):
    prod = db.get(Product, body.product_id)
    if not prod or prod.kind != "finished":
        bad("A recipe must be for a finished product.")
    if not body.ingredients:
        bad("Add at least one ingredient.")
    seen = set()
    r.product_id, r.name, r.yield_qty, r.instructions = body.product_id, body.name, body.yield_qty, body.instructions
    r.ingredients.clear()
    for ing in body.ingredients:
        m = db.get(Product, ing.material_id)
        if not m or m.kind == "finished":
            bad("Ingredients must be raw materials or packaging.")
        if ing.material_id in seen:
            bad(f"{m.name} is listed twice.")
        seen.add(ing.material_id)
        r.ingredients.append(RecipeIngredient(material_id=ing.material_id, quantity=ing.quantity))
    db.flush()
    db.refresh(r)
    # keep the finished product's standard cost in step with its recipe (+ configured overhead)
    overhead = float(settings_service.get(db, "overhead_percent_of_ingredient_cost") or 0)
    prod.cost_kobo = int(round(svc.recipe_unit_cost(r) * (1 + overhead / 100)))


@router.post("/recipes", status_code=201)
def create_recipe(body: RecipeIn, request: Request, p=Depends(require("recipes.manage")), db: Session = Depends(get_db)):
    r = Recipe()
    db.add(r)
    _save_recipe(db, r, body)
    audit.log(db, p.user, "recipe_created", "recipe", r.id, request=request)
    db.commit()
    return _recipe_out(r)


@router.put("/recipes/{rid}")
def update_recipe(rid: int, body: RecipeIn, request: Request, p=Depends(require("recipes.manage")), db: Session = Depends(get_db)):
    r = db.get(Recipe, rid)
    if not r:
        raise HTTPException(404, "Recipe not found.")
    _save_recipe(db, r, body)
    audit.log(db, p.user, "recipe_updated", "recipe", r.id, request=request)
    db.commit()
    return _recipe_out(r)


# ---------------- stages ----------------
@router.get("/stages")
def stages(p=Depends(require("production.view", "recipes.manage", any_of=True)), db: Session = Depends(get_db)):
    return [{"id": s.id, "name": s.name, "sequence": s.sequence, "department": s.department, "is_active": s.is_active}
            for s in db.query(ProductionStage).order_by(ProductionStage.sequence)]


@router.post("/stages", status_code=201)
def add_stage(body: StageIn, p=Depends(require("recipes.manage")), db: Session = Depends(get_db)):
    if db.query(ProductionStage).filter(func.lower(ProductionStage.name) == body.name.lower()).first():
        bad("Stage already exists.", 409)
    s = ProductionStage(**body.model_dump())
    db.add(s)
    db.commit()
    return {"id": s.id}


@router.put("/stages/{sid}")
def edit_stage(sid: int, body: StageIn, p=Depends(require("recipes.manage")), db: Session = Depends(get_db)):
    s = db.get(ProductionStage, sid)
    if not s:
        raise HTTPException(404, "Stage not found.")
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    db.commit()
    return {"id": s.id}


# ---------------- plans & batches ----------------
@router.post("/plans", status_code=201)
def create_plan(body: PlanIn, request: Request, p=Depends(require("production.manage")), db: Session = Depends(get_db)):
    scope_branch(p, body.branch_id)
    if not body.batches:
        bad("Add at least one product to the plan.")
    if body.start_time and body.expected_end and body.expected_end <= body.start_time:
        bad("Expected completion must be after the start time.")
    if body.supervisor_id:
        sup = db.get(User, body.supervisor_id)
        if not sup or not sup.role.is_staff:
            bad("Supervisor must be a staff member.")
    plan = ProductionPlan(number=numbering.number(db, "plan", "PLN"), branch_id=body.branch_id, plan_date=body.plan_date,
                          start_time=body.start_time, expected_end=body.expected_end, supervisor_id=body.supervisor_id,
                          notes=body.notes, created_by=p.id, is_demo=settings_service.is_demo_mode(db))
    db.add(plan)
    db.flush()
    created = []
    for ln in body.batches:
        prod = db.get(Product, ln.product_id)
        if not prod or prod.kind != "finished":
            bad("Production is only for finished products.")
        recipe = db.query(Recipe).filter(Recipe.product_id == prod.id, Recipe.is_active == True).first()  # noqa
        b = ProductionBatch(batch_number=numbering.number(db, "batch", "BAT"), plan_id=plan.id, branch_id=body.branch_id,
                            product_id=prod.id, recipe_id=recipe.id if recipe else None, planned_qty=ln.planned_qty,
                            order_id=ln.order_id, supervisor_id=body.supervisor_id, scheduled_start=body.start_time,
                            expected_end=body.expected_end, created_by=p.id, is_demo=plan.is_demo)
        db.add(b)
        db.flush()
        svc.init_batch(db, b)
        created.append(b.batch_number)
    notify.notify_permission(db, "production.view", f"Production scheduled: {plan.number}", ", ".join(created), "#/production", "production", body.branch_id, p.id)
    if body.supervisor_id:
        notify.notify_user(db, body.supervisor_id, f"You supervise plan {plan.number}", f"{len(created)} batch(es) on {body.plan_date}", "#/production", "production")
    audit.log(db, p.user, "production_planned", "plan", plan.number, {"batches": created}, request)
    db.commit()
    return {"plan": plan.number, "batches": created}


@router.get("/batches")
def list_batches(status: str = "", branch_id: int | None = None, date_from: date | None = None, date_to: date | None = None,
                 page: int = 1, size: int = 50, p=Depends(require("production.view")), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    qs = db.query(ProductionBatch).filter(ProductionBatch.is_demo == demo, branch_filter(p, ProductionBatch.branch_id, branch_id))
    if status:
        qs = qs.filter(ProductionBatch.status == status)
    if date_from:
        qs = qs.filter(ProductionBatch.created_at >= common.day_start(date_from))
    if date_to:
        qs = qs.filter(ProductionBatch.created_at < common.day_end(date_to))
    total = qs.count()
    rows = qs.order_by(ProductionBatch.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "items": [batch_out(b) for b in rows]}


def _batch(db, p, bid):
    b = db.get(ProductionBatch, bid)
    if not b or not p.can_branch(b.branch_id):
        raise HTTPException(404, "Batch not found.")
    return b


@router.get("/batches/{bid}")
def get_batch(bid: int, p=Depends(require("production.view")), db: Session = Depends(get_db)):
    return batch_out(_batch(db, p, bid))


@router.post("/batches/{bid}/start")
def start_batch(bid: int, request: Request, p=Depends(require("production.manage")), db: Session = Depends(get_db)):
    b = _batch(db, p, bid)
    svc.start(db, b, p.user)
    audit.log(db, p.user, "batch_started", "batch", b.batch_number, request=request)
    db.commit()
    return batch_out(b)


@router.post("/batches/{bid}/advance")
def advance(bid: int, body: StageAdvanceIn, p=Depends(require("production.manage")), db: Session = Depends(get_db)):
    b = _batch(db, p, bid)
    svc.advance_stage(db, b, p.user, body.notes)
    db.commit()
    return batch_out(b)


@router.post("/batches/{bid}/assign-stage")
def assign_stage(bid: int, body: StageAssignIn, p=Depends(require("production.manage")), db: Session = Depends(get_db)):
    b = _batch(db, p, bid)
    log = next((l for l in b.stage_logs if l.id == body.stage_log_id), None)
    if not log:
        bad("Stage not found on this batch.", 404)
    if body.user_id:
        u = db.get(User, body.user_id)
        if not u or not u.role.is_staff:
            bad("Assignee must be a staff member.")
        notify.notify_user(db, u.id, f"Production stage assigned: {log.stage.name}", f"Batch {b.batch_number}", "#/workspace", "task")
    log.assigned_to = body.user_id
    db.commit()
    return batch_out(b)


@router.post("/batches/{bid}/complete")
def complete(bid: int, body: BatchCompleteIn, request: Request, p=Depends(require("production.manage")), db: Session = Depends(get_db)):
    b = _batch(db, p, bid)
    svc.complete(db, b, p.user, body.actual_qty, body.rejected_qty, body.wastage_qty, body.actual_consumption, body.notes)
    audit.log(db, p.user, "batch_completed", "batch", b.batch_number, {"actual": body.actual_qty, "rejected": body.rejected_qty}, request)
    db.commit()
    return batch_out(b)


@router.post("/batches/{bid}/cancel")
def cancel_batch(bid: int, p=Depends(require("production.manage")), db: Session = Depends(get_db)):
    b = _batch(db, p, bid)
    if b.status not in ("planned",):
        bad("Only planned batches can be cancelled.", 409)
    b.status = "cancelled"
    db.commit()
    return batch_out(b)


@router.get("/summary")
def summary(branch_id: int | None = None, date_from: date | None = None, date_to: date | None = None,
            p=Depends(require("production.view")), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    qs = [ProductionBatch.is_demo == demo, ProductionBatch.status == "completed", branch_filter(p, ProductionBatch.branch_id, branch_id)]
    if date_from:
        qs.append(ProductionBatch.completed_at >= common.day_start(date_from))
    if date_to:
        qs.append(ProductionBatch.completed_at < common.day_end(date_to))
    r = db.execute(select(func.coalesce(func.sum(ProductionBatch.planned_qty), 0), func.coalesce(func.sum(ProductionBatch.actual_qty), 0),
                          func.coalesce(func.sum(ProductionBatch.rejected_qty), 0), func.coalesce(func.sum(ProductionBatch.wastage_qty), 0),
                          func.coalesce(func.sum(ProductionBatch.total_cost_kobo), 0), func.count()).where(*qs)).one()
    planned, actual = Decimal(r[0]), Decimal(r[1])
    return {"planned": num(planned), "actual": num(actual), "rejected": num(r[2]), "wastage": num(r[3]), "total_cost_kobo": int(r[4]),
            "batches": r[5], "efficiency_percent": round(float(actual / planned * 100), 1) if planned else 0,
            "cost_per_unit_kobo": int(r[4] / actual) if actual else 0}
