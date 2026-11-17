// Console pages (1/2): overview, branches, orders, customers, payments, products, inventory.
import { api, h, raw, esc, mount, $, $$, icon, state, can, loading, errorBox, badge, naira, nairaShort, num, fdate, fdt, title, toast, busy, modal, openForm, confirmDialog, table, pager, opts, download, openPdf, debounce, todayISO, daysAgoISO, fieldsHTML, readFields } from "./core.js";
import { lineChart, barChart, hbarChart, donutChart } from "./charts.js";

export const branchList = async () => { state.staffBranches = await api("/branches"); return state.staffBranches; };
export const branchOpts = (all) => opts(state.staffBranches || [], { all });

// Generic filtered, paginated list page
export function listPage(el, { head, desc, toolbar = "", filters = [], load, cols, onRow, size = 25, empty }) {
  let page = 1;
  mount(el, h`<div class="page-head"><div><h1>${head}</h1>${desc ? h`<p>${desc}</p>` : ""}</div><div class="row">${raw(toolbar)}</div></div>
    ${filters.length ? h`<div class="filters" id="flt">${filters.map((f) => h`<label class="f">${f.label}${f.type === "select" ? h`<select name="${f.name}">${f.options.map((o) => h`<option value="${o.value}" ${String(o.value) === String(f.value ?? "") ? raw("selected") : ""}>${o.label}</option>`)}</select>` : h`<input name="${f.name}" type="${f.type || "text"}" value="${f.value ?? ""}" ${f.placeholder ? raw(`placeholder="${esc(f.placeholder)}"`) : ""}>`}</label>`)}</div>` : ""}
    <div class="card flush"><div id="res">${loading()}</div></div>`);
  const res = $("#res", el); let last = [];
  const params = () => { const p = {}; $$("#flt [name]", el).forEach((i) => (p[i.name] = i.value)); return p; };
  const refresh = async (resetPage) => {
    if (resetPage) page = 1;
    try { const r = await load(params(), page, size); last = r.items; mount(res, h`${table(cols, r.items, { empty: empty || "No records found.", rowAttr: onRow ? (row, i) => `class="clickable" data-i="${i}"` : null })}${r.total > size ? pager(r.total, page, size) : ""}`); extra && extra(r); } catch (e) { mount(res, errorBox(e)); }
  };
  let extra = null;
  const d = debounce(() => refresh(true), 350);
  $$("#flt [name]", el).forEach((i) => { i.addEventListener(i.tagName === "SELECT" || i.type === "date" ? "change" : "input", d); });
  res.addEventListener("click", (e) => { const pg = e.target.closest("[data-page]"); if (pg) { page = Number(pg.dataset.page); refresh(); return; } const tr = e.target.closest("tr[data-i]"); if (tr && onRow && !e.target.closest("a,button")) onRow(last[tr.dataset.i], refresh); });
  refresh();
  return { refresh, setExtra: (f) => (extra = f), el };
}

