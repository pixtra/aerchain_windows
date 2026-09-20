"use strict";

const $ = (id) => document.getElementById(id);
const VIEW = $("view");
const BOT = "AerBot";
// AerBot thread survives tab switches (view innerHTML is rebuilt each time).
let aerbotThreadHtml = "";
try { aerbotThreadHtml = localStorage.getItem("ktq_thread") || ""; } catch (_) {}
const saveThread = () => {
  const t = $("thread");
  if (!t) return;
  aerbotThreadHtml = t.innerHTML;
  try { localStorage.setItem("ktq_thread", aerbotThreadHtml); } catch (_) {}
};
const VIEW_TITLE = {
  overview: "Decision Overview", rfx: "RFx & Suppliers", ingestion: "Ingestion & Evidence",
  comparison: "Offer Comparison", aerbot: "AerBot", scenarios: "What-If Scenarios",
  award: "Recommended Award", trust: "Trust & Evidence", settings: "Settings",
};

const api = (path, opts) => fetch("/api" + path, opts).then(async (r) => {
  if (r.status === 401) {
    location.href = "/login?next=" + encodeURIComponent(location.pathname);
    throw new Error("login required");
  }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
  return r.json();
});

function fmt(n, d = 2) {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
}
function inr(v) { return "₹ " + fmt(v); }
function cash(c, v) { return `${c} ${fmt(v, 3)}`; }
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
const info = (tip) => `<i class="info" data-tip="${esc(tip)}">i</i>`;

// Human-readable labels: "L07 · CB Item 006" instead of bare codes.
// LINE_MAP is filled from /api/lines; codes stay as secondary mono text.
let LINE_MAP = {};
async function ensureLines() {
  if (Object.keys(LINE_MAP).length) return;
  try {
    (await api("/lines")).forEach((l) => {
      LINE_MAP[l.line_number] = l.buyer_description || l.sku_id;
    });
  } catch (_) {}
}
function lineLabel(n) {
  if (n === null || n === undefined || n === "") return "—";
  const d = LINE_MAP[n];
  return d ? `${rfTag(n)} · ${esc(d)}` : rfTag(n);
}
const rfTag = (n) => `RF${String(n).padStart(2, "0")}`;
let SUP_MAP = {};
async function ensureSuppliers() {
  if (Object.keys(SUP_MAP).length) return;
  try {
    (await api("/suppliers")).forEach((s) => {
      SUP_MAP[s.supplier_id] = s.supplier_name || s.supplier_id;
    });
  } catch (_) {}
}
function supLabel(id) { return esc(SUP_MAP[id] || id); }

function badge(classList, text) { return `<span class="badge ${classList}">${esc(text)}</span>`; }
function eligBadge(r) {
  if (r.error_state) return badge("warn", "UNRESOLVED");
  return r.overall_eligible ? badge("good", "ELIGIBLE") : badge("bad", "INELIGIBLE");
}

