import csv
import io
from datetime import date, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import literal_column, select, func, and_
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies.auth import require, scope_branch
from app.models import (Order, OrderItem, Expense, ExpenseCategory, FinancialTransaction, Branch, Product, InventoryBalance, ProductionBatch,
                        DeliveryAssignment, DeliveryRun, Driver, User, AuditLog, SupplierInvoice, Supplier, Customer, Payment, Task, Role)
from app.services import analytics, settings_service
from app.routers.finance import pnl
from app.utils import common
from app.utils.common import bad, num, naira
from app.utils.pdf import table_pdf

router = APIRouter(prefix="/api/reports", tags=["Reports"])
FINANCE_REPORTS = {"expenses", "payment_methods", "outstanding_payments", "supplier_balances", "cash_flow", "profit_loss", "branch_comparison"}
CATALOG = [
    ("sales_daily", "Daily sales"), ("sales_weekly", "Weekly sales"), ("sales_monthly", "Monthly sales"), ("sales_annual", "Annual sales"),
    ("expenses", "Expense report"), ("branch_revenue", "Branch revenue"), ("payment_methods", "Payment methods"),
    ("outstanding_payments", "Outstanding payments"), ("supplier_balances", "Supplier balances"), ("cash_flow", "Cash flow"),
    ("profit_loss", "Profit & loss"), ("production", "Production"), ("stock", "Stock levels"), ("deliveries", "Deliveries"),
    ("staff_activity", "Staff activity"), ("branch_comparison", "Branch comparison")]


class F:  # filter bundle
    def __init__(self, db, p, branch_id, start, end, product_id, customer_id, staff_id, department, txn_type):
        self.db, self.p, self.start, self.end = db, p, start, end
        self.demo = settings_service.is_demo_mode(db)
        self.ids = analytics.scope_ids(p, branch_id)
        self.branch_id, self.product_id, self.customer_id, self.staff_id, self.department, self.txn_type = branch_id, product_id, customer_id, staff_id, department, txn_type


def k(v):
    return naira(int(v or 0))


def _order_filters(f):
    c = [Order.is_demo == f.demo, Order.status != "cancelled", analytics._branch_cond(Order.branch_id, f.ids),
         analytics.ldate(Order.created_at) >= f.start, analytics.ldate(Order.created_at) <= f.end]
    if f.customer_id:
        c.append(Order.customer_id == f.customer_id)
    if f.product_id:
        c.append(Order.id.in_(select(OrderItem.order_id).where(OrderItem.product_id == f.product_id)))
    return c


def _sales_by(f, trunc):
    ld = analytics.ldate(Order.created_at)
    key = ld if trunc == "day" else func.date_trunc(trunc, func.timezone(common.TZ.key, Order.created_at))
    rows = f.db.execute(select(key, func.count(), func.sum(Order.total_kobo), func.sum(Order.paid_kobo)).where(*_order_filters(f)).group_by(literal_column("1")).order_by(literal_column("1"))).all()
    fmt = {"day": "%Y-%m-%d", "week": "Wk of %Y-%m-%d", "month": "%b %Y", "year": "%Y"}[trunc]
    cols = ["Period", "Orders", "Billed", "Paid", "Outstanding"]
    out = [[(r[0] if isinstance(r[0], date) else r[0].date()).strftime(fmt), r[1], k(r[2]), k(r[3]), k(r[2] - r[3])] for r in rows]
    tot = sum(int(r[2]) for r in rows)
    return cols, out, {"Total billed": k(tot), "Orders": sum(r[1] for r in rows)}


