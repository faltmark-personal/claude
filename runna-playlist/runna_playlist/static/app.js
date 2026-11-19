"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (s) => { s = Math.round(Math.abs(s)); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}` : `${m}:${String(x).padStart(2, "0")}`; };
const signed = (s) => (s > 0 ? "+" : s < 0 ? "−" : "±") + fmt(s);
const parseDur = (t) => { t = String(t).trim(); if (/^\d+$/.test(t)) return +t;
  const p = t.split(":").map(Number); if (p.some(isNaN)) return NaN; return p.reduce((a, b) => a * 60 + b, 0); };

const S = { settings: null, labels: {}, auth: {}, workout: null, plan: null, library: null };

const EXAMPLES = {
  "Easy run 40 min (Z2)": "Warm up: 5m@Z1, Easy: 30m@Z2, Cool down: 5m@Z1",
  "Threshold 5×4 min": "Warm up: 10m@Z2, 5x(Rep: 4m@Z4, Recovery: 90s@Z1), Cool down: 8m@Z1",
  "Tempo 20 min": "Warm up: 10m@Z2, Tempo: 20m@Z3, Cool down: 10m@Z1",
  "Track 6×800 m @ 4:20/km": "Warm up: 12m@Z2, 6x(Rep: 800m@4:20/km@Z5, Jog: 2m@Z1), Cool down: 10m@Z1",
  "Fartlek 8×1 min": "Warm up: 10m@Z2, 8x(Fast: 1m@Z5, Float: 1m@Z2), Steady: 10m@Z3, Cool down: 5m@Z1",
  "Long run with fast finish": "Easy: 60m@Z2, Steady: 15m@Z3, Fast finish: 10m@Z4, Cool down: 5m@Z1",
};

async function api(path, opts = {}) {
  const init = { method: opts.method || (opts.body !== undefined || opts.form ? "POST" : "GET"), headers: {} };
  if (opts.form) init.body = opts.form;
  else if (opts.body !== undefined) { init.body = JSON.stringify(opts.body); init.headers["Content-Type"] = "application/json"; }
  const r = await fetch(path, init);
  const text = await r.text();
  let data; try { data = JSON.parse(text); } catch { data = text; }
  if (!r.ok) throw new Error((data && data.detail) ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : r.statusText);
  return data;
}
let toastTimer;
function toast(msg, err = false) { const t = $("#toast"); t.textContent = msg; t.className = err ? "err" : ""; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), err ? 7000 : 3500); }
async function guard(btn, fn) { const old = btn && btn.innerHTML; if (btn) { btn.disabled = true; btn.innerHTML = `<span class="spin"></span> ${old}`; }
  try { return await fn(); } catch (e) { toast(e.message, true); } finally { if (btn) { btn.disabled = false; btn.innerHTML = old; } } }

