"use strict";

// Segment colors for the share bar (readable in light and dark themes)
const PALETTE = ["#2457d6", "#d9822b", "#2a9d6f", "#9b4dca", "#c23b5a", "#1f8fa6", "#7a8a1f", "#b5651d"];

const state = {
  meta: null,
  offersById: new Map(),
  campaigns: [],
  currentId: null,
  campaign: null,
  streams: [],               // streams of the current campaign; offer streams carry a draft
  busy: false,
  closedArchives: new Set(), // archives are open by default; remember the ones the user closed
};

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    let msg = data?.detail ?? `Error ${res.status}`;
    if (Array.isArray(msg)) msg = msg.map((e) => e.msg.replace(/^Value error, /, "")).join("; ");
    throw new Error(msg);
  }
  return data;
}

function toast(text) {
  const el = $("#toast");
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => el.classList.remove("show"), 3000);
}

function offerLabel(id) {
  const o = state.offersById.get(id);
  return o ? `${id} — ${o.name}` : String(id);
}

function parseOfferInput(value) {
  const id = parseInt(String(value).trim(), 10);
  return Number.isFinite(id) && id > 0 ? id : null;
}

// ---------- tabs ----------
document.querySelectorAll(".tabs button").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

function switchTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) =>
    b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  $("#tab-create").hidden = name !== "create";
  $("#tab-editor").hidden = name !== "editor";
  if (name === "editor") loadCampaigns();
}

// ---------- reference data ----------
async function loadMeta() {
  try {
    state.meta = await api("/api/meta");
  } catch (e) {
    $("#create-error").textContent = `Could not load reference data: ${e.message}`;
    return;
  }
  const m = state.meta;
  m.offers.forEach((o) => state.offersById.set(o.id, o));
  $("#offers-list").innerHTML = m.offers.map((o) => `<option value="${esc(o.id)} — ${esc(o.name)}">`).join("");
  $("#prefix").textContent = m.campaign_prefix;

  // Show a dropdown only when there is something to choose from
  const fill = (name, items, def) => {
    $(`select[name="${name}"]`).innerHTML = items
      .map((i) => `<option value="${esc(i.id)}" title="ID ${esc(i.id)}" ${i.id === def ? "selected" : ""}>${esc(i.name)}</option>`)
      .join("");
    return items.length > 1;
  };
  const choice = [
    fill("domain_id", m.domains, m.defaults.domain_id),
    fill("group_id", m.groups, m.defaults.group_id),
    fill("traffic_source_id", m.traffic_sources, m.defaults.traffic_source_id),
  ];
  if (!choice.some(Boolean)) {
    const names = [m.domains, m.groups, m.traffic_sources].map((l) => l[0]?.name ?? "—");
    $("#fixed-settings").textContent = `Domain ${names[0]}, group ${names[1]}, source ${names[2]}`;
    $("#fixed-settings").hidden = false;
    $("details.more").hidden = true;
  }
}

// ---------- campaign creator ----------
$("#create-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  const err = $("#create-error");
  err.textContent = "";

  const offerId = parseOfferInput(f.offer.value);
  const geo = f.geo.value.split(/[\s,;]+/).map((c) => c.trim()).filter(Boolean);
  if (!f.name.value.trim()) return (err.textContent = "Enter a campaign name.");
  if (!geo.length) return (err.textContent = "Enter at least one country, e.g. DE or MX, AU, RO.");
  const bad = geo.find((c) => !/^[a-zA-Z]{2}$/.test(c));
  if (bad) return (err.textContent = `“${bad}” is not a country code: use two-letter codes like MX, AU, RO.`);
  if (!offerId) return (err.textContent = "Pick an offer from the list or enter its ID.");

  const btn = f.querySelector("button[type=submit]");
  btn.disabled = true;
  btn.textContent = "Creating…";
  try {
    const num = (v) => (v ? Number(v) : null);
    const res = await api("/api/campaigns", {
      method: "POST",
      body: {
        name: f.name.value,
        geo,
        offer_id: offerId,
        domain_id: num(f.domain_id.value),
        group_id: num(f.group_id.value),
        traffic_source_id: num(f.traffic_source_id.value),
      },
    });
    showResult(res);
    f.name.value = "";
    toast("Campaign created");
  } catch (e) {
    err.textContent = e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Create campaign";
  }
});