function table(cols, rows, opts = {}) {
  if (!rows || !rows.length) return `<div class="empty">No rows.</div>`;
  return `<div class="table-scroll"><table><thead><tr>${cols.map((c) => `<th class="${c.num ? "num" : ""}">${c.label}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr${opts.rowAttr ? ` ${opts.rowAttr(r)}` : ""}>${cols.map((c) => `<td class="${c.num ? "num" : ""}">${c.render ? c.render(r[c.key], r) : esc(r[c.key])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

/* ---------------------------------------------------------- detail drawer */
function openDrawer(title, bodyHtml) {
  closeDrawer();
  const ov = document.createElement("div");
  ov.id = "drawer-ov";
  ov.innerHTML = `<div id="drawer"><div class="dhead"><div>${title}</div>`
    + `<button class="btn ghost" id="drawer-x">Close ✕</button></div>`
    + `<div class="dbody">${bodyHtml}</div></div>`;
  document.body.appendChild(ov);
  ov.addEventListener("click", (e) => { if (e.target === ov) closeDrawer(); });
  $("drawer-x").onclick = closeDrawer;
}
function closeDrawer() { document.getElementById("drawer-ov")?.remove(); }
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

async function showOffer(offerId) {
  openDrawer(`Offer <span class="mono">${esc(offerId)}</span>`, "<div class='spin' style='display:inline-block'></div>");
  try {
    const [calc, ev] = await Promise.all([
      api(`/offers/${offerId}/calculation`), api(`/offers/${offerId}/evidence`)]);
    openDrawer(`Offer <span class="mono">${esc(offerId)}</span> · ${esc(calc.supplier)} · Line ${calc.line_number}`,
      `<div class="assump">Eligibility: <strong>${esc(calc.eligibility)}</strong></div>`
      + table([{ label: "Step", key: "k" }, { label: "Value", key: "v" }],
        calc.steps.map(([a, b]) => ({ k: a, v: String(b) })))
      + `<h3 style="margin:14px 0 8px">Evidence</h3>` + table(
        [{ label: "Source", key: "source_file", render: (v) => `<span class="mono">${esc(v)}</span>` },
         { label: "Location", key: "source_location", render: (v) => `<span class="mono">${esc(v)}</span>` },
         { label: "Extract", key: "source_text" },
         { label: "Confidence", key: "extraction_confidence" },
         { label: "Verify", key: "verification_status" }], ev));
  } catch (e) { openDrawer("Offer", `<div class="empty">${esc(e.message)}</div>`); }
}

async function showLine(lineNumber) {
  openDrawer(lineLabel(lineNumber), "<div class='spin' style='display:inline-block'></div>");
  try {
    const [offers, lines] = await Promise.all([
      api(`/offers?line=${lineNumber}&limit=100`), api("/lines")]);
    const meta = (lines || []).find((l) => l.line_number === lineNumber) || {};
    const ranked = [...offers].sort(
      (a, b) => (a.effective_economic_cost ?? 1e18) - (b.effective_economic_cost ?? 1e18));
    openDrawer(`${lineLabel(lineNumber)}`,
      `<div class="note">Qty ${fmt(meta.required_quantity, 0)} ${esc(meta.buyer_uom || "")} · `
      + `lead ≤ ${meta.required_lead_time_days || "—"}d · ${offers.length} offers</div>`
      + `<div style="margin-top:10px">` + table(
        [{ label: "#", key: "i", num: true },
         { label: "Supplier", key: "supplier_name" },
         { label: "Quoted", key: "quoted_unit_price", render: (v, r) => `${esc(r.quoted_currency)} ${fmt(v, 4)}/${esc(r.quoted_uom)}` },
         { label: "Effective", key: "effective_economic_cost", num: true, render: (v) => inr(v) },
         { label: "Status", key: "overall_eligible", render: (v, r) => v ? badge("good", "ELIGIBLE") : badge("bad", esc(r.eligibility_reason || "INELIGIBLE")) }],
        ranked.map((r, i) => ({ ...r, i: i + 1 })),
        { rowAttr: (r) => `data-offer="${esc(r.offer_id)}"` }) + `</div>`
      + `<div class="note">click an offer for its full calculation waterfall</div>`);
  } catch (e) { openDrawer("Line", `<div class="empty">${esc(e.message)}</div>`); }
}

// one delegated handler for every drill-down in every tab
VIEW.addEventListener("click", (e) => {
  const o = e.target.closest("[data-offer]");
  if (o && o.dataset.offer) { showOffer(o.dataset.offer); return; }
  const l = e.target.closest("[data-line]");
  if (l && l.dataset.line) showLine(parseInt(l.dataset.line, 10));
});

function toast(msg, ok) {
  const e = document.createElement("div");
  e.style.cssText = `position:fixed;top:14px;right:14px;z-index:9;background:${ok ? "#0e3a2b" : "#3a1318"};color:${ok ? "#31d98f" : "#ff6b7a"};padding:10px 16px;border-radius:10px;border:1px solid #233047;font-size:13px`;
  e.textContent = msg;
  document.body.appendChild(e);
  setTimeout(() => e.remove(), 2600);
}

async function setTitle() {
  try { const r = await api("/rfx"); $("decision-date").textContent = "decision " + r.decision_date; } catch (_) {}
}

/* ---------------------------------------------------------------- views */
async function viewOverview() {
  const rfx = await api("/rfx");
  const cov = await api("/coverage");
  const sup = await api("/suppliers");
  const comp = await api("/comparison?eligible_only=1");
  await ensureLines();
  const competitive = cov.filter((c) => c.coverage_status === "COMPETITIVE").length;
  const gaps = cov.filter((c) => c.coverage_status !== "COMPETITIVE");
  const maxSup = Math.max(1, ...sup.map((s) => s.offers));
  VIEW.innerHTML = `
  <h2 class="view-title">${rfx.rfx_id} · ${esc(rfx.rfx_name)}</h2>
  <div class="grid kpi-row">
    <div class="kpi"><div class="v">${rfx.line_count}</div><div class="l">RFx lines ${info("Demand slots in this RFx — one per item, quantity and delivery terms the buyer asked suppliers to quote.")}</div></div>
    <div class="kpi"><div class="v">${rfx.supplier_count}</div><div class="l">Responding suppliers ${info("Invited suppliers who actually sent a quote. SUP-008 was invited but never responded.")}</div></div>
    <div class="kpi"><div class="v">${rfx.offer_count}</div><div class="l">Offers received ${info("Every supplier quote on every line — 131 in total, eligible or not.")}</div></div>
    <div class="kpi good"><div class="v">${rfx.eligible_count}</div><div class="l">Eligible offers ${info("Quotes passing ALL gates: quantity, lead time, quality, validity and mapping. Only these can win.")}</div></div>
    <div class="kpi warn"><div class="v">${rfx.review_count}</div><div class="l">Require review ${info("Low extraction confidence or unresolved units — a buyer should eyeball these before awarding.")}</div></div>
    <div class="kpi"><div class="v">${competitive}/${cov.length}</div><div class="l">Competitive lines ${info("Lines with 2+ qualified quotes. Single-quote and zero-quote lines need buyer action.")}</div></div>
  </div>
  <div class="grid cols-2" style="margin-top:16px">
    <div class="card"><h3>Supplier participation</h3>
      ${table([{label:"Supplier", key:"supplier_id"},{label:"Name", key:"supplier_name"},{label:"Currency", key:"currency"},
        {label:"Offers", key:"offers", num:true},{label:"Eligible", key:"eligible", num:true},
        {label:"Offer mix", key:"offers", render: (v, r) => `<div class="bar-wrap" style="min-width:120px"><div class="progress" style="flex:1"><div style="width:${(r.offers / maxSup * 100).toFixed(0)}%"></div></div><span class="note">${r.offers}/${r.eligible}</span></div>`}],
        sup)}
    </div>
    <div class="card"><h3>Coverage gaps ${info("Lines without healthy competition: who is mapped, who quoted, who qualified — and what the buyer should do about each.")}</h3>
      ${gaps.length ? table([{label:"Line", key:"line_number", render:(v,r)=>`${lineLabel(v)}<br/><span class="mono note">${esc(r.sku_id)}</span>`},
        {label:"Mapped", key:"mapped_supplier_count", num:true},
        {label:"Offers", key:"offer_count", num:true},{label:"Qualified", key:"qualified_offer_count", num:true},{label:"Status", key:"coverage_status"},
        {label:"Buyer action", key:"buyer_action"}], gaps,
      { rowAttr: (r) => `data-line="${r.line_number}"` }) : '<div class="empty">Fully competitive.</div>'}
    </div>
  </div>
  <div class="card" style="margin-top:16px"><h3>Cheapest eligible offer per line ${info("The lowest true cost per line after currency, pack-size, discount, freight and payment-date math. Quoted price is what the supplier wrote; effective cost is what you would actually pay.")}</h3>
    ${table([{label:"Line", key:"line_number", render:(v,r)=>`${lineLabel(v)}<br/><span class="mono note">${esc(r.sku_id)}</span>`},
      {label:"Supplier", key:"supplier_name"},
      {label:"Quoted", key:"quoted_unit_price", render:(v,r)=>`${esc(r.quoted_currency)} ${fmt(v,4)}/${esc(r.quoted_uom)}`},
      {label:"Norm. price", key:"normalized_unit_price", num:true, render:(v)=>inr(v)},
      {label:"Disc%", key:"applicable_discount_percentage", num:true, render:(v)=>(v??"—")+"%"},
      {label:"Effective cost", key:"effective_economic_cost", num:true, render:(v)=>inr(v)},
      {label:"Offer", key:"offer_id", render: (v) => `<span class="mono">${v}</span>`}],
      comp.filter((r) => r.line_rank === 1),
      { rowAttr: (r) => `data-offer="${esc(r.offer_id)}" data-line="${r.line_number}"` })}
  </div>`;
}

async function viewRfx() {
  const [rfx, lines, sup] = await Promise.all([api("/rfx"), api("/lines"), api("/suppliers")]);
  VIEW.innerHTML = `
  <h2 class="view-title" style="margin-top:0">Draft a new RFx ${info("Talk it into existence here or via AerBot. Drafts are planning records — no offers, no award, clearly labeled. The live decision layer stays on RFX-001.")}</h2>
  <div class="card" style="max-width:760px;margin-bottom:22px">
    <div class="filterbar">
      <input id="d-name" placeholder="RFx name" style="flex:1;min-width:200px" />
      <input id="d-cat" placeholder="category" style="width:150px" />
      <input id="d-dead" placeholder="deadline YYYY-MM-DD" style="width:170px" />
    </div>
    <div class="filterbar"><input id="d-terms" placeholder="terms (e.g. Net 30, delivery to Pune)" style="flex:1" /></div>
    <div class="filterbar"><textarea id="d-lines" rows="4" style="flex:1;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px" placeholder="one per line: Item-006 x 20000"></textarea></div>
    <div class="filterbar"><button class="btn primary" id="btn-draft">Save draft</button></div>
    <div id="draft-out" class="note"></div>
    <div id="draft-confirm"></div>
    <div id="draft-list"></div>
  </div>
  <h2 class="view-title">RFx ${esc(rfx.rfx_id)} — lines ${info("Everything the buyer asked for: item, quantity, pack unit, lead time. Click a row to see all quotes on that line.")}</h2>
  <div class="card">${table(
    [{label:"Line", key:"line_number", render:(v)=>rfTag(v)},
     {label:"SKU", key:"sku_id"},{label:"Description", key:"buyer_description"},
     {label:"Buyer UOM", key:"buyer_uom"},{label:"Qty", key:"required_quantity", num:true, render:(v)=>fmt(v,0)},
     {label:"Lead time", key:"required_lead_time_days", num:true, render:(v)=>v+"d"},
     {label:"Quality req.", key:"quality_requirement"}], lines,
    { rowAttr: (r) => `data-line="${r.line_number}"` })}</div>
  <h2 class="view-title" style="margin-top:22px">Suppliers</h2>
  <div class="card">${table(
    [{label:"ID", key:"supplier_id"},{label:"Supplier", key:"supplier_name"},{label:"Currency", key:"currency"},
     {label:"Country", key:"country"},{label:"Default lead", key:"default_lead_time_days", num:true, render:(v)=>(v||"—")+"d"},
     {label:"Offers", key:"offers", num:true},{label:"Eligible", key:"eligible", num:true},
     {label:"Status", key:"eligible", render:(v,r)=> v<r.offers ? badge("warn","Partial qual.") : badge("good", r.offers?"All offers qual.":"No quotes")}], sup)}</div>`;
  const loadDrafts = async () => {
    try {
      const ds = await api("/rfx/drafts");
      $("draft-list").innerHTML = ds.length ? table(
        [{ label: "Draft", key: "draft_id", render: (v) => `<span class="mono">${v}</span>` },
         { label: "Name", key: "name" }, { label: "Lines", key: "line_count", num: true },
         { label: "Status", key: "x", render: () => badge("warn", "DRAFT") },
         { label: "", key: "draft_id", render: (v) => `<button class="btn ghost" data-draft-del="${v}">Delete</button>` }],
        ds.map((d) => ({ ...d, x: 1 }))) : '<div class="empty">No drafts yet.</div>';
      $("draft-list").querySelectorAll("[data-draft-del]").forEach((b) => (b.onclick = async () => {
        await api(`/rfx/drafts/${b.dataset.draftDel}`, { method: "DELETE" });
        toast("Draft deleted", true);
        loadDrafts();
      }));
    } catch (_) {}
  };
  const clearDraftForm = () => {
    ["d-name", "d-cat", "d-dead", "d-terms", "d-lines"].forEach((id) => { $(id).value = ""; });
    $("draft-confirm").innerHTML = "";
  };
  loadDrafts();
  const postDraft = async (extra) => {
    const r = await fetch("/api/rfx/drafts", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        name: $("d-name").value, category: $("d-cat").value,
        deadline: $("d-dead").value, terms: $("d-terms").value,
        lines_text: $("d-lines").value, ...(extra || {}) }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      const err = new Error();
      err.status = r.status;
      err.detail = d.detail;
      throw err;
    }
    return d;
  };
  $("btn-draft").onclick = async () => {
    $("draft-confirm").innerHTML = "";
    try {
      const r = await postDraft();
      $("draft-out").textContent = `saved ${r.draft_id} (${r.lines} lines)`
        + `${r.skus_created && r.skus_created.length ? ` · new SKUs: ${r.skus_created.join(", ")}` : ""} — DRAFT, not live.`;
      toast("Draft saved", true);
      clearDraftForm();
      loadDrafts();
    } catch (e) {
      if (e.status === 409 && e.detail && e.detail.unknown_skus) {
        const u = e.detail.unknown_skus;
        $("draft-out").innerHTML = `${esc(e.detail.error)}<br/>Confirm creation — nothing is invented until you say so:`;
        $("draft-confirm").innerHTML = u.map((s, i) => `
          <div class="filterbar" style="gap:8px">
            <span class="note">line ${s.line_no}</span>
            <input id="ns-code-${i}" value="${esc(s.suggested_code || s.sku || "")}" title="SKU code" style="width:110px" />
            <input id="ns-name-${i}" value="${esc(s.name || "")}" placeholder="item name" style="flex:1;min-width:140px" />
            <input id="ns-uom-${i}" placeholder="UOM: EA/BOX/..." style="width:130px" />
          </div>`).join("")
          + `<button class="btn primary" id="btn-confirm-sku">Create SKUs & save draft</button>`;
        $("btn-confirm-sku").onclick = async () => {
          try {
            const r = await postDraft({ new_skus: u.map((s, i) => ({
              sku_id: $(`ns-code-${i}`).value, name: $(`ns-name-${i}`).value,
              uom: $(`ns-uom-${i}`).value, line_no: s.line_no })) });
            $("draft-out").textContent = `saved ${r.draft_id} (${r.lines} lines) · new SKUs: ${(r.skus_created || []).join(", ")} — DRAFT, not live.`;
            $("draft-confirm").innerHTML = "";
            toast("Draft saved with new SKUs", true);
            clearDraftForm();
            loadDrafts();
          } catch (e2) {
            $("draft-out").textContent = (e2.detail && (e2.detail.error || e2.detail)) || e2.message;
          }
        };
      } else {
        $("draft-out").textContent = (e.detail && (e.detail.error || e.detail)) || e.message;
      }
    }
  };
}

async function viewIngestion() {
  const offers = await api("/offers?eligible=0");
  const raw = await api("/export/raw").then((r) => r.text()).catch(() => "");
  const rows = offers;
  VIEW.innerHTML = `
  <h2 class="view-title">Ingestion — from raw artifacts to decision-ready</h2>
  <div class="card" style="margin-bottom:16px"><h3>Upload your own supplier file ${info("Your real quotes go through the same engines: Excel/PDF text, real OCR for images, then matched to the product catalogue. Unmatched rows stay flagged — never guessed.")}</h3>
    <div class="filterbar">
      <input id="up-file" type="file" accept=".xlsx,.pdf,.docx,.jpg,.jpeg,.png,.txt,.eml" />
      <select id="up-sup"><option value="">Auto-detect supplier</option></select>
      <input id="up-lang" placeholder="ocr langs, e.g. eng" title="Tesseract languages (eng+hin needs the data pack)" style="width:110px" />
      <button class="btn primary" id="btn-upload">Extract</button>
      <span class="note">xlsx · pdf (incl. scanned) · image (real Tesseract OCR) · email text — rows match the product master; unmatched rows stay flagged, never invented.</span>
    </div>
    <div id="up-out" class="note">No file uploaded yet.</div>
    <div id="up-table"></div>
    <div id="up-promote" style="margin-top:10px"></div>
  </div>
  <div class="grid kpi-row">
    <div class="kpi"><div class="v">${rows.length}</div><div class="l">Extracted offers (131)</div></div>
    <div class="kpi"><div class="v">100%</div><div class="l">Traceable to source evidence</div></div>
    <div class="kpi warn"><div class="v">${rows.filter(r=>r.requires_review||r.error_state||['LOW','MEDIUM'].includes(r.extraction_confidence)).length}</div><div class="l">Extraction flags</div></div>
    <div class="kpi"><div class="v">7</div><div class="l">Source artifacts (xlsx/pdf/image/email)</div></div>
  </div>
  <div class="card" style="margin-top:16px"><h3>Extraction confidence by artifact</h3>
    <div class="table-scroll">${table(
      [{label:"Offer", key:"offer_id", render:(v)=>`<span class="mono">${v}</span>`},
       {label:"Line", key:"line_number", render:(v)=>rfTag(v)},
       {label:"Supplier", key:"supplier_name"},{label:"Source", key:"source_file", render:(v)=>`<span class="mono">${esc(v)}</span>`},
       {label:"Type", key:"source_type"},{label:"Location", key:"source_location", render:(v)=>`<span class="mono">${esc(v)}</span>`},
       {label:"Text", key:"source_text"},
       {label:"Extractor conf.", key:"extraction_confidence", render:(v)=> v==="HIGH"?badge("good",v):v==="MEDIUM"?badge("warn",v):badge("bad",v)},
       {label:"Normalization", key:"normalization_confidence", render:(v)=> v==="HIGH"?badge("good",v):badge("warn",v)},
       {label:"Verify", key:"verification_status", render:(v)=> v==="CALCULATED"?badge("good",v):badge("warn",v)}], rows,
      { rowAttr: (r) => `data-offer="${esc(r.offer_id)}"` })}</div>
  </div>`;
  if (raw) console.log("raw export bytes:", raw.length);
  try {
    const sups = await api("/suppliers");
    $("up-sup").innerHTML = `<option value="">Auto-detect supplier</option>` +
      sups.map((s) => `<option value="${s.supplier_id}">${s.supplier_id} · ${esc(s.supplier_name)}</option>`).join("");
  } catch (_) {}
  $("btn-upload").onclick = async () => {
    const f = $("up-file").files[0];
    if (!f) { $("up-out").textContent = "Choose a file first."; return; }
    if (f.size === 0) {
      $("up-out").textContent = `"${f.name}" is empty (0 bytes). Pick a non-empty file — `
        + `cloud-drive placeholders and empty files read as 0 bytes.`;
      return;
    }
    $("up-out").textContent = `extracting ${f.name}…`;
    $("up-table").innerHTML = ""; $("up-promote").innerHTML = "";
    const fd = new FormData();
    fd.append("file", f, f.name);
    if ($("up-sup").value) fd.append("supplier_id", $("up-sup").value);
    if ($("up-lang").value.trim()) fd.append("ocr_lang", $("up-lang").value.trim());
    try {
      const r = await fetch("/api/ingest/upload", { method: "POST", body: fd }).then(async (x) => {
        if (!x.ok) throw new Error((await x.json().catch(() => ({}))).detail || x.status);
        return x.json();
      });
      $("up-out").innerHTML = `${esc(f.name)} → <strong>${r.rows}</strong> rows via ${esc(r.engine)} · `
        + `${r.matched} matched to product master · ${r.unresolved} unresolved.`;
      const prev = (r.rows_preview || []).map((x) => ({ code: x.sku_code, qty: x.quantity,
        uom: x.unit_uom, currency: x.currency, price: x.unit_price,
        matched: x.matched_supplier_id ? `${x.matched_supplier_id} / ${x.matched_sku_id}` : "—",
        flags: (x.unresolved || []).join(", ") || "clean" }));
      $("up-table").innerHTML = table(
        [{label:"Code", key:"code", render:(v)=>`<span class="mono">${esc(v)}</span>`},
         {label:"Qty", key:"qty", num:true},{label:"UOM", key:"uom"},
         {label:"Currency", key:"currency"},{label:"Price", key:"price", num:true},
         {label:"Matched", key:"matched"},{label:"Flags", key:"flags"}], prev)
        + (r.rows > prev.length ? `<div class="note">showing first ${prev.length} of ${r.rows} rows</div>` : "");
      $("up-promote").innerHTML = `
        <div class="filterbar" style="margin-top:8px">
          <span class="note">Promote to live decision layer (buyer-confirmed):</span>
          <label class="note">Net days</label><input id="pm-pay" type="number" value="30" style="width:70px"/>
          <label class="note">valid-until fallback</label><input id="pm-valid" placeholder="2026-12-31" style="width:110px"/>
          <label class="note">lead fallback (d)</label><input id="pm-lead" type="number" placeholder="—" style="width:70px"/>
          <button class="btn primary" id="btn-promote">Promote #${r.file_id}</button>
        </div><div id="pm-out" class="note"></div>`;
      $("btn-promote").onclick = async () => {
        $("pm-out").textContent = "promoting through real engines…";
        const body = { payment_days: parseInt($("pm-pay").value) || 30 };
        if ($("pm-valid").value.trim()) body.default_valid_until = $("pm-valid").value.trim();
        if ($("pm-lead").value.trim() !== "") body.default_lead_days = parseInt($("pm-lead").value);
        try {
          const p = await api(`/ingest/uploads/${r.file_id}/promote`,
            { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
          $("pm-out").innerHTML = `promoted <strong>${p.promoted}</strong> offers (${p.eligible} eligible), `
            + `award recomputed: ${p.lines_awarded} lines. Assumptions: ${p.assumptions.map(esc).join(" · ")}.`
            + (p.skipped.length ? `<br/>skipped: ${p.skipped.map((s) => `row ${s.row} ${esc(s.code || "")} (${esc(s.reason)})`).join("; ")}` : "")
            + (p.tiers_applied ? `<br/>discount-tier rules parsed from file text: ${p.tiers_applied}` : "");
          toast("Promoted — comparison & award updated", true);
        } catch (e) { $("pm-out").textContent = "Promote failed: " + e.message; }
      };
    } catch (e) { $("up-out").textContent = "Extraction failed: " + e.message; }
  };
}

async function viewComparison() {
  const raw = await api("/offers?eligible=0&limit=500");
  // normalize engine field names into the shape this view renders/filters on
  const rows = raw.map((r) => ({ ...r,
    line: "RF" + String(r.line_number).padStart(2, "0"),
    quoted: `${r.quoted_currency} ${fmt(r.quoted_unit_price, 4)}/${r.quoted_uom}`,
    normalized: r.normalized_unit_price,
    discount: r.applicable_discount_percentage,
    effective_cost: r.effective_economic_cost,
    eligibility: r.overall_eligible ? "ELIGIBLE"
      : ("INELIGIBLE" + (r.eligibility_reason ? " — " + r.eligibility_reason : "")),
  }));
  VIEW.innerHTML = `
  <h2 class="view-title">Offer comparison — ranked by effective economic cost ${info("Every quote on every line, cheapest true cost first. Click a row for the full step-by-step calculation behind that number.")}</h2>
  <div class="card">
    <div class="filterbar">
      <select id="f-line"><option value="">All lines</option>${Array.from({length:30},(_,i)=>`<option value="${i+1}">RF${String(i+1).padStart(2,"0")}</option>`).join("")}</select>
      <select id="f-elig"><option value="0">All offers</option><option value="1">Eligible only</option></select>
      <span class="note">effective cost = (norm price − discount + freight − financing benefit)</span>
      <button class="btn ghost" id="btn-csv">Export CSV</button>
    </div>
    <div id="cmp-table"></div>
  </div>`;
  const cols = [
    {label:"#", key:"line_rank", num:true},
    {label:"Line", key:"line", render:(v,r)=>`${esc(v)} · ${esc(r.quoted_description || r.sku_id || "")}`},
    {label:"Supplier", key:"supplier_name"},{label:"Quoted", key:"quoted"},
    {label:"Norm.", key:"normalized", num:true, render:(v)=>inr(v)},
    {label:"Disc%", key:"discount", num:true},{label:"Effective", key:"effective_cost", num:true, render:(v)=>inr(v)},
    {label:"Lead", key:"lead_time_days", num:true, render:(v)=>v+"d"},
    {label:"MOQ", key:"moq", num:true},
    {label:"Eligibility", key:"eligibility", render:(v)=>v}
  ];
  const render = async () => {
    const line = $("f-line").value, elig = $("f-elig").value;
    let data = rows;
    if (line) data = data.filter((r) => r.line === "RF" + String(line).padStart(2,"0"));
    if (elig === "1") data = data.filter((r) => r.eligibility === "ELIGIBLE");
    const grouped = {};
    data.forEach((r) => { (grouped[r.line] = grouped[r.line] || []).push(r); });
    Object.values(grouped).forEach((g) => g
      .sort((a, b) => (a.effective_cost ?? 1e18) - (b.effective_cost ?? 1e18))
      .forEach((r, i) => (r.line_rank = i + 1)));
    data.sort((a, b) => a.line.localeCompare(b.line) || a.line_rank - b.line_rank);
    $("cmp-table").innerHTML = table(cols, data,
      { rowAttr: (r) => `data-offer="${esc(r.offer_id)}" data-line="${r.line_number}"` })
      + `<div class="note">click any row for the full calculation waterfall</div>`;
  };
  $("f-line").onchange = render; $("f-elig").onchange = render;
  $("btn-csv").onclick = () => window.open("/api/export/offers", "_blank");
  render();
}

function sharedAerBotHtml() {
  return `
  <h2 class="view-title"><span class="bot-avatar">A</span> ${BOT} <span class="note">· procurement aerbot</span></h2>
  <div id="model-status"></div>
  <div class="chat-wrap">
    <div class="filterbar" style="margin-bottom:0">
      <div class="suggest" id="suggests" style="flex:1"></div>
      <button class="btn ghost" id="btn-export" title="Download this conversation as Markdown">Export</button>
      <button class="btn ghost" id="btn-clear" title="Clear this conversation">Clear</button>
    </div>
    <div id="thread"></div>
    <div class="chat-input">
      <input id="ask" placeholder="Ask about costs, coverage, eligibility, award, what-ifs…" />
      <button class="btn primary" id="btn-ask">Ask</button>
    </div>
  </div>`;
}

let chatLog = [];
try { chatLog = JSON.parse(localStorage.getItem("ktq_log") || "[]"); } catch (_) { chatLog = []; }
const saveLog = () => {
  try { localStorage.setItem("ktq_log", JSON.stringify(chatLog.slice(-30))); } catch (_) {}
};
let chatSession = null;
try { chatSession = localStorage.getItem("ktq_session") || null; } catch (_) {}
if (!chatSession) {
  chatSession = "s-" + Date.now().toString(36) + Math.floor(Math.random() * 1e6).toString(36);
  try { localStorage.setItem("ktq_session", chatSession); } catch (_) {}
}

async function viewAerBot() {
  VIEW.innerHTML = sharedAerBotHtml();
  if (aerbotThreadHtml) $("thread").innerHTML = aerbotThreadHtml;
  const suggestions = (await api("/aerbot/suggestions")).suggestions;
  $("suggests").innerHTML = suggestions.map((s) => `<button>${esc(s)}</button>`).join("");
  $("suggests").querySelectorAll("button").forEach((b) => (b.onclick = () => ask(b.textContent)));
  $("btn-ask").onclick = () => ask($("ask").value);
  $("ask").onkeydown = (e) => { if (e.key === "Enter") ask($("ask").value); };
  $("btn-clear").onclick = () => {
    $("thread").innerHTML = "";
    chatLog = [];
    saveThread(); saveLog();
    fetch("/api/aerbot/forget", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: chatSession }) }).catch(() => {});
    chatSession = "s-" + Date.now().toString(36) + Math.floor(Math.random() * 1e6).toString(36);
    try { localStorage.setItem("ktq_session", chatSession); } catch (_) {}
    toast("Chat cleared", true);
  };
  $("btn-export").onclick = () => {
    if (!chatLog.length) { toast("Nothing to export yet"); return; }
    const md = chatLog.map((m, i) =>
      `## Q${i + 1}: ${m.q}\n\n**${m.title}**${m.provider ? ` _(via ${m.provider})_ ` : ""}\n\n${m.narrative}\n`).join("\n---\n\n");
    const blob = new Blob([`# Aerchain AerBot transcript\n\n${md}`], { type: "text/markdown" });
    const aEl = document.createElement("a");
    aEl.href = URL.createObjectURL(blob);
    aEl.download = "aerbot-transcript.md";
    aEl.click();
    URL.revokeObjectURL(aEl.href);
  };
  try {
    const st = await api("/aerbot/status");
    $("model-status").innerHTML = st.configured
      ? `<div class="modelbar"><span class="pulse"></span><div>
           <div class="mmain">${BOT} is running on <strong>${esc(st.provider)}</strong> · <span class="mono">${esc(st.model)}</span></div>
           <div class="note">${st.chain && st.chain.length > 1 ? `fallback chain: ${st.chain.map(esc).join(" → ")} · ` : ""}grounded in live engine data, no canned answers${st.serving ? ` · last answer via ${esc(st.serving)}` : ""}</div>
         </div></div>`
      : `<div class="modelbar off"><span class="pulse"></span><div>
           <div class="mmain">${BOT} is offline</div>
           <div class="note">${esc(st.detail)}.</div>
         </div></div>`;
  } catch (_) {}
}

