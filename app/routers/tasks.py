from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies.auth import require, staff_principal, scope_branch
from app.models import Task, User, Role, AuditLog, Notification
from app.schemas.common import TaskIn, TaskUpdateIn
from app.serializers import task_out, user_out
from app.services import audit, notify
from app.utils.common import bad

router = APIRouter(prefix="/api", tags=["Staff Tasks & Workspace"])
STAFF_FLOW = {"assigned": {"accepted", "in_progress", "completed", "needs_review"}, "accepted": {"in_progress", "completed", "needs_review"},
              "in_progress": {"completed", "needs_review"}, "needs_review": {"in_progress", "accepted"}, "completed": set()}


def _names(db):
    return {u.id: u.full_name for u in db.query(User).all()}


@router.get("/tasks")
def list_tasks(mine: bool = True, status: str = "", assigned_to: int | None = None, p=Depends(staff_principal), db: Session = Depends(get_db)):
    qs = db.query(Task)
    if mine or not p.can("tasks.manage"):
        qs = qs.filter(Task.assigned_to == p.id)
    else:
        if p.branch_ids is not None:
            qs = qs.filter(or_(Task.branch_id.in_(p.branch_ids or {-1}), Task.branch_id.is_(None), Task.created_by == p.id))
        if assigned_to:
            qs = qs.filter(Task.assigned_to == assigned_to)
    if status:
        qs = qs.filter(Task.status.in_(status.split(",")))
    n = _names(db)
    return [task_out(t, n) for t in qs.order_by(Task.due_at.nulls_last(), Task.id.desc()).limit(200)]


@router.post("/tasks", status_code=201)
def create_task(body: TaskIn, request: Request, p=Depends(require("tasks.manage")), db: Session = Depends(get_db)):
    if not body.assigned_to and not body.department:
        bad("Assign the task to a person or a department.")
    if body.branch_id:
        scope_branch(p, body.branch_id)
    targets = []
    if body.assigned_to:
        u = db.get(User, body.assigned_to)
        if not u or not u.is_active or not u.role.is_staff:
            bad("Assignee must be an active staff member.")
        if u.branch_id and not p.can_branch(u.branch_id):
            bad("You cannot assign tasks to staff of another branch.", 403)
        targets = [u]
    else:
        qs = db.query(User).join(Role).filter(Role.is_staff == True, User.is_active == True, User.department == body.department)  # noqa
        if p.branch_ids is not None:
            qs = qs.filter(User.branch_id.in_(p.branch_ids or {-1}))
        targets = qs.all()
        if not targets:
            bad("No active staff found in that department.")
    for u in targets:
        t = Task(title=body.title, instructions=body.instructions, priority=body.priority, assigned_to=u.id, department=u.department,
                 branch_id=body.branch_id or u.branch_id, due_at=body.due_at, created_by=p.id)
        db.add(t)
        notify.notify_user(db, u.id, f"New task: {body.title}", body.instructions[:120], "#/workspace", "task")
    audit.log(db, p.user, "task_created", "task", "", {"title": body.title, "count": len(targets)}, request)
    db.commit()
    return {"created": len(targets)}


@router.patch("/tasks/{tid}")
def update_task(tid: int, body: TaskUpdateIn, p=Depends(staff_principal), db: Session = Depends(get_db)):
    t = db.get(Task, tid)
    if not t:
        raise HTTPException(404, "Task not found.")
    is_assignee = t.assigned_to == p.id
    is_manager = p.can("tasks.manage") and (t.created_by == p.id or p.branch_ids is None or p.can_branch(t.branch_id))
    if not (is_assignee or is_manager):
        raise HTTPException(404, "Task not found.")
    if body.status:
        if body.status not in ("assigned", "accepted", "in_progress", "completed", "needs_review"):
            bad("Invalid status.")
        if is_manager and not is_assignee and body.status in ("needs_review", "completed", "in_progress", "assigned"):
            # manager review: send back for rework, or sign off
            t.review_note = body.review_note or t.review_note
            if body.status == "needs_review" and not (body.review_note or "").strip():
                bad("Add a review note explaining what needs to change.")
            t.status = body.status
            if body.status == "completed":
                t.completed_at = t.completed_at or datetime.now(timezone.utc)
            if t.assigned_to:
                notify.notify_user(db, t.assigned_to, f"Task '{t.title}' {body.status.replace('_', ' ')}", body.review_note or "", "#/workspace", "task")
        else:
            if body.status not in STAFF_FLOW.get(t.status, set()):
                bad(f"Cannot move task from {t.status.replace('_', ' ')} to {body.status.replace('_', ' ')}.", 409)
            if body.status == "completed" and not (body.completion_notes or t.completion_notes):
                bad("Add completion notes before marking the task complete.")
            if body.status == "needs_review" and not (body.problem_report or "").strip():
                bad("Describe the problem or reason you cannot do this task.")
            t.status = body.status
            if body.status == "completed":
                t.completed_at = datetime.now(timezone.utc)
            if body.status in ("completed", "needs_review") and t.created_by:
                notify.notify_user(db, t.created_by, f"Task '{t.title}' {body.status.replace('_', ' ')} by {p.user.full_name}", "", "#/tasks", "task")
    if body.completion_notes is not None and is_assignee:
        t.completion_notes = body.completion_notes
    if body.problem_report is not None and is_assignee:
        t.problem_report = body.problem_report
        if body.problem_report and t.created_by:
            notify.notify_user(db, t.created_by, f"Problem reported on '{t.title}'", body.problem_report[:120], "#/tasks", "task")
    db.commit()
    return task_out(t, _names(db))


@router.get("/workspace")
def workspace(p=Depends(staff_principal), db: Session = Depends(get_db)):
    tasks = db.query(Task).filter(Task.assigned_to == p.id).all()
    acts = db.query(AuditLog).filter(AuditLog.user_id == p.id).order_by(AuditLog.id.desc()).limit(15).all()
    return {"profile": user_out(p.user), "task_counts": {s: sum(1 for t in tasks if t.status == s) for s in ("assigned", "accepted", "in_progress", "completed", "needs_review")},
            "overdue": sum(1 for t in tasks if t.due_at and t.status != "completed" and t.due_at < datetime.now(timezone.utc)),
            "unread_notifications": db.query(Notification).filter(Notification.user_id == p.id, Notification.is_read == False).count(),  # noqa
            "activity": [{"action": a.action, "entity": a.entity, "entity_id": a.entity_id, "at": a.created_at.isoformat()} for a in acts]}