function showResult(r) {
  const box = $("#create-result");
  box.hidden = false;
  box.innerHTML = `
    <h3>Campaign “${esc(r.name)}” created</h3>
    <dl>
      <dt>ID</dt><dd>${esc(r.id)}</dd>
      <dt>Alias</dt><dd>${esc(r.alias ?? "—")}</dd>
      <dt>Stream 1</dt><dd>#${esc(r.geo_stream_id)}: ${esc(r.geo.join(", "))} → Google</dd>
      <dt>Stream 2</dt><dd>#${esc(r.offer_stream_id)}: everyone else → ${esc(offerLabel(r.offer_id))}</dd>
    </dl>
    <div class="actions">
      <a href="${esc(r.admin_url)}" target="_blank" rel="noopener">Open in Keitaro</a>
      <button class="link" type="button" id="open-in-editor">Edit offers</button>
    </div>`;
  $("#open-in-editor").addEventListener("click", () => {
    switchTab("editor");
    openCampaign(r.id);
  });
}

// ---------- campaign list ----------
async function loadCampaigns() {
  try {
    state.campaigns = await api("/api/campaigns?limit=500");
  } catch (e) {
    $("#campaign-list").innerHTML = `<li class="error">${esc(e.message)}</li>`;
    return;
  }
  renderCampaignList();
}

function renderCampaignList() {
  const q = $("#campaign-search").value.trim().toLowerCase();
  const items = state.campaigns.filter((c) => !q || `${c.id} ${c.name}`.toLowerCase().includes(q));
  $("#campaign-list").innerHTML = items.length
    ? items.map((c) => `
        <li><button type="button" data-id="${esc(c.id)}" ${c.id === state.currentId ? 'aria-current="true"' : ""}>
          <span class="name">${c.has_draft ? `<span class="dot" title="Has changes not pushed to Keitaro"></span><span class="sr">Has unpushed changes. </span>` : ""}${esc(c.name)}</span><span class="id">${esc(c.id)}</span>
        </button></li>`).join("")
    : `<li class="empty">${q ? "Nothing found" : "No campaigns yet — create one on the other tab."}</li>`;
}

$("#campaign-search").addEventListener("input", renderCampaignList);
$("#campaign-list").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button[data-id]");
  if (btn) openCampaign(Number(btn.dataset.id));
});

// ---------- editor ----------
// Every action is saved in the wrapper right away (draft in the DB).
// Keitaro is only updated by the Push button.

const PIN_ICON = `<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><path fill="currentColor" d="M9.8 1.2a.75.75 0 0 1 1.06 0l3.94 3.94a.75.75 0 0 1 0 1.06l-.53.53a1.75 1.75 0 0 1-1.6.47l-2.2 2.2.5 2.47a.75.75 0 0 1-.2.68l-.7.7a.75.75 0 0 1-1.06 0L6.3 10.5l-3.52 3.52a.75.75 0 1 1-1.06-1.06L5.24 9.44 2.53 6.73a.75.75 0 0 1 0-1.06l.7-.7a.75.75 0 0 1 .68-.2l2.47.5 2.2-2.2a1.75 1.75 0 0 1 .47-1.6l.53-.53Z"/></svg>`;

async function openCampaign(id, { fetching = false } = {}) {
  state.currentId = id;
  renderCampaignList();
  const box = $("#editor");
  if (!fetching) box.innerHTML = `<p class="empty">Loading campaign…</p>`;
  try {
    const data = await api(`/api/campaigns/${id}`);
    state.campaign = data.campaign;
    state.streams = data.streams;
    renderEditor();
    syncCampaignMark();
    if (fetching) {
      const changes = data.streams.reduce((n, s) => n + (s.draft?.kt_changes?.length || 0), 0);
      toast(changes ? `Fetched from Keitaro: ${changes} change${changes > 1 ? "s" : ""} applied` : "Fetched from Keitaro: no changes");
    }
  } catch (e) {
    if (fetching) toast(e.message);
    else box.innerHTML = `<p class="error">${esc(e.message)}</p>`;
  }
}

