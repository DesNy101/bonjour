// Public customer portal: catalogue, cart, checkout, tracking, account.
import { api, h, raw, esc, mount, $, $$, naira, num, title, fdt, fdate, badge, toast, busy, state, saveCart, icon, logoTile, openForm, modal, loading, errorBox, todayISO, events, fieldsHTML, readFields } from "./core.js";

const STEPS = ["pending", "confirmed", "paid", "in_production", "ready_for_dispatch", "out_for_delivery", "delivered"];
const PICKUP_STEPS = ["pending", "confirmed", "paid", "in_production", "ready_for_collection", "completed"];

export const cartCount = () => state.cart.reduce((a, b) => a + b.quantity, 0);
export const cartTotals = () => { let sub = 0; for (const l of state.cart) sub += l.price_kobo * l.quantity; return sub; };

export function header(active) {
  const cfg = state.config || {}; const u = state.user;
  return h`<header class="sf-head"><div class="sf-bar">
    <a href="#/" aria-label="Bonjour Bakery home">${logoTile(46)}</a>
    <nav class="sf-links"><a href="#/" class="${active === "home" ? "active" : ""}">Order bread</a><a href="#/track" class="${active === "track" ? "active" : ""}">Track order</a><a href="#/contact" class="${active === "contact" ? "active" : ""}">Contact</a></nav>
    <span class="grow"></span>
    ${u && !u.is_staff ? h`<a class="btn" href="#/account">${icon("user")} <span class="small">${u.full_name.split(" ")[0]}</span></a>` : u ? h`<a class="btn" href="#/app">${icon("grid")} Dashboard</a>` : h`<a class="btn" href="#/login">${icon("user")} Sign in</a>`}
    <button class="btn primary" data-cart-open aria-label="Open cart">${icon("cart")} <span>Cart</span> <span class="badge" style="background:#fff;color:#e65c00" data-cart-count>${cartCount()}</span></button>
  </div></header>`;
}
export const footer = () => { const c = state.config || {}; return h`<footer class="footer"><div class="sf-wrap row between" style="align-items:flex-start;gap:24px"><div class="stack" style="gap:10px">${logoTile(48)}<div>${c.tagline || ""}</div></div>
  <div class="stack" style="gap:4px"><strong style="color:#fff">Contact</strong><span>${c.contact_address || ""}</span>${c.contact_phone ? h`<span>${icon("phone")} ${c.contact_phone}</span>` : ""}${c.contact_email ? h`<span>${c.contact_email}</span>` : ""}</div>
  <div class="stack" style="gap:4px"><strong style="color:#fff">Quick links</strong><a href="#/">Order bread</a><a href="#/track">Track an order</a><a href="#/staff">Staff sign in</a></div></div></footer>`; };

