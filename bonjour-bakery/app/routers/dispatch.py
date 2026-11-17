from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies.auth import require, scope_branch, branch_filter
from app.models import (Driver, Vehicle, VehicleIssue, DeliveryRun, DeliveryAssignment, DeliveryConfirmation, Order, User, Role, Branch)
from app.schemas.common import (DriverIn, VehicleIn, RunIn, DeliveryDoneIn, DeliveryFailIn, VehicleIssueIn)
from app.serializers import run_out, order_out, assign_out
from app.services import dispatch as svc, audit, settings_service, notify, orders as osvc
from app.utils import common
from app.utils.common import bad
from app.utils.uploads import save_image

router = APIRouter(prefix="/api", tags=["Dispatch & Drivers"])


def _driver(d: Driver):
    return {"id": d.id, "user_id": d.user_id, "name": d.user.full_name, "phone": d.phone or d.user.phone, "license_no": d.license_no,
            "branch_id": d.branch_id, "status": d.status, "is_active": d.is_active, "is_demo": d.is_demo}


def _vehicle(v: Vehicle):
    return {"id": v.id, "plate_number": v.plate_number, "vehicle_type": v.vehicle_type, "capacity_units": v.capacity_units,
            "branch_id": v.branch_id, "status": v.status, "notes": v.notes, "is_active": v.is_active, "is_demo": v.is_demo}