function tab(name) { $$("nav button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + name));
  if (name === "library") loadLibrary(); if (name === "settings") renderSettings(); }
$$("nav button").forEach((b) => (b.onclick = () => tab(b.dataset.tab)));

const MODE_NAMES = { demo: "Demo library", youtube_data: "YouTube · official API", ytmusic: "YouTube Music · ytmusicapi (unofficial)" };
function renderMode() { $("#mode-pill").textContent = MODE_NAMES[S.settings.mode]; }

/* ---------------- workout ---------------- */
function setWorkout(w) { S.workout = w; renderWorkout(); refreshBlocks(); }
function workoutPayload() { return { name: S.workout.name, segments: S.workout.segments.map((s) => ({ ...s, duration: s.duration_s })) }; }
let blocksTimer;
function refreshBlocks() { clearTimeout(blocksTimer); blocksTimer = setTimeout(async () => {
  try { const r = await api("/api/workout/parse", { body: { workout: workoutPayload() } }); renderBlocksNote(r.blocks); } catch (e) { $("#w-blocks-note").textContent = e.message; } }, 250); }
function renderBlocksNote(blocks) {
  const merged = blocks.filter((b) => b.merged);
  $("#w-blocks-note").innerHTML = merged.length
    ? `Songs can't change every minute, so ${merged.length} group(s) of short steps share one tempo: ` +
      merged.map((b) => `<b>${esc(b.name)}</b> → Z${b.zone}`).join("; ") + ". Change this under Settings → Planning."
    : "Every step is long enough to get its own music.";
}
function renderWorkout() {
  const w = S.workout; $("#w-title").textContent = w.name || "Segments"; $("#w-name").value = w.name;
  const total = w.segments.reduce((a, s) => a + s.duration_s, 0);
  $("#w-total").textContent = `${w.segments.length} steps · ${fmt(total)}`;
  $("#w-profile").innerHTML = w.segments.map((s) =>
    `<div class="z${s.zone}" style="flex:${s.duration_s};height:${15 + s.zone * 17}%" title="${esc(s.name)} · ${fmt(s.duration_s)} · Z${s.zone}"></div>`).join("");
  $("#w-rows").innerHTML = w.segments.map((s, i) => `
    <tr data-i="${i}">
      <td class="muted">${i + 1}</td>
      <td><input data-f="name" value="${esc(s.name)}"></td>
      <td class="dur"><input data-f="duration" value="${fmt(s.duration_s)}" title="mm:ss"></td>
      <td><select data-f="zone">${[1, 2, 3, 4, 5].map((z) => `<option value="${z}" ${z === s.zone ? "selected" : ""}>Z${z} ${esc(S.labels[z] || "")}</option>`).join("")}</select></td>
      <td><select data-f="kind">${["warmup", "work", "recovery", "cooldown"].map((k) => `<option ${k === s.kind ? "selected" : ""}>${k}</option>`).join("")}</select></td>
      <td class="actions"><button type="button" class="icon" data-a="up" title="Move up">↑</button><button type="button" class="icon" data-a="down" title="Move down">↓</button><button type="button" class="icon" data-a="dup" title="Duplicate">⧉</button><button type="button" class="icon" data-a="del" title="Delete">✕</button></td>
    </tr>${s.note ? `<tr class="note"><td></td><td colspan="5" class="hint warnc">⚠ ${esc(s.note)}</td></tr>` : ""}`).join("");
}
$("#w-rows").addEventListener("change", (e) => { const tr = e.target.closest("tr[data-i]"); if (!tr) return;
  const s = S.workout.segments[+tr.dataset.i], f = e.target.dataset.f;
  if (f === "duration") { const d = parseDur(e.target.value); if (!(d > 0)) { toast("Duration as mm:ss, e.g. 4:30", true); e.target.value = fmt(s.duration_s); return; } s.duration_s = d; }
  else if (f === "zone") { s.zone = +e.target.value; s.note = ""; } else s[f] = e.target.value;
  renderWorkout(); refreshBlocks(); });
$("#w-rows").addEventListener("click", (e) => { const a = e.target.dataset.a; if (!a) return; const i = +e.target.closest("tr").dataset.i, segs = S.workout.segments;
  if (a === "del") segs.splice(i, 1); if (a === "dup") segs.splice(i + 1, 0, { ...segs[i] });
  if (a === "up" && i > 0) [segs[i - 1], segs[i]] = [segs[i], segs[i - 1]];
  if (a === "down" && i < segs.length - 1) [segs[i + 1], segs[i]] = [segs[i], segs[i + 1]];
  renderWorkout(); refreshBlocks(); });
$("#w-add").onclick = () => { S.workout.segments.push({ name: "Step", duration_s: 300, zone: 2, kind: "work", note: "" }); renderWorkout(); refreshBlocks(); };
$("#w-name").onchange = (e) => { S.workout.name = e.target.value; renderWorkout(); };
$("#w-parse").onclick = (e) => guard(e.target, async () => {
  const r = await api("/api/workout/parse", { body: { spec: $("#w-spec").value, name: $("#w-name").value } }); setWorkout(r.workout); });
const ex = $("#w-examples"); Object.keys(EXAMPLES).forEach((k) => ex.insertAdjacentHTML("beforeend", `<option>${esc(k)}</option>`));
ex.onchange = () => { if (!ex.value) return; $("#w-spec").value = EXAMPLES[ex.value]; $("#w-name").value = ex.value; ex.value = ""; $("#w-parse").click(); };
$("#w-fit").onchange = async (e) => { const f = e.target.files[0]; if (!f) return; const fd = new FormData(); fd.append("file", f);
  try { const r = await api("/api/workout/fit", { form: fd }); setWorkout(r.workout); toast(`Imported “${r.workout.name}”. Check steps marked ⚠.`); } catch (err) { toast(err.message, true); }
  e.target.value = ""; };
async function loadIntervals() {
  const box = $("#intervals-body");
  if (!S.auth.intervals?.connected) { box.innerHTML = "Add your personal API key in Settings to list planned runs."; return; }
  box.innerHTML = `<span class="spin"></span> Loading planned runs…`;
  try { const r = await api("/api/intervals/events?days=21");
    box.innerHTML = r.events.length ? r.events.map((ev) => `<div class="row"><span class="grow">${esc(ev.date)} · ${esc(ev.name)}${ev.moving_time ? " · " + fmt(ev.moving_time) : ""}</span><button type="button" data-ev="${esc(ev.id)}">Use</button></div>`).join("") : "No planned runs in the next 3 weeks.";
    $$("button[data-ev]", box).forEach((b) => (b.onclick = () => guard(b, async () => { const w = await api(`/api/intervals/events/${encodeURIComponent(b.dataset.ev)}`); setWorkout(w.workout); toast(`Imported “${w.workout.name}”.`); })));
  } catch (e) { box.textContent = e.message; }
}
$("#w-generate").onclick = (e) => guard(e.target, async () => { await generate(); tab("playlist"); });

/* ---------------- plan ---------------- */
const itemsPayload = () => S.plan.items.map((it) => ({ key: it.track.key, block: it.block, locked: it.locked }));
async function generate(seed) {
  const locked = S.plan ? S.plan.items.filter((i) => i.locked).map((i) => ({ key: i.track.key, block: i.block })) : [];
  S.plan = await api("/api/plan", { body: { workout: workoutPayload(), locked, seed: seed ?? null } });
  if (!$("#p-name").value) $("#p-name").value = S.settings.playlist_title;
  $("#p-saved").innerHTML = ""; renderPlan();
}
async function retime() { const locked = new Set(S.plan.items.filter((i) => i.locked).map((i) => i.track.key));
  S.plan = await api("/api/plan/retime", { body: { workout: workoutPayload(), items: itemsPayload() } });
  S.plan.items.forEach((i) => (i.locked = locked.has(i.track.key))); renderPlan(); }
const originBadge = (t) => t.liked ? `<span class="badge liked">♥ Liked</span>`
  : t.origin === "radio" ? `<span class="badge radio">Song radio</span>` : `<span class="badge rec">${t.origin === "liked-artist" ? "Artist you like" : "Similar artist"}</span>`;
function renderPlan() {
  const p = S.plan, tm = p.timing; $("#p-empty").hidden = true; $("#p-body").hidden = false;
  $("#p-title").textContent = `${p.workout.name} · ${fmt(p.workout.duration_s)}`;
  const liked = p.items.filter((i) => i.track.liked).length, off = tm.off_zone_items.length, diff = tm.difference_s;
  const cls = (v, a, b) => (Math.abs(v) <= a ? "good" : Math.abs(v) <= b ? "warnc" : "badc");
  $("#p-summary").innerHTML = `
    <div><b>${p.items.length}</b>songs</div>
    <div><b>${fmt(tm.playlist_s)}</b>playlist length</div>
    <div><b class="${cls(diff, 45, 120)}">${signed(diff)}</b>vs workout</div>
    <div><b class="${cls(tm.max_offset_s, S.settings.slack_s, 90)}">${fmt(tm.max_offset_s)}</b>largest boundary offset</div>
    <div><b>${liked}/${p.items.length}</b>from your likes</div>
    <div><b class="${off ? "badc" : "good"}">${off}</b>outside tempo range</div>`;
  const short = Object.entries(p.shortfall_s || {}).filter(([, s]) => s > 0);
  if (short.length) $("#p-summary").insertAdjacentHTML("beforeend", `<div class="hint warnc" style="flex-basis:100%">Not enough songs at the right tempo for ${short.map(([z, s]) => `Z${z} (${fmt(s)})`).join(", ")}. Closest-tempo songs were used. Add BPMs in Library, turn recommendations on, or widen that zone's range.</div>`);
  // timeline
  const total = Math.max(p.workout.duration_s, tm.playlist_s) || 1, pct = (s) => (s / total) * 100;
  let t = 0; const segs = p.workout.segments.map((s) => { const d = `<div class="z${s.zone}" style="left:${pct(t)}%;width:${pct(s.duration_s)}%" title="${esc(s.name)} · Z${s.zone} · ${fmt(s.duration_s)}">${esc(s.name)}</div>`; t += s.duration_s; return d; }).join("");
  const blocks = p.blocks.map((b) => `<div class="z${b.zone}" style="left:${pct(b.start_s)}%;width:${pct(b.duration_s)}%;opacity:.85" title="${esc(b.name)} → Z${b.zone}">Z${b.zone}</div>`).join("");
  const songs = p.items.map((it, i) => `<div class="${it.in_zone ? "z" + p.blocks[it.block].zone : "off"}" style="left:${pct(it.start_s)}%;width:${pct(it.track.duration_s)}%" title="${esc(it.track.title)} · ${it.track.bpm ?? "?"} BPM">${i + 1}. ${esc(it.track.title)}</div>`).join("");
  const ticks = []; const step = total > 3600 ? 900 : total > 1500 ? 300 : 120; for (let x = 0; x <= total; x += step) ticks.push(`<span style="left:${pct(x)}%">${fmt(x)}</span>`);
  $("#p-timeline").innerHTML = `<div class="tl-label">Workout</div><div class="tl-row">${segs}</div>
    <div class="tl-label">Tempo target (short steps grouped)</div><div class="tl-row" style="height:18px">${blocks}</div>
    <div class="tl-label">Songs</div><div class="tl-row">${songs}</div><div class="tl-axis">${ticks.join("")}</div>`;
  // rows
  $("#p-rows").innerHTML = p.items.map((it, i) => { const tr = it.track, b = p.blocks[it.block];
    const eff = it.effective_bpm && Math.round(it.effective_bpm) !== Math.round(tr.bpm || 0) ? ` <span class="muted" title="matched at ${it.effective_bpm > tr.bpm ? "double" : "half"} time">(feels ${Math.round(it.effective_bpm)})</span>` : "";
    return `<tr data-i="${i}" draggable="true" class="${it.locked ? "locked" : ""} ${it.in_zone ? "" : "offzone"}">
      <td class="muted">${i + 1}</td><td>${fmt(it.start_s)}</td>
      <td class="song"><b>${esc(tr.title)}</b><span>${esc(tr.artists.join(", "))}</span></td>
      <td>${fmt(tr.duration_s)}</td>
      <td class="bpm" title="source: ${esc(tr.bpm_source || "unknown")}">${tr.bpm ? Math.round(tr.bpm) : "?"}${eff}${it.in_zone ? "" : " ⚠"}<span class="reason">${esc(tr.bpm_source || "")}</span></td>
      <td><span class="znum z${b.zone}">Z${b.zone}</span> ${esc(b.name)}</td>
      <td>${originBadge(tr)}${tr.reason ? `<span class="reason">${esc(tr.reason)}</span>` : ""}</td>
      <td class="actions">
        <button type="button" class="icon" data-a="swap" title="Replace with another song">⇄</button>
        <button type="button" class="icon" data-a="lock" title="${it.locked ? "Unlock" : "Keep this song when regenerating"}">${it.locked ? "🔒" : "🔓"}</button>
        <button type="button" class="icon" data-a="up" title="Move earlier">↑</button><button type="button" class="icon" data-a="down" title="Move later">↓</button>
        <button type="button" class="icon" data-a="del" title="Remove">✕</button>
        ${tr.video_id && !tr.video_id.startsWith("demo") ? `<a class="icon" href="https://music.youtube.com/watch?v=${encodeURIComponent(tr.video_id)}" target="_blank" rel="noopener" title="Listen">▶</a>` : ""}
      </td></tr>`; }).join("");
  // timing
  $("#p-timing").innerHTML = tm.blocks.map((r) => { const o = r.offset_s; const c = o == null ? "badc" : Math.abs(o) <= S.settings.slack_s ? "good" : Math.abs(o) <= 90 ? "warnc" : "badc";
    return `<tr><td>${esc(r.name)}${r.merged ? ' <span class="muted">(grouped)</span>' : ""}</td><td><span class="znum z${r.zone}">Z${r.zone}</span></td>
      <td>${fmt(r.start_s)}–${fmt(r.end_s)}</td><td>${r.music_start_s == null ? "—" : fmt(r.music_start_s)}</td>
      <td class="${c}">${o == null ? "no songs" : signed(o)}</td><td>${r.songs}</td></tr>`; }).join("");
  const recs = p.items.filter((i) => !i.track.video_id).length;
  $("#p-save-hint").textContent = S.settings.mode === "demo" ? "Demo mode: saving is simulated. Connect an account in Settings to save for real."
    : `Saves to your ${MODE_NAMES[S.settings.mode]} account${S.settings.reuse_playlist ? ", replacing the songs in a playlist with this name if one exists" : ""}.` +
      (recs ? ` ${recs} recommended song(s) will be looked up on YouTube first${S.settings.mode === "youtube_data" ? " (100 quota units each)" : ""}.` : "");
}
$("#p-rows").addEventListener("click", async (e) => { const btn = e.target.closest("button[data-a]"); if (!btn) return;
  const i = +btn.closest("tr").dataset.i, items = S.plan.items, a = btn.dataset.a;
  if (a === "lock") { items[i].locked = !items[i].locked; renderPlan(); return; }
  if (a === "swap") return showAlternatives(i);
  if (a === "del") items.splice(i, 1);
  if (a === "up" && i > 0) moveItem(i, i - 1);
  if (a === "down" && i < items.length - 1) moveItem(i, i + 1);
  guard(null, retime); });
let dragFrom = null;
$("#p-rows").addEventListener("dragstart", (e) => { dragFrom = +e.target.closest("tr").dataset.i; });
$("#p-rows").addEventListener("dragover", (e) => { e.preventDefault(); $$("#p-rows tr").forEach((r) => r.classList.remove("dragover")); e.target.closest("tr")?.classList.add("dragover"); });
$("#p-rows").addEventListener("drop", (e) => { e.preventDefault(); const tr = e.target.closest("tr"); if (!tr || dragFrom == null) return;
  moveItem(dragFrom, +tr.dataset.i); dragFrom = null; guard(null, retime); });
// Reorder songs; each position keeps its workout segment, so a song moved into a
// hard block is judged against that block's tempo.
function moveItem(from, to) { const items = S.plan.items, slots = items.map((x) => x.block);
  const [moved] = items.splice(from, 1); items.splice(to, 0, moved); items.forEach((x, k) => (x.block = slots[k])); }

function dialog(title, html) { $("#dlg-title").textContent = title; $("#dlg-body").innerHTML = html; $("#dlg").showModal(); }
function trackRow(t, extra, action) { return `<tr><td class="song"><b>${esc(t.title)}</b><span>${esc(t.artists.join(", "))}</span></td><td>${fmt(t.duration_s)}</td>
  <td>${t.bpm ? Math.round(t.bpm) : "?"}</td><td>${originBadge(t)}</td><td>${extra}</td><td>${action}</td></tr>`; }
async function showAlternatives(i) {
  const it = S.plan.items[i], b = S.plan.blocks[it.block];
  dialog(`Replace “${it.track.title}” (Z${b.zone}, ${b.name})`, `<span class="spin"></span>`);
  try { const r = await api("/api/plan/alternatives", { body: { workout: workoutPayload(), items: itemsPayload(), index: i } });
    const alts = r.alternatives;
    $("#dlg-body").innerHTML = `<p class="hint">Songs that fit Z${b.zone} (${S.settings.zones.ranges[b.zone].join("–")} BPM), best first. The length difference changes the timing of everything after this song.</p>
      <table class="alt-table"><thead><tr><th>Song</th><th>Length</th><th>BPM</th><th>From</th><th>vs current</th><th></th></tr></thead><tbody>
      ${alts.map((a, k) => trackRow(a.track, `<span class="${Math.abs(a.duration_delta_s) < 30 ? "good" : "muted"}">${signed(a.duration_delta_s)}</span>`, `<button type="button" data-k="${k}">Use</button>`)).join("") || "<tr><td colspan=6>No other songs fit this tempo range.</td></tr>"}
      </tbody></table>${searchBox()}`;
    $$("#dlg-body button[data-k]").forEach((btn) => (btn.onclick = () => { S.plan.items[i] = { ...it, track: alts[+btn.dataset.k].track, locked: true }; $("#dlg").close(); guard(null, retime); }));
    wireSearch((t) => { S.plan.items[i] = { ...it, track: t, locked: true }; });
  } catch (e) { $("#dlg-body").textContent = e.message; }
}
const searchBox = () => `<h3>Or search your songs</h3><div class="row"><input id="q" class="grow" placeholder="Title or artist"><button type="button" id="q-go">Search</button></div><table class="alt-table"><tbody id="q-res"></tbody></table>`;
function wireSearch(onPick) { const go = async () => { const r = await api("/api/plan/search", { body: { q: $("#q").value } });
  $("#q-res").innerHTML = r.results.map((t, k) => trackRow(t, t.zones.length ? t.zones.map((z) => `<span class="znum z${z}">Z${z}</span>`).join(" ") : '<span class="muted">no zone</span>', `<button type="button" data-q="${k}">Use</button>`)).join("") || "<tr><td>No matches.</td></tr>";
  $$("#q-res button[data-q]").forEach((b) => (b.onclick = () => { onPick(r.results[+b.dataset.q]); $("#dlg").close(); guard(null, retime); })); };
  $("#q-go").onclick = go; $("#q").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } }; }