function renderEditor() {
  const c = state.campaign;
  const adminUrl = state.meta?.admin_url_template.replace("{id}", c.id);
  $("#editor").innerHTML = `
    <div class="editor-head">
      <div><h2>${esc(c.name)}</h2><p>ID ${esc(c.id)}${c.alias ? `, alias ${esc(c.alias)}` : ""}</p></div>
      <div class="head-actions">
        <button class="ghost" type="button" id="fetch-streams">Fetch streams from KT</button>
        ${adminUrl ? `<a href="${esc(adminUrl)}" target="_blank" rel="noopener">Open in Keitaro</a>` : ""}
      </div>
    </div>
    ${state.streams.length ? state.streams.map(renderStream).join("") : `<p class="empty">This campaign has no streams.</p>`}`;
}

function filterText(s) {
  const parts = (s.filters || []).map((f) =>
    `${f.name} ${f.mode === "reject" ? "not in" : "in"} ${(f.payload || []).join(", ")}`);
  return parts.length ? parts.join("; ") : "None";
}

function isParticipant(o) {
  return (o.status === "live" || o.status === "new") && o.state === "active";
}

function badge(o) {
  const off = o.state !== "active" ? `<span class="badge off">disabled in KT</span>` : "";
  if (o.status === "new") return `<span class="badge new">new</span>${off}`;
  if (o.status === "removing") return `<span class="badge removing">will be removed</span>`;
  if (o.status === "live" && o.changed) {
    const was = o.pushed_share != null ? `, ${o.pushed_share}% in KT` : "";
    return `<span class="badge changed">changed${esc(was)}</span>${off}`;
  }
  return off;
}