def build(name: str, f: F):
    db = f.db
    if name in ("sales_daily", "sales_weekly", "sales_monthly", "sales_annual"):
        return _sales_by(f, {"sales_daily": "day", "sales_weekly": "week", "sales_monthly": "month", "sales_annual": "year"}[name])
    if name == "expenses":
        q = select(Expense, ExpenseCategory.name).join(ExpenseCategory, ExpenseCategory.id == Expense.category_id).where(
            Expense.is_demo == f.demo, analytics._branch_cond(Expense.branch_id, f.ids), Expense.expense_date.between(f.start, f.end))
        rows = db.execute(q.order_by(Expense.expense_date.desc())).all()
        br = {b.id: b.name for b in db.query(Branch)}
        return (["Date", "Ref", "Category", "Description", "Branch", "Status", "Amount"],
                [[e.expense_date.isoformat(), e.reference, c, e.description, br.get(e.branch_id), e.status, k(e.amount_kobo)] for e, c in rows],
                {"Approved total": k(sum(e.amount_kobo for e, _ in rows if e.status == "approved"))})
    if name == "branch_revenue":
        rows = db.execute(select(Branch.name, func.count(), func.sum(Order.total_kobo), func.sum(Order.paid_kobo)).join(Order, Order.branch_id == Branch.id)
                          .where(*_order_filters(f)).group_by(Branch.name).order_by(func.sum(Order.total_kobo).desc())).all()
        return ["Branch", "Orders", "Billed", "Paid"], [[r[0], r[1], k(r[2]), k(r[3])] for r in rows], {}
    if name == "payment_methods":
        q = [Payment.is_demo == f.demo, analytics._branch_cond(Payment.branch_id, f.ids), analytics.ldate(Payment.created_at).between(f.start, f.end)]
        rows = db.execute(select(Payment.method, Payment.status, func.count(), func.sum(Payment.amount_kobo)).where(*q).group_by(Payment.method, Payment.status).order_by(Payment.method)).all()
        return ["Method", "Status", "Count", "Amount"], [[r[0].replace("_", " "), r[1].replace("_", " "), r[2], k(r[3])] for r in rows], {}
    if name == "outstanding_payments":
        rows = db.execute(select(Order).where(Order.is_demo == f.demo, Order.status != "cancelled", Order.total_kobo > Order.paid_kobo,
                                              analytics._branch_cond(Order.branch_id, f.ids)).order_by(Order.created_at)).scalars().all()
        return (["Order", "Date", "Customer", "Phone", "Total", "Paid", "Balance"],
                [[o.order_number, o.created_at.date().isoformat(), o.contact_name, o.contact_phone, k(o.total_kobo), k(o.paid_kobo), k(o.total_kobo - o.paid_kobo)] for o in rows],
                {"Total outstanding": k(sum(o.total_kobo - o.paid_kobo for o in rows))})
    if name == "supplier_balances":
        rows = db.execute(select(Supplier.name, func.coalesce(func.sum(SupplierInvoice.amount_kobo), 0), func.coalesce(func.sum(SupplierInvoice.paid_kobo), 0))
                          .join(SupplierInvoice, SupplierInvoice.supplier_id == Supplier.id, isouter=True).where(Supplier.is_demo == f.demo).group_by(Supplier.name)).all()
        return ["Supplier", "Invoiced", "Paid", "Balance"], [[r[0], k(r[1]), k(r[2]), k(r[1] - r[2])] for r in rows], {"Total payable": k(sum(r[1] - r[2] for r in rows))}
    if name == "cash_flow":
        q = [FinancialTransaction.is_demo == f.demo, analytics._branch_cond(FinancialTransaction.branch_id, f.ids), FinancialTransaction.txn_date.between(f.start, f.end)]
        if f.txn_type:
            q.append(FinancialTransaction.kind == f.txn_type)
        rows = db.execute(select(FinancialTransaction.txn_date, FinancialTransaction.direction, func.sum(FinancialTransaction.amount_kobo)).where(*q).group_by(literal_column("1"), literal_column("2")).order_by(literal_column("1"))).all()
        m = {}
        for d, dr, v in rows:
            m.setdefault(d, {"in": 0, "out": 0})[dr] = int(v)
        net = 0
        out = []
        for d in sorted(m):
            n = m[d]["in"] - m[d]["out"]
            net += n
            out.append([d.isoformat(), k(m[d]["in"]), k(m[d]["out"]), k(n), k(net)])
        return ["Date", "Cash in", "Cash out", "Net", "Running net"], out, {"Net cash flow": k(net)}
    if name == "profit_loss":
        r = pnl(db, f.p, f.branch_id, f.start, f.end)
        rows = [["Revenue (billed)", k(r["revenue_kobo"])], ["Cost of goods sold (recipe cost + overhead)", k(r["cost_of_goods_kobo"])], ["Gross profit (estimated)", k(r["gross_profit_kobo"])],
                ["Operating expenses", k(r["operating_expenses_kobo"])], ["Net profit (estimated)", k(r["net_profit_kobo"])], ["Cash received", k(r["cash_received_kobo"])],
                ["Outstanding receivables", k(r["outstanding_receivables_kobo"])], ["Supplier payables", k(r["supplier_payables_kobo"])]]
        return ["Line", "Amount"], rows, {"Basis": r["note"]}
    if name == "production":
        q = [ProductionBatch.is_demo == f.demo, analytics._branch_cond(ProductionBatch.branch_id, f.ids), analytics.ldate(ProductionBatch.created_at).between(f.start, f.end)]
        if f.product_id:
            q.append(ProductionBatch.product_id == f.product_id)
        rows = db.execute(select(ProductionBatch).where(*q).order_by(ProductionBatch.id.desc())).scalars().all()
        def eff(b): return f"{float(b.actual_qty) / float(b.planned_qty) * 100:.0f}%" if b.status == "completed" and b.planned_qty else "-"
        return (["Batch", "Product", "Status", "Planned", "Actual", "Rejected", "Wastage", "Efficiency", "Cost"],
                [[b.batch_number, b.product.name, b.status, num(b.planned_qty), num(b.actual_qty), num(b.rejected_qty), num(b.wastage_qty), eff(b), k(b.total_cost_kobo)] for b in rows],
                {"Batches": len(rows)})
    if name == "stock":
        q = (select(Product, Branch.name, InventoryBalance.quantity).join(InventoryBalance, InventoryBalance.product_id == Product.id).join(Branch, Branch.id == InventoryBalance.branch_id)
             .where(Product.is_demo == f.demo, analytics._branch_cond(InventoryBalance.branch_id, f.ids)))
        if f.product_id:
            q = q.where(Product.id == f.product_id)
        rows = db.execute(q.order_by(Product.name)).all()
        return (["SKU", "Item", "Type", "Branch", "Qty", "Reorder level", "Value", "Alert"],
                [[p_.sku, p_.name, p_.kind, b, num(qty), num(p_.reorder_level), k(Decimal(qty) * p_.cost_kobo), "LOW" if p_.reorder_level and qty <= p_.reorder_level else ""] for p_, b, qty in rows],
                {"Stock value": k(sum(Decimal(qty) * p_.cost_kobo for p_, _, qty in rows))})
    if name == "deliveries":
        q = (select(DeliveryAssignment, DeliveryRun, Order).join(DeliveryRun, DeliveryRun.id == DeliveryAssignment.run_id).join(Order, Order.id == DeliveryAssignment.order_id)
             .where(DeliveryRun.is_demo == f.demo, analytics._branch_cond(DeliveryRun.branch_id, f.ids), analytics.ldate(DeliveryRun.scheduled_departure).between(f.start, f.end)))
        rows = db.execute(q.order_by(DeliveryRun.scheduled_departure.desc())).all()
        return (["Run", "Driver", "Vehicle", "Order", "Customer", "Address", "Status", "Reason"],
                [[r.run_number, r.driver.user.full_name, r.vehicle.plate_number, o.order_number, o.contact_name, o.delivery_address, a.status, a.failure_reason] for a, r, o in rows],
                {"Delivered": sum(1 for a, _, _ in rows if a.status == "delivered"), "Failed": sum(1 for a, _, _ in rows if a.status == "failed")})
    if name == "staff_activity":
        q = select(AuditLog.user_label, AuditLog.action, func.count()).where(analytics.ldate(AuditLog.created_at).between(f.start, f.end))
        if f.staff_id:
            q = q.where(AuditLog.user_id == f.staff_id)
        if f.department:
            q = q.where(AuditLog.user_id.in_(select(User.id).where(User.department == f.department)))
        rows = db.execute(q.group_by(AuditLog.user_label, AuditLog.action).order_by(AuditLog.user_label, func.count().desc())).all()
        return ["Staff", "Action", "Count"], [[r[0], r[1].replace("_", " "), r[2]] for r in rows], {}
    if name == "branch_comparison":
        rows = []
        for b in db.query(Branch).filter(Branch.is_demo == f.demo, Branch.is_active == True).order_by(Branch.name):  # noqa
            if not f.p.can_branch(b.id):
                continue
            s = analytics.overview(db, f.p, b.id, f.start, f.end)["stats"]
            rows.append([b.name, s["total_orders"], k(s["total_revenue_kobo"]), k(s["total_expenses_kobo"]), k(s["estimated_gross_profit_kobo"]), k(s["stock_value_kobo"])])
        return ["Branch", "Orders", "Revenue", "Expenses", "Est. gross profit", "Stock value"], rows, {}
    raise HTTPException(404, "Unknown report.")