$("#p-add").onclick = () => { dialog("Add a song at the end", searchBox()); wireSearch((t) => {
  S.plan.items.push({ track: t, block: S.plan.blocks.length - 1, locked: true }); }); };
$("#p-regen").onclick = (e) => guard(e.target, () => generate(Math.floor(Math.random() * 1e9)));
$("#p-csv").onclick = (e) => guard(e.target, async () => {
  const r = await fetch("/api/plan/export.csv", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ workout: workoutPayload(), items: itemsPayload() }) });
  if (!r.ok) throw new Error("Export failed"); const blob = await r.blob(); const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = (S.workout.name || "workout").replace(/[^\w-]+/g, "_") + "_playlist.csv"; a.click(); });
$("#p-save").onclick = (e) => guard(e.target, async () => {
  const r = await api("/api/playlist/save", { body: { workout: workoutPayload(), items: itemsPayload(), title: $("#p-name").value } });
  $("#p-saved").innerHTML = `<div class="saved-ok"><b>Saved “${esc(r.title)}”</b> with ${r.saved} songs.
    ${S.settings.mode !== "demo" ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">Open in YouTube Music ↗</a>` : ""}
    ${r.not_found.length ? `<div class="warnc">Not found on YouTube, left out: ${r.not_found.map(esc).join("; ")}</div>` : ""}
    <div class="hint">Next: on your watch, open YouTube Music, pick this playlist, sync on Wi-Fi, and turn shuffle off. <a href="#" id="to-garmin">Step-by-step</a></div></div>`;
  $("#to-garmin").onclick = (ev) => { ev.preventDefault(); tab("garmin"); };
  const locked = S.plan.items.map((i) => i.locked); S.plan = r.plan;
  S.plan.items.forEach((i, k) => (i.locked = !!locked[k])); renderPlan(); });

/* ---------------- library ---------------- */
async function loadLibrary() { try { S.library = await api("/api/library"); renderLibrary(); } catch (e) { toast(e.message, true); } }
function renderLibrary() {
  const L = S.library, z = S.settings.zones.ranges;
  $("#l-coverage").innerHTML = [1, 2, 3, 4, 5].map((k) => `<div class="z${k}"><b>${Math.round(L.coverage_s[k] / 60)} min</b>Z${k} · ${z[k][0]}–${z[k][1]} BPM</div>`).join("");
  const q = $("#l-filter").value.toLowerCase(), unk = $("#l-unknown").checked;
  const rows = L.tracks.filter((t) => (!unk || !t.bpm) && (!q || t.title.toLowerCase().includes(q) || t.artists.join(" ").toLowerCase().includes(q)));
  const known = L.tracks.filter((t) => t.bpm).length;
  $("#l-count").textContent = `${L.tracks.length} songs · ${known} with BPM (${L.tracks.length ? Math.round((known / L.tracks.length) * 100) : 0}%)`;
  $("#l-rows").innerHTML = rows.slice(0, 500).map((t) => `<tr><td class="song"><b>${esc(t.title)}</b><span>${esc(t.artists.join(", "))}</span></td><td>${fmt(t.duration_s)}</td>
    <td><input class="num" type="number" min="40" max="250" step="1" data-key="${esc(t.key)}" value="${t.bpm ? Math.round(t.bpm) : ""}" placeholder="?"></td>
    <td class="muted">${esc(t.bpm_source || "unknown")}</td><td>${t.zones.map((k) => `<span class="znum z${k}">Z${k}</span>`).join(" ")}</td></tr>`).join("")
    + (rows.length > 500 ? `<tr><td colspan=5 class="muted">…${rows.length - 500} more, use the filter</td></tr>` : "");
  if (!L.tracks.length) $("#l-rows").innerHTML = `<tr><td colspan=5 class="muted">No songs yet. Press “Sync liked songs”.</td></tr>`;
}
$("#l-filter").oninput = renderLibrary; $("#l-unknown").onchange = renderLibrary;
$("#l-rows").addEventListener("change", async (e) => { const k = e.target.dataset.key; if (!k) return;
  try { await api("/api/library/bpm", { method: "PUT", body: { key: k, bpm: e.target.value } }); toast("BPM saved"); loadLibrary(); } catch (err) { toast(err.message, true); } });
async function sync(refresh) { try { await api("/api/library/sync", { body: { refresh_unknown: refresh } }); pollSync(); } catch (e) { toast(e.message, true); } }
async function pollSync() { const s = await api("/api/library/status");
  $("#l-progress").innerHTML = s.running ? `<span class="spin"></span> Looking up tempos… ${s.done}/${s.total || "?"} (the first sync of a big library can take a few minutes; later ones use the cache)` : s.error ? `<span class="badc">Sync failed: ${esc(s.error)}</span>` : s.total ? `Synced ${s.total} songs.` : "";
  if (s.running) setTimeout(pollSync, 1200); else loadLibrary(); }
$("#l-sync").onclick = () => sync(false); $("#l-retry").onclick = () => sync(true);

/* ---------------- settings ---------------- */
function renderSettings() { const s = S.settings;
  $$("input[name=mode]").forEach((r) => (r.checked = r.value === s.mode));
  $("#s-redirect").textContent = location.origin + "/api/auth/google/callback";
  $("#s-google-status").innerHTML = S.auth.google.connected ? `<span class="good">✓ Google account connected</span>` : S.auth.google.configured ? "Client uploaded. Press Connect." : "No OAuth client uploaded yet.";
  $("#s-ytm-status").innerHTML = S.auth.ytmusic.connected ? `<span class="good">✓ ytmusicapi set up</span>` : "Not set up.";
  $("#s-intervals-status").innerHTML = S.auth.intervals.connected ? `<span class="good">✓ Key saved</span>. Planned runs appear on the Workout tab.` : "";
  $("#s-cadence").value = s.cadence_spm; $("#s-halfdouble").checked = s.zones.allow_half_double;
  $("#s-zones").innerHTML = [1, 2, 3, 4, 5].map((z) => `<tr><td><span class="znum z${z}">Z${z}</span></td><td>${esc(S.labels[z])}</td>
    <td><input type="number" data-z="${z}" data-m="0" value="${s.zones.ranges[z][0]}"></td><td><input type="number" data-z="${z}" data-m="1" value="${s.zones.ranges[z][1]}"></td></tr>`).join("");
  $("#s-minblock").value = s.min_block_s; $("#s-merge").value = s.merge_strategy; $("#s-slack").value = s.slack_s;
  $("#s-recs").checked = s.recommendations; $("#s-preview").checked = s.analyze_previews; $("#s-title").value = s.playlist_title;
  $("#s-reuse").checked = s.reuse_playlist; $("#s-privacy").value = s.privacy; $("#s-maxhr").value = s.max_hr; $("#s-easy").value = s.easy_pace; $("#s-hard").value = s.hard_pace; }
function collectSettings() { const ranges = {}; [1, 2, 3, 4, 5].forEach((z) => (ranges[z] = [+$(`#s-zones input[data-z="${z}"][data-m="0"]`).value, +$(`#s-zones input[data-z="${z}"][data-m="1"]`).value]));
  return { mode: $("input[name=mode]:checked").value, cadence_spm: +$("#s-cadence").value, zones: { ranges, allow_half_double: $("#s-halfdouble").checked },
    min_block_s: +$("#s-minblock").value, merge_strategy: $("#s-merge").value, slack_s: +$("#s-slack").value, recommendations: $("#s-recs").checked,
    analyze_previews: $("#s-preview").checked, playlist_title: $("#s-title").value, reuse_playlist: $("#s-reuse").checked, privacy: $("#s-privacy").value,
    max_hr: +$("#s-maxhr").value, easy_pace: $("#s-easy").value, hard_pace: $("#s-hard").value }; }
