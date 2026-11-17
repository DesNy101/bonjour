from app.utils.common import num


def iso(d):
    return d.isoformat() if d else None


def user_out(u, perms=None):
    d = {"id": u.id, "email": u.email, "full_name": u.full_name, "phone": u.phone, "role": u.role.key,
         "role_name": u.role.name, "is_staff": u.role.is_staff, "branch_id": u.branch_id,
         "branch_name": u.branch.name if u.branch else None, "employee_id": u.employee_id, "department": u.department,
         "job_title": u.job_title, "is_active": u.is_active, "must_change_password": u.must_change_password,
         "last_login": iso(u.last_login), "work_schedule": u.work_schedule, "is_demo": u.is_demo,
         "created_at": iso(u.created_at)}
    if perms is not None:
        d["permissions"] = sorted(perms)
    return d


def branch_out(b, manager=None):
    return {"id": b.id, "code": b.code, "name": b.name, "address": b.address, "state": b.state, "lga": b.lga,
            "phone": b.phone, "manager_id": b.manager_id, "manager_name": manager.full_name if manager else None,
            "is_active": b.is_active, "opened_on": iso(b.opened_on), "accepts_online_orders": b.accepts_online_orders,
            "is_demo": b.is_demo}


def product_out(p, qty=None):
    d = {"id": p.id, "sku": p.sku, "name": p.name, "kind": p.kind, "category_id": p.category_id,
         "category": p.category.name if p.category else None, "size_label": p.size_label, "unit": p.unit,
         "description": p.description, "image_url": p.image_url, "price_kobo": p.price_kobo,
         "wholesale_price_kobo": p.wholesale_price_kobo, "cost_kobo": p.cost_kobo, "reorder_level": num(p.reorder_level),
         "is_active": p.is_active, "is_sellable": p.is_sellable, "is_demo": p.is_demo}
    if qty is not None:
        d["quantity"] = num(qty)
        d["low_stock"] = bool(p.reorder_level) and qty <= p.reorder_level
    return d


def customer_out(c, full=True):
    d = {"id": c.id, "name": c.name, "phone": c.phone, "email": c.email, "customer_type": c.customer_type,
         "preferred_branch_id": c.preferred_branch_id, "is_guest": c.is_guest, "notes": c.notes, "is_demo": c.is_demo,
         "created_at": iso(c.created_at)}
    if full:
        d["addresses"] = [{"id": a.id, "label": a.label, "address": a.address, "lga": a.lga, "is_default": a.is_default}
                          for a in c.addresses]
    return d


def payment_out(p):
    return {"id": p.id, "reference": p.reference, "order_id": p.order_id, "amount_kobo": p.amount_kobo, "method": p.method,
            "status": p.status, "proof_reference": p.proof_reference, "branch_id": p.branch_id,
            "verified_by": p.verified_by, "verified_at": iso(p.verified_at), "created_at": iso(p.created_at)}


def order_out(o, internal=True):
    d = {"id": o.id, "order_number": o.order_number, "status": o.status, "payment_status": o.payment_status,
         "order_type": o.order_type, "channel": o.channel, "branch_id": o.branch_id, "contact_name": o.contact_name,
         "contact_phone": o.contact_phone, "delivery_address": o.delivery_address, "delivery_lga": o.delivery_lga,
         "preferred_date": iso(o.preferred_date), "preferred_time": o.preferred_time, "subtotal_kobo": o.subtotal_kobo,
         "delivery_fee_kobo": o.delivery_fee_kobo, "tax_kobo": o.tax_kobo, "total_kobo": o.total_kobo,
         "paid_kobo": o.paid_kobo, "balance_kobo": o.total_kobo - o.paid_kobo, "created_at": iso(o.created_at),
         "items": [{"product_id": i.product_id, "name": i.name, "quantity": i.quantity,
                    "unit_price_kobo": i.unit_price_kobo, "line_total_kobo": i.line_total_kobo} for i in o.items],
         "units": sum(i.quantity for i in o.items)}
    if internal:
        d.update({"customer_id": o.customer_id, "contact_email": o.contact_email, "notes": o.notes,
                  "delivery_instructions": o.delivery_instructions, "cancel_reason": o.cancel_reason,
                  "stock_deducted": o.stock_deducted, "is_demo": o.is_demo, "tracking_token": o.tracking_token,
                  "payments": [payment_out(p) for p in o.payments],
                  "history": [{"from": h.from_status, "to": h.to_status, "by": h.user_label, "note": h.note,
                               "at": iso(h.created_at)} for h in o.history]})
    return d