@router.get("")
def catalog(p=Depends(require("reports.view"))):
    return [{"key": key, "title": t, "finance": key in FINANCE_REPORTS} for key, t in CATALOG if key not in FINANCE_REPORTS or p.can("finance.view")]


@router.get("/{name}")
def report(name: str, format: str = "json", branch_id: int | None = None, date_from: date | None = None, date_to: date | None = None,
           product_id: int | None = None, customer_id: int | None = None, staff_id: int | None = None, department: str = "", txn_type: str = "",
           p=Depends(require("reports.view")), db: Session = Depends(get_db)):
    if name not in dict(CATALOG):
        raise HTTPException(404, "Unknown report.")
    if name in FINANCE_REPORTS and not p.can("finance.view"):
        raise HTTPException(403, "You do not have permission to view financial reports.")
    if format != "json" and not p.can("reports.export"):
        raise HTTPException(403, "You do not have permission to export reports.")
    scope_branch(p, branch_id)
    t = common.today()
    start, end = date_from or t.replace(day=1), date_to or t
    if end < start:
        bad("End date is before start date.")
    cols, rows, summary = build(name, F(db, p, branch_id, start, end, product_id, customer_id, staff_id, department, txn_type))
    title = dict(CATALOG)[name]
    sub = f"{start.isoformat()} to {end.isoformat()}"
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([title, sub])
        w.writerow(cols)
        w.writerows(rows)
        return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}-{start}-{end}.csv"'})
    if format == "pdf":
        pdf = table_pdf(title, sub + ("   |   " + "   ".join(f"{a}: {b}" for a, b in summary.items()) if summary and name != "profit_loss" else ""), cols, rows,
                        settings_service.get(db, "business_name"))
        return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})
    return {"key": name, "title": title, "range": sub, "columns": cols, "rows": rows, "summary": summary}
