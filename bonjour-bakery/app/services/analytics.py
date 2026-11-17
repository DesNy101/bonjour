from datetime import date, timedelta, datetime
from sqlalchemy import literal_column, select, func, cast, Date, and_, case, literal
from sqlalchemy.orm import Session
from app.models import (Order, OrderItem, Expense, ExpenseCategory, FinancialTransaction, Branch, Product, InventoryBalance,
                        User, Role, Driver, DeliveryAssignment, ProductionBatch, Payment, SupplierInvoice, Customer)
from app.utils import common
from app.utils.common import num
from app.services import settings_service

PENDING = ("pending", "confirmed", "awaiting_payment", "paid")
PROCESSING = ("queued_for_production", "in_production", "ready_for_collection", "ready_for_dispatch",
              "assigned_to_driver", "out_for_delivery")
DONE = ("delivered", "completed")


def ldate(col):
    return cast(func.timezone(common.TZ.key, col), Date)


def _branch_cond(col, branch_ids):
    if branch_ids is None:
        return literal(True)
    return col.in_(branch_ids or {-1})


def scope_ids(principal, requested):
    """Resolve branch filter -> None (all) or set of ids."""
    if requested:
        return {requested}
    return principal.branch_ids


def revenue_between(db, demo, ids, start: date, end: date):
    q = select(func.coalesce(func.sum(Order.total_kobo), 0)).where(
        Order.status != "cancelled", Order.is_demo == demo, _branch_cond(Order.branch_id, ids),
        ldate(Order.created_at) >= start, ldate(Order.created_at) <= end)
    return int(db.execute(q).scalar())


def overview(db: Session, principal, branch_id=None, start: date | None = None, end: date | None = None):
    demo = settings_service.is_demo_mode(db)
    ids = scope_ids(principal, branch_id)
    t = common.today()
    end = end or t
    start = start or (t - timedelta(days=29))
    ob = [Order.is_demo == demo, _branch_cond(Order.branch_id, ids)]
    in_range = [ldate(Order.created_at) >= start, ldate(Order.created_at) <= end]

    status_rows = dict(db.execute(select(Order.status, func.count()).where(*ob, *in_range).group_by(Order.status)).all())
    cnt = lambda group: sum(status_rows.get(s, 0) for s in group)  # noqa

    revenue = int(db.execute(select(func.coalesce(func.sum(Order.total_kobo), 0)).where(*ob, *in_range, Order.status != "cancelled")).scalar())
    cash = int(db.execute(select(func.coalesce(func.sum(FinancialTransaction.amount_kobo), 0)).where(
        FinancialTransaction.is_demo == demo, _branch_cond(FinancialTransaction.branch_id, ids), FinancialTransaction.kind == "revenue",
        FinancialTransaction.txn_date >= start, FinancialTransaction.txn_date <= end)).scalar())
    outstanding = int(db.execute(select(func.coalesce(func.sum(Order.total_kobo - Order.paid_kobo), 0)).where(
        *ob, Order.status != "cancelled")).scalar())
    expenses = int(db.execute(select(func.coalesce(func.sum(Expense.amount_kobo), 0)).where(
        Expense.is_demo == demo, _branch_cond(Expense.branch_id, ids), Expense.status == "approved",
        Expense.expense_date >= start, Expense.expense_date <= end)).scalar())
    cogs = int(db.execute(select(func.coalesce(func.sum(OrderItem.unit_cost_kobo * OrderItem.quantity), 0)).join(Order, Order.id == OrderItem.order_id).where(
        *ob, *in_range, Order.status != "cancelled")).scalar())
    stock_value = db.execute(select(func.coalesce(func.sum(InventoryBalance.quantity * Product.cost_kobo), 0)).join(
        Product, Product.id == InventoryBalance.product_id).where(Product.is_demo == demo, _branch_cond(InventoryBalance.branch_id, ids))).scalar()
    low = db.execute(select(func.count()).select_from(InventoryBalance).join(Product, Product.id == InventoryBalance.product_id).where(
        Product.is_demo == demo, Product.is_active == True, Product.reorder_level > 0,  # noqa
        InventoryBalance.quantity <= Product.reorder_level, _branch_cond(InventoryBalance.branch_id, ids))).scalar()
    week_start = t - timedelta(days=t.weekday())
    month_start = t.replace(day=1)
    staff_count = db.execute(select(func.count()).select_from(User).join(Role, Role.id == User.role_id).where(
        Role.is_staff == True, User.is_active == True, User.is_demo == demo,  # noqa
        _branch_cond(User.branch_id, ids) if ids is not None else literal(True))).scalar()
    drivers = db.execute(select(func.count()).select_from(Driver).where(Driver.is_active == True, Driver.is_demo == demo,  # noqa
                                                                     _branch_cond(Driver.branch_id, ids) if ids is not None else literal(True))).scalar()
    in_progress = db.execute(select(func.count()).select_from(DeliveryAssignment).join(Order, Order.id == DeliveryAssignment.order_id).where(
        DeliveryAssignment.status == "out_for_delivery", Order.is_demo == demo, _branch_cond(Order.branch_id, ids))).scalar()
    branches = db.execute(select(func.count()).select_from(Branch).where(Branch.is_active == True, Branch.is_demo == demo,  # noqa
                                                                       Branch.id.in_(ids or {-1}) if ids is not None else literal(True))).scalar()

    stats = {
        "total_revenue_kobo": revenue, "cash_received_kobo": cash, "revenue_today_kobo": revenue_between(db, demo, ids, t, t),
        "revenue_week_kobo": revenue_between(db, demo, ids, week_start, t),
        "revenue_month_kobo": revenue_between(db, demo, ids, month_start, t),
        "total_orders": sum(status_rows.values()), "pending_orders": cnt(PENDING), "processing_orders": cnt(PROCESSING),
        "completed_orders": cnt(DONE), "cancelled_orders": cnt(("cancelled",)),
        "outstanding_payments_kobo": outstanding, "total_expenses_kobo": expenses, "estimated_cogs_kobo": cogs,
        "estimated_gross_profit_kobo": revenue - cogs, "estimated_net_profit_kobo": revenue - cogs - _opex(db, demo, ids, start, end),
        "stock_value_kobo": int(stock_value or 0), "low_stock_count": low, "active_branches": branches,
        "total_staff": staff_count, "active_drivers": drivers, "deliveries_in_progress": in_progress,
    }
    return {"range": {"from": start.isoformat(), "to": end.isoformat()}, "stats": stats, "charts": charts(db, demo, ids, start, end),
            "recent_orders": _recent(db, demo, ids)}