function bars(rows) {
  // auto-chart: first text column as labels, first all-numeric column as values
  if (!rows || !rows.length) return "";
  const keys = Object.keys(rows[0]);
  const label = keys.find((k) => isNaN(parseFloat(rows[0][k])));
  const num = keys.find((k) => k !== label && rows.every((r) =>
    r[k] === null || r[k] === undefined || r[k] === "" || !isNaN(parseFloat(r[k]))));
  if (!label || !num) return "";
  const data = rows.filter((r) => !isNaN(parseFloat(r[num]))).slice(0, 10);
  if (!data.length) return "";
  const max = Math.max(...data.map((r) => parseFloat(r[num]))) || 1;
  return `<div style="margin:10px 0">` + data.map((r) => `
    <div class="bar-wrap" style="margin:4px 0"><span class="note" style="min-width:150px;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(String(r[label]))}</span>`
    + `<div class="progress" style="flex:1"><div style="width:${(parseFloat(r[num]) / max * 100).toFixed(1)}%"></div></div>`
    + `<span class="note mono">${esc(String(r[num]))}</span></div>`).join("") + `</div>`;
}

function md(str) {  return str.replace(/^###\s*(.*)$/gm, '<div style="font-size:15px;font-weight:700;margin-top:2px">$1</div>')
    .replace(/^(\*\*.*?\*\*)$/gm, '<div class="t" style="margin:10px 0 4px">$1</div>')
    .replace(/^\|(.*)\|$/gm, (m) => {
      const cells = m.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      return `<div style="font-family:var(--mono);font-size:11.5px;color:var(--muted)">${cells.map(esc).join(" · ")}</div>`;
    })
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br/>");
}

async function ask(q) {
  q = q.trim(); if (!q) return;
  $("thread").insertAdjacentHTML("beforeend",
    `<div class="msg user"><div class="who">You</div>${esc(q)}</div>`);
  saveThread();
  $("ask").value = ""; $("ask").disabled = true; $("btn-ask").disabled = true;
  const placeholder = document.createElement("div");
  placeholder.className = "msg answer thinking";
  placeholder.innerHTML = `<div class="who">${BOT}</div><span class="typing"><span></span><span></span><span></span></span>`;
  $("thread").appendChild(placeholder);
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  try {
    const a = await api("/aerbot/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q, session_id: chatSession }) });
    const ev = a.evidence && a.evidence.length ? `<div class="table-scroll" style="margin-top:10px">${table(
      [{label:"Source", key:"source_file", render:(v)=>`<span class="mono">${esc(v)}</span>`},
       {label:"Location", key:"location", render:(v)=>`<span class="mono">${esc(v)}</span>`},
       {label:"Extract", key:"confidence"}], a.evidence)}</div>` : "";
    const tbl = a.table && a.table.length ? `<div class="table-scroll" style="margin-top:10px">${table(
      Object.keys(a.table[0]).map((k) => ({ label: k.replace(/_/g, " ").toUpperCase(), key: k })), a.table)}</div>` : "";
    const cht = a.table && a.table.length ? bars(a.table) : "";
    placeholder.outerHTML = `<div class="msg answer"><div class="who">${BOT}${a.provider ? ` · ${esc(a.provider)}` : ""}</div><div class="t">${esc(a.title)}</div><div>${md(a.narrative)}</div>${cht}${tbl}${ev}
      ${a.assumptions && a.assumptions.length ? `<div class="assump"><strong>Assumptions</strong><br/>${a.assumptions.map(esc).join("<br/>")}</div>` : ""}
      ${a.exclusions && a.exclusions.length ? `<div class="assump"><strong>Excluded / not determined</strong><br/>${a.exclusions.map(esc).join("<br/>")}</div>` : ""}
      ${a.uncertainties && a.uncertainties.length ? `<div class="assump"><strong>Uncertainty</strong><br/>${a.uncertainties.map(esc).join("<br/>")}</div>` : ""}</div>`;
    chatLog.push({ q, title: a.title, narrative: a.narrative, provider: a.provider || null });
    saveLog();
    saveThread();
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  } catch (e) {
    const raw = e.message || "request failed";
    const slow = /524|timeout|timed out|failed to fetch|network ?error|load failed|504|502/i.test(raw);
    placeholder.outerHTML = slow
      ? `<div class="msg answer"><div class="who">${BOT}</div><div class="t">Still thinking — the connection gave up first</div>
         <div>Your question is being worked on, but the answer is taking longer than the link allows
         (public links time out at ~100s; when Groq is rate-limited retries can take a few minutes).
         Nothing is broken — try one of these:</div>
         <div class="assump">Ask a smaller question (one line or supplier) · Use the bulk brief suggestion for whole-RFx analysis · Check Settings → Groq cloud: a second key doubles the quota · Your chat so far is saved</div>
         <div class="note">technical detail: ${esc(raw)}</div></div>`
      : `<div class="msg answer"><div class="who">${BOT}</div><div class="t">Something went wrong</div>${esc(raw)}</div>`;
    saveThread();
  }
  $("ask").disabled = false; $("btn-ask").disabled = false;
}

async function viewScenarios() {
  const [rfx, comparison] = [await api("/rfx"), await api("/comparison?eligible_only=0")];
  const suppliers = [...new Set(comparison.map((r) => r.supplier_id))].sort();
  VIEW.innerHTML = `
  <h2 class="view-title">What-if scenarios — recalc economics deterministically ${info("Ask 'what if supplier B gave 5% more?' and every affected line is recomputed through the real engines — no estimates.")}</h2>
  <div class="card" style="max-width:760px">
    <div class="filterbar">
      <select id="s-sup">${suppliers.map((s) => `<option value="${s}">${s}</option>`).join("")}</select>
      <label class="note">additional discount</label><input id="s-add" type="number" value="5" step="0.5" style="width:90px"/>
      <button class="btn primary" id="btn-run">Run scenario</button>
    </div>
    <div id="scn-out" class="note">Choose a supplier and discount, then run.</div>
  </div>
  <div class="card" style="margin-top:16px"><h3>Latest run</h3><div id="scn-table"></div></div>
  <div class="card" style="margin-top:16px"><h3>Award what-if — constraints, recomputed live</h3>
    <div class="filterbar">
      <label class="note">exclude</label>
      <select id="a-exc"><option value="">(nobody)</option>${suppliers.map((s) => `<option value="${s}">${s}</option>`).join("")}</select>
      <label class="note">max share %</label><input id="a-share" type="number" placeholder="—" style="width:80px"/>
      <label class="note">min suppliers</label><input id="a-min" type="number" placeholder="—" style="width:70px"/>
      <button class="btn primary" id="btn-award-run">Re-run award</button>
    </div>
    <div id="awd-out"></div>
  </div>`;
  $("btn-award-run").onclick = async () => {
    const body = { scenario_name: "Ad-hoc constrained award" };
    if ($("a-exc").value) body.supplier_exclusions = [$("a-exc").value];
    const sh = parseFloat($("a-share").value), mn = parseInt($("a-min").value);
    if (sh > 0) body.max_supplier_share = sh;
    if (mn > 0) body.min_qualified_suppliers = mn;
    $("awd-out").innerHTML = "<div class='spin' style='display:inline-block'></div>";
    try {
      const r = await api("/award", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body) });
      const share = r.awards_by_supplier || r.supplier_share || {};
      $("awd-out").innerHTML = `<div class="note">${r.line_count} lines awarded`
        + `${r.conditions_applied && r.conditions_applied.length ? ` · conditions: ${r.conditions_applied.map(esc).join("; ")}` : ""}</div>`
        + table([{ label: "Supplier", key: "s", render: (v) => supLabel(v) }, { label: "Lines", key: "n", num: true }],
          Object.entries(share).map(([s, n]) => ({ s, n })))
        + table([{ label: "Line", key: "line_number", render: (v, x) => `${lineLabel(v)}` },
          { label: "Winner", key: "supplier_id", render: (v) => supLabel(v) },
          { label: "Offer", key: "offer_id", render: (v) => `<span class="mono">${esc(v)}</span>` }],
          (r.awards || []).slice(0, 12),
          { rowAttr: (x) => `data-offer="${esc(x.offer_id)}" data-line="${x.line_number}"` })
        + ((r.awards || []).length > 12 ? `<div class="note">showing 12 of ${r.awards.length} — full split on the Award tab</div>` : "");
    } catch (e) { $("awd-out").innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  };
  $("btn-run").onclick = async () => {
    const sup = $("s-sup").value, add = parseFloat($("s-add").value) || 0;
    $("scn-out").textContent = "running…";
    const res = await api("/scenarios/run", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario_name: `+${add}% discount ${sup}`, additional_discounts: { [sup]: add } }) });
    $("scn-out").innerHTML = `${res.records.length} offers recalculated for ${esc(res.scenario)}.`;
    const rows = res.records.filter((r) => r.supplier_id === sup);
    $("scn-table").innerHTML = table(
      [{label:"Line", key:"line_number", render:(v)=>rfTag(v)},{label:"Supplier", key:"supplier_name"},
       {label:"Norm", key:"normalized_unit_price", num:true, render:(v)=>inr(v)},
       {label:"Discount benefit", key:"discount_benefit", num:true, render:(v)=>inr(v)},
       {label:"Financing", key:"financing_benefit", num:true, render:(v)=>inr(v)},
       {label:"Effective", key:"effective_economic_cost", num:true, render:(v)=>inr(v)},
       {label:"Eligible", key:"overall_eligible", render:(v)=> v?"ELIGIBLE":"INELIGIBLE"}], rows);
    $("scn-out").scrollIntoView({ behavior: "smooth" });
  };
}