function cartDrawer() {
  return h`<div class="cart-drawer" id="cart-drawer" aria-label="Shopping cart"><div class="card-head"><h3 style="margin:0">Your cart</h3><button class="btn ghost sm" data-cart-close aria-label="Close cart">${icon("x")}</button></div>
  <div style="flex:1;overflow:auto;padding:6px 18px" id="cart-lines"></div><div style="padding:16px 18px;border-top:1px solid var(--line)" id="cart-foot"></div></div>`;
}
export function renderCart() {
  const lines = $("#cart-lines"), foot = $("#cart-foot"); if (!lines) return;
  $$("[data-cart-count]").forEach((e) => (e.textContent = cartCount()));
  if (!state.cart.length) { mount(lines, h`<div class="empty">Your cart is empty.<br>Add some fresh bread!</div>`); mount(foot, h`<button class="btn block" data-cart-close>Keep browsing</button>`); return; }
  mount(lines, h`${state.cart.map((l) => h`<div class="cart-line"><div><div class="strong">${l.name}</div><div class="muted small">${naira(l.price_kobo)} each</div>
    <div class="qty" style="margin-top:6px"><button data-dec="${l.product_id}" aria-label="Less">−</button><span>${l.quantity}</span><button data-inc="${l.product_id}" aria-label="More">+</button></div></div>
    <div class="right"><div class="strong">${naira(l.price_kobo * l.quantity)}</div><button class="btn ghost sm" data-remove="${l.product_id}" style="color:var(--red)">Remove</button></div></div>`)}`);
  mount(foot, h`<div class="sum"><span>Subtotal</span><strong>${naira(cartTotals())}</strong></div><p class="muted small" style="margin:2px 0 10px">Delivery fee and totals are calculated at checkout.</p><a class="btn primary block" href="#/checkout" data-cart-close>Checkout</a>`);
}
export function cartAdd(p, qty = 1) {
  const l = state.cart.find((x) => x.product_id === p.id);
  if (l) l.quantity += qty; else state.cart.push({ product_id: p.id, name: p.name + (p.size_label ? ` (${p.size_label})` : ""), price_kobo: p.price_kobo, quantity: qty });
  saveCart(); renderCart();
}
export function bindCart(root) {
  root.addEventListener("click", (e) => {
    const t = e.target;
    if (t.closest("[data-cart-open]")) { $("#cart-drawer").classList.add("open"); renderCart(); }
    if (t.closest("[data-cart-close]")) $("#cart-drawer").classList.remove("open");
    const inc = t.closest("[data-inc]"), dec = t.closest("[data-dec]"), rm = t.closest("[data-remove]");
    if (inc) { state.cart.find((x) => x.product_id == inc.dataset.inc).quantity++; saveCart(); renderCart(); }
    if (dec) { const l = state.cart.find((x) => x.product_id == dec.dataset.dec); l.quantity = Math.max(1, l.quantity - 1); saveCart(); renderCart(); }
    if (rm) { state.cart = state.cart.filter((x) => x.product_id != rm.dataset.remove); saveCart(); renderCart(); }
  });
}
export function shell(active, content) { return h`${header(active)}<main class="sf-wrap" style="padding-top:6px">${content}</main>${footer()}${cartDrawer()}`; }

// ---------------- home / catalogue ----------------
export async function home(root) {
  mount(root, shell("home", loading()));
  const branches = state.branches;
  if (!state.cartBranch || !branches.find((b) => b.id === state.cartBranch)) { state.cartBranch = branches[0]?.id || null; saveCart(); }
  let products = [];
  try { products = await api("/public/products", { params: { branch_id: state.cartBranch } }); } catch (e) { mount(root, shell("home", errorBox(e))); return; }
  const cfg = state.config;
  const br = branches.find((b) => b.id === state.cartBranch);
  const sample = (p) => h`<div class="prod" data-pid="${p.id}"><div class="img">${p.image_url ? h`<img src="${p.image_url}" alt="${p.name}" loading="lazy">` : icon("bread")}<span class="badge ${p.availability === "available" ? "green" : p.availability === "limited" ? "amber" : ""}">${p.availability === "available" ? "Fresh today" : p.availability === "limited" ? "Selling fast" : "Baked to order"}</span></div>
    <div class="body"><div class="name">${p.name}</div><div class="muted small">${[p.size_label && "Size: " + p.size_label, p.category].filter(Boolean).join(" · ")}</div><div class="desc">${p.description || ""}</div>
    <div class="row between"><span class="price">${naira(p.price_kobo)}</span><button class="btn primary sm" data-add="${p.id}">${icon("plus")} Add</button></div></div></div>`;
  mount(root, shell("home", h`
    <section class="hero"><div class="txt"><h1>Fresh bread, <em>baked daily</em>.<br>Delivered to your door.</h1><p>${String(cfg.tagline || "").replace(/[.!\s]*$/, "")}. Order online for delivery or pickup from your nearest Bonjour branch.</p>
      <div class="row"><a class="btn primary" href="#catalogue" data-scroll>Order now</a><a class="btn" style="background:transparent;color:#fff;border-color:#555" href="#/track">Track my order</a></div></div>
      <div class="art"><img src="/assets/bonjour-logo.png" alt="Bonjour Bakery logo"></div></section>
    <section id="catalogue"><div class="row between" style="margin-bottom:12px"><div><h2>Our bread</h2><span class="muted">Prices in Nigerian Naira. Availability shown for the selected branch.</span></div>
      <label class="f" style="min-width:260px">Order from branch<select id="branch-pick">${state.branches.map((b) => h`<option value="${b.id}" ${b.id === state.cartBranch ? raw("selected") : ""}>${b.name}${b.lga ? " - " + b.lga : ""}</option>`)}</select></label></div>
      ${br ? h`<p class="muted small" style="margin-top:0">${icon("pin")} ${br.address || br.lga} ${br.phone ? " · " + br.phone : ""}</p>` : ""}
      ${products.length ? h`<div class="catalog">${products.map(sample)}</div>` : h`<div class="card empty">No products are available online right now. Please check back soon or call us.</div>`}</section>`));
  const pick = $("#branch-pick"); if (pick) pick.onchange = () => { state.cartBranch = Number(pick.value); saveCart(); home(root); };
  const sc = $("[data-scroll]"); if (sc) sc.onclick = (e) => { e.preventDefault(); $("#catalogue").scrollIntoView({ behavior: "smooth" }); };
  root.onclick = (e) => { const a = e.target.closest("[data-add]"); if (a) { const p = products.find((x) => x.id == a.dataset.add); cartAdd(p); toast(`${p.name} added to cart`, "ok"); } };
  renderCart();
}