def _opex(db, demo, ids, start, end):
    """Operating expenses exclude categories already captured through recipe/COGS costing (raw materials, packaging)."""
    return int(db.execute(select(func.coalesce(func.sum(Expense.amount_kobo), 0)).join(ExpenseCategory, ExpenseCategory.id == Expense.category_id).where(
        Expense.is_demo == demo, _branch_cond(Expense.branch_id, ids), Expense.status == "approved", ExpenseCategory.counts_in_cogs == False,  # noqa
        Expense.expense_date >= start, Expense.expense_date <= end)).scalar())


def _recent(db, demo, ids):
    rows = db.execute(select(Order).where(Order.is_demo == demo, _branch_cond(Order.branch_id, ids)).order_by(Order.id.desc()).limit(8)).scalars().all()
    return [{"id": o.id, "order_number": o.order_number, "contact_name": o.contact_name, "total_kobo": o.total_kobo,
             "status": o.status, "payment_status": o.payment_status, "created_at": o.created_at.isoformat()} for o in rows]


def charts(db, demo, ids, start, end):
    ob = [Order.is_demo == demo, _branch_cond(Order.branch_id, ids), Order.status != "cancelled"]
    d = ldate(Order.created_at)
    daily = db.execute(select(d, func.sum(Order.total_kobo), func.count()).where(*ob, d >= start, d <= end).group_by(d).order_by(d)).all()
    daily_map = {r[0]: (int(r[1]), r[2]) for r in daily}
    days, cur = [], start
    while cur <= end:
        v = daily_map.get(cur, (0, 0))
        days.append({"date": cur.isoformat(), "revenue_kobo": v[0], "orders": v[1]})
        cur += timedelta(days=1)

    t = common.today()
    w0 = t - timedelta(days=t.weekday()) - timedelta(weeks=7)
    wk = ldate(Order.created_at)
    wrows = db.execute(select(func.date_trunc("week", func.timezone(common.TZ.key, Order.created_at)), func.sum(Order.total_kobo)).where(
        *ob, wk >= w0).group_by(literal_column("1")).order_by(literal_column("1"))).all()
    wmap = {r[0].date(): int(r[1]) for r in wrows}
    weekly = [{"label": (w0 + timedelta(weeks=i)).strftime("%d %b"), "revenue_kobo": wmap.get(w0 + timedelta(weeks=i), 0)} for i in range(8)]

    m0 = (t.replace(day=1) - timedelta(days=330)).replace(day=1)
    mrows = db.execute(select(func.date_trunc("month", func.timezone(common.TZ.key, Order.created_at)), func.sum(Order.total_kobo)).where(
        *ob, ldate(Order.created_at) >= m0).group_by(literal_column("1")).order_by(literal_column("1"))).all()
    mmap = {r[0].date(): int(r[1]) for r in mrows}
    monthly, cur = [], m0
    while cur <= t:
        monthly.append({"label": cur.strftime("%b %y"), "revenue_kobo": mmap.get(cur, 0)})
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)

    by_branch = db.execute(select(Branch.name, func.coalesce(func.sum(Order.total_kobo), 0)).join(Order, Order.branch_id == Branch.id).where(
        *ob, d >= start, d <= end).group_by(Branch.name).order_by(func.sum(Order.total_kobo).desc())).all()
    best = db.execute(select(OrderItem.name, func.sum(OrderItem.quantity), func.sum(OrderItem.line_total_kobo)).join(Order, Order.id == OrderItem.order_id).where(
        *ob, d >= start, d <= end).group_by(OrderItem.name).order_by(func.sum(OrderItem.quantity).desc()).limit(8)).all()
    exp = db.execute(select(ExpenseCategory.name, func.sum(Expense.amount_kobo)).join(Expense, Expense.category_id == ExpenseCategory.id).where(
        Expense.is_demo == demo, _branch_cond(Expense.branch_id, ids), Expense.status == "approved", Expense.expense_date >= start,
        Expense.expense_date <= end).group_by(ExpenseCategory.name).order_by(func.sum(Expense.amount_kobo).desc())).all()
    cr = db.execute(select(d, func.count()).where(Order.is_demo == demo, _branch_cond(Order.branch_id, ids), d >= start, d <= end).group_by(d)).all()
    done = db.execute(select(d, func.count()).where(Order.is_demo == demo, _branch_cond(Order.branch_id, ids), Order.status.in_(DONE), d >= start, d <= end).group_by(d)).all()
    cm, dm = dict(cr), dict(done)
    fulfil = [{"date": x["date"], "created": cm.get(date.fromisoformat(x["date"]), 0), "fulfilled": dm.get(date.fromisoformat(x["date"]), 0)} for x in days]
    pd = ldate(ProductionBatch.created_at)
    prod = db.execute(select(Product.name, func.sum(ProductionBatch.planned_qty), func.sum(ProductionBatch.actual_qty)).join(
        Product, Product.id == ProductionBatch.product_id).where(ProductionBatch.is_demo == demo, _branch_cond(ProductionBatch.branch_id, ids),
                                                              ProductionBatch.status == "completed", pd >= start, pd <= end).group_by(Product.name)).all()
    return {"daily_sales": days, "weekly_revenue": weekly, "monthly_revenue": monthly,
            "revenue_by_branch": [{"name": r[0], "revenue_kobo": int(r[1])} for r in by_branch],
            "best_sellers": [{"name": r[0], "quantity": int(r[1]), "revenue_kobo": int(r[2])} for r in best],
            "expenses_by_category": [{"name": r[0], "amount_kobo": int(r[1])} for r in exp],
            "order_fulfilment": fulfil,
            "production_performance": [{"name": r[0], "planned": num(r[1]), "actual": num(r[2])} for r in prod]}