async function viewAward() {
  const [res, rfx, conds, all, cov] = await Promise.all([
    api("/award/current"), api("/rfx"), api("/conditions").catch(() => []),
    api("/comparison?eligible_only=0&limit=500"), api("/coverage")]);
  await ensureLines(); await ensureSuppliers();
  const winByLine = {};
  res.awards.forEach((a) => { winByLine[a.line_number] = a; });
  const eligByLine = {};
  all.forEach((r) => {
    if (r.overall_eligible) (eligByLine[r.line_number] = eligByLine[r.line_number] || []).push(r);
  });
  Object.values(eligByLine).forEach((g) => g.sort(
    (a, b) => a.effective_economic_cost - b.effective_economic_cost));
  let total = 0, avgTotal = 0;
  const close = [], perSup = {};
  res.awards.forEach((a) => {
    const g = eligByLine[a.line_number] || [];
    const qty = (g[0] && g[0].required_quantity) || 0;
    const val = a.effective_economic_cost * qty;
    total += val;
    avgTotal += (g.reduce((s, r) => s + r.effective_economic_cost, 0) / Math.max(1, g.length)) * qty;
    const s = perSup[a.supplier_id] = perSup[a.supplier_id] || { lines: [], value: 0 };
    s.lines.push(a.line_number);
    s.value += val;
    if (g.length > 1 && g[0].effective_economic_cost > 0) {
      const m = (g[1].effective_economic_cost - g[0].effective_economic_cost)
        / g[0].effective_economic_cost * 100;
      if (m < 3) close.push({
        line_number: a.line_number, winner: a.supplier_id,
        winner_cost: g[0].effective_economic_cost, runner: g[1].supplier_id,
        runner_cost: g[1].effective_economic_cost, margin: m });
    }
  });
  const savings = avgTotal - total;
  const nsup = Object.keys(perSup).length;
  const maxVal = Math.max(1, ...Object.values(perSup).map((s) => s.value));
  const awardedLines = new Set(res.awards.map((a) => a.line_number));
  const unawarded = cov.filter((c) => !awardedLines.has(c.line_number));
  const supIds = Object.keys(perSup).sort((a, b) => perSup[b].value - perSup[a].value);
  VIEW.innerHTML = `
  <h2 class="view-title">Recommended award — ${esc(res.scenario_name)}
    <a class="btn ghost" href="/api/export/award" style="margin-left:12px;font-size:12px">Export CSV</a></h2>
  <div class="card verdict"><h3>The verdict ${info("The recommended split: cheapest eligible offer on each line. Total value = winner cost × required quantity, summed. Savings = what you would pay at the average eligible price instead.")}</h3>
    <div class="verdict-line">Award <strong>${res.line_count} of ${rfx.line_count} lines</strong>
      across <strong>${nsup} suppliers</strong> for <strong>${inr(total)}</strong> —
      <span class="good">${inr(savings)} below</span> the eligible-average baseline.</div>
    <div class="grid kpi-row" style="margin-top:14px">
      <div class="kpi"><div class="v" style="font-size:22px">${inr(total)}</div><div class="l">Total award value</div></div>
      <div class="kpi good"><div class="v" style="font-size:22px">${inr(savings)}</div><div class="l">Saved vs average</div></div>
      <div class="kpi"><div class="v">${res.line_count}/${rfx.line_count}</div><div class="l">Lines awarded</div></div>
      <div class="kpi ${close.length ? "warn" : ""}"><div class="v">${close.length}</div><div class="l">Close calls to review</div></div>
    </div>
    ${res.conditions_applied && res.conditions_applied.length
      ? `<div class="assump">Conditions shaping this award: ${res.conditions_applied.map(esc).join(" · ")}</div>` : ""}
  </div>
  <h2 class="view-title" style="margin-top:22px">Winners ${info("Who takes which lines and for how much. Line chips open the line; award value is winner cost × required quantity.")}</h2>
  <div class="grid cols-2">${supIds.map((s) => `
    <div class="card"><h3>${supLabel(s)} <span class="mono note">${esc(s)}</span></h3>
      <div class="grid kpi-row">
        <div class="kpi"><div class="v">${perSup[s].lines.length}</div><div class="l">Lines won</div></div>
        <div class="kpi"><div class="v" style="font-size:19px">${inr(perSup[s].value)}</div><div class="l">Award value</div></div>
      </div>
      <div class="bar-wrap" style="margin:10px 0"><div class="progress" style="flex:1"><div style="width:${(perSup[s].value / maxVal * 100).toFixed(0)}%"></div></div></div>
      <div>${perSup[s].lines.sort((a, b) => a - b).map((l) => `<button class="btn ghost" data-line="${l}" style="margin:0 6px 6px 0">${rfTag(l)}</button>`).join("")}</div>
    </div>`).join("")}</div>
  <div class="grid cols-2" style="margin-top:16px">
    <div class="card"><h3>Close calls — winner margin under 3% ${info("Lines where the runner-up is breathing down the winner's neck. Small data wobbles could flip these — review before signing.")}</h3>
      ${close.length ? table(
        [{ label: "Line", key: "line_number", render: (v) => lineLabel(v) },
         { label: "Winner", key: "winner", render: (v, r) => `${supLabel(v)} <span class="note">${inr(r.winner_cost)}</span>` },
         { label: "Runner-up", key: "runner", render: (v, r) => `${supLabel(v)} <span class="note">${inr(r.runner_cost)}</span>` },
         { label: "Margin", key: "margin", num: true, render: (v) => `<span class="note">${v.toFixed(2)}%</span>` }],
        close.sort((a, b) => a.margin - b.margin),
        { rowAttr: (r) => `data-line="${r.line_number}"` })
        : '<div class="empty">No close calls — every winner leads by 3%+.</div>'}
    </div>
    <div class="card"><h3>Not awarded — buyer action ${info("Lines with no winner (no quotes, or nothing eligible). Each names exactly what the buyer must do: re-tender, negotiate, or drop.")}</h3>
      ${unawarded.length ? table(
        [{ label: "Line", key: "line_number", render: (v, r) => `${lineLabel(v)}` },
         { label: "Status", key: "coverage_status" },
         { label: "Action", key: "buyer_action" }],
        unawarded, { rowAttr: (r) => `data-line="${r.line_number}"` })
        : '<div class="empty">Every line awarded.</div>'}
    </div>
  </div>
  <details class="card" style="margin-top:16px"><summary style="cursor:pointer"><strong>Full line-by-line decisions (${res.awards.length})</strong></summary>
    <div style="margin-top:12px">${table(
      [{ label: "Line", key: "line_number", render: (v, r) => `${lineLabel(v)}<br/><span class="mono note">${esc(r.supplier)} · ${esc(r.offer)}</span>` },
       { label: "Winner", key: "supplier", render: (v) => supLabel(v) },
       { label: "Effective cost", key: "cost", num: true, render: (v) => inr(v) },
       { label: "Rationale", key: "reason" }],
      res.awards.map((a) => ({ line_number: a.line_number, supplier: a.supplier_id,
        offer: a.offer_id, cost: a.effective_economic_cost, reason: a.decision_reason })),
      { rowAttr: (r) => `data-offer="${esc(r.offer)}" data-line="${r.line_number}"` })}</div>
  </details>
  <div class="card" style="margin-top:16px"><h3>Buyer conditions (plain English, enforced at award) ${info("Your rules — exclusions, share caps, lead/quality/validity/cost limits — written in plain words and applied to every award run. Anything the parser cannot understand is rejected with guidance, never guessed.")}</h3>
    <div class="filterbar">
      <input id="cd-text" placeholder='e.g. exclude SUP-004 · no supplier more than 40% · lead time max 10 days' style="flex:1;min-width:280px" />
      <button class="btn primary" id="btn-cond">Add condition</button>
    </div>
    <div id="cd-out" class="note">${conds.length ? "" : "No conditions — pure cheapest-eligible award."}</div>
    <div id="cd-list">${conds.map((c) => `
      <div class="filterbar" style="gap:8px">
        <span class="note">#${c.condition_id}</span>
        <span>${esc(c.value_text || c.kind)}${c.target ? ` <span class="mono">${esc(c.target)}</span>` : ""}</span>
        <span class="note">${esc(c.kind)} · ${esc(c.source || "")}</span>
        <button class="btn ghost" data-tog="${c.condition_id}">${c.active ? "Disable" : "Enable"}</button>
        <button class="btn ghost" data-del="${c.condition_id}">Delete</button>
      </div>`).join("")}</div>
    ${res.conditions_applied && res.conditions_applied.length
      ? `<div class="assump">Applied to this award: ${res.conditions_applied.map(esc).join(" · ")}</div>` : ""}
  </div>`;
  const refreshAward = () => document.querySelector('.tab[data-tab="award"]').click();
  $("btn-cond").onclick = async () => {
    const t = $("cd-text").value.trim();
    if (!t) return;
    try {
      await api("/conditions", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: t }) });
      toast("Condition added — award recomputed", true);
      refreshAward();
    } catch (e) { $("cd-out").textContent = e.message; }
  };
  $("cd-text").onkeydown = (e) => { if (e.key === "Enter") $("btn-cond").click(); };
  VIEW.querySelectorAll("[data-tog]").forEach((b) => (b.onclick = async () => {
    const on = b.textContent === "Disable";
    await api(`/conditions/${b.dataset.tog}`, { method: "PATCH",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ active: !on }) });
    refreshAward();
  }));
  VIEW.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    await api(`/conditions/${b.dataset.del}`, { method: "DELETE" });
    refreshAward();
  }));
}