function renderStream(s) {
  const head = `
    <div class="stream-head">
      <h3>Stream: ${esc(s.name || "—")} <span class="pos">(#${esc(s.position ?? "?")})</span></h3>
      <span class="meta">filter by ${esc(filterText(s))}, stream_id ${esc(s.id)}${s.state === "disabled" ? ", disabled" : ""}</span>
    </div>`;

  if (!s.editable) {
    return `<article class="stream compact" data-stream="${s.id}">${head}</article>`;
  }

  const d = s.draft;
  const colors = new Map(d.offers.map((o, i) => [o.offer_id, PALETTE[i % PALETTE.length]]));
  const parts = d.offers.filter(isParticipant);
  const total = d.total;

  const segments = parts.filter((o) => o.share > 0)
    .map((o) => `<span style="flex-grow:${o.share};background:${colors.get(o.offer_id)}" title="${esc(offerLabel(o.offer_id))}: ${o.share}%">${o.share}%</span>`)
    .join("");
  const gap = total < 100 ? `<span class="gap" style="flex-grow:${100 - total}">${100 - total}% unassigned</span>` : "";

  const rows = d.offers.map((o) => {
    const inStream = o.status === "live" || o.status === "new";
    const active = isParticipant(o);
    const pinTitle = o.pinned ? "Unpin share" : (o.can_pin ? "Pin share: it will not change when shares are recalculated" : o.pin_hint);
    return `
    <tr class="st-${o.status}">
      <td><span class="swatch" style="background:${active ? colors.get(o.offer_id) : "var(--line)"}"></span>${esc(offerLabel(o.offer_id))} ${badge(o)}</td>
      <td class="share">${inStream
        ? `<input type="number" min="0" max="${o.share_max}" step="1" value="${esc(o.share)}" data-act="share" data-stream="${s.id}"
             data-offer="${o.offer_id}" aria-label="Share of offer ${esc(o.offer_id)}"
             title="${esc(o.share_hint || `Other unpinned offers will adjust. Max ${o.share_max}%`)}"
             ${o.share_hint ? "disabled" : ""}>&thinsp;%`
        : `<span class="was">${o.pushed_share ?? 0}%</span>`}</td>
      <td class="pin">${inStream
        ? `<button type="button" class="pin-btn" data-act="pin" data-stream="${s.id}" data-offer="${o.offer_id}"
             aria-pressed="${o.pinned}" title="${esc(pinTitle)}" aria-label="${esc(pinTitle)}"
             ${o.pinned || o.can_pin ? "" : "disabled"}>${PIN_ICON}</button>` : ""}</td>
      <td>${o.status === "removing"
        ? `<button class="remove" type="button" data-act="restore" data-stream="${s.id}" data-offer="${o.offer_id}">Undo remove</button>`
        : `<button class="remove" type="button" data-act="remove" data-stream="${s.id}" data-offer="${o.offer_id}">Remove</button>`}</td>
    </tr>`;
  }).join("");

  const archive = d.archived.length ? `
    <details class="archive" ${state.closedArchives.has(s.id) ? "" : "open"} data-archive="${s.id}">
      <summary>Archive: removed from Keitaro (${d.archived.length})</summary>
      <table class="offers"><tbody>${d.archived.map((o) => `
        <tr class="st-archived">
          <td><span class="swatch" style="background:var(--line)"></span>${esc(offerLabel(o.offer_id))}</td>
          <td class="when">${o.archived_at ? esc(new Date(o.archived_at).toLocaleString("en-GB")) : ""}</td>
          <td><button class="remove" type="button" data-act="restore" data-stream="${s.id}" data-offer="${o.offer_id}">Restore</button></td>
        </tr>`).join("")}</tbody></table>
    </details>` : "";

  const ktChanges = d.kt_changes?.length ? `
    <div class="notice kt">
      <strong>Changes made in Keitaro:</strong>
      <ul>${d.kt_changes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
    </div>` : "";
  const status = d.dirty ? `<p class="notice">Changes are saved in the wrapper but not pushed to Keitaro yet.</p>` : "";

  return `<article class="stream ${d.dirty ? "pending" : ""}" data-stream="${s.id}">${head}
    ${ktChanges}${status}
    <div class="sharebar ${total > 100 ? "over" : ""}" aria-hidden="true">${segments}${gap}</div>
    <table class="offers">
      <thead><tr><th>Offer</th><th>Share</th><th><span class="sr">Pin</span></th><th></th></tr></thead>
      <tbody>${rows || `<tr><td colspan="4" class="empty">No offers — add at least one.</td></tr>`}</tbody>
    </table>
    <div class="add">
      <input list="offers-list" placeholder="Offer ID or name" data-add-input="${s.id}" autocomplete="off">
      <button class="ghost" type="button" data-act="add" data-stream="${s.id}">Add</button>
    </div>
    ${archive}
    <div class="footer">
      <span class="total ${d.problems.length && d.dirty ? "bad" : ""}">Total: ${total}%${total === 100 || !parts.length ? "" : " — must be 100%"}</span>
      <div class="buttons">
        <button class="ghost" type="button" data-act="rebalance" data-stream="${s.id}" title="Pinned shares stay as they are">Split evenly</button>
        <button class="ghost" type="button" data-act="discard" data-stream="${s.id}" ${d.dirty ? "" : "disabled"}>Discard changes</button>
        <button class="primary" type="button" data-act="push" data-stream="${s.id}" ${d.can_push ? "" : "disabled"}>Push to Keitaro</button>
      </div>
    </div>
  </article>`;
}

function rerenderStream(streamId, focusSel) {
  const s = state.streams.find((x) => x.id === streamId);
  const el = document.querySelector(`.stream[data-stream="${streamId}"]`);
  el.outerHTML = renderStream(s);
  if (focusSel) document.querySelector(`.stream[data-stream="${streamId}"] ${focusSel}`)?.focus();
}

