// Small dependency-free SVG charts (work offline, themed to the brand).
import { esc, raw, nairaShort } from "./core.js";
export const COLORS = ["#ff6600", "#232120", "#f2a65a", "#8a847e", "#1f8a5b", "#2b6cb0", "#d6372f", "#b7791f", "#6b46c1", "#0e8f9c"];
const W = 640, H = 260, PL = 52, PR = 14, PT = 14, PB = 34;
const niceMax = (m) => { if (m <= 0) return 1; const p = Math.pow(10, Math.floor(Math.log10(m))); const n = m / p; return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p; };
const empty = (msg = "No data for this period") => raw(`<div class="empty">${esc(msg)}</div>`);

function axes(max, fmt, ticks = 4) {
  let s = "";
  for (let i = 0; i <= ticks; i++) { const v = (max / ticks) * i; const y = H - PB - ((H - PT - PB) * i) / ticks; s += `<line x1="${PL}" x2="${W - PR}" y1="${y}" y2="${y}" stroke="#ece8e4"/><text x="${PL - 8}" y="${y + 4}" text-anchor="end" font-size="11" fill="#8a847e">${esc(fmt(v))}</text>`; }
  return s;
}
const skip = (n) => Math.max(1, Math.ceil(n / 8));

export function lineChart(series, labels, { fmt = nairaShort, colors = COLORS, area = true } = {}) {
  const all = series.flatMap((s) => s.data); if (!labels.length || !all.some((v) => v > 0)) return empty();
  const max = niceMax(Math.max(...all)); const n = labels.length, iw = W - PL - PR, ih = H - PT - PB;
  const x = (i) => PL + (n === 1 ? iw / 2 : (iw * i) / (n - 1)), y = (v) => H - PB - (ih * v) / max;
  let s = axes(max, fmt);
  series.forEach((se, si) => {
    const pts = se.data.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
    const c = colors[si % colors.length];
    if (area && si === 0) s += `<path d="M${x(0)},${H - PB} L${pts.join(" L")} L${x(n - 1)},${H - PB}Z" fill="${c}" opacity=".10"/>`;
    s += `<polyline fill="none" stroke="${c}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round" points="${pts.join(" ")}"/>`;
    if (n <= 31) se.data.forEach((v, i) => { s += `<circle cx="${x(i)}" cy="${y(v)}" r="3" fill="#fff" stroke="${c}" stroke-width="2"><title>${esc(labels[i])}: ${esc(fmt(v))}</title></circle>`; });
  });
  labels.forEach((l, i) => { if (i % skip(n) === 0) s += `<text x="${x(i)}" y="${H - 12}" text-anchor="middle" font-size="11" fill="#8a847e">${esc(l)}</text>`; });
  const leg = series.length > 1 ? `<div class="legend">${series.map((se, i) => `<span><i style="background:${colors[i % colors.length]}"></i>${esc(se.name)}</span>`).join("")}</div>` : "";
  return raw(`<div class="chart-wrap"><svg viewBox="0 0 ${W} ${H}" role="img">${s}</svg></div>${leg}`);
}

export function barChart(series, labels, { fmt = nairaShort, colors = COLORS } = {}) {
  const all = series.flatMap((s) => s.data); if (!labels.length || !all.some((v) => v > 0)) return empty();
  const max = niceMax(Math.max(...all)); const n = labels.length, iw = W - PL - PR, ih = H - PT - PB, gw = iw / n, bw = Math.min(38, (gw * 0.7) / series.length);
  let s = axes(max, fmt);
  labels.forEach((l, i) => {
    const cx = PL + gw * i + gw / 2;
    series.forEach((se, si) => { const v = se.data[i], bh = (ih * v) / max, bx = cx - (bw * series.length) / 2 + bw * si; s += `<rect x="${bx}" y="${H - PB - bh}" width="${bw - 2}" height="${bh}" rx="4" fill="${colors[si % colors.length]}"><title>${esc(l)} - ${esc(se.name)}: ${esc(fmt(v))}</title></rect>`; });
    if (i % skip(n) === 0) s += `<text x="${cx}" y="${H - 12}" text-anchor="middle" font-size="11" fill="#8a847e">${esc(String(l).slice(0, 12))}</text>`;
  });
  const leg = series.length > 1 ? `<div class="legend">${series.map((se, i) => `<span><i style="background:${colors[i % colors.length]}"></i>${esc(se.name)}</span>`).join("")}</div>` : "";
  return raw(`<div class="chart-wrap"><svg viewBox="0 0 ${W} ${H}" role="img">${s}</svg></div>${leg}`);
}

export function hbarChart(items, { fmt = nairaShort } = {}) {
  if (!items.length || !items.some((i) => i.value > 0)) return empty();
  const max = Math.max(...items.map((i) => i.value));
  return raw(`<div class="stack" style="gap:9px">${items.map((it, i) => `<div><div class="row between small"><span class="strong">${esc(it.label)}</span><span class="muted">${esc(fmt(it.value))}</span></div><div style="background:#f0edea;border-radius:99px;height:9px;margin-top:3px"><div style="width:${Math.max(2, (it.value / max) * 100)}%;height:9px;border-radius:99px;background:${COLORS[i % COLORS.length]}"></div></div></div>`).join("")}</div>`);
}

export function donutChart(items, { fmt = nairaShort } = {}) {
  const total = items.reduce((a, b) => a + b.value, 0); if (!total) return empty();
  const r = 70, c = 2 * Math.PI * r; let off = 0, s = "";
  items.forEach((it, i) => { const len = (it.value / total) * c; s += `<circle r="${r}" cx="100" cy="100" fill="none" stroke="${COLORS[i % COLORS.length]}" stroke-width="26" stroke-dasharray="${len} ${c - len}" stroke-dashoffset="${-off}" transform="rotate(-90 100 100)"><title>${esc(it.label)}: ${esc(fmt(it.value))}</title></circle>`; off += len; });
  s += `<text x="100" y="96" text-anchor="middle" font-size="12" fill="#8a847e">Total</text><text x="100" y="116" text-anchor="middle" font-size="17" font-weight="800" fill="#232120">${esc(fmt(total))}</text>`;
  return raw(`<div class="row" style="align-items:center;flex-wrap:nowrap"><svg viewBox="0 0 200 200" style="width:170px;flex:none"><g>${s}</g></svg><div class="legend" style="flex-direction:column;gap:6px">${items.map((it, i) => `<span><i style="background:${COLORS[i % COLORS.length]}"></i>${esc(it.label)} <b>${esc(fmt(it.value))}</b></span>`).join("")}</div></div>`);
}