async function viewTrust() {
  const [unc, evidence] = [await api("/uncertainties"), await api("/offers?eligible=0")];
  await ensureLines();
  VIEW.innerHTML = `
  <h2 class="view-title">Trust &amp; Evidence — what we believe and why ${info("Every shaky record in one place, and the source file behind every single figure. Nothing here is taken on faith.")}</h2>
  <div class="grid cols-2">
    <div class="card"><h3>Uncertain, review-required and unresolved records</h3>
      <div class="table-scroll">${table(
        [{label:"Line", key:"line", render:(v)=>lineLabel(v)},{label:"Supplier", key:"supplier_name"},
         {label:"State", key:"field_state", render:(v)=> v==="requires_review"?badge("warn","REVIEW"):v==="UOM_UNRESOLVED"?badge("bad","UOM_UNRESOLVED"):badge("warn",v||"REVIEW")},
         {label:"Extract conf.", key:"extraction_confidence", render:(v)=> v==="HIGH"?badge("good",v):badge("warn",v)},
          {label:"Note", key:"note"}], unc,
        { rowAttr: (r) => (r.line ? `data-line="${r.line}"` : "") })}</div></div>
    <div class="card"><h3>Every figure traces to evidence</h3>
      <div class="table-scroll">${table(
        [{label:"Offer", key:"offer_id", render:(v)=>`<span class="mono">${v}</span>`},
         {label:"Supplier", key:"supplier_name"},{label:"Source file", key:"source_file", render:(v)=>`<span class="mono">${esc(v)}</span>`},
         {label:"Source type", key:"source_type"},{label:"Location", key:"source_location", render:(v)=>`<span class="mono">${esc(v)}</span>`},
         {label:"Conf.", key:"extraction_confidence", render:(v)=> v==="HIGH"?badge("good",v):badge("warn",v)},
         {label:"Verify", key:"verification_status"}], evidence,
        { rowAttr: (r) => `data-offer="${esc(r.offer_id)}"` })}</div></div>
  </div>`;
}