function syncCampaignMark() {
  const c = state.campaigns.find((x) => x.id === state.currentId);
  if (!c) return;
  const dirty = state.streams.some((s) => s.editable && s.draft?.dirty);
  if (c.has_draft !== dirty) {
    c.has_draft = dirty;
    renderCampaignList();
  }
}

// Runs an action on the server and re-renders the stream from the response
async function act(streamId, method, path, body, { focus, success } = {}) {
  if (state.busy) return;
  state.busy = true;
  const s = state.streams.find((x) => x.id === streamId);
  try {
    s.draft = await api(path, { method, body });
    rerenderStream(streamId, focus);
    syncCampaignMark();
    if (typeof success === "function") success = success(s.draft);
    if (success) toast(success);
  } catch (e) {
    toast(e.message);
    rerenderStream(streamId, focus);
  } finally {
    state.busy = false;
  }
}

$("#editor").addEventListener("click", async (ev) => {
  if (ev.target.closest("#fetch-streams")) {
    const btn = $("#fetch-streams");
    btn.disabled = true;
    btn.textContent = "Fetching…";
    await openCampaign(state.currentId, { fetching: true });
    loadCampaigns();
    return;
  }

  const btn = ev.target.closest("button[data-act]");
  if (!btn || btn.disabled) return;
  const sid = Number(btn.dataset.stream);
  const oid = Number(btn.dataset.offer);
  const s = state.streams.find((x) => x.id === sid);
  const base = `/api/streams/${sid}`;

  switch (btn.dataset.act) {
    case "add": {
      const input = document.querySelector(`[data-add-input="${sid}"]`);
      const id = parseOfferInput(input.value);
      if (!id) return toast("Pick an offer from the list or enter its ID");
      return act(sid, "POST", `${base}/offers`, { offer_id: id }, { focus: "[data-add-input]", success: "Offer added to the draft" });
    }
    case "remove":
      return act(sid, "DELETE", `${base}/offers/${oid}`, null,
        { success: s.draft.offers.find((o) => o.offer_id === oid)?.status === "new" ? "Offer removed from the draft" : "Offer will be removed on push" });
    case "restore":
      return act(sid, "POST", `${base}/offers/${oid}/restore`, null, { success: "Offer restored to the draft" });
    case "pin": {
      const pinned = btn.getAttribute("aria-pressed") !== "true";
      return act(sid, "PATCH", `${base}/offers/${oid}`, { pinned }, { success: pinned ? "Share pinned" : "Share unpinned" });
    }
    case "rebalance":
      return act(sid, "POST", `${base}/rebalance`);
    case "discard":
      if (!confirm("Discard all unpushed changes in this stream?")) return;
      return act(sid, "POST", `${base}/discard`, null, { success: "Draft now matches Keitaro" });
    case "push":
      return act(sid, "POST", `${base}/push`, null, { success: "Changes pushed to Keitaro" });
  }
});

$("#editor").addEventListener("change", (ev) => {
  const el = ev.target;
  if (el.dataset.act !== "share") return;
  const sid = Number(el.dataset.stream);
  const oid = Number(el.dataset.offer);
  const share = Math.max(0, Math.min(100, Math.round(Number(el.value) || 0)));
  act(sid, "PATCH", `/api/streams/${sid}/offers/${oid}`, { share }, {
    focus: `[data-act="share"][data-offer="${oid}"]`,
    success: (d) => {
      const o = d.offers.find((x) => x.offer_id === oid);
      return o && o.share < share ? `Max for this offer is ${o.share}%: the rest is taken by pinned offers` : "";
    },
  });
});

// Remember closed archives so re-rendering keeps them closed
$("#editor").addEventListener("toggle", (ev) => {
  const d = ev.target.closest?.("details[data-archive]");
  if (!d) return;
  const id = Number(d.dataset.archive);
  d.open ? state.closedArchives.delete(id) : state.closedArchives.add(id);
}, true);

loadMeta();