async function saveSettings(patch) { const r = await api("/api/settings", { method: "PUT", body: patch ?? collectSettings() });
  S.settings = r.settings; S.auth = r.auth; renderMode(); renderSettings(); return r; }
$("#s-save").onclick = (e) => guard(e.target, async () => { await saveSettings(); toast("Settings saved"); if (S.plan) await retime(); });
$("#s-derive").onclick = async () => { const r = await api(`/api/zones/from-cadence?spm=${+$("#s-cadence").value}`);
  [1, 2, 3, 4, 5].forEach((z) => { $(`#s-zones input[data-z="${z}"][data-m="0"]`).value = r.ranges[z][0]; $(`#s-zones input[data-z="${z}"][data-m="1"]`).value = r.ranges[z][1]; });
  toast("Ranges updated. Press Save settings to keep them."); };
$$("input[name=mode]").forEach((r) => (r.onchange = () => guard(null, async () => { await saveSettings({ mode: r.value }); toast(`Using ${MODE_NAMES[r.value]}. Sync your library on the Library tab.`); })));
$("#s-google-file").onchange = async (e) => { const fd = new FormData(); fd.append("file", e.target.files[0]);
  try { S.auth = await api("/api/auth/google/client", { form: fd }); renderSettings(); toast("OAuth client saved"); } catch (err) { toast(err.message, true); } };