// ---------------- overview ----------------
export async function overview(el) {
  await branchList();
  mount(el, h`<div class="page-head"><div><h1>Business overview</h1><p>Live figures from the database for the selected period and branch.</p></div></div>
    <div class="filters"><label class="f">Branch<select id="o-b">${branchOpts("All branches").map((o) => h`<option value="${o.value}">${o.label}</option>`)}</select></label><label class="f">From<input type="date" id="o-from" value="${daysAgoISO(29)}"></label><label class="f">To<input type="date" id="o-to" value="${todayISO()}"></label>
    <div class="row">${[["Today", 0], ["7 days", 6], ["30 days", 29], ["90 days", 89]].map(([l, d]) => h`<button class="btn sm" data-range="${d}">${l}</button>`)}</div></div><div id="ov">${loading()}</div>`);
  const draw = async () => {
    const box = $("#ov", el); mount(box, loading());
    try {
      const d = await api("/dashboard", { params: { branch_id: $("#o-b").value, date_from: $("#o-from").value, date_to: $("#o-to").value } }); const s = d.stats, c = d.charts;
      const S = (l, v, sub = "", cls = "") => h`<div class="stat ${cls}"><div class="l">${l}</div><div class="v">${v}</div>${sub ? h`<div class="s">${sub}</div>` : ""}</div>`;
      mount(box, h`<div class="stats">${S("Total revenue", naira(s.total_revenue_kobo), "Billed, non-cancelled orders", "accent")}${S("Revenue today", naira(s.revenue_today_kobo))}${S("Revenue this week", naira(s.revenue_week_kobo))}${S("Revenue this month", naira(s.revenue_month_kobo))}
        ${S("Cash received", naira(s.cash_received_kobo), "Verified payments")}${S("Outstanding payments", naira(s.outstanding_payments_kobo), "Owed by customers", s.outstanding_payments_kobo ? "warn" : "")}${S("Total expenses", naira(s.total_expenses_kobo), "Approved expenses")}${S("Est. gross profit", naira(s.estimated_gross_profit_kobo), "Revenue − recipe cost")}
        ${S("Total orders", num(s.total_orders))}${S("Pending orders", num(s.pending_orders))}${S("Processing orders", num(s.processing_orders))}${S("Completed orders", num(s.completed_orders))}${S("Cancelled orders", num(s.cancelled_orders))}
        ${S("Current stock value", naira(s.stock_value_kobo))}${S("Low-stock items", num(s.low_stock_count), "At or below reorder level", s.low_stock_count ? "warn" : "")}${S("Active branches", num(s.active_branches))}${S("Total staff", num(s.total_staff))}${S("Active drivers", num(s.active_drivers))}${S("Deliveries in progress", num(s.deliveries_in_progress))}</div>
        <div class="charts" style="margin-top:16px"><div class="card wide"><h3>Daily sales</h3>${lineChart([{ name: "Revenue", data: c.daily_sales.map((x) => x.revenue_kobo) }], c.daily_sales.map((x) => x.date.slice(5)))}</div>
        <div class="card"><h3>Weekly revenue (8 weeks)</h3>${barChart([{ name: "Revenue", data: c.weekly_revenue.map((x) => x.revenue_kobo) }], c.weekly_revenue.map((x) => x.label))}</div>
        <div class="card"><h3>Monthly revenue (12 months)</h3>${barChart([{ name: "Revenue", data: c.monthly_revenue.map((x) => x.revenue_kobo) }], c.monthly_revenue.map((x) => x.label))}</div>
        <div class="card"><h3>Revenue by branch</h3>${donutChart(c.revenue_by_branch.map((x) => ({ label: x.name, value: x.revenue_kobo })))}</div>
        <div class="card"><h3>Best-selling bread</h3>${hbarChart(c.best_sellers.map((x) => ({ label: x.name, value: x.quantity })), { fmt: (v) => num(v) + " sold" })}</div>
        <div class="card"><h3>Expenses by category</h3>${donutChart(c.expenses_by_category.map((x) => ({ label: x.name, value: x.amount_kobo })))}</div>
        <div class="card"><h3>Production: planned vs actual</h3>${barChart([{ name: "Planned", data: c.production_performance.map((x) => x.planned) }, { name: "Actual", data: c.production_performance.map((x) => x.actual) }], c.production_performance.map((x) => x.name), { fmt: num })}</div>
        <div class="card wide"><h3>Order fulfilment trend</h3>${lineChart([{ name: "Orders created", data: c.order_fulfilment.map((x) => x.created) }, { name: "Fulfilled", data: c.order_fulfilment.map((x) => x.fulfilled) }], c.order_fulfilment.map((x) => x.date.slice(5)), { fmt: num, area: false })}</div>
        <div class="card wide flush"><div class="card-head"><h3 style="margin:0">Recent orders</h3><a href="#/orders" class="btn sm">View all</a></div>${table([{ label: "Order", render: (o) => h`<strong>${o.order_number}</strong>` }, { label: "Customer", key: "contact_name" }, { label: "Total", align: "right", render: (o) => naira(o.total_kobo) }, { label: "Status", render: (o) => badge(o.status) }, { label: "Payment", render: (o) => badge(o.payment_status) }, { label: "Placed", render: (o) => fdt(o.created_at) }], d.recent_orders)}</div></div>`);
    } catch (e) { mount(box, errorBox(e)); }
  };
  ["o-b", "o-from", "o-to"].forEach((i) => ($("#" + i).onchange = draw));
  el.onclick = (e) => { const r = e.target.closest("[data-range]"); if (r) { $("#o-from").value = daysAgoISO(Number(r.dataset.range)); $("#o-to").value = todayISO(); draw(); } };
  draw();
}