def customer_view_order(o):
    """What a customer may see: progress and payment status only - no internal notes, staff, stock info."""
    d = order_out(o, internal=False)
    d["notes"] = o.notes
    d["payments"] = [{"reference": p.reference, "method": p.method, "status": p.status, "amount_kobo": p.amount_kobo}
                     for p in o.payments]
    d["progress"] = [{"status": h.to_status, "at": iso(h.created_at)} for h in o.history]
    return d


def batch_out(b):
    return {"id": b.id, "batch_number": b.batch_number, "plan_id": b.plan_id, "branch_id": b.branch_id,
            "product_id": b.product_id, "product_name": b.product.name, "order_id": b.order_id,
            "planned_qty": num(b.planned_qty), "actual_qty": num(b.actual_qty), "rejected_qty": num(b.rejected_qty),
            "wastage_qty": num(b.wastage_qty), "status": b.status, "current_stage_id": b.current_stage_id,
            "supervisor_id": b.supervisor_id, "scheduled_start": iso(b.scheduled_start), "expected_end": iso(b.expected_end),
            "started_at": iso(b.started_at), "completed_at": iso(b.completed_at), "total_cost_kobo": b.total_cost_kobo,
            "efficiency": round(float(b.actual_qty) / float(b.planned_qty) * 100, 1) if b.status == "completed" and b.planned_qty else None,
            "stages": [{"id": l.id, "stage": l.stage.name, "department": l.stage.department, "status": l.status,
                        "assigned_to": l.assigned_to, "started_at": iso(l.started_at), "completed_at": iso(l.completed_at)}
                       for l in b.stage_logs],
            "consumption": [{"material_id": c.material_id, "name": c.material.name, "unit": c.material.unit,
                             "expected_qty": num(c.expected_qty), "actual_qty": num(c.actual_qty) if c.actual_qty is not None else None,
                             "cost_kobo": c.cost_kobo} for c in b.consumption]}


def run_out(r, orders=None):
    orders = orders or {}
    return {"id": r.id, "run_number": r.run_number, "branch_id": r.branch_id, "status": r.status,
            "driver_id": r.driver_id, "driver_name": r.driver.user.full_name, "vehicle_id": r.vehicle_id,
            "vehicle": r.vehicle.plate_number, "scheduled_departure": iso(r.scheduled_departure),
            "expected_return": iso(r.expected_return), "actual_departure": iso(r.actual_departure),
            "actual_return": iso(r.actual_return), "notes": r.notes,
            "assignments": [assign_out(a, orders.get(a.order_id)) for a in r.assignments]}


def assign_out(a, o=None):
    d = {"id": a.id, "order_id": a.order_id, "sequence": a.sequence, "status": a.status,
         "failure_reason": a.failure_reason, "driver_notes": a.driver_notes, "started_at": iso(a.started_at),
         "completed_at": iso(a.completed_at)}
    if a.confirmation:
        d["confirmation"] = {"received_by": a.confirmation.received_by_name, "confirmed": a.confirmation.customer_confirmed,
                             "lat": a.confirmation.latitude, "lng": a.confirmation.longitude, "at": iso(a.confirmation.created_at)}
    if o is not None:
        d.update({"order_number": o.order_number, "customer_name": o.contact_name, "customer_phone": o.contact_phone,
                  "address": o.delivery_address, "lga": o.delivery_lga, "instructions": o.delivery_instructions,
                  "units": sum(i.quantity for i in o.items), "items": [{"name": i.name, "quantity": i.quantity} for i in o.items],
                  "total_kobo": o.total_kobo, "balance_kobo": o.total_kobo - o.paid_kobo,
                  "payment_method": next((p.method for p in o.payments), ""), "preferred_time": o.preferred_time})
    return d


def expense_out(e):
    return {"id": e.id, "reference": e.reference, "category_id": e.category_id, "category": e.category.name,
            "description": e.description, "amount_kobo": e.amount_kobo, "branch_id": e.branch_id,
            "expense_date": iso(e.expense_date), "supporting_ref": e.supporting_ref, "status": e.status,
            "recorded_by": e.recorded_by, "decided_by": e.decided_by, "is_demo": e.is_demo}


def task_out(t, names=None):
    names = names or {}
    return {"id": t.id, "title": t.title, "instructions": t.instructions, "priority": t.priority, "status": t.status,
            "assigned_to": t.assigned_to, "assignee": names.get(t.assigned_to), "department": t.department,
            "branch_id": t.branch_id, "due_at": iso(t.due_at), "created_by": t.created_by, "creator": names.get(t.created_by),
            "completion_notes": t.completion_notes, "problem_report": t.problem_report, "review_note": t.review_note,
            "completed_at": iso(t.completed_at), "created_at": iso(t.created_at)}
