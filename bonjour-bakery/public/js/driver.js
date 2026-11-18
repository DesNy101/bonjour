// Mobile-first driver app. Drivers only ever receive their own assignments from the API.
import { api, h, raw, mount, $, $$, icon, logoTile, state, loading, errorBox, badge, naira, title, toast, busy, modal, openForm, confirmDialog, fdt } from "./core.js";

export async function render(root) {
  const draw = async () => {
    let me, data;
    try { [me, data] = await Promise.all([api("/driver/me"), api("/driver/deliveries", { params: { scope: "today" } })]); } catch (e) { mount(root, h`<div class="drv"><div class="drv-top">${logoTile(40)}</div><div class="drv-card">${errorBox(e)}</div></div>`); return; }
    const s = data.summary;
    mount(root, h`<div class="drv"><div class="drv-top">${logoTile(40)}<div class="grow"><div class="strong">${state.user.full_name}</div><div class="small" style="color:#bbb">${me.vehicle ? "Vehicle " + me.vehicle.plate_number : "No vehicle assigned"}${me.current_run ? " · " + me.current_run : ""}</div></div><button class="btn sm" id="out">${icon("logout")}</button></div>
      <div class="drv-sum"><div class="stat"><div class="l">Pending</div><div class="v">${s.pending}</div></div><div class="stat"><div class="l">Delivered</div><div class="v" style="color:var(--green)">${s.completed}</div></div><div class="stat"><div class="l">Failed</div><div class="v" style="color:var(--red)">${s.failed}</div></div></div>
      <div class="row" style="padding:0 12px"><button class="btn sm" id="refresh">${icon("refresh")} Refresh</button>${me.vehicle ? h`<button class="btn sm" id="vissue" data-v="${me.vehicle.id}">${icon("ban")} Report vehicle problem</button>` : ""}</div>
      ${data.items.length ? data.items.map((d) => card(d)) : h`<div class="drv-card empty">No deliveries assigned to you today.</div>`}</div>`);
    $("#out").onclick = async () => { await api("/auth/logout", { method: "POST" }); location.reload(); };
    $("#refresh").onclick = draw;
    const vi = $("#vissue"); if (vi) vi.onclick = () => openForm({ title: "Report vehicle problem", fields: [{ name: "description", label: "What is wrong?", type: "textarea", required: true, span: true }], submitLabel: "Send report", onSubmit: async (v, m) => { await api("/driver/vehicle-issues", { method: "POST", body: { vehicle_id: Number(vi.dataset.v), ...v } }); toast("Reported to the vehicle manager", "ok"); m.close(); } });
  };
  const card = (d) => h`<div class="drv-card" data-a="${d.id}"><div class="row between"><h3>${d.customer_name}</h3>${badge(d.status)}</div><div class="muted small">${d.order_number} · ${d.units} units · ${d.run}</div>
    <p style="margin:10px 0 4px">${icon("pin")} ${d.address}${d.lga ? ", " + d.lga : ""}</p>${d.instructions ? h`<p class="muted small" style="margin:0">Note: ${d.instructions}</p>` : ""}<p class="small" style="margin:6px 0">${d.items.map((i) => i.quantity + "× " + i.name).join(", ")}</p>
    ${d.balance_kobo > 0 ? h`<div class="badge amber">Collect ${naira(d.balance_kobo)} (${title(d.payment_method)})</div>` : h`<div class="badge green">Paid</div>`}
    ${d.failure_reason ? h`<p class="small" style="color:var(--red)">Failed: ${d.failure_reason}</p>` : ""}
    <div class="drv-actions"><a class="btn" href="tel:${d.customer_phone}">${icon("phone")} Call</a><a class="btn" target="_blank" rel="noopener" href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(d.address + " " + (d.lga || "") + " Nigeria")}">${icon("pin")} Map</a>
    ${d.status === "assigned" ? h`<button class="btn primary" style="grid-column:span 2" data-start="${d.id}">Start delivery</button>` : ""}
    ${d.status === "out_for_delivery" ? h`<button class="btn success" data-done="${d.id}" data-bal="${d.balance_kobo}">Delivered</button><button class="btn danger" data-fail="${d.id}">Failed</button>` : ""}</div></div>`;
  root.onclick = async (e) => {
    const st = e.target.closest("[data-start]"), dn = e.target.closest("[data-done]"), fl = e.target.closest("[data-fail]");
    if (st) { try { await busy(st, () => api(`/driver/deliveries/${st.dataset.start}/start`, { method: "POST" })); toast("Delivery started", "ok"); draw(); } catch (er) { toast(er.message, "bad"); } }
    if (fl) openForm({ title: "Delivery failed", fields: [{ name: "reason", label: "Reason", type: "select", options: ["Customer unreachable", "Customer refused", "Wrong or incomplete address", "Customer not at location", "Vehicle problem", "Other"].map((x) => ({ value: x, label: x })), required: true }, { name: "notes", label: "Notes", type: "textarea", span: true }], submitLabel: "Submit", onSubmit: async (v, m) => { await api(`/driver/deliveries/${fl.dataset.fail}/fail`, { method: "POST", body: v }); m.close(); toast("Recorded", "ok"); draw(); } });
    if (dn) {
      const id = dn.dataset.done, bal = Number(dn.dataset.bal);
      const m = openForm({ title: "Confirm delivery", fields: [{ name: "received_by_name", label: "Received by (customer name)", required: true }, { name: "customer_confirmed", label: "Customer confirmed receipt", type: "checkbox", value: true }, ...(bal > 0 ? [{ name: "cash_collected_kobo", label: "Cash collected (₦)", type: "money", value: bal, hint: `Outstanding ${naira(bal)}. Finance will verify the cash. Enter 0 if none collected.` }] : []),
        { name: "notes", label: "Delivery notes", type: "textarea", span: true }, { html: '<label class="f">Photo of delivery (optional)<input type="file" accept="image/*" capture="environment" id="d-photo"></label>' }, { html: '<label class="f check"><input type="checkbox" id="d-gps"> Attach my GPS location</label>' }],
        submitLabel: "Mark delivered", onSubmit: async (v, mm) => {
          let lat = null, lng = null;
          if ($("#d-gps").checked && navigator.geolocation) { try { const p = await new Promise((res, rej) => navigator.geolocation.getCurrentPosition(res, rej, { timeout: 8000 })); lat = p.coords.latitude; lng = p.coords.longitude; } catch { toast("Location unavailable - continuing without it"); } }
          await api(`/driver/deliveries/${id}/complete`, { method: "POST", body: { received_by_name: v.received_by_name, customer_confirmed: v.customer_confirmed, notes: v.notes, cash_collected_kobo: v.cash_collected_kobo || 0, latitude: lat, longitude: lng } });
          const f = $("#d-photo").files[0]; if (f) { const fd = new FormData(); fd.append("file", f); try { await api(`/driver/deliveries/${id}/photo`, { method: "POST", form: fd }); } catch (er) { toast("Delivered, but photo failed: " + er.message, "bad"); } }
          mm.close(); toast("Delivery recorded", "ok"); draw();
        } });
    }
  };
  mount(root, loading()); draw();
}