// ---------------- branches ----------------
export async function branches(el) {
  await branchList();
  const staff = can("staff.view") ? (await api("/staff", { params: { size: 200 } })).items : [];
  const form = (b = {}) => openForm({ title: b.id ? "Edit branch" : "New branch", values: b, fields: [{ name: "name", label: "Branch name", required: true }, { name: "code", label: "Branch code", required: true, hint: "Short unique code, e.g. YNG" }, { name: "address", label: "Address", span: true }, { name: "state", label: "State" }, { name: "lga", label: "Local government area" },
    { name: "phone", label: "Contact number", type: "tel" }, { name: "opened_on", label: "Opening date", type: "date" }, { name: "manager_id", label: "Branch manager", type: "select", numeric: true, options: [{ value: "", label: "- none -" }, ...staff.map((s) => ({ value: s.id, label: `${s.full_name} (${s.role_name})` }))], nullable: true },
    { name: "is_active", label: "Branch is operating", type: "checkbox", value: b.id ? b.is_active : true }, { name: "accepts_online_orders", label: "Accepts online orders", type: "checkbox", value: b.id ? b.accepts_online_orders : true }],
    onSubmit: async (v, m) => { v.manager_id = v.manager_id ? Number(v.manager_id) : null; await api(b.id ? `/branches/${b.id}` : "/branches", { method: b.id ? "PUT" : "POST", body: v }); m.close(); toast("Branch saved", "ok"); branches(el); } });
  const cmp = can("branches.view") ? await api("/branches/compare") : [];
  mount(el, h`<div class="page-head"><div><h1>Branch management</h1><p>Create branches, assign managers and compare performance (month to date).</p></div>${can("branches.manage") ? h`<button class="btn primary" id="b-new">${icon("plus")} New branch</button>` : ""}</div>
    <div class="card flush">${table([{ label: "Branch", render: (b) => h`<strong>${b.name}</strong><div class="muted small">${b.code}${b.is_demo ? " · demo" : ""}</div>` }, { label: "Location", render: (b) => `${b.address || ""} ${b.lga ? "· " + b.lga : ""}, ${b.state}` }, { label: "Manager", render: (b) => b.manager_name || "-" }, { label: "Status", render: (b) => badge(b.is_active ? "active" : "inactive", b.is_active ? "Active" : "Inactive") },
      { label: "Opened", render: (b) => fdate(b.opened_on) }, { label: "", nolabel: true, render: (b) => h`<button class="btn sm" data-perf="${b.id}">Performance</button> ${can("branches.manage") ? h`<button class="btn sm" data-edit="${b.id}">${icon("edit")}</button>` : ""}` }], state.staffBranches)}</div>
    <div class="card" style="margin-top:16px"><h3>Branch comparison - month to date</h3>${table([{ label: "Branch", key: "name" }, { label: "Orders", align: "right", key: "orders" }, { label: "Revenue", align: "right", render: (r) => naira(r.revenue_kobo) }, { label: "Expenses", align: "right", render: (r) => naira(r.expenses_kobo) }, { label: "Est. gross profit", align: "right", render: (r) => naira(r.gross_profit_kobo) }, { label: "Stock value", align: "right", render: (r) => naira(r.stock_value_kobo) }, { label: "Units produced", align: "right", render: (r) => num(r.units_produced) }], cmp)}
      <div style="margin-top:14px">${barChart([{ name: "Revenue", data: cmp.map((r) => r.revenue_kobo) }, { name: "Expenses", data: cmp.map((r) => r.expenses_kobo) }], cmp.map((r) => r.name))}</div></div>`);
  const nb = $("#b-new"); if (nb) nb.onclick = () => form();
  el.onclick = async (e) => {
    const ed = e.target.closest("[data-edit]"), pf = e.target.closest("[data-perf]");
    if (ed) form(state.staffBranches.find((b) => b.id == ed.dataset.edit));
    if (pf) { const b = state.staffBranches.find((x) => x.id == pf.dataset.perf); const m = modal({ title: `${b.name} - this month`, wide: true, body: loading() }); try { const d = await api(`/branches/${b.id}/performance`, { params: { date_from: todayISO().slice(0, 8) + "01", date_to: todayISO() } }); const s = d.stats;
      mount(m.body, h`<div class="stats">${[["Revenue", naira(s.total_revenue_kobo)], ["Orders", s.total_orders], ["Expenses", naira(s.total_expenses_kobo)], ["Est. gross profit", naira(s.estimated_gross_profit_kobo)], ["Stock value", naira(s.stock_value_kobo)], ["Low stock", s.low_stock_count]].map(([l, v]) => h`<div class="stat"><div class="l">${l}</div><div class="v">${v}</div></div>`)}</div><div style="margin-top:14px">${lineChart([{ name: "Revenue", data: d.charts.daily_sales.map((x) => x.revenue_kobo) }], d.charts.daily_sales.map((x) => x.date.slice(5)))}</div>`); } catch (er) { mount(m.body, errorBox(er)); } }
  };
}

