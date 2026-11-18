// Staff console shell: permission-aware navigation, notifications, page host.
import { api, h, raw, mount, $, $$, icon, logoTile, state, can, loading, errorBox, fdt, toast, events, title } from "./core.js";
import * as P1 from "./pages.js";
import * as P2 from "./pages2.js";

export const NAV = [
  { g: "Business", items: [
    { id: "overview", label: "Overview", icon: "grid", perms: ["dashboard.view"], load: P1.overview },
    { id: "branches", label: "Branch Management", icon: "branch", perms: ["branches.view"], load: P1.branches },
    { id: "orders", label: "Orders", icon: "cart", perms: ["orders.view"], load: P1.orders },
    { id: "customers", label: "Customers", icon: "users", perms: ["customers.view"], load: P1.customers },
    { id: "payments", label: "Payments", icon: "wallet", perms: ["payments.view"], load: P1.payments } ] },
  { g: "Operations", items: [
    { id: "products", label: "Products", icon: "bread", perms: ["products.view"], load: P1.products },
    { id: "production", label: "Production", icon: "flame", perms: ["production.view"], load: P2.production },
    { id: "inventory", label: "Inventory", icon: "box", perms: ["inventory.view"], load: P1.inventory },
    { id: "suppliers", label: "Suppliers", icon: "shop", perms: ["suppliers.view"], load: P2.suppliers },
    { id: "purchasing", label: "Purchasing", icon: "clip", perms: ["purchasing.view"], load: P2.purchasing } ] },
  { g: "Logistics", items: [
    { id: "dispatch", label: "Dispatch", icon: "truck", perms: ["dispatch.view"], load: P2.dispatch },
    { id: "drivers", label: "Drivers", icon: "user", perms: ["dispatch.view", "drivers.manage"], load: P2.drivers },
    { id: "vehicles", label: "Vehicles", icon: "truck", perms: ["dispatch.view", "vehicles.manage"], load: P2.vehicles } ] },
  { g: "Finance", items: [
    { id: "finance", label: "Finance", icon: "coin", perms: ["finance.view"], load: P2.finance },
    { id: "expenses", label: "Expenses", icon: "receipt", perms: ["finance.view", "expenses.record"], load: P2.expenses },
    { id: "reports", label: "Reports", icon: "chart", perms: ["reports.view"], load: P2.reports } ] },
  { g: "Administration", items: [
    { id: "staff", label: "Staff Management", icon: "users", perms: ["staff.view"], load: P2.staffPage },
    { id: "tasks", label: "Tasks", icon: "check", perms: ["tasks.manage"], load: P2.tasksManage },
    { id: "audit", label: "Audit Logs", icon: "log", perms: ["audit.view"], load: P2.audit },
    { id: "settings", label: "Settings", icon: "gear", perms: ["settings.view"], load: P2.settings } ] },
  { g: "My work", items: [
    { id: "workspace", label: "My Workspace", icon: "home", perms: [], load: P2.workspace },
    { id: "notifications", label: "Notifications", icon: "bell", perms: [], load: P2.notifications } ] },
];
const allowed = (it) => !it.perms.length || it.perms.some(can);
export const visible = () => NAV.map((g) => ({ ...g, items: g.items.filter(allowed) })).filter((g) => g.items.length);
export const firstPage = () => visible()[0]?.items[0]?.id || "workspace";

