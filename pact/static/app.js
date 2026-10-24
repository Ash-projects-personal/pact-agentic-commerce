"use strict";

let scenarios = [];
let currentDeal = null;
// Per-deal role tokens (queue item W). The create response and the deal
// view carry both tokens; the UI holds them in memory and sends the
// right one on each state-changing call. Deal ids are random and the
// tokens are bearer capabilities, so this is demo-grade role separation,
// not real user auth.
let dealTokens = { buyer: null, seller: null };
let gridApi = null;
let ledgerRows = [];
let currentLedgerDealId = null;
let expandedSeqs = new Set();
let repChart = null;
let lastAgents = [];

const $ = (id) => document.getElementById(id);

async function api(path, method, body, role) {
  const opts = { method: method || "GET", headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  // Role is "buyer" or "seller" on state-changing deal calls; the
  // matching per-deal token rides the X-Deal-Token header.
  if (role && dealTokens[role]) opts.headers["X-Deal-Token"] = dealTokens[role];
  const resp = await fetch(path, opts);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text);
  }
  return resp.json();
}

function repClass(score) {
  if (score >= 75) return "high";
  if (score >= 50) return "mid";
  return "low";
}

function renderAgents(agents) {
  lastAgents = agents || [];
  $("agentList").innerHTML = lastAgents.map((a) => (
    '<div class="agent">' +
    '<span class="rep ' + repClass(a.reputation) + '">' + a.reputation + "</span>" +
    '<div class="name">' + a.name + "</div>" +
    '<div class="persona">' + a.persona + " · " + a.deals + " deals settled</div>" +
    '<div class="repbar"><div class="repfill ' + repClass(a.reputation) +
    '" style="width:' + Math.max(0, Math.min(100, a.reputation)) + '%"></div></div>' +
    "</div>"
  )).join("");
  renderRepChart(lastAgents);
}

function chartsLib() {
  if (window.AgCharts) return window.AgCharts;
  if (window.agCharts && window.agCharts.AgCharts) return window.agCharts.AgCharts;
  return null;
}

function renderRepChart(agents) {
  const wrap = $("repChart");
  if (!wrap) return;
  const lib = chartsLib();
  if (!lib || !agents || !agents.length) {
    wrap.style.display = "none";
    return;
  }
  wrap.style.display = "";
  const data = agents.map((a) => ({
    agent: String(a.name).replace(/ Agent$/, ""),
    reputation: a.reputation,
  }));
  const options = {
    container: wrap,
    data: data,
    title: { text: "Reputation by agent", fontSize: 12, color: "#5d6b7a" },
    series: [{
      type: "bar", direction: "horizontal",
      xKey: "agent", yKey: "reputation",
      fill: "#0b5fff", strokeWidth: 0,
    }],
    axes: [
      { type: "category", position: "left", label: { fontSize: 10 } },
      {
        type: "number", position: "bottom", min: 0, max: 100,
        label: { fontSize: 10 }, gridLine: { enabled: true },
      },
    ],
    padding: { top: 2, right: 10, bottom: 2, left: 4 },
    legend: { enabled: false },
  };
  try {
    if (repChart) {
      repChart.update(options);
    } else {
      repChart = lib.create(options);
    }
  } catch (err) {
    try {
      if (repChart && typeof repChart.destroy === "function") repChart.destroy();
    } catch (e) { /* already gone */ }
    repChart = null;
    wrap.replaceChildren();
    try {
      repChart = lib.create(options);
    } catch (e2) {
      wrap.style.display = "none";
    }
  }
}

async function refreshAgents() {
  const agents = await api("/api/agents");
  renderAgents(agents);
}

const MONEY_EVENTS = new Set([
  "payment_approval_requested", "bond_approval_requested", "payment_held",
  "bond_posted", "payment_released", "bond_returned", "buyer_refunded",
  "bond_slashed",
]);
const BAD_EVENTS = new Set([
  "buyer_refunded", "bond_slashed", "negotiation_failed", "payment_error",
  "webhook_rejected", "revision_skipped",
]);