// ---------------- orders ----------------
const ORDER_FLOW = { pending: "Confirm order", confirmed: "Mark ready", paid: "Mark ready", queued_for_production: "Start production", in_production: "Mark ready", ready_for_collection: "Mark collected", delivered: "Complete" };
export async function orders(el) {
  await branchList(); const meta = await api("/orders/meta");
  const lp = listPage(el, { head: "Orders", desc: "All customer, walk-in and bulk orders.", toolbar: can("orders.create") ? '<button class="btn primary" id="o-new">+ New order</button>' : "",
    filters: [{ name: "q", label: "Search", placeholder: "Order no, name, phone" }, { name: "branch_id", label: "Branch", type: "select", options: branchOpts("All") }, { name: "status", label: "Status", type: "select", options: [{ value: "", label: "All" }, ...meta.statuses.map((s) => ({ value: s.key, label: s.label }))] },
      { name: "payment_status", label: "Payment", type: "select", options: [{ value: "", label: "All" }, ...["unpaid", "pending_verification", "partially_paid", "paid"].map((x) => ({ value: x, label: title(x) }))] }, { name: "channel", label: "Channel", type: "select", options: [{ value: "", label: "All" }, ...["online", "walk_in", "wholesale", "bulk", "staff"].map((x) => ({ value: x, label: title(x) }))] },
      { name: "date_from", label: "From", type: "date" }, { name: "date_to", label: "To", type: "date" }],
    load: (p, page, size) => api("/orders", { params: { ...p, page, size } }),
    cols: [{ label: "Order", render: (o) => h`<strong>${o.order_number}</strong><div class="muted small">${fdt(o.created_at)}</div>` }, { label: "Customer", render: (o) => h`${o.contact_name}<div class="muted small">${o.contact_phone}</div>` }, { label: "Type", render: (o) => h`${title(o.order_type)}<div class="muted small">${title(o.channel)}</div>` }, { label: "Total", align: "right", render: (o) => naira(o.total_kobo) }, { label: "Status", render: (o) => badge(o.status) }, { label: "Payment", render: (o) => badge(o.payment_status) }],
    onRow: (o, refresh) => orderDetail(o.id, refresh) });
  const nb = $("#o-new"); if (nb) nb.onclick = () => newOrder(lp.refresh);
}
export async function orderDetail(id, refresh) {
  const m = modal({ title: "Order", wide: true, body: loading() });
  const draw = async () => {
    try {
      const o = await api(`/orders/${id}`); const meta = await api("/orders/meta"); const next = meta.transitions[o.status] || [];
      m.el.querySelector("h3").textContent = `Order ${o.order_number}`;
      const btn = (s, l, cls = "") => h`<button class="btn sm ${cls}" data-st="${s}">${l}</button>`;
      const stBtns = next.filter((s) => !["cancelled", "assigned_to_driver", "out_for_delivery", "delivered", "queued_for_production", "in_production"].includes(s)).map((s) => btn(s, title(s)));
      mount(m.body, h`<div class="row between"><div class="row">${badge(o.status)} ${badge(o.payment_status)} ${o.is_demo ? h`<span class="badge demo">Demo</span>` : ""}</div>
        <div class="row no-print"><button class="btn sm" data-pdf="receipt">${icon("print")} Receipt</button><button class="btn sm" data-pdf="invoice">${icon("doc")} Invoice</button></div></div>
        <div class="grid2" style="margin-top:14px"><dl class="kv"><dt>Customer</dt><dd>${o.contact_name}<br>${o.contact_phone} ${o.contact_email || ""}</dd><dt>Branch</dt><dd>${o.branch_name}</dd><dt>${title(o.order_type)}</dt><dd>${o.delivery_address || "Pickup"} ${o.delivery_lga || ""}</dd><dt>Preferred</dt><dd>${fdate(o.preferred_date)} ${o.preferred_time}</dd><dt>Channel</dt><dd>${title(o.channel)}</dd>${o.notes ? h`<dt>Notes</dt><dd>${o.notes}</dd>` : ""}${o.cancel_reason ? h`<dt>Cancelled</dt><dd>${o.cancel_reason}</dd>` : ""}</dl>
        <div>${o.items.map((i) => h`<div class="sum small"><span>${i.quantity} × ${i.name}</span><span>${naira(i.line_total_kobo)}</span></div>`)}<div class="sum small"><span>Delivery</span><span>${naira(o.delivery_fee_kobo)}</span></div>${o.tax_kobo ? h`<div class="sum small"><span>Tax</span><span>${naira(o.tax_kobo)}</span></div>` : ""}<div class="sum total"><span>Total</span><span>${naira(o.total_kobo)}</span></div><div class="sum small"><span>Paid</span><span>${naira(o.paid_kobo)}</span></div><div class="sum small"><strong>Balance</strong><strong>${naira(o.balance_kobo)}</strong></div></div></div>
        <h4 style="margin:16px 0 8px">Payments</h4>${table([{ label: "Reference", key: "reference" }, { label: "Method", render: (p) => title(p.method) }, { label: "Amount", align: "right", render: (p) => naira(p.amount_kobo) }, { label: "Status", render: (p) => badge(p.status) }, { label: "Proof / note", render: (p) => p.proof_reference || "-" },
          { label: "", nolabel: true, render: (p) => can("payments.verify") && ["awaiting_verification", "pending"].includes(p.status) && !(p.method === "bank_transfer" && p.status === "pending") ? h`<button class="btn sm success" data-vp="${p.id}" data-ok="1">Verify</button> <button class="btn sm danger" data-vp="${p.id}" data-ok="0">Reject</button>` : "" }], o.payments, { empty: "No payments recorded." })}
        <h4 style="margin:16px 0 8px">Status history</h4><ul class="timeline">${o.history.map((x) => h`<li><strong>${title(x.to)}</strong> <span class="muted">· ${x.by} · ${fdt(x.at)}</span>${x.note ? h`<div class="muted small">${x.note}</div>` : ""}</li>`)}</ul>
        <div class="row no-print" style="margin-top:8px;padding-top:14px;border-top:1px solid var(--line)">${can("orders.manage") ? h`${stBtns}${["confirmed", "paid"].includes(o.status) ? h`<button class="btn sm" data-prod>${icon("flame")} Send to production</button>` : ""}${o.balance_kobo > 0 && o.status !== "cancelled" ? h`<button class="btn sm" data-addpay>${icon("wallet")} Record payment</button>` : ""}${["pending", "confirmed", "awaiting_payment", "paid", "queued_for_production"].includes(o.status) ? h`<button class="btn sm" data-edit>${icon("edit")} Edit</button>` : ""}` : ""}${can("orders.cancel") && next.includes("cancelled") ? h`<button class="btn sm danger" data-cancel>${icon("ban")} Cancel order</button>` : ""}</div>`);
      m.body.onclick = async (e) => {
        const st = e.target.closest("[data-st]"), vp = e.target.closest("[data-vp]"), pdf = e.target.closest("[data-pdf]");
        const act = async (fn) => { try { await fn(); await draw(); refresh && refresh(); } catch (er) { toast(er.message, "bad"); } };
        if (st) act(async () => { await api(`/orders/${id}/status`, { method: "POST", body: { status: st.dataset.st } }); toast("Status updated", "ok"); });
        if (vp) act(async () => { await api(`/payments/${vp.dataset.vp}/verify`, { method: "POST", body: { approve: vp.dataset.ok === "1" } }); toast("Payment updated", "ok"); });
        if (pdf) openPdf(`/orders/${id}/document.pdf`, { kind: pdf.dataset.pdf }).catch((er) => toast(er.message, "bad"));
        if (e.target.closest("[data-prod]")) act(async () => { const r = await api(`/orders/${id}/assign-production`, { method: "POST" }); toast("Queued: " + r.batches.join(", "), "ok"); });
        if (e.target.closest("[data-cancel]")) openForm({ title: "Cancel order", intro: "A reason is required and will be kept in the history.", fields: [{ name: "note", label: "Reason", type: "textarea", required: true, span: true }], submitLabel: "Cancel order", onSubmit: async (v, mm) => { await api(`/orders/${id}/status`, { method: "POST", body: { status: "cancelled", note: v.note } }); mm.close(); toast("Order cancelled", "ok"); draw(); refresh && refresh(); } });
        if (e.target.closest("[data-addpay]")) openForm({ title: "Record payment", fields: [{ name: "method", label: "Method", type: "select", options: ["cash", "pos", "bank_transfer", "cash_on_delivery", "cash_at_pickup"].map((x) => ({ value: x, label: title(x) })) }, { name: "amount_kobo", label: "Amount (₦)", type: "money", value: o.balance_kobo, required: true }, { name: "reference_note", label: "Reference / note", span: true }],
          onSubmit: async (v, mm) => { await api(`/orders/${id}/payments`, { method: "POST", body: { method: v.method, amount_kobo: v.amount_kobo, reference_note: v.reference_note } }); mm.close(); toast("Payment recorded", "ok"); draw(); refresh && refresh(); } });
        if (e.target.closest("[data-edit]")) openForm({ title: "Edit order details", values: o, fields: [{ name: "contact_name", label: "Customer name" }, { name: "contact_phone", label: "Phone" }, ...(o.order_type === "delivery" ? [{ name: "delivery_address", label: "Delivery address", span: true }, { name: "delivery_instructions", label: "Instructions", span: true }] : []), { name: "preferred_date", label: "Preferred date", type: "date", value: o.preferred_date }, { name: "preferred_time", label: "Preferred time" }, { name: "notes", label: "Notes", type: "textarea", span: true }],
          onSubmit: async (v, mm) => { await api(`/orders/${id}`, { method: "PATCH", body: v }); mm.close(); toast("Order updated", "ok"); draw(); refresh && refresh(); } });
      };
    } catch (e) { mount(m.body, errorBox(e)); }
  };
  draw();
}
async function newOrder(refresh) {
  const prods = (await api("/products", { params: { kind: "finished", active: true, size: 200 } })).items.filter((p) => p.is_sellable);
  const custs = can("customers.view") ? (await api("/customers", { params: { size: 200 } })).items : [];
  const lines = {};
  const m = openForm({ title: "New order", wide: true, submitLabel: "Create order", fields: [
    { name: "channel", label: "Order type", type: "select", options: [{ value: "walk_in", label: "Walk-in sale (counter)" }, { value: "staff", label: "On behalf of customer" }, { value: "wholesale", label: "Wholesale" }, { value: "bulk", label: "Bulk order" }] },
    { name: "branch_id", label: "Branch", type: "select", numeric: true, options: branchOpts(), required: true },
    { name: "customer_id", label: "Existing customer", type: "select", numeric: true, nullable: true, options: [{ value: "", label: "- New / walk-in -" }, ...custs.map((c) => ({ value: c.id, label: `${c.name} (${title(c.customer_type)})` }))] },
    { name: "contact_name", label: "Customer name", required: true, value: "Walk-in customer" }, { name: "contact_phone", label: "Phone", type: "tel" },
    { name: "order_type", label: "Fulfilment", type: "select", options: [{ value: "pickup", label: "Pickup / collected now" }, { value: "delivery", label: "Delivery" }] }, { name: "delivery_address", label: "Delivery address (if delivery)", span: true },
    { name: "payment_method", label: "Payment method", type: "select", options: ["cash", "pos", "bank_transfer", "cash_on_delivery", "cash_at_pickup"].map((x) => ({ value: x, label: title(x) })) }, { name: "amount_paid_kobo", label: "Amount received now (₦)", type: "money", hint: "Leave blank for full payment on walk-in sales; blank on other orders = unpaid" },
    { name: "notes", label: "Notes", span: true }, { html: `<div><strong>Items</strong><div class="stack" style="gap:6px;margin-top:6px">${prods.map((p) => `<div class="row between"><span>${esc(p.name)} ${p.size_label ? "(" + esc(p.size_label) + ")" : ""} <span class="muted small">${naira(p.price_kobo)}</span></span><input type="number" min="0" value="0" data-line="${p.id}" style="width:90px" class="input"></div>`).join("")}</div></div>` }],
    onSubmit: async (v, mm) => {
      const items = $$("[data-line]", mm.el).map((i) => ({ product_id: Number(i.dataset.line), quantity: Number(i.value) })).filter((l) => l.quantity > 0);
      if (!items.length) throw new Error("Add at least one item with a quantity.");
      if (v.customer_id) { const c = custs.find((x) => x.id == v.customer_id); v.contact_name = c.name; v.contact_phone = c.phone || v.contact_phone; }
      const body = { ...v, items, customer_id: v.customer_id ? Number(v.customer_id) : null, amount_paid_kobo: v.amount_paid_kobo || 0 };
      if (v.channel === "walk_in") body.order_type = "pickup";
      const o = await api("/orders", { method: "POST", body }); mm.close(); toast(`Order ${o.order_number} created`, "ok"); refresh && refresh(); orderDetail(o.id, refresh);
    } });
}