# ---------------- drivers ----------------
@router.get("/drivers")
def drivers(p=Depends(require("dispatch.view", "drivers.manage", any_of=True)), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    qs = db.query(Driver).filter(Driver.is_demo == demo)
    if p.branch_ids is not None:
        qs = qs.filter(or_(Driver.branch_id.in_(p.branch_ids or {-1}), Driver.branch_id.is_(None)))
    return [_driver(d) for d in qs.all()]


@router.post("/drivers", status_code=201)
def add_driver(body: DriverIn, p=Depends(require("drivers.manage")), db: Session = Depends(get_db)):
    u = db.get(User, body.user_id)
    if not u or u.role.key != "driver":
        bad("Select a staff member with the Driver role.")
    if db.query(Driver).filter(Driver.user_id == u.id).first():
        bad("This user already has a driver profile.", 409)
    d = Driver(**body.model_dump(), is_demo=u.is_demo)
    db.add(d)
    db.commit()
    db.refresh(d)
    return _driver(d)


@router.put("/drivers/{did}")
def edit_driver(did: int, body: DriverIn, p=Depends(require("drivers.manage")), db: Session = Depends(get_db)):
    d = db.get(Driver, did)
    if not d:
        raise HTTPException(404, "Driver not found.")
    if body.status not in ("available", "on_delivery", "off_duty"):
        bad("Invalid status.")
    d.license_no, d.phone, d.branch_id, d.status, d.is_active = body.license_no, body.phone, body.branch_id, body.status, body.is_active
    db.commit()
    return _driver(d)


# ---------------- vehicles ----------------
@router.get("/vehicles")
def vehicles(p=Depends(require("dispatch.view", "vehicles.manage", any_of=True)), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    qs = db.query(Vehicle).filter(Vehicle.is_demo == demo)
    if p.branch_ids is not None:
        qs = qs.filter(or_(Vehicle.branch_id.in_(p.branch_ids or {-1}), Vehicle.branch_id.is_(None)))
    issues = dict(db.execute(select(VehicleIssue.vehicle_id, func.count()).where(VehicleIssue.status == "open").group_by(VehicleIssue.vehicle_id)).all())
    return [_vehicle(v) | {"open_issues": issues.get(v.id, 0)} for v in qs.order_by(Vehicle.plate_number)]


@router.post("/vehicles", status_code=201)
def add_vehicle(body: VehicleIn, p=Depends(require("vehicles.manage")), db: Session = Depends(get_db)):
    if db.query(Vehicle).filter(func.lower(Vehicle.plate_number) == body.plate_number.lower()).first():
        bad("A vehicle with this plate number exists.", 409)
    v = Vehicle(**body.model_dump(), is_demo=settings_service.is_demo_mode(db))
    v.plate_number = v.plate_number.upper()
    db.add(v)
    db.commit()
    return _vehicle(v)


@router.put("/vehicles/{vid}")
def edit_vehicle(vid: int, body: VehicleIn, p=Depends(require("vehicles.manage")), db: Session = Depends(get_db)):
    v = db.get(Vehicle, vid)
    if not v:
        raise HTTPException(404, "Vehicle not found.")
    if body.status not in ("available", "in_use", "maintenance"):
        bad("Invalid status.")
    for k, val in body.model_dump().items():
        setattr(v, k, val.upper() if k == "plate_number" else val)
    db.commit()
    return _vehicle(v)


@router.get("/vehicle-issues")
def vehicle_issues(p=Depends(require("vehicles.manage", "dispatch.view", any_of=True)), db: Session = Depends(get_db)):
    names = {u.id: u.full_name for u in db.query(User).all()}
    plates = {v.id: v.plate_number for v in db.query(Vehicle).all()}
    return [{"id": i.id, "vehicle": plates.get(i.vehicle_id), "description": i.description, "status": i.status, "by": names.get(i.reported_by),
             "at": i.created_at.isoformat()} for i in db.query(VehicleIssue).order_by(VehicleIssue.id.desc()).limit(100)]


@router.post("/vehicle-issues/{iid}/resolve")
def resolve_issue(iid: int, p=Depends(require("vehicles.manage")), db: Session = Depends(get_db)):
    i = db.get(VehicleIssue, iid)
    if not i:
        raise HTTPException(404, "Issue not found.")
    i.status = "resolved"
    db.commit()
    return {"ok": True}


# ---------------- dispatch board ----------------
@router.get("/dispatch/board")
def board(branch_id: int | None = None, delivery_date: date | None = None, lga: str = "", p=Depends(require("dispatch.view")), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    qs = db.query(Order).filter(Order.is_demo == demo, Order.status == "ready_for_dispatch", Order.order_type == "delivery",
                                branch_filter(p, Order.branch_id, branch_id))
    if delivery_date:
        qs = qs.filter(Order.preferred_date == delivery_date)
    if lga:
        qs = qs.filter(Order.delivery_lga == lga)
    orders = qs.order_by(Order.preferred_date.nulls_last(), Order.delivery_lga, Order.id).all()
    awaiting = db.query(func.count()).select_from(Order).filter(Order.is_demo == demo, Order.status.in_(("paid", "confirmed", "in_production", "queued_for_production")),
                                                                   Order.order_type == "delivery", branch_filter(p, Order.branch_id, branch_id)).scalar()
    return {"unassigned": [order_out(o, internal=False) | {"customer_phone": o.contact_phone} for o in orders],
            "in_preparation_count": awaiting}


@router.get("/dispatch/availability")
def availability(departure: datetime, expected_return: datetime, branch_id: int | None = None, p=Depends(require("dispatch.view")), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    busy_d = {r for (r,) in db.execute(select(DeliveryRun.driver_id).where(DeliveryRun.status.in_(("planned", "in_progress")),
                                                                         DeliveryRun.scheduled_departure < expected_return, DeliveryRun.expected_return > departure))}
    busy_v = {r for (r,) in db.execute(select(DeliveryRun.vehicle_id).where(DeliveryRun.status.in_(("planned", "in_progress")),
                                                                          DeliveryRun.scheduled_departure < expected_return, DeliveryRun.expected_return > departure))}
    ds = [d for d in db.query(Driver).filter(Driver.is_active == True, Driver.is_demo == demo).all() if d.id not in busy_d and d.status != "off_duty"]  # noqa
    vs = [v for v in db.query(Vehicle).filter(Vehicle.is_active == True, Vehicle.is_demo == demo, Vehicle.status != "maintenance").all() if v.id not in busy_v]  # noqa
    return {"drivers": [_driver(d) for d in ds], "vehicles": [_vehicle(v) for v in vs]}


def _runs_with_orders(db, runs):
    ids = {a.order_id for r in runs for a in r.assignments}
    omap = {o.id: o for o in db.query(Order).filter(Order.id.in_(ids or {-1}))}
    return [run_out(r, omap) for r in runs]


@router.get("/dispatch/runs")
def list_runs(status: str = "", branch_id: int | None = None, day: date | None = None, p=Depends(require("dispatch.view")), db: Session = Depends(get_db)):
    demo = settings_service.is_demo_mode(db)
    qs = db.query(DeliveryRun).filter(DeliveryRun.is_demo == demo, branch_filter(p, DeliveryRun.branch_id, branch_id))
    if status:
        qs = qs.filter(DeliveryRun.status.in_(status.split(",")))
    if day:
        qs = qs.filter(DeliveryRun.scheduled_departure >= common.day_start(day), DeliveryRun.scheduled_departure < common.day_end(day))
    return _runs_with_orders(db, qs.order_by(DeliveryRun.scheduled_departure.desc()).limit(100).all())


@router.post("/dispatch/runs", status_code=201)
def create_run(body: RunIn, request: Request, p=Depends(require("dispatch.manage")), db: Session = Depends(get_db)):
    scope_branch(p, body.branch_id)
    run = svc.create_run(db, p.user, body.branch_id, body.driver_id, body.vehicle_id, body.scheduled_departure, body.expected_return,
                         body.order_ids, body.notes)
    run.is_demo = settings_service.is_demo_mode(db)
    audit.log(db, p.user, "delivery_run_created", "delivery_run", run.run_number, {"orders": body.order_ids}, request)
    db.commit()
    db.refresh(run)
    return _runs_with_orders(db, [run])[0]


def _run(db, p, rid):
    r = db.get(DeliveryRun, rid)
    if not r or not p.can_branch(r.branch_id):
        raise HTTPException(404, "Delivery run not found.")
    return r


@router.post("/dispatch/runs/{rid}/cancel")
def cancel_run(rid: int, request: Request, p=Depends(require("dispatch.manage")), db: Session = Depends(get_db)):
    r = _run(db, p, rid)
    if r.status != "planned":
        bad("Only runs that have not departed can be cancelled.", 409)
    for a in r.assignments:
        if a.status == "assigned":
            svc.remove_assignment(db, a, p.user)
    r.status = "cancelled"
    audit.log(db, p.user, "delivery_run_cancelled", "delivery_run", r.run_number, request=request)
    db.commit()
    return {"ok": True}


@router.post("/dispatch/runs/{rid}/reschedule")
def reschedule_run(rid: int, departure: datetime, expected_return: datetime, request: Request, p=Depends(require("dispatch.manage")), db: Session = Depends(get_db)):
    r = _run(db, p, rid)
    if r.status != "planned":
        bad("Only planned runs can be rescheduled.", 409)
    if expected_return <= departure:
        bad("Expected return must be after departure.")
    for col, val, label in ((DeliveryRun.driver_id, r.driver_id, "Driver"), (DeliveryRun.vehicle_id, r.vehicle_id, "Vehicle")):
        c = svc._overlap(db, col, val, departure, expected_return, exclude_id=r.id)
        if c:
            bad(f"{label} is already booked on run {c.run_number} in that window.", 409)
    r.scheduled_departure, r.expected_return = departure, expected_return
    notify.notify_user(db, r.driver.user_id, f"Run {r.run_number} rescheduled", departure.strftime("%d %b %H:%M"), "#/driver", "delivery")
    audit.log(db, p.user, "delivery_run_rescheduled", "delivery_run", r.run_number, request=request)
    db.commit()
    return _runs_with_orders(db, [r])[0]


@router.post("/dispatch/assignments/{aid}/remove")
def remove_assignment(aid: int, p=Depends(require("dispatch.manage")), db: Session = Depends(get_db)):
    a = db.get(DeliveryAssignment, aid)
    if not a or not p.can_branch(a.run.branch_id):
        raise HTTPException(404, "Assignment not found.")
    svc.remove_assignment(db, a, p.user)
    db.commit()
    return {"ok": True}


@router.get("/dispatch/failed")
def failed(p=Depends(require("dispatch.view")), db: Session = Depends(get_db)):
    rows = db.query(DeliveryAssignment).join(DeliveryRun).filter(DeliveryAssignment.status == "failed", branch_filter(p, DeliveryRun.branch_id)) \
        .order_by(DeliveryAssignment.id.desc()).limit(50).all()
    omap = {o.id: o for o in db.query(Order).filter(Order.id.in_({a.order_id for a in rows} or {-1}))}
    return [assign_out(a, omap.get(a.order_id)) | {"run": a.run.run_number, "order_status": omap[a.order_id].status} for a in rows]


# ---------------- driver app ----------------
def _my_driver(db, p) -> Driver:
    d = db.query(Driver).filter(Driver.user_id == p.id).first()
    if not d:
        raise HTTPException(404, "No driver profile is linked to your account. Ask your dispatch manager.")
    return d


def _my_assignment(db, p, aid) -> DeliveryAssignment:
    d = _my_driver(db, p)
    a = db.get(DeliveryAssignment, aid)
    if not a or a.run.driver_id != d.id:
        raise HTTPException(404, "Delivery not found.")  # drivers can never reach someone else's assignment
    return a


@router.get("/driver/me")
def driver_me(p=Depends(require("driver.app")), db: Session = Depends(get_db)):
    d = _my_driver(db, p)
    run = db.query(DeliveryRun).filter(DeliveryRun.driver_id == d.id, DeliveryRun.status.in_(("planned", "in_progress"))) \
        .order_by(DeliveryRun.scheduled_departure).first()
    return {"driver": _driver(d), "vehicle": _vehicle(run.vehicle) if run else None, "current_run": run.run_number if run else None}


@router.get("/driver/deliveries")
def my_deliveries(scope: str = "today", p=Depends(require("driver.app")), db: Session = Depends(get_db)):
    d = _my_driver(db, p)
    qs = db.query(DeliveryAssignment).join(DeliveryRun).filter(DeliveryRun.driver_id == d.id, DeliveryRun.status != "cancelled")
    if scope == "today":
        t = common.today()
        qs = qs.filter(or_(DeliveryRun.scheduled_departure.between(common.day_start(t), common.day_end(t)),
                           DeliveryRun.status.in_(("planned", "in_progress"))))
    rows = qs.order_by(DeliveryRun.scheduled_departure.desc(), DeliveryAssignment.sequence).limit(100).all()
    omap = {o.id: o for o in db.query(Order).filter(Order.id.in_({a.order_id for a in rows} or {-1}))}
    items = [assign_out(a, omap.get(a.order_id)) | {"run": a.run.run_number, "vehicle": a.run.vehicle.plate_number,
                                                     "departure": a.run.scheduled_departure.isoformat()} for a in rows if a.status != "removed"]
    cnt = lambda s: sum(1 for i in items if i["status"] in s)  # noqa
    return {"summary": {"pending": cnt(("assigned", "out_for_delivery")), "completed": cnt(("delivered",)), "failed": cnt(("failed",)), "total": len(items)},
            "items": items}


@router.post("/driver/deliveries/{aid}/start")
def d_start(aid: int, request: Request, p=Depends(require("driver.app")), db: Session = Depends(get_db)):
    a = _my_assignment(db, p, aid)
    svc.start_delivery(db, a, p.user)
    audit.log(db, p.user, "delivery_started", "order", a.order_id, request=request)
    db.commit()
    return {"status": a.status}


@router.post("/driver/deliveries/{aid}/complete")
def d_complete(aid: int, body: DeliveryDoneIn, request: Request, p=Depends(require("driver.app")), db: Session = Depends(get_db)):
    a = _my_assignment(db, p, aid)
    svc.complete_delivery(db, a, p.user, body.received_by_name, body.customer_confirmed, body.notes, body.latitude, body.longitude, body.cash_collected_kobo)
    audit.log(db, p.user, "delivery_completed", "order", a.order_id, {"cash": body.cash_collected_kobo}, request)
    db.commit()
    return {"status": a.status}


@router.post("/driver/deliveries/{aid}/photo")
async def d_photo(aid: int, file: UploadFile = File(...), p=Depends(require("driver.app")), db: Session = Depends(get_db)):
    a = _my_assignment(db, p, aid)
    if not a.confirmation:
        bad("Complete the delivery first, then attach a photo.", 409)
    a.confirmation.photo_path = await save_image(file, "deliveries")
    db.commit()
    return {"photo": a.confirmation.photo_path}


@router.post("/driver/deliveries/{aid}/fail")
def d_fail(aid: int, body: DeliveryFailIn, request: Request, p=Depends(require("driver.app")), db: Session = Depends(get_db)):
    a = _my_assignment(db, p, aid)
    svc.fail_delivery(db, a, p.user, body.reason, body.notes)
    audit.log(db, p.user, "delivery_failed", "order", a.order_id, {"reason": body.reason}, request)
    db.commit()
    return {"status": a.status}


@router.post("/driver/vehicle-issues", status_code=201)
def report_vehicle_issue(body: VehicleIssueIn, p=Depends(require("driver.app")), db: Session = Depends(get_db)):
    d = _my_driver(db, p)
    run = db.query(DeliveryRun).filter(DeliveryRun.driver_id == d.id, DeliveryRun.vehicle_id == body.vehicle_id,
                                       DeliveryRun.status.in_(("planned", "in_progress"))).first()
    if not run:
        bad("You can only report problems on the vehicle assigned to your current run.", 403)
    db.add(VehicleIssue(vehicle_id=body.vehicle_id, reported_by=p.id, description=body.description))
    notify.notify_permission(db, "vehicles.manage", f"Vehicle problem reported ({run.vehicle.plate_number})", body.description, "#/vehicles", "vehicle", run.branch_id)
    db.commit()
    return {"ok": True}