export function contact(root) {
  const c = state.config;
  mount(root, shell("contact", h`<div class="card" style="max-width:640px;margin:20px auto"><h2>Contact us</h2><dl class="kv" style="margin-top:14px"><dt>Address</dt><dd>${c.contact_address}</dd><dt>Phone</dt><dd>${c.contact_phone || "-"}</dd><dt>Email</dt><dd>${c.contact_email || "-"}</dd></dl>
    <h3 style="margin-top:22px">Our branches</h3>${state.branches.map((b) => h`<div class="cart-line"><div><div class="strong">${b.name}</div><div class="muted small">${b.address} ${b.lga ? "· " + b.lga : ""}</div></div><div class="muted small">${b.phone || ""}</div></div>`)}</div>`));
}

// ---------------- checkout ----------------
export async function checkout(root) {
  if (!state.cart.length) { location.hash = "#/"; return; }
  const cfg = state.config, u = state.user; let cust = u?.customer;
  const branch = state.branches.find((b) => b.id === state.cartBranch) || state.branches[0];
  const slots = cfg.delivery_time_slots || [];
  const methods = (type) => [["cash_on_delivery", "Cash on delivery", "Pay the driver when your bread arrives", cfg.pay_cash_on_delivery && type === "delivery"], ["cash_at_pickup", "Cash at pickup", "Pay at the counter when you collect", cfg.pay_cash_at_pickup && type === "pickup"],
    ["bank_transfer", "Bank transfer", "Transfer, then confirm with your reference. We verify before confirming.", cfg.pay_bank_transfer], ["paystack", "Pay online (card / transfer)", "Secure payment by Paystack", cfg.paystack_available && cfg.pay_online]].filter((m) => m[3]);
  const form = { type: "delivery", method: null };
  const draw = () => {
    const sub = cartTotals(); const fee = form.type === "delivery" ? (cfg.free_delivery_above_kobo && sub >= cfg.free_delivery_above_kobo ? 0 : cfg.delivery_fee_kobo) : 0;
    const tax = cfg.tax_enabled ? Math.round(sub * cfg.tax_rate_percent / 100) : 0; const ms = methods(form.type); if (!ms.find((m) => m[0] === form.method)) form.method = ms[0]?.[0];
    const addrs = cust?.addresses || [];
    mount($("#co"), h`<div class="two-col"><div class="stack">
      <div class="card"><h3>1. How would you like your order?</h3><div class="choice"><label class="${form.type === "delivery" ? "on" : ""}"><input type="radio" name="otype" value="delivery" ${form.type === "delivery" ? raw("checked") : ""}> <span>${icon("truck")} Delivery<br><span class="muted small">To your address</span></span></label>
        <label class="${form.type === "pickup" ? "on" : ""}"><input type="radio" name="otype" value="pickup" ${form.type === "pickup" ? raw("checked") : ""}> <span>${icon("shop")} Pickup<br><span class="muted small">From ${branch?.name}</span></span></label></div></div>
      <div class="card"><h3>2. Your details</h3><div class="grid2"><label class="f">Full name *<input id="c-name" value="${u?.full_name || ""}" autocomplete="name"></label><label class="f">Phone number *<input id="c-phone" type="tel" value="${u?.phone || ""}" autocomplete="tel"></label>
        <label class="f span2">Email ${form.method === "paystack" ? "*" : "(optional)"}<input id="c-email" type="email" value="${u?.email || ""}" autocomplete="email"></label>
        ${form.type === "delivery" ? h`${addrs.length ? h`<label class="f span2">Saved address<select id="c-saved"><option value="">Enter a new address</option>${addrs.map((a) => h`<option value="${a.id}">${a.label}: ${a.address}</option>`)}</select></label>` : ""}
          <label class="f span2">Delivery address *<textarea id="c-addr" placeholder="House number, street, landmark"></textarea></label>
          <label class="f">Area / LGA<select id="c-lga">${(cfg.delivery_lgas || []).map((l) => h`<option>${l}</option>`)}</select></label>
          <label class="f">Delivery instructions<input id="c-instr" placeholder="e.g. call on arrival"></label>` : ""}
        <label class="f">Preferred ${form.type === "delivery" ? "delivery" : "pickup"} date<input id="c-date" type="date" min="${todayISO()}" value="${todayISO()}"></label>
        <label class="f">Preferred time<select id="c-time">${slots.map((s) => h`<option>${s}</option>`)}</select></label>
        <label class="f span2">Order notes<input id="c-notes" placeholder="Anything we should know?"></label></div>
        ${!u ? h`<p class="muted small" style="margin-bottom:0">Checking out as a guest. <a href="#/login">Sign in</a> or <a href="#/register">create an account</a> to save addresses and track orders easily.</p>` : ""}</div>
      <div class="card"><h3>3. Payment</h3><div class="choice" style="flex-direction:column">${ms.map((m) => h`<label class="${form.method === m[0] ? "on" : ""}"><input type="radio" name="pm" value="${m[0]}" ${form.method === m[0] ? raw("checked") : ""}><span>${m[1]}<br><span class="muted small">${m[2]}</span></span></label>`)}</div></div></div>
      <div class="card" style="position:sticky;top:76px"><h3>Order summary</h3><p class="muted small" style="margin-top:-6px">${icon("pin")} ${branch?.name}</p>${state.cart.map((l) => h`<div class="sum small"><span>${l.quantity} × ${l.name}</span><span>${naira(l.price_kobo * l.quantity)}</span></div>`)}
        <div class="sum" style="margin-top:8px"><span>Subtotal</span><span>${naira(sub)}</span></div><div class="sum"><span>Delivery</span><span>${fee ? naira(fee) : form.type === "delivery" ? "Free" : "-"}</span></div>${tax ? h`<div class="sum"><span>Tax</span><span>${naira(tax)}</span></div>` : ""}
        <div class="sum total"><span>Total</span><span>${naira(sub + fee + tax)}</span></div><div class="err hidden" id="co-err" style="margin:10px 0"></div>
        <button class="btn primary block" id="place" style="margin-top:12px">Place order</button><p class="muted small">Totals are re-calculated securely by our system when you submit.</p></div></div>`);
    $$("[name=otype]").forEach((r) => (r.onchange = () => { snap(); form.type = r.value; draw(); }));
    $$("[name=pm]").forEach((r) => (r.onchange = () => { snap(); form.method = r.value; draw(); }));
    const saved = $("#c-saved"); if (saved) saved.onchange = () => { const a = addrs.find((x) => x.id == saved.value); if (a) { $("#c-addr").value = a.address; $("#c-lga").value = a.lga || $("#c-lga").value; } };
    restore();
    $("#place").onclick = submit;
  };
  let keep = {}; const ids = ["c-name", "c-phone", "c-email", "c-addr", "c-lga", "c-instr", "c-date", "c-time", "c-notes"];
  const snap = () => ids.forEach((i) => { const e = $("#" + i); if (e) keep[i] = e.value; });
  const restore = () => ids.forEach((i) => { const e = $("#" + i); if (e && keep[i] !== undefined) e.value = keep[i]; });
  const submit = async () => {
    const err = $("#co-err"); err.classList.add("hidden");
    const body = { branch_id: state.cartBranch, order_type: form.type, contact_name: $("#c-name").value.trim(), contact_phone: $("#c-phone").value.trim(), contact_email: $("#c-email").value.trim(),
      delivery_address: form.type === "delivery" ? $("#c-addr").value.trim() : "", delivery_lga: form.type === "delivery" ? $("#c-lga").value : "", delivery_instructions: form.type === "delivery" ? $("#c-instr").value : "",
      preferred_date: $("#c-date").value || null, preferred_time: $("#c-time").value, notes: $("#c-notes").value, payment_method: form.method, items: state.cart.map((l) => ({ product_id: l.product_id, quantity: l.quantity })) };
    if (!body.contact_name || !body.contact_phone) { err.textContent = "Please enter your name and phone number."; err.classList.remove("hidden"); return; }
    if (form.type === "delivery" && !body.delivery_address) { err.textContent = "Please enter your delivery address."; err.classList.remove("hidden"); return; }
    try {
      const r = await busy($("#place"), () => api("/public/orders", { method: "POST", body }));
      state.cart = []; saveCart();
      sessionStorage.setItem("bj_last_order", JSON.stringify({ n: r.order_number, t: r.tracking_token, p: body.contact_phone }));
      if (form.method === "paystack") { try { const pay = await api(`/public/orders/${r.order_number}/paystack`, { method: "POST", params: { token: r.tracking_token } }); location.href = pay.authorization_url; return; } catch (e) { toast(e.message, "bad"); } }
      location.hash = `#/track/${r.order_number}?token=${r.tracking_token}&new=1`;
    } catch (e) { err.textContent = e.message; err.classList.remove("hidden"); err.scrollIntoView({ block: "center" }); }
  };
  mount(root, shell("", h`<h1 style="margin:18px 0 14px">Checkout</h1><div id="co"></div>`)); draw(); renderCart();
}