// ---------------- customers ----------------
export async function customers(el) {
  await branchList();
  const form = (c = {}) => openForm({ title: c.id ? "Edit customer" : "New customer", values: c, fields: [{ name: "name", label: "Name", required: true }, { name: "phone", label: "Phone", type: "tel" }, { name: "email", label: "Email", type: "email" }, { name: "customer_type", label: "Customer type", type: "select", options: ["retail", "wholesale", "bulk", "business"].map((x) => ({ value: x, label: title(x) })) },
    ...(!c.id ? [{ name: "address", label: "Address", span: true }] : []), { name: "notes", label: "Notes", type: "textarea", span: true }], onSubmit: async (v, m) => { v.preferred_branch_id = c.preferred_branch_id || null; await api(c.id ? `/customers/${c.id}` : "/customers", { method: c.id ? "PUT" : "POST", body: v }); m.close(); toast("Customer saved", "ok"); lp.refresh(); } });
  const lp = listPage(el, { head: "Customers", desc: "Retail, wholesale, bulk and business customers with purchase history.", toolbar: can("customers.manage") ? '<button class="btn primary" id="c-new">+ New customer</button>' : "",
    filters: [{ name: "q", label: "Search", placeholder: "Name, phone, email" }, { name: "customer_type", label: "Type", type: "select", options: [{ value: "", label: "All" }, ...["retail", "wholesale", "bulk", "business"].map((x) => ({ value: x, label: title(x) }))] }],
    load: (p, page, size) => api("/customers", { params: { ...p, page, size } }),
    cols: [{ label: "Customer", render: (c) => h`<strong>${c.name}</strong>${c.is_guest ? h` <span class="badge">Guest</span>` : ""}<div class="muted small">${c.phone} ${c.email}</div>` }, { label: "Type", render: (c) => badge(c.customer_type) }, { label: "Orders", align: "right", key: "orders" }, { label: "Total purchases", align: "right", render: (c) => naira(c.total_purchases_kobo) }, { label: "Outstanding", align: "right", render: (c) => c.outstanding_kobo ? h`<span style="color:var(--red);font-weight:700">${naira(c.outstanding_kobo)}</span>` : "-" }],
    onRow: async (c) => { const m = modal({ title: c.name, wide: true, body: loading() }); try { const d = await api(`/customers/${c.id}`); mount(m.body, h`<div class="row between"><dl class="kv"><dt>Phone</dt><dd>${d.phone}</dd><dt>Email</dt><dd>${d.email || "-"}</dd><dt>Type</dt><dd>${title(d.customer_type)}</dd><dt>Addresses</dt><dd>${d.addresses.map((a) => a.address).join("; ") || "-"}</dd><dt>Total purchases</dt><dd>${naira(d.total_purchases_kobo)}</dd><dt>Outstanding</dt><dd>${naira(d.outstanding_kobo)}</dd></dl>${can("customers.manage") ? h`<button class="btn" id="c-edit">${icon("edit")} Edit</button>` : ""}</div><h4 style="margin:14px 0 6px">Order history</h4>${table([{ label: "Order", key: "order_number" }, { label: "Date", render: (o) => fdt(o.created_at) }, { label: "Total", align: "right", render: (o) => naira(o.total_kobo) }, { label: "Status", render: (o) => badge(o.status) }, { label: "Payment", render: (o) => badge(o.payment_status) }], d.orders, { empty: "No orders yet." })}`); const ed = $("#c-edit", m.el); if (ed) ed.onclick = () => { m.close(); form(d); }; } catch (e) { mount(m.body, errorBox(e)); } } });
  const nb = $("#c-new"); if (nb) nb.onclick = () => form();
}