function eventFamily(t) {
  if (MONEY_EVENTS.has(t)) return "money";
  if (t === "reputation_change") return "rep";
  if (t.startsWith("verification") || t.startsWith("revision")) return "verify";
  if (t.startsWith("negotiation") || t === "price_agreed" ||
      t === "contract_written" || t === "deal_created") return "deal";
  return "sys";
}

const EVENT_LABELS = {
  deal_created: "Deal created",
  negotiation_move: "Negotiation move",
  price_agreed: "Price agreed",
  contract_written: "Contract written",
  negotiation_failed: "Negotiation failed",
  payment_approval_requested: "Payment approval requested",
  bond_approval_requested: "Bond approval requested",
  payment_held: "Payment held",
  bond_posted: "Bond posted",
  payment_released: "Payment released",
  bond_returned: "Bond returned",
  buyer_refunded: "Buyer refunded",
  bond_slashed: "Bond slashed",
  bond_too_small: "Bond too small",
  payment_error: "Payment error",
  delivery_submitted: "Delivery submitted",
  revision_submitted: "Revision submitted",
  revision_requested: "Revision requested",
  revision_skipped: "Revision skipped",
  verification_check: "Verification check",
  verification_summary: "Verification summary",
  reputation_change: "Reputation changed",
  webhook_received: "Webhook received",
  webhook_rejected: "Webhook rejected",
  quality_knob_ignored: "Quality setting ignored",
};