let unreadTimer;
export async function render(root, route) {
  const groups = visible(); const flat = groups.flatMap((g) => g.items); const page = flat.find((i) => i.id === route) || flat.find((i) => i.id === firstPage());
  const u = state.user;
  if (!$("#console")) {
    mount(root, h`<div id="console">${state.config?.demo_mode ? h`<div class="demo-bar">DEMO DATA MODE - records shown are sample data. Switch back in Settings → Data mode.</div>` : ""}
      <div class="shell"><aside class="side" id="side"><div class="brand">${logoTile(62)}</div><nav id="nav"></nav><div class="me"><div class="strong">${u.full_name}</div><div class="muted small" style="color:#9d968f">${u.role_name}${u.branch_name ? " · " + u.branch_name : ""}</div>
        <div class="row" style="margin-top:10px"><button class="btn sm" id="pw-btn" style="background:#222;color:#fff;border-color:#333">${icon("key")} Password</button><button class="btn sm" id="out-btn" style="background:#222;color:#fff;border-color:#333">${icon("logout")} Sign out</button></div></div></aside><div class="scrim" id="scrim"></div>
        <div class="main"><header class="topbar"><button class="btn ghost menu-btn" id="menu" aria-label="Menu">${icon("menu")}</button><h1 id="page-title"></h1><span class="grow"></span>
          <a class="btn sm no-print" href="#/" target="_blank" rel="noopener">${icon("shop")} Storefront</a>
          <div style="position:relative"><button class="btn notif-btn" id="bell" aria-label="Notifications">${icon("bell")}<span class="dot hidden" id="bell-n">0</span></button><div class="dropdown hidden" id="bell-dd"></div></div></header>
          <div class="content" id="page"></div></div></div></div>`);
    $("#menu").onclick = () => { $("#side").classList.add("open"); $("#scrim").classList.add("open"); };
    $("#scrim").onclick = closeNav;
    $("#out-btn").onclick = async () => { try { await api("/auth/logout", { method: "POST" }); } catch {} state.user = null; location.hash = "#/staff"; location.reload(); };
    $("#pw-btn").onclick = changePassword;
    $("#bell").onclick = toggleBell;
    document.addEventListener("click", (e) => { if (!e.target.closest("#bell-dd") && !e.target.closest("#bell")) $("#bell-dd")?.classList.add("hidden"); });
    pollUnread(); clearInterval(unreadTimer); unreadTimer = setInterval(pollUnread, 45000);
  }
  closeNav();
  mount($("#nav"), h`${groups.map((g) => h`<div class="grp">${g.g}</div>${g.items.map((i) => h`<a class="nav-a ${i.id === page.id ? "active" : ""}" href="#/${i.id}">${icon(i.icon)}<span>${i.label}</span></a>`)}`)}`);
  $("#page-title").textContent = page.label;
  const el = $("#page"); mount(el, loading());
  try { await page.load(el); } catch (e) { mount(el, errorBox(e)); }
}
const closeNav = () => { $("#side")?.classList.remove("open"); $("#scrim")?.classList.remove("open"); };
async function pollUnread() { try { const r = await api("/notifications", { params: { unread: true } }); const n = $("#bell-n"); if (n) { n.textContent = r.unread; n.classList.toggle("hidden", !r.unread); } } catch {} }
async function toggleBell() {
  const dd = $("#bell-dd"); if (!dd.classList.contains("hidden")) return dd.classList.add("hidden");
  dd.classList.remove("hidden"); mount(dd, loading());
  try { const r = await api("/notifications"); mount(dd, h`<div class="row between dd-item"><strong>Notifications</strong><button class="btn sm" id="mark-all">Mark all read</button></div>${r.items.length ? r.items.slice(0, 12).map((n) => h`<a class="dd-item ${n.is_read ? "" : "unread"}" style="display:block;color:inherit;text-decoration:none" href="${n.link || "#/notifications"}"><div class="strong">${n.title}</div><div class="muted small">${n.body}</div><div class="muted small">${fdt(n.created_at)}</div></a>`) : h`<div class="empty">You're all caught up.</div>`}<a class="dd-item" style="display:block;text-align:center" href="#/notifications">See all</a>`);
    $("#mark-all").onclick = async () => { await api("/notifications/read", { method: "POST" }); pollUnread(); dd.classList.add("hidden"); };
  } catch (e) { mount(dd, errorBox(e)); }
}
function changePassword() {
  import("./core.js").then(({ openForm }) => openForm({ title: "Change password", fields: [{ name: "current_password", label: "Current password", type: "password", required: true }, { name: "new_password", label: "New password", type: "password", required: true, hint: "At least 8 characters with letters and numbers" }],
    onSubmit: async (v, m) => { await api("/auth/change-password", { method: "POST", body: v }); toast("Password changed", "ok"); m.close(); } }));
}