$("#s-google-connect").onclick = () => (location.href = "/api/auth/google/start");
$("#s-google-disc").onclick = async () => { S.auth = await api("/api/auth/disconnect", { body: { which: "google" } }); renderSettings(); };
$("#s-ytm-save").onclick = (e) => guard(e.target, async () => { S.auth = await api("/api/auth/ytmusic", { body: { headers_raw: $("#s-ytm-headers").value } });
  $("#s-ytm-headers").value = ""; await init(false); toast("ytmusicapi ready. Sync your library next."); });
$("#s-ytm-disc").onclick = async () => { S.auth = await api("/api/auth/disconnect", { body: { which: "ytmusic" } }); renderSettings(); };
$("#s-intervals-save").onclick = (e) => guard(e.target, async () => { S.auth = await api("/api/auth/intervals", { body: { api_key: $("#s-intervals").value } });
  $("#s-intervals").value = ""; renderSettings(); loadIntervals(); toast("Saved"); });

/* ---------------- init ---------------- */
async function init(first = true) {
  const r = await api("/api/settings"); S.settings = r.settings; S.labels = r.zone_labels; S.auth = r.auth; renderMode();
  if (first) { $("#w-parse").click(); loadIntervals(); }
  const h = location.hash; if (h.startsWith("#settings")) { tab("settings"); if (h.includes("connected")) toast("Google account connected. Sync your library on the Library tab."); if (h.includes("auth_error")) toast("Google sign-in was cancelled or failed", true); history.replaceState(null, "", "/"); }
}
init().catch((e) => toast(e.message, true));
