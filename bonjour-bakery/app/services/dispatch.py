from datetime import datetime, timezone
from sqlalchemy import select, and_
from sqlalchemy.orm import Session
from app.models import (DeliveryRun, DeliveryAssignment, DeliveryConfirmation, Driver, Vehicle, Order, Customer, Payment)
from app.services import notify, orders as order_svc, payments as pay_svc, numbering
from app.utils.common import bad


def _overlap(db, model_col, value, dep, ret, exclude_id=None):
    q = select(DeliveryRun).where(model_col == value, DeliveryRun.status.in_(("planned", "in_progress")),
                                  DeliveryRun.scheduled_departure < ret, DeliveryRun.expected_return > dep)
    if exclude_id:
        q = q.where(DeliveryRun.id != exclude_id)
    return db.execute(q).scalars().first()


def create_run(db: Session, user, branch_id, driver_id, vehicle_id, departure, expected_return, order_ids, notes="") -> DeliveryRun:
    if expected_return <= departure:
        bad("Expected return must be after departure.")
    driver = db.get(Driver, driver_id)
    vehicle = db.get(Vehicle, vehicle_id)
    if not driver or not driver.is_active:
        bad("Driver not available.")
    if not vehicle or not vehicle.is_active:
        bad("Vehicle not available.")
    if vehicle.status == "maintenance":
        bad("Vehicle is under maintenance.")
    c = _overlap(db, DeliveryRun.driver_id, driver_id, departure, expected_return)
    if c:
        bad(f"Driver already has run {c.run_number} in that time window.", 409)
    c = _overlap(db, DeliveryRun.vehicle_id, vehicle_id, departure, expected_return)
    if c:
        bad(f"Vehicle already assigned to run {c.run_number} in that time window.", 409)
    orders = []
    units = 0
    for oid in dict.fromkeys(order_ids):
        o = db.execute(select(Order).where(Order.id == oid).with_for_update()).scalar_one_or_none()
        if not o:
            bad(f"Order {oid} not found.", 404)
        if o.branch_id != branch_id:
            bad(f"Order {o.order_number} belongs to a different branch.")
        if o.status != "ready_for_dispatch":
            bad(f"Order {o.order_number} is not ready for dispatch (status: {order_svc.LABELS[o.status]}).", 409)
        units += sum(i.quantity for i in o.items)
        orders.append(o)
    if not orders:
        bad("Select at least one order for the run.")
    if units > vehicle.capacity_units:
        bad(f"Load of {units} units exceeds vehicle capacity of {vehicle.capacity_units}.")
    run = DeliveryRun(run_number=numbering.number(db, "run", "RUN"), branch_id=branch_id, driver_id=driver_id,
                      vehicle_id=vehicle_id, scheduled_departure=departure, expected_return=expected_return,
                      notes=notes, created_by=user.id)
    run.assignments = [DeliveryAssignment(order_id=o.id, sequence=i + 1) for i, o in enumerate(orders)]
    db.add(run)
    db.flush()
    for o in orders:
        order_svc.change_status(db, o, "assigned_to_driver", user, f"Assigned to run {run.run_number}", force=True)
    notify.notify_user(db, driver.user_id, f"New delivery run {run.run_number}", f"{len(orders)} order(s), {units} units", "#/driver", "delivery")
    return run


def _finish_run_if_done(db: Session, run: DeliveryRun):
    if all(a.status in ("delivered", "failed", "removed") for a in run.assignments):
        run.status = "completed"
        run.actual_return = datetime.now(timezone.utc)
        run.driver.status = "available"
        if run.vehicle.status == "in_use":
            run.vehicle.status = "available"


def start_delivery(db: Session, a: DeliveryAssignment, user):
    run = a.run
    if a.status != "assigned":
        bad("Delivery has already been started.", 409)
    if run.status == "cancelled":
        bad("This run was cancelled.", 409)
    now = datetime.now(timezone.utc)
    a.status, a.started_at = "out_for_delivery", now
    if run.status == "planned":
        run.status, run.actual_departure = "in_progress", now
        run.driver.status = "on_delivery"
        run.vehicle.status = "in_use"
    o = db.get(Order, a.order_id)
    order_svc.change_status(db, o, "out_for_delivery", user, f"Driver {user.full_name} started delivery", force=True)


def complete_delivery(db: Session, a: DeliveryAssignment, user, received_by="", confirmed=True, notes="", lat=None, lng=None,
                      cash_collected_kobo: int = 0, photo_path=""):
    if a.status != "out_for_delivery":
        bad("Start the delivery before completing it.", 409)
    o = db.get(Order, a.order_id)
    a.status, a.completed_at, a.driver_notes = "delivered", datetime.now(timezone.utc), notes
    a.confirmation = DeliveryConfirmation(received_by_name=received_by, customer_confirmed=confirmed, notes=notes,
                                          latitude=lat, longitude=lng, photo_path=photo_path)
    if cash_collected_kobo and cash_collected_kobo > 0:
        remaining = o.total_kobo - o.paid_kobo
        if cash_collected_kobo > remaining:
            bad("Cash collected exceeds the amount still owed on this order.")
        # an existing pending COD payment is converted; finance verifies the cash after remittance
        pend = next((p for p in o.payments if p.method == "cash_on_delivery" and p.status == "pending"), None)
        if pend and pend.amount_kobo == cash_collected_kobo:
            pend.status = "awaiting_verification"
        else:
            pay_svc.create(db, o, "cash_on_delivery", cash_collected_kobo, user.id, "awaiting_verification", f"Collected by driver {user.full_name}")
        db.flush()
        db.refresh(o)
        pay_svc.recompute_order_payment(o)
    order_svc.change_status(db, o, "delivered", user, f"Delivered. Received by {received_by or 'customer'}", force=True)
    _finish_run_if_done(db, a.run)
    notify.notify_permission(db, "dispatch.view", f"Delivered: {o.order_number}", f"Run {a.run.run_number}", "#/dispatch", "delivery", o.branch_id)


def fail_delivery(db: Session, a: DeliveryAssignment, user, reason: str, notes=""):
    if a.status not in ("assigned", "out_for_delivery"):
        bad("Delivery cannot be failed in its current state.", 409)
    if not reason.strip():
        bad("A failure reason is required.")
    o = db.get(Order, a.order_id)
    a.status, a.failure_reason, a.completed_at, a.driver_notes = "failed", reason, datetime.now(timezone.utc), notes
    if o.status == "assigned_to_driver":
        o.status = "ready_for_dispatch"  # back to pool; history recorded below
        order_svc._record(db, o, "assigned_to_driver", "ready_for_dispatch", user, f"Delivery failed: {reason}")
    else:
        order_svc.change_status(db, o, "ready_for_dispatch", user, f"Delivery failed: {reason}", force=True)
    _finish_run_if_done(db, a.run)
    notify.notify_permission(db, "dispatch.manage", f"Failed delivery: {o.order_number}", reason, "#/dispatch", "delivery", o.branch_id)


def remove_assignment(db: Session, a: DeliveryAssignment, user):
    if a.status != "assigned":
        bad("Only not-yet-started assignments can be removed.", 409)
    o = db.get(Order, a.order_id)
    a.status = "removed"
    o.status = "ready_for_dispatch"
    order_svc._record(db, o, "assigned_to_driver", "ready_for_dispatch", user, "Removed from delivery run")
    _finish_run_if_done(db, a.run)