// ---------------- tracking ----------------
function timeline(o) {
  const steps = o.order_type === "delivery" ? STEPS : PICKUP_STEPS; const done = new Set((o.progress || []).map((p) => p.status));
  if (o.status === "cancelled") return h`<div class="err">This order was cancelled.${o.cancel_reason ? " Reason: " + o.cancel_reason : ""}</div>`;
  const idx = Math.max(...steps.map((s, i) => (done.has(s) ? i : -1)));
  const labels = { pending: "Received", confirmed: "Confirmed", paid: "Paid", in_production: "Baking", ready_for_dispatch: "Ready", ready_for_collection: "Ready to collect", out_for_delivery: "On the way", delivered: "Delivered", completed: "Completed" };
  return h`<div class="steps">${steps.map((s, i) => h`<div class="step ${i <= idx ? "done" : ""}">${labels[s]}</div>`)}</div>`;
}
export function orderCard(o) {
  const pay = o.payments?.[0];
  return h`<div class="card stack"><div class="row between"><div><div class="muted small">Order number</div><h2>${o.order_number}</h2></div><div class="row">${badge(o.status)} ${badge(o.payment_status)}</div></div>${timeline(o)}
    <dl class="kv"><dt>Placed</dt><dd>${fdt(o.created_at)}</dd><dt>${o.order_type === "delivery" ? "Delivery" : "Pickup"}</dt><dd>${o.delivery_address || "Collect from branch"} ${o.preferred_date ? "· " + fdate(o.preferred_date) + " " + (o.preferred_time || "") : ""}</dd>
    <dt>Payment</dt><dd>${pay ? title(pay.method) + " · " + title(pay.status) : "-"}</dd></dl>
    <div>${o.items.map((i) => h`<div class="sum small"><span>${i.quantity} × ${i.name}</span><span>${naira(i.line_total_kobo)}</span></div>`)}<div class="sum"><span>Delivery</span><span>${naira(o.delivery_fee_kobo)}</span></div><div class="sum total"><span>Total</span><span>${naira(o.total_kobo)}</span></div>
    ${o.paid_kobo ? h`<div class="sum small"><span>Paid</span><span>${naira(o.paid_kobo)}</span></div>` : ""}</div></div>`;
}
export async function track(root, num_, qs) {
  const last = JSON.parse(sessionStorage.getItem("bj_last_order") || "null");
  const show = async (number, phone, token) => {
    const box = $("#track-result"); mount(box, loading());
    try {
      const o = await api("/public/track", { params: { number, phone, token } });
      const bank = state.config; const needsProof = o.payments.find((p) => p.method === "bank_transfer" && ["pending", "rejected"].includes(p.status));
      mount(box, h`${qs.get("new") ? h`<div class="card" style="background:var(--green-50);border-color:#bfe4d1;margin-bottom:14px"><h3 style="margin:0">🎉 Thank you! Your order has been placed.</h3><p style="margin:6px 0 0">Keep your order number <strong>${o.order_number}</strong> to track it any time.</p></div>` : ""}
        ${needsProof ? h`<div class="card" style="margin-bottom:14px;border-color:var(--orange)"><h3>Pay by bank transfer</h3><p>Transfer <strong>${naira(needsProof.amount_kobo)}</strong> to:</p><dl class="kv"><dt>Bank</dt><dd>${bank.bank_name || "Not configured - please call us"}</dd><dt>Account number</dt><dd><strong>${bank.bank_account_number || "-"}</strong></dd><dt>Account name</dt><dd>${bank.bank_account_name || "-"}</dd><dt>Reference</dt><dd>${o.order_number}</dd></dl>
          <p class="muted small">After paying, enter your transfer reference below. Our team will <strong>verify</strong> it before confirming your order - submitting a reference does not mark the order as paid.</p><div class="row"><input class="input grow" id="proof-ref" placeholder="Bank transfer reference / session ID"><button class="btn primary" id="proof-btn">Submit reference</button></div></div>` : ""}
        ${orderCard(o)}`);
      const pb = $("#proof-btn"); if (pb) pb.onclick = async () => { const ref = $("#proof-ref").value.trim(); if (ref.length < 3) return toast("Enter your transfer reference", "bad"); try { const r = await busy(pb, () => api(`/public/orders/${o.order_number}/payment-proof`, { method: "POST", params: { token, phone }, body: { transfer_reference: ref } })); toast(r.message, "ok"); show(number, phone, token); } catch (e) { toast(e.message, "bad"); } };
    } catch (e) { mount(box, errorBox(e)); }
  };
  mount(root, shell("track", h`<div style="max-width:720px;margin:20px auto" class="stack"><h1>Track your order</h1><form class="card row" id="track-form" style="align-items:flex-end"><label class="f grow">Order number<input id="t-num" value="${num_ || last?.n || ""}" placeholder="BJ-20261114-0001"></label>
    <label class="f grow">Phone used on the order<input id="t-phone" type="tel" value="${last?.p || state.user?.phone || ""}"></label><button class="btn primary">Track</button></form><div id="track-result"></div></div>`));
  $("#track-form").onsubmit = (e) => { e.preventDefault(); show($("#t-num").value.trim(), $("#t-phone").value.trim(), ""); };
  const token = qs.get("token") || (last && last.n === num_ ? last.t : "");
  if (num_ && (token || state.user)) show(num_, last?.p || "", token); else if (num_ && last?.n === num_) show(num_, last.p, last.t);
  renderCart();
}

