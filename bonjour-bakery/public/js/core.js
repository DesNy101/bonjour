// Core helpers: safe templating, API client, UI primitives (modal, toast, forms, tables, pager).
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
export const raw = (s) => new Raw(s);
const part = (v) => (v instanceof Raw ? v.s : Array.isArray(v) ? v.map(part).join("") : v === false || v == null ? "" : esc(v));
export function h(strings, ...vals) { let out = ""; strings.forEach((s, i) => { out += s; if (i < vals.length) out += part(vals[i]); }); return new Raw(out); }
export const $ = (sel, el = document) => el.querySelector(sel);
export const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
export const mount = (el, content) => { el.innerHTML = content instanceof Raw ? content.s : String(content); return el; };

// ---------- formatting ----------
export const naira = (kobo) => "₦" + (Number(kobo || 0) / 100).toLocaleString("en-NG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const nairaShort = (kobo) => { const n = Number(kobo || 0) / 100; const a = Math.abs(n); return "₦" + (a >= 1e9 ? (n / 1e9).toFixed(1) + "B" : a >= 1e6 ? (n / 1e6).toFixed(1) + "M" : a >= 1e3 ? (n / 1e3).toFixed(0) + "k" : n.toFixed(0)); };
export const num = (n) => Number(n || 0).toLocaleString("en-NG", { maximumFractionDigits: 3 });
export const fdate = (s) => (s ? new Date(/^\d{4}-\d{2}-\d{2}$/.test(s) ? s + "T00:00:00" : s).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "-");
export const fdt = (s) => (s ? new Date(s).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "-");
export const title = (s) => String(s || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
export const todayISO = () => new Date().toLocaleDateString("en-CA", { timeZone: "Africa/Lagos" });
export const daysAgoISO = (n) => new Date(Date.now() - n * 864e5).toLocaleDateString("en-CA", { timeZone: "Africa/Lagos" });
export const toLocalInput = (d) => { const z = new Date(d.getTime() - d.getTimezoneOffset() * 6e4); return z.toISOString().slice(0, 16); };
export const debounce = (fn, ms = 300) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

const GOOD = ["completed", "delivered", "paid", "verified", "approved", "received", "available", "done", "reconciled", "resolved"];
const BAD = ["cancelled", "rejected", "failed", "unpaid", "expired", "maintenance", "removed"];
const WARN = ["pending", "awaiting_payment", "awaiting_verification", "pending_verification", "pending_approval", "submitted", "draft", "assigned", "partially_paid", "part_paid", "planned", "needs_review", "open", "queued_for_production"];
export const badge = (s, label) => { const k = String(s); const c = GOOD.includes(k) ? "green" : BAD.includes(k) ? "red" : WARN.includes(k) ? "amber" : ["in_progress", "in_production", "out_for_delivery", "active", "on_delivery", "in_use", "accepted", "confirmed"].includes(k) ? "blue" : ""; return h`<span class="badge ${c}">${label || title(k)}</span>`; };

// ---------- icons ----------
const P = {
  home: "M3 11l9-8 9 8M5 10v10h14V10", grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z", branch: "M12 21s-7-6.2-7-11a7 7 0 0114 0c0 4.8-7 11-7 11zM12 12a2 2 0 100-4 2 2 0 000 4",
  cart: "M3 4h2l2.4 11h10.2L20 7H6M9 20a1 1 0 100-2 1 1 0 000 2M17 20a1 1 0 100-2 1 1 0 000 2", users: "M16 20v-1a4 4 0 00-4-4H7a4 4 0 00-4 4v1M9.5 11a3.5 3.5 0 100-7 3.5 3.5 0 000 7M21 20v-1a4 4 0 00-3-3.9M16 4.1a3.5 3.5 0 010 6.8",
  bread: "M4 10a4 4 0 014-4h8a4 4 0 014 4v1a2 2 0 01-1 1.7V19a1 1 0 01-1 1H6a1 1 0 01-1-1v-6.3A2 2 0 014 11z", flame: "M12 3c1 3 5 5 5 10a5 5 0 01-10 0c0-2 1-3 2-4 0 2 1 3 2 3 0-3-1-6 1-9z",
  box: "M21 8l-9-5-9 5 9 5 9-5zM3 8v8l9 5 9-5V8M12 13v8", truck: "M2 6h11v10H2zM13 9h5l3 3v4h-8M6 19a2 2 0 100-4 2 2 0 000 4M17 19a2 2 0 100-4 2 2 0 000 4",
  coin: "M12 21a9 9 0 100-18 9 9 0 000 18M9.5 9.5C9.5 8.4 10.6 8 12 8s2.5.5 2.5 1.5S13.4 11 12 11s-2.5.6-2.5 1.5S10.6 14 12 14s2.5-.4 2.5-1.5M12 6.5V8M12 14v1.5",
  chart: "M4 20V10M10 20V4M16 20v-7M22 20H2", bell: "M18 16v-5a6 6 0 10-12 0v5l-2 2h16zM10 21h4", log: "M8 4h8l4 4v12H4V4zM8 12h8M8 16h8", gear: "M12 15a3 3 0 100-6 3 3 0 000 6M19 12a7 7 0 00-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 00-2-1.2L14 3h-4l-.5 2.6a7 7 0 00-2 1.2l-2.4-1-2 3.4 2 1.6A7 7 0 005 12c0 .4 0 .8.1 1.2l-2 1.6 2 3.4 2.4-1a7 7 0 002 1.2L10 21h4l.5-2.6a7 7 0 002-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2z",
  plus: "M12 5v14M5 12h14", x: "M6 6l12 12M18 6L6 18", search: "M11 18a7 7 0 100-14 7 7 0 000 14M21 21l-4.3-4.3", menu: "M4 6h16M4 12h16M4 18h16", check: "M5 13l4 4L19 7", user: "M20 21a8 8 0 10-16 0M12 12a4 4 0 100-8 4 4 0 000 8",
  logout: "M9 21H5V3h4M16 17l5-5-5-5M21 12H9", clip: "M9 4h6l1 2h3v14H5V6h3zM9 12h6M9 16h4", wallet: "M3 7h16a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2zM3 7l2-3h12M16 14h2", receipt: "M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6",
  doc: "M6 3h9l4 4v14H6zM14 3v5h5M9 13h6M9 17h6", edit: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4", trash: "M5 7h14M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3", phone: "M5 4h4l2 5-2.5 1.5a11 11 0 005 5L15 13l5 2v4a2 2 0 01-2 2A16 16 0 013 6a2 2 0 012-2",
  pin: "M12 21s-7-6.2-7-11a7 7 0 0114 0c0 4.8-7 11-7 11zM12 12a2 2 0 100-4 2 2 0 000 4", clock: "M12 21a9 9 0 100-18 9 9 0 000 18M12 7v5l3 2", download: "M12 4v12M7 11l5 5 5-5M5 20h14", print: "M7 9V3h10v6M6 18H4v-7h16v7h-2M7 14h10v7H7z",
  star: "M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z", tag: "M3 12V4h8l10 10-8 8zM7.5 8.5h.01", shop: "M4 9l1-5h14l1 5M4 9a3 3 0 006 0 3 3 0 006 0 3 3 0 004 0M5 12v8h14v-8", refresh: "M20 11a8 8 0 10-2.3 6M20 5v6h-6",
  key: "M15 8a4 4 0 11-3 6.6L4 22v-3l2-2h2v-2l3.4-3.4A4 4 0 0115 8z", shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z", ban: "M12 21a9 9 0 100-18 9 9 0 000 18M5.7 5.7l12.6 12.6", info: "M12 21a9 9 0 100-18 9 9 0 000 18M12 11v5M12 8h.01",
};
export const icon = (n, cls = "") => raw(`<svg class="icon ${cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="${P[n] || P.info}"/></svg>`);

// ---------- API ----------
const csrfCookie = () => (document.cookie.split("; ").find((c) => c.startsWith("bj_csrf=")) || "").split("=")[1] || "";
export const events = new EventTarget();
export async function api(path, { method = "GET", body, params, blob, form } = {}) {
  let url = "/api" + path;
  if (params) { const q = new URLSearchParams(); for (const [k, v] of Object.entries(params)) if (v !== "" && v != null && v !== false) q.set(k, v); const s = q.toString(); if (s) url += (url.includes("?") ? "&" : "?") + s; }
  const headers = {};
  if (method !== "GET") headers["X-CSRF-Token"] = csrfCookie();
  let payload;
  if (form) payload = form; else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  let res;
  try { res = await fetch(url, { method, headers, body: payload, credentials: "same-origin" }); }
  catch (e) { throw new Error(navigator.onLine ? "Could not reach the server. Please try again." : "You are offline. This action needs an internet connection and was NOT submitted."); }
  if (blob) { if (!res.ok) throw new Error("Could not generate the file."); return res.blob(); }
  let data = null;
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) {
    let msg = data && data.detail;
    if (Array.isArray(msg)) msg = msg.map((e) => `${(e.loc || []).slice(1).join(".")}: ${String(e.msg).replace(/^Value error, /, "")}`).join("; ");
    if (res.status === 401 && !path.startsWith("/auth/login")) events.dispatchEvent(new Event("unauthorized"));
    const err = new Error(msg || `Request failed (${res.status})`); err.status = res.status; throw err;
  }
  return data;
}

// ---------- toast / busy ----------
export function toast(msg, kind = "") {
  let box = $(".toasts"); if (!box) { box = document.createElement("div"); box.className = "toasts"; document.body.appendChild(box); }
  const t = document.createElement("div"); t.className = "toast " + kind; t.textContent = msg; t.setAttribute("role", "status"); box.appendChild(t);
  setTimeout(() => t.remove(), kind === "bad" ? 6000 : 3200);
}
export async function busy(btn, fn) {
  if (btn) { btn.disabled = true; btn.dataset.t = btn.innerHTML; btn.innerHTML = '<span class="spinner"></span>'; }
  try { return await fn(); } finally { if (btn) { btn.disabled = false; btn.innerHTML = btn.dataset.t; } }
}
export const loading = () => h`<div class="loading"><div class="spinner"></div><div>Loading…</div></div>`;
export const errorBox = (e) => h`<div class="err">${e.message || e}</div>`;

// ---------- modal ----------
export function modal({ title: t, body, footer, wide = false, onClose }) {
  const ov = document.createElement("div"); ov.className = "overlay";
  ov.innerHTML = `<div class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true"><div class="modal-h"><h3>${esc(t)}</h3><button class="btn ghost sm" data-close aria-label="Close">${icon("x").s}</button></div><div class="modal-b"></div>${footer ? '<div class="modal-f"></div>' : ""}</div>`;
  const b = $(".modal-b", ov); mount(b, body); if (footer) mount($(".modal-f", ov), footer);
  const close = () => { ov.remove(); document.removeEventListener("keydown", esc_); onClose && onClose(); };
  const esc_ = (e) => { if (e.key === "Escape") close(); };
  ov.addEventListener("mousedown", (e) => { if (e.target === ov) close(); });
  ov.addEventListener("click", (e) => { if (e.target.closest("[data-close]")) close(); });
  document.addEventListener("keydown", esc_); document.body.appendChild(ov);
  const first = $("input:not([type=hidden]),select,textarea", ov); first && first.focus();
  return { el: ov, body: b, close };
}
export function confirmDialog(message, { okLabel = "Confirm", danger = false, title: t = "Please confirm" } = {}) {
  return new Promise((resolve) => {
    const m = modal({ title: t, body: h`<p style="margin:0">${message}</p>`, footer: h`<button class="btn" data-no>Cancel</button><button class="btn ${danger ? "danger" : "primary"}" data-yes>${okLabel}</button>`, onClose: () => resolve(false) });
    $("[data-no]", m.el).onclick = () => { m.close(); resolve(false); };
    $("[data-yes]", m.el).onclick = () => { m.el.remove(); resolve(true); };
  });
}

// ---------- forms ----------
// field: {name,label,type,options:[{value,label}],required,hint,value,span,min,step,placeholder,html}
export function fieldHTML(f, v) {
  const val = v ?? f.value ?? "";
  const req = f.required ? "required" : "";
  const cls = f.span ? "span2" : "";
  if (f.html) return h`<div class="${cls}">${raw(f.html)}</div>`;
  if (f.type === "checkbox") return h`<label class="f check ${cls}"><input type="checkbox" name="${f.name}" ${val ? raw("checked") : ""}> ${f.label}</label>`;
  let ctl;
  if (f.type === "select") ctl = h`<select name="${f.name}" ${raw(req)}>${(f.options || []).map((o) => h`<option value="${o.value}" ${String(o.value) === String(val) ? raw("selected") : ""}>${o.label}</option>`)}</select>`;
  else if (f.type === "textarea") ctl = h`<textarea name="${f.name}" ${raw(req)} placeholder="${f.placeholder || ""}">${val}</textarea>`;
  else if (f.type === "money") ctl = h`<input name="${f.name}" type="number" step="0.01" min="0" inputmode="decimal" ${raw(req)} value="${val === "" ? "" : (Number(val) / 100).toFixed(2)}" placeholder="0.00">`;
  else ctl = h`<input name="${f.name}" type="${f.type || "text"}" ${raw(req)} value="${val}" ${f.min != null ? raw(`min="${f.min}"`) : ""} ${f.step ? raw(`step="${f.step}"`) : ""} ${f.placeholder ? raw(`placeholder="${esc(f.placeholder)}"`) : ""} ${f.type === "password" ? raw('autocomplete="new-password"') : ""} ${f.maxlength ? raw(`maxlength="${f.maxlength}"`) : ""}>`;
  return h`<label class="f ${cls}">${f.label}${f.required ? " *" : ""}${ctl}${f.hint ? h`<span class="hint">${f.hint}</span>` : ""}</label>`;
}
export const fieldsHTML = (fields, values = {}) => h`<div class="grid2">${fields.map((f) => fieldHTML(f, values[f.name]))}</div>`;
export function readFields(root, fields) {
  const out = {};
  for (const f of fields) {
    if (f.html) continue;
    const el = root.querySelector(`[name="${f.name}"]`); if (!el) continue;
    if (f.type === "checkbox") out[f.name] = el.checked;
    else if (f.type === "money") out[f.name] = el.value === "" ? null : Math.round(parseFloat(el.value) * 100);
    else if (f.type === "number") out[f.name] = el.value === "" ? null : Number(el.value);
    else if (f.type === "datetime-local") out[f.name] = el.value ? new Date(el.value).toISOString() : null;
    else if (f.type === "select" && f.numeric) out[f.name] = el.value === "" ? null : Number(el.value);
    else out[f.name] = el.value === "" && (f.nullable || f.type === "date") ? null : el.value;
  }
  return out;
}
export function openForm({ title: t, fields, values = {}, submitLabel = "Save", onSubmit, wide = false, intro = "", extra }) {
  const m = modal({ title: t, wide, body: h`<form novalidate><div class="err hidden" data-err></div>${intro ? h`<p class="muted" style="margin-top:0">${intro}</p>` : ""}${fieldsHTML(fields, values)}${extra ? raw(extra) : ""}</form>`,
    footer: h`<button class="btn" data-close type="button">Cancel</button><button class="btn primary" data-save type="button">${submitLabel}</button>` });
  const form = $("form", m.el), errBox = $("[data-err]", m.el), save = $("[data-save]", m.el);
  const submit = async () => {
    errBox.classList.add("hidden");
    for (const f of fields) { if (f.required && !f.html) { const el = form.querySelector(`[name="${f.name}"]`); if (el && !String(el.value).trim()) { errBox.textContent = `${f.label} is required.`; errBox.classList.remove("hidden"); el.focus(); return; } } }
    try { await busy(save, () => onSubmit(readFields(form, fields), m)); } catch (e) { errBox.textContent = e.message; errBox.classList.remove("hidden"); }
  };
  save.onclick = submit; form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });
  return m;
}