/* ------------------------------------------------------------------ boot */
const ROUTES = { overview: viewOverview, rfx: viewRfx, ingestion: viewIngestion,
  comparison: viewComparison, aerbot: viewAerBot, scenarios: viewScenarios,
  award: viewAward, trust: viewTrust, settings: viewSettings };

async function viewSettings() {
  const st = await api("/settings/provider").catch(() => ({ groq_keys: [] }));
  VIEW.innerHTML = `
  <h2 class="view-title">Settings</h2>
  <div class="card" style="max-width:720px"><h3>Groq keys ${info("Your API keys, tried top to bottom — the next takes over on rate limits. Saved on this server, so every open instance (this device or others on the link) shares the same pool. Keys never leave this server except to Groq itself.")}</h3>
    <div id="groq-status" class="note"></div>
    <div id="key-list" style="margin:6px 0"></div>
    <div class="filterbar" style="margin-bottom:0">
      <input id="set-key" type="password" placeholder="paste a gsk-… key (free at console.groq.com/keys)" style="width:280px" autocomplete="off" />
      <button class="btn primary" id="btn-add-key">Add key</button>
    </div>
    <div id="set-out" class="note"></div>
  </div>
  <div class="card" style="max-width:720px;margin-top:16px"><h3>Model data ${info("Factory reset rebuilds the golden dataset and wipes everything added since: uploads, buyer conditions, RFx drafts, and chat memory. Saved Groq keys are kept.")}</h3>
    <div class="filterbar" style="margin-top:10px">
      <button class="btn ghost" id="btn-factory">Factory reset</button>
      <span class="note">golden rebuild + wipe uploads, conditions, drafts — pristine demo state</span>
    </div>
  </div>`;
  let keyState = st.groq_keys || [];
  const postSettings = async (body) => {
    const s = await api("/settings/provider", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) });
    if (s.groq_keys) { keyState = s.groq_keys; renderKeys(); }
    return s;
  };
  const renderKeys = () => {
    const status = $("groq-status");
    status.innerHTML = keyState.length
      ? `<span class="badge good">${keyState.length} key${keyState.length > 1 ? "s" : ""} active</span>`
      : `<span class="badge warn">NO KEYS — AerBot cannot answer until you add one</span>`;
    const box = $("key-list");
    box.innerHTML = keyState.length ? keyState.map((k, i) => `
      <div class="prov-row">
        <span class="note">#${i + 1}</span>
        <span class="mono">${esc(k.hint)}</span>
        <button class="btn ghost" data-rmkey="${k.index}">Remove</button>
      </div>`).join("") : `<div class="note">No keys saved — paste one above (free at console.groq.com/keys).</div>`;
    box.querySelectorAll("[data-rmkey]").forEach((b) => (b.onclick = async () => {
      try {
        await postSettings({ groq_keys_remove: +b.dataset.rmkey });
        toast("Key removed", true);
      } catch (e) { $("set-out").textContent = e.message; }
    }));
  };
  renderKeys();
  const addKey = async () => {
    const key = $("set-key").value.trim();
    if (!key) return;
    $("set-out").textContent = "validating key with Groq…";
    try {
      const s = await postSettings({ groq_keys_add: key });
      $("set-key").value = "";
      $("set-out").textContent = `key added — ${s.groq_keys.length} key${s.groq_keys.length > 1 ? "s" : ""} in the shared pool`;
      toast("Key added", true);
    } catch (e) { $("set-out").textContent = e.message; }
  };
  $("btn-add-key").onclick = addKey;
  $("set-key").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); addKey(); }
  });
  let armed = false, armTimer = null;
  $("btn-factory").onclick = async () => {
    if (!armed) {
      armed = true;
      $("btn-factory").textContent = "Confirm reset?";
      armTimer = setTimeout(() => {
        armed = false;
        const b = $("btn-factory");
        if (b) b.textContent = "Factory reset";
      }, 4000);
      return;
    }
    clearTimeout(armTimer);
    $("btn-factory").disabled = true;
    $("btn-factory").textContent = "resetting…";
    try {
      const r = await api("/system/factory-reset", { method: "POST" });
      toast(`Pristine state restored (${r.uploads_removed} uploads, ${r.conditions_removed} conditions, ${r.drafts_removed} drafts wiped)`, true);
      viewSettings();
    } catch (e) {
      $("btn-factory").disabled = false;
      $("btn-factory").textContent = "Factory reset";
      toast(e.message);
    }
  };
}

document.querySelectorAll(".tab").forEach((t) => {
  t.onclick = async () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    const name = t.dataset.tab;
    VIEW.innerHTML = `<div class="empty"><div class="spin" style="display:inline-block"></div> loading…</div>`;
    try { await ROUTES[name](); } catch (e) { VIEW.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  };
});

$("btn-reset").onclick = async () => {
  $("btn-reset").disabled = true; $("btn-reset").textContent = "re-seeding…";
  const r = await api("/system/reset", { method: "POST" });
  toast(`Fresh dataset dealt (seed ${r.seed}). Switching to Overview.`, true);
  $("btn-reset").textContent = "Re-seed data"; $("btn-reset").disabled = false;
  setTitle();
  document.querySelector('.tab[data-tab="overview"]').click();
};

api("/settings/access").then((s) => {
  if (s.gate) $("btn-logout").style.display = "";
}).catch(() => {});
$("btn-logout").onclick = async () => {
  await api("/auth/logout", { method: "POST" }).catch(() => {});
  location.href = "/login";
};

setTitle();
document.querySelector('.tab[data-tab="overview"]').click();