// ---------------- auth + account ----------------
export function authScreen(root, mode, extra = {}) {
  const art = h`<div class="auth-art"><img src="/assets/bonjour-logo.png" alt="Bonjour Bakery"><p>${mode === "staff" ? "Bakery management system. Sign in with your staff account." : "Fresh bread, baked daily. Sign in to track orders and reorder your favourites."}</p></div>`;
  const forms = {
    login: { t: "Welcome back", f: [["email", "Email", "email"], ["password", "Password", "password"]], b: "Sign in" },
    staff: { t: "Staff sign in", f: [["email", "Work email", "email"], ["password", "Password", "password"]], b: "Sign in" },
    register: { t: "Create your account", f: [["name", "Full name", "text"], ["email", "Email", "email"], ["phone", "Phone number", "tel"], ["password", "Password (min 8, letters & numbers)", "password"]], b: "Create account" },
    forgot: { t: "Reset your password", f: [["email", "Email", "email"]], b: "Send reset link" },
    setup: { t: "First-time admin setup", f: [["name", "Your full name", "text"], ["email", "Admin email", "email"], ["password", "Password (min 8, letters & numbers)", "password"], ["setup_key", "Setup key", "password"]], b: "Create admin account" },
    reset: { t: "Choose a new password", f: [["new_password", "New password", "password"]], b: "Update password" },
  }[mode];
  mount(root, h`<div class="auth">${art}<div class="auth-form"><form class="auth-card" id="auth-form" novalidate><div><a href="#/" class="small">← Back to the bakery</a></div><h1 style="margin-top:12px">${forms.t}</h1>
    <div class="stack"><div class="err hidden" id="auth-err"></div><div class="ok hidden" id="auth-ok"></div>${forms.f.map(([n, l, t]) => h`<label class="f">${l}<input name="${n}" type="${t}" required autocomplete="${n === "setup_key" ? "off" : n === "password" ? (mode === "register" || mode === "setup" ? "new-password" : "current-password") : n === "email" ? "email" : "on"}"></label>`)}
    <button class="btn primary block" id="auth-btn">${forms.b}</button>
    ${mode === "login" ? h`<div class="row between small"><a href="#/forgot">Forgot password?</a><a href="#/register">Create account</a></div>` : mode === "staff" ? h`<div class="small"><a href="#/forgot">Forgot password?</a></div><div class="small hidden" id="setup-link">No admin account yet? <a href="#/setup">Create the first admin</a></div>` : mode === "register" ? h`<div class="small">Already registered? <a href="#/login">Sign in</a></div>` : h`<div class="small"><a href="#/login">Back to sign in</a></div>`}
    ${mode === "login" ? h`<div class="small muted">Staff member? <a href="#/staff">Staff sign in</a></div>` : ""}</div></form></div></div>`);
  if (mode === "staff") api("/auth/setup-status").then((s) => { if (s.needed) $("#setup-link")?.classList.remove("hidden"); }).catch(() => {});
  if (mode === "setup") api("/auth/setup-status").then((s) => { if (!s.needed) { $("#auth-err").textContent = "Setup is already complete. Please sign in."; $("#auth-err").classList.remove("hidden"); $("#auth-btn").disabled = true; } }).catch(() => {});
  $("#auth-form").onsubmit = async (e) => {
    e.preventDefault(); const err = $("#auth-err"), ok = $("#auth-ok"); err.classList.add("hidden"); ok.classList.add("hidden");
    const body = Object.fromEntries(new FormData(e.target).entries()); const btn = $("#auth-btn");
    try {
      if (mode === "forgot") { const r = await busy(btn, () => api("/auth/forgot-password", { method: "POST", body })); ok.textContent = r.message + (r.note ? " " + r.note : ""); ok.className = "badge green"; ok.style.padding = "10px"; if (r.dev_reset_token) { ok.innerHTML += `<br>Dev mode reset link: <a href="#/reset/${esc(r.dev_reset_token)}">open</a>`; } return; }
      if (mode === "reset") { await busy(btn, () => api("/auth/reset-password", { method: "POST", body: { token: extra.token, new_password: body.new_password } })); toast("Password updated. Please sign in.", "ok"); location.hash = "#/login"; return; }
      const r = await busy(btn, () => api(mode === "register" ? "/auth/register" : mode === "setup" ? "/auth/setup" : "/auth/login", { method: "POST", body }));
      state.user = r.user; events.dispatchEvent(new Event("signedin"));
      if (mode === "staff" && !r.user.is_staff) { await api("/auth/logout", { method: "POST" }); state.user = null; throw new Error("This is not a staff account. Use customer sign in."); }
      location.hash = r.user.is_staff ? "#/app" : (state.cart.length ? "#/checkout" : "#/account");
    } catch (er) { err.textContent = er.message; err.classList.remove("hidden"); }
  };
}