// ---------------- payments ----------------
export async function payments(el) {
  await branchList();
  listPage(el, { head: "Payments", desc: "Verify bank transfers and driver-collected cash. Nothing is marked paid until an authorised staff member verifies it (or the gateway confirms it).",
    filters: [{ name: "q", label: "Search", placeholder: "Reference / order" }, { name: "status", label: "Status", type: "select", value: "awaiting_verification", options: [{ value: "", label: "All" }, ...["pending", "awaiting_verification", "verified", "rejected", "failed"].map((x) => ({ value: x, label: title(x) }))] }, { name: "method", label: "Method", type: "select", options: [{ value: "", label: "All" }, ...["bank_transfer", "cash", "cash_on_delivery", "cash_at_pickup", "pos", "paystack"].map((x) => ({ value: x, label: title(x) }))] }],
    load: (p, page, size) => api("/payments", { params: { ...p, page, size } }),
    cols: [{ label: "Reference", render: (p) => h`<strong>${p.reference}</strong><div class="muted small">${fdt(p.created_at)}</div>` }, { label: "Order", render: (p) => h`${p.order_number}<div class="muted small">${p.customer}</div>` }, { label: "Method", render: (p) => title(p.method) }, { label: "Amount", align: "right", render: (p) => naira(p.amount_kobo) }, { label: "Customer reference", render: (p) => p.proof_reference || "-" }, { label: "Status", render: (p) => badge(p.status) },
      { label: "", nolabel: true, render: (p) => can("payments.verify") && p.status === "awaiting_verification" ? h`<button class="btn sm success" data-vp="${p.id}" data-ok="1">Verify</button> <button class="btn sm danger" data-vp="${p.id}" data-ok="0">Reject</button>` : "" }] });
  el.addEventListener("click", async (e) => { const b = e.target.closest("[data-vp]"); if (!b) return; const ok = b.dataset.ok === "1"; if (!(await confirmDialog(ok ? "Confirm that the money has actually been received?" : "Reject this payment?", { okLabel: ok ? "Yes, verify" : "Reject", danger: !ok }))) return; try { await api(`/payments/${b.dataset.vp}/verify`, { method: "POST", body: { approve: ok } }); toast("Payment updated", "ok"); payments(el); } catch (er) { toast(er.message, "bad"); } });
}