function eventLabel(t) {
  if (EVENT_LABELS[t]) return EVENT_LABELS[t];
  const s = String(t || "").replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

const PAYLOAD_LABELS = {
  order_id: "Order ID",
  capture_id: "Capture ID",
  payout_batch_id: "Payout batch ID",
  refund_id: "Refund ID",
  amount: "Amount (USD)",
  mode: "Mode",
  rail: "Rail",
  check_id: "Check",
  passed: "Passed",
  measured: "Measured",
  required: "Required",
  total: "Total checks",
  approval_url: "Approval link",
  request_id: "Request ID",
  capture_request_id: "Capture request ID",
  version: "Version",
  words: "Words",
};

function payloadLabel(key) {
  if (PAYLOAD_LABELS[key]) return PAYLOAD_LABELS[key];
  const s = String(key).replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function payloadValueText(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function EventPillRenderer(params) {
  const span = document.createElement("span");
  span.className = "evpill " + eventFamily(params.value);
  span.textContent = eventLabel(params.value);
  span.title = params.value || "";
  return span;
}

function PayloadRenderer(params) {
  const data = (params.data && params.data._payload) || {};
  const wrap = document.createElement("div");
  wrap.className = "payload";
  const title = document.createElement("div");
  title.className = "payload-title";
  title.textContent = "Event data for #" + params.data.seq +
    " (" + params.data.event_type + ")";
  wrap.appendChild(title);
  const keys = Object.keys(data);
  if (!keys.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = "No extra data recorded on this event.";
    wrap.appendChild(p);
    return wrap;
  }
  const table = document.createElement("table");
  table.className = "payload-table";
  keys.forEach((key) => {
    const tr = document.createElement("tr");
    const tdKey = document.createElement("td");
    tdKey.className = "pk";
    tdKey.textContent = payloadLabel(key);
    const tdVal = document.createElement("td");
    tdVal.className = "pv";
    if (key === "approval_url" && data[key]) {
      const a = document.createElement("a");
      a.href = String(data[key]);
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = "Open the approval page";
      tdVal.appendChild(a);
    } else {
      tdVal.textContent = payloadValueText(data[key]);
    }
    tr.appendChild(tdKey);
    tr.appendChild(tdVal);
    table.appendChild(tr);
  });
  wrap.appendChild(table);
  return wrap;
}

class NoRowsOverlay {
  init() {
    this.eGui = document.createElement("div");
    this.eGui.className = "no-rows-msg";
    this.eGui.textContent =
      "No ledger events yet. Run a deal and every step lands here, in order.";
  }
  getGui() { return this.eGui; }
  refresh() { return false; }
}

const COL_STATE_KEY = "pact-ledger-columns-v1";

function saveColumnState() {
  if (!gridApi) return;
  try {
    localStorage.setItem(COL_STATE_KEY, JSON.stringify(gridApi.getColumnState()));
  } catch (e) { /* storage can be unavailable; the grid still works */ }
}

function restoreColumnState() {
  if (!gridApi) return;
  try {
    const raw = localStorage.getItem(COL_STATE_KEY);
    if (raw) gridApi.applyColumnState({ state: JSON.parse(raw), applyOrder: true });
  } catch (e) { /* a bad saved state must never break the grid */ }
}

function buildDisplayRows() {
  const out = [];
  ledgerRows.forEach((r) => {
    out.push(r);
    if (expandedSeqs.has(r.seq)) {
      out.push({
        _detail: true,
        seq: r.seq,
        event_type: r.event_type,
        _payload: r.data || {},
      });
    }
  });
  return out;
}

function keepDetailsWithParents(params) {
  const nodes = params.nodes;
  const details = new Map();
  const parents = [];
  nodes.forEach((n) => {
    if (n.data && n.data._detail) {
      const list = details.get(n.data.seq) || [];
      list.push(n);
      details.set(n.data.seq, list);
    } else {
      parents.push(n);
    }
  });
  const ordered = [];
  parents.forEach((n) => {
    ordered.push(n);
    (details.get(n.data.seq) || []).forEach((d) => ordered.push(d));
  });
  nodes.length = 0;
  ordered.forEach((n) => nodes.push(n));
}

function formatLedgerTime(value) {
  const d = new Date(value);
  if (isNaN(d)) return value == null ? "" : String(value);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" }) +
    " " + d.toLocaleTimeString("en-GB");
}

function rowAmount(row) {
  if (!row || row._detail) return null;
  const a = row.data && row.data.amount;
  return typeof a === "number" ? a : null;
}

function formatUsd(n) {
  return "$" + Number(n).toFixed(2);
}

function setupGrid() {
  const el = $("ledgerGrid");
  const columnDefs = [
    { field: "seq", headerName: "#", width: 55, filter: true },
    {
      field: "timestamp", headerName: "Time", width: 150, filter: true,
      valueFormatter: (p) => formatLedgerTime(p.value),
    },
    {
      field: "event_type", headerName: "Event", width: 200, filter: true,
      cellRenderer: EventPillRenderer, cellClass: "event-cell",
      headerTooltip: "Click an event to open its data",
    },
    { field: "actor", headerName: "Actor", width: 95, filter: true },
    {
      headerName: "Amount", width: 110, filter: true,
      valueGetter: (p) => rowAmount(p.data),
      valueFormatter: (p) => (p.value == null ? "" : formatUsd(p.value)),
    },
    {
      field: "message", headerName: "Detail", flex: 1, filter: true,
      wrapText: true, autoHeight: true,
    },
  ];
  if (window.agGrid && window.agGrid.createGrid) {
    const opts = {
      columnDefs: columnDefs,
      rowData: [],
      defaultColDef: {
        sortable: true, resizable: true, filter: true, floatingFilter: true,
      },
      animateRows: true,
      enableCellTextSelection: true,
      getRowId: (p) => (p.data._detail ? "detail-" + p.data.seq : String(p.data.seq)),
      isFullWidthRow: (params) => {
        const node = params && params.rowNode ? params.rowNode : params;
        return !!(node && node.data && node.data._detail);
      },
      fullWidthCellRenderer: PayloadRenderer,
      postSortRows: keepDetailsWithParents,
      noRowsOverlayComponent: NoRowsOverlay,
      rowClassRules: {
        "row-bad": (p) => !!p.data && BAD_EVENTS.has(p.data.event_type),
        "row-money": (p) => !!p.data && MONEY_EVENTS.has(p.data.event_type),
      },
      onCellClicked: (p) => {
        if (!p.data || p.data._detail) return;
        if (!p.colDef || p.colDef.field !== "event_type") return;
        if (expandedSeqs.has(p.data.seq)) expandedSeqs.delete(p.data.seq);
        else expandedSeqs.add(p.data.seq);
        gridApi.setGridOption("rowData", buildDisplayRows());
      },
      onColumnMoved: saveColumnState,
      onColumnResized: saveColumnState,
      onSortChanged: saveColumnState,
    };
    if (window.agGrid.themeQuartz) {
      opts.theme = window.agGrid.themeQuartz.withParams({
        backgroundColor: "#ffffff",
        foregroundColor: "#1d2733",
        accentColor: "#0b5fff",
        headerBackgroundColor: "#1d2733",
        headerTextColor: "#eaf1f8",
        borderColor: "#dbe2ea",
        rowHoverColor: "#eef3f9",
        fontFamily: "inherit",
        fontSize: 13,
      });
    }
    try {
      gridApi = window.agGrid.createGrid(el, opts);
      restoreColumnState();
    } catch (err) {
      gridApi = null;
    }
  }
  if (!gridApi) {
    el.style.height = "auto";
    const note = document.createElement("p");
    note.className = "muted";
    note.textContent = "AG Grid did not load. The ledger will render as a plain table instead.";
    const fb = document.createElement("div");
    fb.id = "ledgerFallback";
    el.replaceChildren(note, fb);
  }
  wireLedgerTools();
  renderKpis([]);
}

function wireLedgerTools() {
  const filterInput = $("ledgerFilter");
  if (filterInput) {
    filterInput.addEventListener("input", () => {
      if (gridApi) {
        gridApi.setGridOption("quickFilterText", filterInput.value);
      } else {
        renderFallback();
      }
    });
  }
  const exportBtn = $("exportCsvBtn");
  if (exportBtn) {
    exportBtn.disabled = !gridApi;
    exportBtn.title = gridApi ? "" : "CSV export needs the grid view";
    exportBtn.addEventListener("click", exportLedgerCsv);
  }
  const resetBtn = $("resetViewBtn");
  if (resetBtn) {
    resetBtn.addEventListener("click", resetLedgerView);
  }
}

function exportLedgerCsv() {
  if (!gridApi) return;
  const hadExpanded = expandedSeqs.size > 0;
  if (hadExpanded) gridApi.setGridOption("rowData", ledgerRows);
  gridApi.exportDataAsCsv({ fileName: "pact-audit-ledger.csv" });
  if (hadExpanded) gridApi.setGridOption("rowData", buildDisplayRows());
}

function resetLedgerView() {
  const filterInput = $("ledgerFilter");
  if (filterInput) filterInput.value = "";
  if (gridApi) {
    gridApi.setFilterModel(null);
    gridApi.setGridOption("quickFilterText", "");
    gridApi.resetColumnState();
    try { localStorage.removeItem(COL_STATE_KEY); } catch (e) { /* fine */ }
  } else {
    renderFallback();
  }
}

function renderKpis(rawLedger) {
  const strip = $("ledgerKpis");
  if (!strip) return;
  const deal = currentDeal;
  let heldValue = "$0.00";
  let heldNote = "Nothing held right now";
  if (deal && deal.payment && deal.payment.status === "held") {
    heldValue = formatUsd(deal.payment.amount || (deal.spec ? deal.spec.price : 0));
    heldNote = "Price held in the deal ledger";
  }
  let bondValue = "$0.00";
  let bondNote = "No bond posted";
  if (deal && deal.bond && deal.bond.status === "posted") {
    bondValue = formatUsd(deal.bond.amount || (deal.spec ? deal.spec.bond_amount : 0));
    bondNote = "Seller bond at risk";
  }
  let checksValue = "Not run yet";
  let checksNote = "Run verification to see the verdict";
  if (deal && deal.verification) {
    const v = deal.verification;
    checksValue = v.passed_count + " of " + v.total_count;
    checksNote = Math.round((v.passed_count / v.total_count) * 100) +
      " percent of checks passed";
  }
  const tiles = [
    { k: "Money held", v: heldValue, s: heldNote },
    { k: "Bond at risk", v: bondValue, s: bondNote },
    { k: "Checks passed", v: checksValue, s: checksNote },
    { k: "Ledger events", v: String((rawLedger || []).length), s: "Every step, in order" },
  ];
  strip.replaceChildren(...tiles.map((t) => {
    const tile = document.createElement("div");
    tile.className = "kpi";
    const k = document.createElement("div");
    k.className = "k";
    k.textContent = t.k;
    const v = document.createElement("div");
    v.className = "v";
    v.textContent = t.v;
    const s = document.createElement("div");
    s.className = "s";
    s.textContent = t.s;
    tile.appendChild(k);
    tile.appendChild(v);
    tile.appendChild(s);
    return tile;
  }));
}

function renderFallback() {
  const fb = $("ledgerFallback");
  if (!fb) return;
  const filterInput = $("ledgerFilter");
  const q = filterInput ? filterInput.value.trim().toLowerCase() : "";
  const visible = ledgerRows.filter((r) => {
    if (!q) return true;
    const hay = [r.event_type, eventLabel(r.event_type), r.actor, r.message]
      .join(" ").toLowerCase();
    return hay.includes(q);
  });
  // Build the fallback table with textContent, never innerHTML:
  // ledger fields such as event_type can carry text that arrived in
  // a webhook payload, and injecting them raw would be a stored XSS
  // hole in exactly the table meant to be the safe fallback.
  const table = document.createElement("table");
  table.className = "plain";
  const head = document.createElement("tr");
  ["#", "Time", "Event", "Actor", "Amount", "Detail"].forEach((label) => {
    const th = document.createElement("th");
    th.textContent = label;
    head.appendChild(th);
  });
  table.appendChild(head);
  if (!visible.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.textContent =
      "No ledger events yet. Run a deal and every step lands here, in order.";
    tr.appendChild(td);
    table.appendChild(tr);
  }
  visible.forEach((r) => {
    const tr = document.createElement("tr");
    tr.className = "fallback-row";
    tr.title = "Click to open the event data";
    const amount = rowAmount(r);
    const cells = [
      String(r.seq),
      formatLedgerTime(r.timestamp),
      eventLabel(r.event_type),
      r.actor == null ? "" : String(r.actor),
      amount == null ? "" : formatUsd(amount),
      r.message == null ? "" : String(r.message),
    ];
    cells.forEach((value) => {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    });
    tr.addEventListener("click", () => {
      if (expandedSeqs.has(r.seq)) expandedSeqs.delete(r.seq);
      else expandedSeqs.add(r.seq);
      renderFallback();
    });
    table.appendChild(tr);
    if (expandedSeqs.has(r.seq)) {
      const dtr = document.createElement("tr");
      const dtd = document.createElement("td");
      dtd.colSpan = 6;
      const box = document.createElement("div");
      box.className = "payload";
      const data = r.data || {};
      const keys = Object.keys(data);
      if (!keys.length) {
        box.textContent = "No extra data recorded on this event.";
      } else {
        keys.forEach((key) => {
          const line = document.createElement("div");
          const strong = document.createElement("strong");
          strong.textContent = payloadLabel(key) + ": ";
          line.appendChild(strong);
          line.appendChild(document.createTextNode(payloadValueText(data[key])));
          box.appendChild(line);
        });
      }
      dtd.appendChild(box);
      dtr.appendChild(dtd);
      table.appendChild(dtr);
    }
  });
  fb.replaceChildren(table);
}

function renderLedger(ledger) {
  const raw = (ledger || []).slice();
  const dealId = raw.length ? raw[0].deal_id : currentLedgerDealId;
  if (dealId !== currentLedgerDealId) {
    currentLedgerDealId = dealId;
    expandedSeqs = new Set();
  }
  ledgerRows = raw.slice().reverse();
  renderKpis(raw);
  if (gridApi) {
    gridApi.setGridOption("rowData", buildDisplayRows());
  } else {
    renderFallback();
  }
}

function moveLabel(move) {
  if (move.kind === "price") return "Price move · " + move.price + " USD";
  if (move.kind === "walkaway") return "Walk away";
  return "Contract · " + (move.check_id || "") + (move.value !== null && move.value !== undefined ? " · " + move.value : "");
}

function renderThread(deal) {
  if (!deal || !deal.moves.length) return;
  $("thread").innerHTML = deal.moves.map((m) => (
    '<div class="move ' + (m.actor === "buyer" ? "buyer" : "seller") + '">' +
    '<div class="meta">' + m.actor + " · " + moveLabel(m) + "</div>" +
    "<p>" + m.rationale + "</p></div>"
  )).join("");
  const thread = $("thread");
  thread.scrollTop = thread.scrollHeight;
}

function renderSpec(deal) {
  if (!deal || !deal.spec) return;
  const s = deal.spec;
  const checks = s.acceptance_checks.map((c) => {
    const req = c.kind === "contains" ? "must include: " + c.value : "at least " + c.value + " " + (c.unit || "");
    return "<tr><td>" + c.label + "</td><td>" + req + "</td><td>" + c.settled_note + "</td></tr>";
  }).join("");
  $("specCard").innerHTML =
    '<div class="spec-grid">' +
    '<div class="spec-stat"><div class="k">Agreed price</div><div class="v">' + s.price + " USD</div></div>" +
    '<div class="spec-stat"><div class="k">Performance bond</div><div class="v">' + s.bond_amount + " USD</div></div>" +
    '<div class="spec-stat"><div class="k">Bond rate</div><div class="v">' + s.bond_percent + " percent</div></div>" +
    '<div class="spec-stat"><div class="k">Checks written by</div><div class="v">The agents</div></div>' +
    "</div>" +
    "<p class='muted'>" + s.revision_policy + "</p>" +
    "<table class='plain'><tr><th>Acceptance check</th><th>Agreed requirement</th><th>How it settled</th></tr>" + checks + "</table>";
}

function timelineSteps(deal) {
  const steps = [];
  const st = deal ? deal.state : "none";
  steps.push({ label: "Deal created", done: !!deal });
  steps.push({ label: "Negotiation finished", done: !!deal && st !== "negotiating" || (deal && deal.moves.length > 0 && !!deal.spec) });
  steps.push({ label: "Contract frozen with agent written checks", done: !!deal && !!deal.spec });
  const pay = deal ? deal.payment.status : "not_started";
  steps.push({ label: "Payment held: " + (deal && deal.payment.amount ? deal.payment.amount + " USD" : "") + (deal && deal.payment.mode ? " (" + deal.payment.mode + " mode)" : ""), done: ["held", "released", "refunded"].includes(pay) });
  const bond = deal ? deal.bond.status : "not_posted";
  steps.push({ label: "Performance bond posted: " + (deal && deal.bond.amount ? deal.bond.amount + " USD" : ""), done: ["posted", "returned", "slashed"].includes(bond) });
  steps.push({ label: "Delivery submitted", done: !!deal && !!deal.deliverable });
  if (deal && deal.revision_used) steps.push({ label: "Revision round used", done: true });
  steps.push({ label: "Verification complete", done: !!deal && !!deal.verification && ["released", "refunded"].includes(st) });
  if (deal && st === "released") {
    steps.push({ label: "Payment released to seller", done: true });
    steps.push({ label: "Bond returned to seller", done: bond === "returned" });
  }
  if (deal && st === "refunded") {
    steps.push({ label: "Buyer refunded in full", done: true, bad: true });
    steps.push({ label: "Bond slashed to buyer", done: bond === "slashed", bad: true });
  }
  if (deal && st === "failed") steps.push({ label: "Negotiation failed, no money moved", done: true, bad: true });
  return steps;
}

function renderTimeline(deal) {
  $("timeline").innerHTML = timelineSteps(deal).map((s) =>
    '<li class="' + (s.done ? "done" : "") + (s.bad ? " bad" : "") + '">' + s.label + "</li>"
  ).join("");
}

function renderVerification(deal) {
  if (!deal || !deal.verification) return;
  const v = deal.verification;
  $("verification").innerHTML =
    "<p><strong>Round " + v.round + ":</strong> " + v.passed_count + " of " + v.total_count + " negotiated checks passed.</p>" +
    v.results.map((r) => (
      '<div class="check"><span class="pill ' + (r.passed ? "pass" : "fail") + '">' + (r.passed ? "PASS" : "FAIL") + "</span>" +
      "<div><div>" + r.label + "</div><div class='reason'>" + r.reason + "</div></div></div>"
    )).join("");
}

function renderDeal(deal) {
  currentDeal = deal;
  if (!deal) return;
  // Keep the role tokens from the freshest deal view, so the next
  // state-changing click carries them.
  dealTokens = { buyer: deal.buyer_token || null, seller: deal.seller_token || null };
  $("stateLine").textContent = "Deal " + deal.id + " · state: " + deal.state +
    " · buyer rep " + deal.buyer_agent.reputation + " · seller rep " + deal.seller_agent.reputation;
  const disputeRow = $("disputePacketRow");
  if (disputeRow) {
    disputeRow.hidden = false;
    $("disputePacketLink").href = "/api/deals/" + deal.id + "/dispute-packet";
  }
  $("negotiateBtn").disabled = deal.state !== "negotiating";
  $("payBtn").disabled = deal.state !== "agreed";
  $("deliverBtn").disabled = !["paid_held", "revision"].includes(deal.state);
  $("verifyBtn").disabled = deal.state !== "delivered";
  const panel = $("approvalPanel");
  if (deal.state === "awaiting_approval") {
    panel.hidden = false;
    $("approvePayLink").href = deal.payment.approval_url || "#";
    $("approveBondLink").href = deal.bond.approval_url || "#";
  } else {
    panel.hidden = true;
  }
  renderThread(deal);
  renderSpec(deal);
  renderTimeline(deal);
  renderVerification(deal);
  renderLedger(deal.ledger);
  if (deal.deliverable) {
    $("deliverable").textContent = deal.deliverable.content;
  }
  renderAgents([deal.buyer_agent, deal.seller_agent]);
  refreshAgents();
}

async function init() {
  const health = await api("/api/health");
  const badge = $("modeBadge");
  if (health.mode === "demo") {
    badge.textContent = "DEMO MODE: local payment simulator";
  } else {
    badge.textContent = "PayPal sandbox live";
    badge.classList.add("live");
  }
  $("llmBadge").textContent = health.llm_enabled ? "LLM rationales on" : "LLM off: deterministic engine";
  $("bondPct").textContent = health.bond_percent_default;

  scenarios = await api("/api/scenarios");
  const sel = $("scenarioSelect");
  sel.innerHTML = scenarios.map((s) => '<option value="' + s.id + '">' + s.title + "</option>").join("");
  const applyScenario = () => {
    const s = scenarios.find((x) => x.id === sel.value);
    if (!s) return;
    $("scenarioSummary").textContent = s.service_summary + " Seller: " + s.seller.name + " (reputation " + s.seller.reputation + ").";
    $("buyerMax").value = s.default_buyer_max;
    $("sellerFloor").value = s.default_seller_floor;
  };
  sel.addEventListener("change", applyScenario);
  applyScenario();
  setupGrid();
  refreshAgents();

  $("createBtn").addEventListener("click", async () => {
    const deal = await api("/api/deals", "POST", {
      scenario_id: sel.value,
      buyer_max: parseFloat($("buyerMax").value),
      seller_floor: parseFloat($("sellerFloor").value),
    });
    $("thread").innerHTML = '<p class="muted">Deal created. Run the negotiation.</p>';
    $("specCard").innerHTML = '<p class="muted">The frozen contract appears here after negotiation.</p>';
    $("deliverable").textContent = "Nothing delivered yet.";
    $("verification").innerHTML = '<p class="muted">The verifier judges the delivery against the negotiated checks only.</p>';
    renderDeal(deal);
  });
  $("negotiateBtn").addEventListener("click", async () => {
    renderDeal(await api("/api/deals/" + currentDeal.id + "/negotiate/run", "POST", {}, "buyer"));
  });
  $("payBtn").addEventListener("click", async () => {
    renderDeal(await api("/api/deals/" + currentDeal.id + "/pay", "POST", {}, "buyer"));
  });
  $("confirmPayBtn").addEventListener("click", async () => {
    renderDeal(await api("/api/deals/" + currentDeal.id + "/pay/confirm", "POST", {}, "buyer"));
  });
  $("deliverBtn").addEventListener("click", async () => {
    renderDeal(await api("/api/deals/" + currentDeal.id + "/deliver", "POST", { quality: "auto" }, "seller"));
  });
  $("verifyBtn").addEventListener("click", async () => {
    renderDeal(await api("/api/deals/" + currentDeal.id + "/verify", "POST", {}, "buyer"));
  });
}

init().catch((err) => {
  $("stateLine").textContent = "Error: " + err.message;
});