// ---------- tables ----------
export function table(cols, rows, { empty = "Nothing to show yet.", rowAttr, cards = true } = {}) {
  if (!rows || !rows.length) return h`<div class="empty">${empty}</div>`;
  return h`<div class="tbl-wrap"><table class="tbl ${cards ? "cards" : ""}"><thead><tr>${cols.map((c) => h`<th class="${c.align || ""}">${c.label}</th>`)}</tr></thead><tbody>${rows.map((r, i) => h`<tr ${raw(rowAttr ? rowAttr(r, i) : "")}>${cols.map((c) => h`<td class="${c.align || ""} ${c.nolabel ? "nolabel" : ""}" data-l="${c.label}">${c.render ? c.render(r, i) : r[c.key]}</td>`)}</tr>`)}</tbody></table></div>`;
}
export function pager(total, page, size) {
  const pages = Math.max(1, Math.ceil(total / size));
  return h`<div class="pager"><span>${total} record${total === 1 ? "" : "s"}</span><span class="row"><button class="btn sm" data-page="${page - 1}" ${page <= 1 ? raw("disabled") : ""}>Prev</button><span>Page ${page} of ${pages}</span><button class="btn sm" data-page="${page + 1}" ${page >= pages ? raw("disabled") : ""}>Next</button></span></div>`;
}
export const opts = (list, { all, v = "id", l = "name" } = {}) => [...(all !== undefined ? [{ value: "", label: all }] : []), ...list.map((x) => ({ value: x[v], label: x[l] }))];
export async function download(path, params, filename) {
  const blob = await api(path, { params, blob: true }); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = filename; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}
export async function openPdf(path, params) { const blob = await api(path, { params, blob: true }); window.open(URL.createObjectURL(blob), "_blank"); }

// ---------- state ----------
export const state = { user: null, config: null, branches: [], cart: JSON.parse(localStorage.getItem("bj_cart") || "[]"), cartBranch: Number(localStorage.getItem("bj_branch") || 0) || null };
export const saveCart = () => { localStorage.setItem("bj_cart", JSON.stringify(state.cart)); if (state.cartBranch) localStorage.setItem("bj_branch", state.cartBranch); };
export const can = (p) => !!state.user && (state.user.permissions || []).includes(p);
export const logoTile = (hgt = 46) => raw(`<span class="brand-tile" style="height:${hgt}px"><img src="/assets/bonjour-logo-sm.png" alt="Bonjour Bakery" width="${Math.round(hgt * 1.3)}" height="${hgt}"></span>`);