// ---------------- products ----------------
export async function products(el) {
  const cats = await api("/product-categories"); await branchList();
  const form = (p = {}) => openForm({ title: p.id ? "Edit product" : "New product / item", wide: true, values: p, intro: "Finished goods are sold on the storefront. Raw materials and packaging are used in recipes and purchasing.", fields: [
    { name: "name", label: "Name", required: true }, { name: "sku", label: "SKU code", required: true }, { name: "kind", label: "Type", type: "select", options: [{ value: "finished", label: "Finished product" }, { value: "raw", label: "Raw material" }, { value: "packaging", label: "Packaging material" }], value: p.kind || "finished" },
    { name: "category_id", label: "Category", type: "select", numeric: true, nullable: true, options: [{ value: "", label: "-" }, ...cats.map((c) => ({ value: c.id, label: `${c.name}` }))] }, { name: "size_label", label: "Size", hint: "e.g. Family, Large, Mini" }, { name: "unit", label: "Unit", value: p.unit || "pcs" },
    { name: "price_kobo", label: "Selling price (₦)", type: "money", value: p.price_kobo ?? 0 }, { name: "wholesale_price_kobo", label: "Wholesale price (₦)", type: "money", value: p.wholesale_price_kobo ?? 0 }, { name: "cost_kobo", label: "Unit cost (₦)", type: "money", value: p.cost_kobo ?? 0, hint: "Raw materials: purchase cost. Finished bread: set automatically from its recipe." },
    { name: "reorder_level", label: "Reorder level", type: "number", step: "any", value: p.reorder_level ?? 0 }, { name: "description", label: "Description", type: "textarea", span: true },
    ...(!p.id ? [{ name: "opening_stock", label: "Opening stock", type: "number", step: "any", value: 0 }, { name: "opening_branch_id", label: "Opening stock branch", type: "select", numeric: true, nullable: true, options: [{ value: "", label: "-" }, ...(state.staffBranches || []).map((b) => ({ value: b.id, label: b.name }))] }] : []),
    { name: "is_active", label: "Active", type: "checkbox", value: p.id ? p.is_active : true }, { html: p.id ? `<label class="f">Product image (PNG/JPEG/WebP, max 3MB)<input type="file" accept="image/*" id="p-img"></label>` : "" }],
    onSubmit: async (v, m) => { v.category_id = v.category_id ? Number(v.category_id) : null; v.opening_branch_id = v.opening_branch_id ? Number(v.opening_branch_id) : null; v.reorder_level = Number(v.reorder_level || 0); v.opening_stock = Number(v.opening_stock || 0);
      if (p.id) v.kind = p.kind; const r = await api(p.id ? `/products/${p.id}` : "/products", { method: p.id ? "PUT" : "POST", body: v });
      const f = $("#p-img", m.el)?.files[0]; if (f) { const fd = new FormData(); fd.append("file", f); await api(`/products/${r.id}/image`, { method: "POST", form: fd }); }
      m.close(); toast("Saved", "ok"); lp.refresh(); } });
  const lp = listPage(el, { head: "Products", desc: "Finished bread, raw materials and packaging.", toolbar: can("products.manage") ? '<button class="btn" id="cat-new">+ Category</button><button class="btn primary" id="p-new">+ New product</button>' : "",
    filters: [{ name: "q", label: "Search", placeholder: "Name or SKU" }, { name: "kind", label: "Type", type: "select", options: [{ value: "", label: "All" }, { value: "finished", label: "Finished" }, { value: "raw", label: "Raw materials" }, { value: "packaging", label: "Packaging" }] }],
    load: (p, page, size) => api("/products", { params: { ...p, page, size } }),
    cols: [{ label: "Item", render: (p) => h`<strong>${p.name}</strong> ${p.size_label ? h`<span class="badge">${p.size_label}</span>` : ""}${p.is_demo ? h` <span class="badge demo">Demo</span>` : ""}<div class="muted small">${p.sku} · ${p.category || ""}</div>` }, { label: "Type", render: (p) => title(p.kind) }, { label: "Price", align: "right", render: (p) => p.is_sellable ? naira(p.price_kobo) : "-" }, { label: "Unit cost", align: "right", render: (p) => p.cost_kobo !== undefined ? naira(p.cost_kobo) : "-" },
      { label: "In stock", align: "right", render: (p) => h`<span style="${p.low_stock ? "color:var(--red);font-weight:700" : ""}">${num(p.quantity)} ${p.unit}</span>` }, { label: "Status", render: (p) => badge(p.is_active ? "active" : "inactive") }], onRow: can("products.manage") ? (p) => form(p) : null });
  const nb = $("#p-new"); if (nb) nb.onclick = () => form();
  const cn = $("#cat-new"); if (cn) cn.onclick = () => openForm({ title: "New category", fields: [{ name: "name", label: "Name", required: true }, { name: "kind", label: "Applies to", type: "select", options: [{ value: "finished", label: "Finished products" }, { value: "raw", label: "Raw materials" }, { value: "packaging", label: "Packaging" }] }], onSubmit: async (v, m) => { await api("/product-categories", { method: "POST", body: v }); m.close(); toast("Category added", "ok"); products(el); } });
}