export async function account(root) {
  if (!state.user || state.user.is_staff) { location.hash = state.user ? "#/app" : "#/login"; return; }
  mount(root, shell("", loading()));
  let orders = [], notes = [];
  try { [orders, notes] = await Promise.all([api("/me/orders"), api("/me/notifications")]); } catch (e) { mount(root, shell("", errorBox(e))); return; }
  const u = state.user, c = u.customer || { addresses: [] };
  mount(root, shell("", h`<div class="row between" style="margin:18px 0"><div><h1>My account</h1><span class="muted">${u.full_name} · ${u.email}</span></div><button class="btn" id="logout">${icon("logout")} Sign out</button></div>
    <div class="two-col"><div class="stack"><div class="card flush"><div class="card-head"><h3 style="margin:0">Order history</h3></div>${orders.length ? orders.map((o) => h`<div class="cart-line" style="padding:14px 18px"><div><a href="#/track/${o.order_number}" class="strong">${o.order_number}</a><div class="muted small">${fdt(o.created_at)} · ${o.items.map((i) => i.quantity + "× " + i.name).join(", ")}</div><div class="row" style="margin-top:6px">${badge(o.status)} ${badge(o.payment_status)}</div></div>
        <div class="right"><div class="strong">${naira(o.total_kobo)}</div><button class="btn sm" data-reorder="${o.order_number}" style="margin-top:6px">${icon("refresh")} Reorder</button></div></div>`) : h`<div class="empty">No orders yet. <a href="#/">Order some bread!</a></div>`}</div></div>
      <div class="stack"><div class="card"><h3>Profile</h3><div class="stack"><label class="f">Name<input id="p-name" value="${u.full_name}"></label><label class="f">Phone<input id="p-phone" value="${u.phone}"></label><button class="btn primary" id="p-save">Save profile</button></div></div>
        <div class="card"><div class="row between"><h3 style="margin:0">Saved addresses</h3><button class="btn sm" id="addr-add">${icon("plus")} Add</button></div>${(c.addresses || []).map((a) => h`<div class="cart-line"><div><div class="strong">${a.label}${a.is_default ? " (default)" : ""}</div><div class="muted small">${a.address}</div></div><button class="btn ghost sm" data-deladdr="${a.id}" style="color:var(--red)">${icon("trash")}</button></div>`)}${!(c.addresses || []).length ? h`<p class="muted">No saved addresses.</p>` : ""}</div>
        <div class="card"><h3>Notifications</h3>${notes.length ? notes.slice(0, 8).map((n) => h`<div class="cart-line"><div><div class="strong small">${n.title}</div><div class="muted small">${n.body}</div></div><span class="muted small">${fdt(n.created_at)}</span></div>`) : h`<p class="muted">Nothing yet.</p>`}</div></div></div>`));
  $("#logout").onclick = async () => { await api("/auth/logout", { method: "POST" }); state.user = null; location.hash = "#/"; };
  $("#p-save").onclick = async (e) => { try { state.user = await busy(e.target, () => api("/auth/profile", { method: "PATCH", body: { name: $("#p-name").value, phone: $("#p-phone").value } })); toast("Profile saved", "ok"); } catch (er) { toast(er.message, "bad"); } };
  $("#addr-add").onclick = () => openForm({ title: "Add delivery address", fields: [{ name: "label", label: "Label", value: "Home" }, { name: "address", label: "Address", type: "textarea", required: true, span: true }, { name: "lga", label: "Area / LGA" }, { name: "is_default", label: "Make default", type: "checkbox" }],
    onSubmit: async (v, m) => { const r = await api("/auth/addresses", { method: "POST", body: v }); state.user.customer = r; m.close(); account(root); } });
  root.onclick = async (e) => {
    const ro = e.target.closest("[data-reorder]"), da = e.target.closest("[data-deladdr]");
    if (ro) { try { const r = await api(`/me/orders/${ro.dataset.reorder}/reorder`, { method: "POST" }); const prods = await api("/public/products", { params: { branch_id: r.branch_id } }); state.cart = []; r.items.forEach((l) => { const p = prods.find((x) => x.id === l.product_id); if (p) { state.cartBranch = r.branch_id; cartAdd(p, l.quantity); } }); saveCart(); if (r.unavailable.length) toast("Unavailable now: " + r.unavailable.join(", "), "bad"); location.hash = "#/checkout"; } catch (er) { toast(er.message, "bad"); } }
    if (da) { await api(`/auth/addresses/${da.dataset.deladdr}`, { method: "DELETE" }); const me = await api("/auth/me"); state.user = me.user; account(root); }
  };
}
