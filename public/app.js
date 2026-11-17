// Application entry: session check, hash router, service worker, offline banner.
import { api, mount, $, state, events, loading, h } from "./js/core.js";
import * as Store from "./js/store.js";

const root = () => $("#root");
const STAFF_IDS = new Set(["overview", "branches", "orders", "customers", "payments", "products", "production", "inventory", "suppliers", "purchasing", "dispatch",
  "drivers", "vehicles", "finance", "expenses", "reports", "staff", "tasks", "audit", "settings", "workspace", "notifications", "app"]);

function parse() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const parts = path.split("/").filter(Boolean);
  return { name: parts[0] || "", arg: parts[1], qs: new URLSearchParams(query) };
}

let rendering = 0;
async function route() {
  const id = ++rendering;
  const r = parse();
  const el = root();
  window.scrollTo(0, 0);
  const staffUser = state.user && state.user.is_staff;
  try {
    // Staff-console routes. "#/staff" is the sign-in page unless already signed in as staff.
    if (staffUser && STAFF_IDS.has(r.name)) {
      if (state.user.role === "driver") { const D = await import("./js/driver.js"); return D.render(el); }
      const S = await import("./js/staff.js");
      return S.render(el, r.name === "app" ? S.firstPage() : r.name);
    }
    if (staffUser && state.user.role === "driver" && ["", "login", "staff"].includes(r.name)) { location.hash = "#/app"; return; }
    switch (r.name) {
      case "": return Store.home(el);
      case "contact": return Store.contact(el);
      case "checkout": return Store.checkout(el);
      case "track": return Store.track(el, r.arg || "", r.qs);
      case "account": return Store.account(el);
      case "login": return Store.authScreen(el, "login");
      case "register": return Store.authScreen(el, "register");
      case "forgot": return Store.authScreen(el, "forgot");
      case "reset": return Store.authScreen(el, "reset", { token: r.qs.get("token") || "" });
      case "staff": return Store.authScreen(el, "staff");
      default:
        if (STAFF_IDS.has(r.name)) { location.hash = "#/staff"; return; }
        return Store.home(el);
    }
  } catch (e) {
    if (id === rendering) mount(el, h`<div class="sf-wrap" style="padding:40px 0"><div class="err">${e.message || e}</div><p><a href="#/">Back to home</a></p></div>`);
  }
}

async function boot() {
  mount(root(), loading());
  const [cfg, br, me] = await Promise.allSettled([api("/public/config"), api("/public/branches"), api("/auth/me")]);
  if (cfg.status === "fulfilled") state.config = cfg.value;
  if (br.status === "fulfilled") state.branches = Array.isArray(br.value) ? br.value : br.value.items || [];
  if (me.status === "fulfilled") state.user = me.value.user || me.value;
  if (cfg.status === "rejected" && br.status === "rejected") {
    mount(root(), h`<div class="sf-wrap" style="padding:60px 0;text-align:center"><h2>We can't reach the bakery right now</h2><p class="muted">Please check your connection and try again.</p><button class="btn primary" onclick="location.reload()">Retry</button></div>`);
    return;
  }
  window.addEventListener("hashchange", route);
  events.addEventListener("signedin", async () => { try { const m = await api("/auth/me"); state.user = m.user || m; } catch { /* keep */ } });
  events.addEventListener("unauthorized", () => {
    if (!state.user) return;
    state.user = null; location.hash = "#/staff"; route();
  });
  await route();
}

function connectivity() {
  const bar = $("#offline");
  const upd = () => bar.classList.toggle("hidden", navigator.onLine);
  addEventListener("online", upd); addEventListener("offline", upd); upd();
}

connectivity();
if ("serviceWorker" in navigator) addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
boot();