// ---------------- inventory ----------------
export async function inventory(el) {
  await branchList(); const prods = (await api("/products", { params: { size: 500, active: true } })).items;
  mount(el, h`<div class="page-head"><div><h1>Inventory</h1><p>Every stock change is recorded as a movement with who, when and why.</p></div><div class="row">${can("inventory.adjust") ? h`<button class="btn primary" id="i-move">${icon("plus")} Record stock movement</button>` : ""}${can("inventory.transfer") ? h`<button class="btn" id="i-trf">Transfer between branches</button>` : ""}</div></div>
    <div class="tabs"><button class="tab active" data-t="stock">Stock levels</button><button class="tab" data-t="moves">Movement history</button><button class="tab" data-t="trf">Transfers</button></div><div id="inv-body"></div>`);
  const body = $("#inv-body", el); let tab = "stock", cur;
  const show = () => {
    $$(".tab", el).forEach((t) => t.classList.toggle("active", t.dataset.t === tab)); const holder = document.createElement("div"); mount(body, ""); body.appendChild(holder);
    if (tab === "stock") cur = listPage(holder, { head: "Stock levels", filters: [{ name: "q", label: "Search" }, { name: "branch_id", label: "Branch", type: "select", options: branchOpts("All") }, { name: "kind", label: "Type", type: "select", options: [{ value: "", label: "All" }, { value: "finished", label: "Finished" }, { value: "raw", label: "Raw materials" }, { value: "packaging", label: "Packaging" }] }, { name: "low", label: "Low stock only", type: "select", options: [{ value: "", label: "No" }, { value: "true", label: "Yes" }] }],
      load: (p, page, size) => api("/inventory/stock", { params: { ...p, page, size } }), size: 50, cols: [{ label: "Item", render: (r) => h`<strong>${r.name}</strong><div class="muted small">${r.sku}</div>` }, { label: "Type", render: (r) => title(r.kind) }, { label: "Branch", key: "branch" }, { label: "Quantity", align: "right", render: (r) => h`<span style="${r.low_stock ? "color:var(--red);font-weight:800" : ""}">${num(r.quantity)} ${r.unit}</span>${r.low_stock ? h` <span class="badge red">Low</span>` : ""}` }, { label: "Reorder at", align: "right", render: (r) => num(r.reorder_level) }, { label: "Value", align: "right", render: (r) => naira(r.value_kobo) }] });
    if (tab === "moves") cur = listPage(holder, { head: "Movement history", filters: [{ name: "branch_id", label: "Branch", type: "select", options: branchOpts("All") }, { name: "movement_type", label: "Type", type: "select", options: [{ value: "", label: "All" }, ...["addition", "deduction", "damaged", "expired", "wastage", "sale_out", "production_in", "production_out", "purchase_in", "transfer_in", "transfer_out", "opening"].map((x) => ({ value: x, label: title(x) }))] }, { name: "date_from", label: "From", type: "date" }, { name: "date_to", label: "To", type: "date" }],
      load: (p, page, size) => api("/inventory/movements", { params: { ...p, page, size } }), size: 50, cols: [{ label: "When", render: (r) => fdt(r.at) }, { label: "Item", key: "product" }, { label: "Branch", key: "branch" }, { label: "Type", render: (r) => badge(r.type) }, { label: "Qty", align: "right", render: (r) => h`<span style="color:${r.quantity < 0 ? "var(--red)" : "var(--green)"};font-weight:700">${r.quantity > 0 ? "+" : ""}${num(r.quantity)}</span>` }, { label: "Balance", align: "right", render: (r) => num(r.balance_after) }, { label: "Reason / ref", render: (r) => h`${r.reason}<div class="muted small">${r.reference}</div>` }, { label: "By", key: "by" }] });
    if (tab === "trf") api("/inventory/transfers").then((t) => mount(holder, h`<div class="card flush">${table([{ label: "No.", key: "number" }, { label: "Item", key: "product" }, { label: "From", key: "from" }, { label: "To", key: "to" }, { label: "Qty", align: "right", render: (r) => num(r.quantity) }, { label: "Date", render: (r) => fdt(r.at) }, { label: "Note", key: "note" }], t, { empty: "No transfers yet." })}</div>`));
  };
  el.addEventListener("click", (e) => { const t = e.target.closest(".tab"); if (t) { tab = t.dataset.t; show(); } });
  const popts = prods.map((p) => ({ value: p.id, label: `${p.name} (${p.sku})` }));
  const mv = $("#i-move", el); if (mv) mv.onclick = () => openForm({ title: "Record stock movement", fields: [{ name: "product_id", label: "Item", type: "select", numeric: true, options: popts, required: true }, { name: "branch_id", label: "Branch", type: "select", numeric: true, options: branchOpts(), required: true }, { name: "movement_type", label: "Movement", type: "select", options: [{ value: "addition", label: "Stock addition" }, { value: "deduction", label: "Stock deduction" }, { value: "damaged", label: "Damaged goods" }, { value: "expired", label: "Expired goods" }, { value: "wastage", label: "Wastage" }] }, { name: "quantity", label: "Quantity", type: "number", step: "any", min: 0, required: true }, { name: "reason", label: "Reason (required)", type: "textarea", required: true, span: true }],
    onSubmit: async (v, m) => { v.product_id = Number(v.product_id); v.branch_id = Number(v.branch_id); v.quantity = Number(v.quantity); const r = await api("/inventory/movements", { method: "POST", body: v }); m.close(); toast(`Recorded. New balance: ${num(r.balance_after)}`, "ok"); show(); } });
  const tr = $("#i-trf", el); if (tr) tr.onclick = () => openForm({ title: "Transfer stock between branches", fields: [{ name: "product_id", label: "Item", type: "select", numeric: true, options: popts, required: true }, { name: "from_branch_id", label: "From branch", type: "select", numeric: true, options: branchOpts() }, { name: "to_branch_id", label: "To branch", type: "select", numeric: true, options: branchOpts() }, { name: "quantity", label: "Quantity", type: "number", step: "any", min: 0, required: true }, { name: "note", label: "Note", span: true }],
    onSubmit: async (v, m) => { const r = await api("/inventory/transfers", { method: "POST", body: { ...v, product_id: Number(v.product_id), from_branch_id: Number(v.from_branch_id), to_branch_id: Number(v.to_branch_id), quantity: Number(v.quantity) } }); m.close(); toast("Transfer " + r.number + " completed", "ok"); show(); } });
  show();
}
