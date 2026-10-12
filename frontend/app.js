/* HedgeRow — vanilla JS single-page app (no build step). */
"use strict";

// ------------------------------------------------------------------ constants
const PRODUCTION = [
  ["vegetables", "Vegetables"], ["fruit", "Fruit"], ["field_crops", "Field crops"], ["herbs", "Herbs"],
  ["flowers", "Flowers"], ["grass_pasture", "Grass / pasture"], ["hay_forage", "Hay / forage"],
  ["livestock", "Livestock / poultry"], ["other", "Other"],
];
const PLANT_TYPES = ["vegetables", "fruit", "field_crops", "herbs", "flowers"];
const PLANT_SUGGESTIONS = ["Potatoes", "Tomatoes", "Wheat", "Barley", "Maize", "Oilseed rape", "Apples", "Pears",
  "Strawberries", "Grapes", "Onions", "Carrots", "Cabbage", "Lettuce", "Peas", "Beans", "Rice", "Soybeans",
  "Sugar beet", "Oats", "Cucumbers", "Peppers", "Basil", "Mint", "Roses", "Tulips"];
const LIVESTOCK_SUGGESTIONS = ["Cattle (beef)", "Cattle (dairy)", "Sheep", "Goats", "Pigs", "Chickens", "Ducks", "Horses"];
const WATER = [
  ["rainfall_only", "Rainfall only"], ["rain_and_irrigation", "Rainfall and irrigation"],
  ["mainly_irrigation", "Mainly irrigation"], ["other", "Other / not applicable"],
];
const CONCERNS = [
  ["weather", "Weather risks"], ["pests_diseases", "Pests / diseases"], ["soil_water", "Soil / water"],
  ["yield_costs", "Yield / costs"], ["livestock_health", "Livestock health"], ["general", "General advice"],
];
const SIZES = [["small", "Small"], ["medium", "Medium"], ["large", "Large"]];
const URGENCY = { now: "Act now", soon: "Act soon", monitor: "Monitor", info: "For information" };
const label = (list, v) => (list.find(([k]) => k === v) || [, v || "—"])[1];
const humanize = (s) => (s || "").replace(/_/g, " ");

// ------------------------------------------------------------------ helpers
const $app = document.getElementById("app");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {} },
};

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
function fmtDay(s) {
  if (!s) return "";
  const d = new Date(s + "T12:00:00");
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}
function ago(iso) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const h = Math.round(mins / 60);
  return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} days ago`;
}

async function api(path, opts = {}) {
  const token = await ensureSession();
  const res = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(opts.headers || {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401 && !opts.noAuthRedirect) {
    store.set("agri_token", null); store.set("agri_farm", null); sessionPromise = null; me = null;
    location.hash = "#/signin";
    throw new Error("Please sign in again.");
  }
  if (res.status === 403 && !opts.noAuthRedirect) { location.hash = "#/signin"; throw new Error("Please sign in to continue."); }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try { const j = await res.json(); msg = typeof j.detail === "string" ? j.detail : msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

let sessionPromise = null;
function ensureSession() {
  const t = store.get("agri_token");
  if (t) return Promise.resolve(t);
  sessionPromise ||= fetch("/api/session", { method: "POST" }).then((r) => r.json()).then((j) => {
    store.set("agri_token", j.token);
    return j.token;
  });
  return sessionPromise;
}

let me = null;
async function account(refresh = false) {
  if (!me || refresh) me = await api("/api/me");
  paintAccount();
  return me;
}
function paintAccount() {
  const el = document.getElementById("acct");
  if (!el) return;
  el.innerHTML = me && me.registered
    ? `<a href="#/profile" class="muted small">${esc(me.email)}</a>`
    : `<a href="#/signin" class="small">Sign in</a>`;
}
async function requireAccount() {
  const m = await account();
  if (!m.registered) { location.hash = "#/signin"; return false; }
  return true;
}

async function currentFarm() {
  const { farms } = await api("/api/farms");
  const wanted = Number(store.get("agri_farm"));
  const farm = farms.find((f) => f.id === wanted) || farms[0] || null;
  if (farm) store.set("agri_farm", String(farm.id));
  return farm;
}

function render(html) { $app.innerHTML = html; window.scrollTo(0, 0); }
function showError(e) {
  render(`<div class="notice err">${esc(e.message || e)}</div><p><a href="#/">Back to start</a></p>`);
}
function setTabs(active) {
  const bar = document.getElementById("tabbar");
  bar.hidden = !active;
  bar.querySelectorAll("a").forEach((a) => a.classList.toggle("active", a.dataset.tab === active));
}

// ------------------------------------------------------------------ router
const routes = {
  "": welcome, dashboard, history, profile,
  setup: (p) => setup(Number(p[0] || 1)),
  risk: (p) => riskDetail(Number(p[0])),
  signin,
};
async function router() {
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  const fn = routes[parts[0]] || welcome;
  try { await fn(parts.slice(1)); } catch (e) { showError(e); }
}
window.addEventListener("hashchange", router);
router();

// ------------------------------------------------------------------ welcome
async function welcome() {
  setTabs(null);
  render(`<div class="spinner">Loading…</div>`);
  const [farm, m] = await Promise.all([currentFarm(), account()]);
  if (m.registered && farm && farm.status === "complete") { location.hash = "#/dashboard"; return; }
  const resume = farm && farm.status === "draft";
  render(`
    <figure class="hero-img">
      <img src="/static/hero.jpg" alt="A vegetable plot growing alongside a wildflower hedgerow on a farm, with fields and a farmhouse behind"
        width="1280" height="698" fetchpriority="high">
      <figcaption><span class="eyebrow">HedgeRow</span>Farm risk alerts that fit your farm</figcaption>
    </figure>
    <section class="hero">
      <h1>See farm risks earlier and know what to do next.</h1>
      <p>Get weather-based risk alerts and practical next steps for your crops and livestock.</p>
      <ul class="muted">
        <li>About 1–2 minutes to set up. Skip anything you don't know.</li>
        <li>Each alert explains why it appears, its time window and its limits.</li>
        <li>No sensors or extra equipment needed.</li>
      </ul>
      <div class="row" style="margin-top:16px">
        <a class="btn" href="#/setup/${resume ? farm.onboarding_step || 1 : 1}">${resume ? "Continue setup" : "Start quick setup"}</a>
        <a class="btn secondary" href="#/signin">I already have an account</a>
      </div>
      <p class="muted small" style="margin-top:20px">
        <b>Privacy:</b> we use your farm's location only to get local weather forecasts. You can edit or
        delete your farm data at any time from the Farm profile page.
      </p>
    </section>`);
}

// ------------------------------------------------------------------ setup (5 steps)
let draft = null; // working copy of the farm during setup

function blankDraft() {
  return { name: "", location_label: null, latitude: null, longitude: null, timezone: null, size_category: null,
    area_value: null, area_unit: "ha", production_types: [], production_items: [], main_concern: null,
    conditions: { water_access: null } };
}
function farmToDraft(f) {
  return { name: f.name || "", location_label: f.location_label, latitude: f.latitude, longitude: f.longitude,
    timezone: f.timezone, size_category: f.size_category, area_value: f.area_value, area_unit: f.area_unit || "ha",
    production_types: f.production_types || [], main_concern: f.main_concern,
    production_items: (f.production_items || []).map(({ type, name, area_or_count, unit, planting_date, growth_stage }) =>
      ({ type, name, area_or_count, unit, planting_date, growth_stage })),
    conditions: { ...f.conditions } };
}

async function saveDraft(extra = {}) {
  const body = { ...draft, ...extra };
  let farm = await currentFarm();
  farm = farm ? await api(`/api/farms/${farm.id}`, { method: "PUT", body }) : await api("/api/farms", { method: "POST", body });
  store.set("agri_farm", String(farm.id));
  return farm;
}

async function setup(step) {
  setTabs(null);
  await account();
  if (!draft) {
    const farm = await currentFarm();
    draft = farm ? farmToDraft(farm) : blankDraft();
  }
  step = Math.min(5, Math.max(1, step || 1));
  const steps = { 1: stepLocation, 2: stepProduction, 3: stepWater, 4: stepConcern, 5: stepReview };
  const titles = { 1: "Where is your farm?", 2: "What do you grow or raise?", 3: "How do you water your farm?",
    4: "What is your biggest concern?", 5: "Review your farm profile" };
  render(`
    <p class="muted small">Step ${step} of 5</p>
    <div class="progress" aria-hidden="true">${[1, 2, 3, 4, 5].map((i) => `<span class="${i <= step ? "done" : ""}"></span>`).join("")}</div>
    <h1>${titles[step]}</h1>
    <form id="stepform" novalidate>
      <div id="stepbody"></div>
      <div id="steperr"></div>
      <div class="stepnav">
        ${step > 1 ? `<button type="button" class="ghost" id="back">Back</button>` : `<span></span>`}
        <div class="row">
          ${step < 5 && step > 1 ? `<button type="button" class="secondary" id="skip">Skip</button>` : ""}
          <button type="submit" id="next">${step === 5 ? (me && me.registered ? "Confirm and go to dashboard" : "Create account and go to dashboard") : "Next"}</button>
        </div>
      </div>
    </form>`);
  const body = document.getElementById("stepbody");
  const validate = steps[step](body) || (() => null);
  const go = async (to, doValidate) => {
    if (doValidate) {
      const err = validate();
      if (err) { document.getElementById("steperr").innerHTML = `<div class="notice err">${esc(err)}</div>`; return; }
    }
    const btn = document.getElementById("next"); btn.disabled = true;
    try {
      if (step === 5 && to === "done") {
        const m = await account();
        if (!m.registered) {
          await saveDraft({ onboarding_step: 5 });
          await api("/api/auth/register", { method: "POST", noAuthRedirect: true, body: {
            email: document.getElementById("su_email").value, password: document.getElementById("su_pw").value } });
          await account(true);
        }
        await saveDraft({ status: "complete", onboarding_step: 5 });
        draft = null;
        location.hash = "#/dashboard";
        return;
      }
      await saveDraft({ onboarding_step: Math.max(to, 1) });   // persist progress (FR-03)
      location.hash = `#/setup/${to}`;
    } catch (e) {
      document.getElementById("steperr").innerHTML = `<div class="notice err">${esc(e.message)}</div>`;
      btn.disabled = false;
    }
  };
  document.getElementById("stepform").onsubmit = (e) => { e.preventDefault(); go(step === 5 ? "done" : step + 1, true); };
  document.getElementById("back")?.addEventListener("click", () => { location.hash = `#/setup/${step - 1}`; });
  document.getElementById("skip")?.addEventListener("click", () => go(step + 1, false));
}

// Step 1 — location and scale
function stepLocation(body) {
  body.innerHTML = `
    <p class="muted">We need your location for local weather forecasts. Nothing else is shared.</p>
    <label for="loc">Town, region or postcode</label>
    <div class="row" style="flex-wrap:nowrap">
      <input type="search" id="loc" placeholder="e.g. Cambridge, or Iowa City" autocomplete="off">
      <button type="button" class="secondary" id="locbtn">Search</button>
    </div>
    <div id="locresults"></div>
    <div id="locchosen"></div>
    <details style="margin-top:8px"><summary class="muted small">Enter coordinates instead</summary>
      <div class="row" style="margin-top:8px">
        <input type="number" step="any" id="lat" placeholder="Latitude" style="flex:1">
        <input type="number" step="any" id="lon" placeholder="Longitude" style="flex:1">
        <button type="button" class="secondary" id="coordbtn">Use</button>
      </div>
    </details>
    <label for="fname">Farm name <span class="muted small">(optional)</span></label>
    <input type="text" id="fname" maxlength="100" placeholder="e.g. Hillside Farm" value="${esc(draft.name)}">
    <label>How large is your farm?</label>
    <div class="chips" id="sizes">${SIZES.map(([k, v]) =>
      `<button type="button" class="chip" data-v="${k}" aria-pressed="${draft.size_category === k}">${v}</button>`).join("")}</div>
    <details style="margin-top:12px"><summary class="muted small">Add exact area (optional)</summary>
      <div class="row" style="margin-top:8px">
        <input type="number" min="0" step="any" id="area" placeholder="Area" style="flex:2" value="${draft.area_value ?? ""}">
        <select id="unit" style="flex:1"><option value="ha">hectares</option><option value="acres">acres</option></select>
      </div>
    </details>`;
  const chosen = () => {
    document.getElementById("locchosen").innerHTML = draft.latitude != null
      ? `<div class="notice info">📍 <b>${esc(draft.location_label || "Custom location")}</b>
         <span class="muted small">(${draft.latitude.toFixed(3)}, ${draft.longitude.toFixed(3)})</span></div>` : "";
  };
  chosen();
  document.getElementById("unit").value = draft.area_unit || "ha";
  const search = async () => {
    const q = document.getElementById("loc").value.trim();
    const box = document.getElementById("locresults");
    if (q.length < 2) return;
    box.innerHTML = `<p class="muted small">Searching…</p>`;
    try {
      const { results } = await api(`/api/geocode?q=${encodeURIComponent(q)}`);
      box.innerHTML = results.length ? `<ul class="results">${results.map((r, i) =>
        `<li><button type="button" data-i="${i}">${esc(r.label)}</button></li>`).join("")}</ul>`
        : `<p class="muted small">No matches. Try a nearby town or region name, or enter coordinates.</p>`;
      box.querySelectorAll("button").forEach((b) => b.onclick = () => {
        const r = results[Number(b.dataset.i)];
        Object.assign(draft, { location_label: r.label, latitude: r.latitude, longitude: r.longitude, timezone: r.timezone });
        box.innerHTML = ""; chosen();
      });
    } catch (e) { box.innerHTML = `<div class="notice err">${esc(e.message)}</div>`; }
  };
  document.getElementById("locbtn").onclick = search;
  document.getElementById("loc").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); search(); } });
  document.getElementById("coordbtn").onclick = () => {
    const lat = parseFloat(document.getElementById("lat").value), lon = parseFloat(document.getElementById("lon").value);
    if (Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180) {
      Object.assign(draft, { location_label: `Lat ${lat.toFixed(3)}, Lon ${lon.toFixed(3)}`, latitude: lat, longitude: lon });
      chosen();
    }
  };
  document.getElementById("sizes").onclick = (e) => {
    const b = e.target.closest(".chip"); if (!b) return;
    draft.size_category = draft.size_category === b.dataset.v ? null : b.dataset.v;
    body.querySelectorAll("#sizes .chip").forEach((c) => c.setAttribute("aria-pressed", c.dataset.v === draft.size_category));
  };
  return () => {
    draft.name = document.getElementById("fname").value.trim();
    const a = parseFloat(document.getElementById("area").value);
    draft.area_value = Number.isFinite(a) ? a : null;
    draft.area_unit = document.getElementById("unit").value;
    if (draft.latitude == null) return "Please choose your farm location so we can get local weather.";
    return null;
  };
}

// Step 2 — production (multi-select + conditional follow-ups)
function stepProduction(body) {
  const paint = () => {
    const types = draft.production_types;
    const hasPlants = types.some((t) => PLANT_TYPES.includes(t));
    const hasLivestock = types.includes("livestock");
    const plants = draft.production_items.filter((p) => p.type !== "livestock");
    const animals = draft.production_items.filter((p) => p.type === "livestock");
    body.innerHTML = `
      <p class="muted">Select all that apply.</p>
      <div class="chips" id="ptypes">${PRODUCTION.map(([k, v]) =>
        `<button type="button" class="chip" data-v="${k}" aria-pressed="${types.includes(k)}">${v}</button>`).join("")}</div>
      ${hasPlants ? `
        <div class="card">
          <h3>Which crops or plants? <span class="muted small">(optional)</span></h3>
          <p class="muted small">Naming crops lets us add crop-specific checks. Potatoes and tomatoes get late-blight weather alerts.</p>
          <div class="row" style="flex-wrap:nowrap">
            <input type="text" id="plantin" list="plantlist" placeholder="Start typing, e.g. Potatoes">
            <button type="button" class="secondary" id="plantadd">Add</button>
          </div>
          <datalist id="plantlist">${PLANT_SUGGESTIONS.map((s) => `<option value="${s}">`).join("")}</datalist>
          <div class="row" style="margin-top:8px">${plants.map((p) =>
            `<span class="tag">${esc(p.name)}<button type="button" data-rm="${esc(p.name)}" aria-label="Remove ${esc(p.name)}">×</button></span>`).join("")}</div>
        </div>` : ""}
      ${hasLivestock ? `
        <div class="card">
          <h3>Which animals, and roughly how many? <span class="muted small">(optional)</span></h3>
          <div class="row">
            <input type="text" id="animalin" list="animallist" placeholder="Species, e.g. Sheep" style="flex:2;min-width:160px">
            <input type="number" id="animalcount" min="0" placeholder="Approx. number" style="flex:1;min-width:120px">
            <button type="button" class="secondary" id="animaladd">Add</button>
          </div>
          <datalist id="animallist">${LIVESTOCK_SUGGESTIONS.map((s) => `<option value="${s}">`).join("")}</datalist>
          <div class="row" style="margin-top:8px">${animals.map((p) =>
            `<span class="tag">${esc(p.name)}${p.area_or_count ? ` · ${p.area_or_count}` : ""}<button type="button" data-rm="${esc(p.name)}" aria-label="Remove ${esc(p.name)}">×</button></span>`).join("")}</div>
        </div>` : ""}`;
    body.querySelector("#ptypes").onclick = (e) => {
      const b = e.target.closest(".chip"); if (!b) return;
      const v = b.dataset.v;
      draft.production_types = types.includes(v) ? types.filter((t) => t !== v) : [...types, v];
      // drop follow-up items that no longer apply
      const stillPlants = draft.production_types.some((t) => PLANT_TYPES.includes(t));
      draft.production_items = draft.production_items.filter((p) =>
        p.type === "livestock" ? draft.production_types.includes("livestock") : stillPlants);
      paint();
    };
    body.querySelectorAll("[data-rm]").forEach((b) => b.onclick = () => {
      draft.production_items = draft.production_items.filter((p) => p.name !== b.dataset.rm); paint();
    });
    const addPlant = () => {
      const v = body.querySelector("#plantin").value.trim();
      if (!v || draft.production_items.some((p) => p.name.toLowerCase() === v.toLowerCase())) return;
      const type = types.find((t) => PLANT_TYPES.includes(t)) || "vegetables";
      draft.production_items.push({ type, name: v }); paint();
      body.querySelector("#plantin")?.focus();
    };
    const addAnimal = () => {
      const v = body.querySelector("#animalin").value.trim();
      const n = parseFloat(body.querySelector("#animalcount").value);
      if (!v || draft.production_items.some((p) => p.name.toLowerCase() === v.toLowerCase())) return;
      draft.production_items.push({ type: "livestock", name: v, area_or_count: Number.isFinite(n) ? n : null, unit: "head" });
      paint();
    };
    body.querySelector("#plantadd")?.addEventListener("click", addPlant);
    body.querySelector("#plantin")?.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addPlant(); } });
    body.querySelector("#animaladd")?.addEventListener("click", addAnimal);
    body.querySelector("#animalin")?.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addAnimal(); } });
  };
  paint();
  return () => draft.production_types.length ? null : "Select at least one option, or press Skip.";
}

function radioStep(body, list, current, onPick, intro) {
  body.innerHTML = `${intro ? `<p class="muted">${intro}</p>` : ""}${list.map(([k, v]) => `
    <label class="choice"><input type="radio" name="opt" value="${k}" ${current === k ? "checked" : ""}>${v}</label>`).join("")}`;
  body.querySelectorAll("input[name=opt]").forEach((r) => r.onchange = () => onPick(r.value));
}

// Step 3 — water access
function stepWater(body) {
  radioStep(body, WATER, draft.conditions.water_access, (v) => { draft.conditions.water_access = v; },
    "This helps us interpret drought and rainfall risks.");
  return () => draft.conditions.water_access ? null : "Choose an option, or press Skip.";
}

// Step 4 — main concern
function stepConcern(body) {
  radioStep(body, CONCERNS, draft.main_concern, (v) => { draft.main_concern = v; },
    "We'll put related alerts first on your dashboard.");
  return () => draft.main_concern ? null : "Choose an option, or press Skip.";
}

// Step 5 — review
function stepReview(body) {
  const items = (t) => draft.production_items.filter((p) => (t === "livestock") === (p.type === "livestock"))
    .map((p) => p.name + (p.area_or_count ? ` (${p.area_or_count})` : "")).join(", ");
  const row = (k, v, step) => `<dt>${k}</dt><dd>${v ? esc(v) : `<span class="muted">Not provided</span>`}
    <button type="button" class="link small" data-edit="${step}">Edit</button></dd>`;
  body.innerHTML = `
    <div class="card"><dl class="review">
      ${row("Location", draft.location_label, 1)}
      ${row("Farm name", draft.name, 1)}
      ${row("Size", draft.size_category ? label(SIZES, draft.size_category) + (draft.area_value ? ` · ${draft.area_value} ${draft.area_unit}` : "") : "", 1)}
      ${row("Production", draft.production_types.map((t) => label(PRODUCTION, t)).join(", "), 2)}
      ${row("Crops / plants", items("plants"), 2)}
      ${row("Livestock", items("livestock"), 2)}
      ${row("Water", draft.conditions.water_access && label(WATER, draft.conditions.water_access), 3)}
      ${row("Main concern", draft.main_concern && label(CONCERNS, draft.main_concern), 4)}
    </dl></div>
    <p class="muted small">You can change any of this later. We may ask a short follow-up question when it would improve a specific alert.</p>
    ${me && me.registered ? "" : `
    <div class="card">
      <h2 style="margin-top:0">Create your account to save your farm</h2>
      <p class="muted small">So you can come back to your dashboard from any device. Already have an account?
        <a href="#/signin">Sign in</a> and we'll keep these answers.</p>
      <label for="su_email">Email</label>
      <input type="email" id="su_email" autocomplete="email" required>
      <label for="su_pw">Password <span class="muted small">(at least 8 characters)</span></label>
      <input type="password" id="su_pw" autocomplete="new-password" minlength="8" required>
    </div>`}`;
  body.querySelectorAll("[data-edit]").forEach((b) => b.onclick = () => { location.hash = `#/setup/${b.dataset.edit}`; });
  return () => {
    if (draft.latitude == null) return "A location is needed. Please edit step 1.";
    if (!(me && me.registered)) {
      const e = document.getElementById("su_email").value.trim(), p = document.getElementById("su_pw").value;
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(e)) return "Please enter a valid email address.";
      if (p.length < 8) return "Please choose a password of at least 8 characters.";
    }
    return null;
  };
}

// ------------------------------------------------------------------ dashboard
function levelBadge(level) { return `<span class="badge lvl-${level}">${level} risk</span>`; }

function weatherBlock(w) {
  if (w.status === "unavailable") {
    return `<div class="notice err"><b>Weather data unavailable.</b> ${esc(w.error || "")}
      Risk assessments can't be generated without a forecast, so none are shown. Try refreshing later.</div>`;
  }
  const s = w.summary, c = s.current;
  return `
    ${w.status === "stale" ? `<div class="notice warn"><b>Weather data may be out of date</b> (last updated ${fmtTime(w.fetched_at)}).
      ${esc(w.error || "")} Alerts below are based on this older forecast.</div>` : ""}
    <div class="card">
      <div class="spread"><h2 style="margin:0">Weather now</h2><span class="muted small">${esc(c.condition)}</span></div>
      <div class="wx-now"><span class="temp">${Math.round(c.temperature)}°C</span>
        <span class="muted">Humidity ${c.humidity}% · Wind ${Math.round(c.wind_speed)} km/h · Rain ${c.precipitation} mm</span></div>
      <div class="days" style="margin-top:12px">${s.days.map((d) => `
        <div class="day"><b>${fmtDay(d.date).split(",")[0]}</b>${Math.round(d.t_max)}° / ${Math.round(d.t_min)}°
          <div class="muted">${(d.rain_mm ?? 0).toFixed(1)} mm${d.rain_prob != null ? ` · ${d.rain_prob}%` : ""}</div></div>`).join("")}</div>
      <p class="muted small" style="margin:8px 0 0">Source: ${esc(w.source)} · updated ${ago(w.fetched_at)}</p>
    </div>`;
}

function riskCard(a) {
  const top = a.recommendations.filter((r) => r.urgency !== "info").slice(0, 2);
  return `
    <article class="card risk ${a.level}">
      <div class="spread"><h3>${esc(a.title)}</h3>${levelBadge(a.level)}</div>
      <p class="muted small">${esc(a.applies_to)} · ${fmtDay(a.window_start)} – ${fmtDay(a.window_end)} · priority score ${a.priority_score}</p>
      <p>${esc(a.evidence[0])}</p>
      ${top.length ? `<ul class="plain">${top.map((r) => `<li><span class="urg ${r.urgency}">${URGENCY[r.urgency]}</span> ${esc(r.action)}</li>`).join("")}</ul>` : ""}
      ${a.missing_inputs.length ? `<p class="small muted">❓ ${a.missing_inputs.length} quick question${a.missing_inputs.length > 1 ? "s" : ""} could improve this alert.</p>` : ""}
      <a href="#/risk/${a.id}">Why this appears &amp; what to do →</a>
    </article>`;
}

async function dashboard(_, refresh = false) {
  setTabs("dashboard");
  if (!(await requireAccount())) return;
  const farm = await currentFarm();
  if (!farm || farm.status !== "complete") { location.hash = farm ? `#/setup/${farm.onboarding_step || 1}` : "#/"; return; }
  if (!refresh) render(`<div class="spinner">Getting the latest forecast and checking risks…</div>`);
  const d = await api(`/api/farms/${farm.id}/dashboard${refresh ? "?refresh=true" : ""}`);
  const elevated = d.assessments.filter((a) => a.level !== "low");
  const low = d.assessments.filter((a) => a.level === "low");
  const actions = elevated.flatMap((a) => a.recommendations.filter((r) => r.urgency === "now" || r.urgency === "soon")
    .map((r) => ({ ...r, hazard: a.title, aid: a.id, score: a.priority_score })))
    .sort((x, y) => (x.urgency === y.urgency ? y.score - x.score : x.urgency === "now" ? -1 : 1)).slice(0, 5);
  const f = d.farm;
  render(`
    <div class="spread">
      <div><h1 style="margin-bottom:2px">${esc(f.name || "My farm")}</h1>
        <p class="muted small">📍 ${esc(f.location_label)} · ${f.production_types.map((t) => label(PRODUCTION, t)).join(", ") || "No production types yet"}</p></div>
      <button class="secondary" id="refresh">Refresh</button>
    </div>
    <p class="muted small">Risks checked ${d.assessed_at ? fmtTime(d.assessed_at) : "—"} · rules ${esc(d.model_version)}</p>
    ${weatherBlock(d.weather)}
    ${d.weather.status !== "unavailable" ? `
      ${actions.length ? `<h2>Top actions</h2><div class="card"><ul class="actions-list">${actions.map((r) => `
        <li><span class="urg ${r.urgency}">${URGENCY[r.urgency]}</span> · <span class="muted small">${esc(r.hazard)}</span><br>
        <a href="#/risk/${r.aid}" style="color:inherit;text-decoration:none">${esc(r.action)}</a></li>`).join("")}</ul></div>` : ""}
      <h2>Risk alerts</h2>
      ${elevated.length ? elevated.map(riskCard).join("") :
        `<div class="notice info">✅ No elevated risks in the current forecast for the hazards we check.</div>`}
      ${low.length ? `<h2>Checked: no elevated risk</h2><div class="card"><ul class="actions-list">${low.map((a) => `
        <li class="spread"><span>${esc(a.title)} <span class="muted small">· ${esc(a.evidence[0])}</span></span>
        <a href="#/risk/${a.id}" class="small">Details</a></li>`).join("")}</ul></div>` : ""}
    ` : ""}
    ${d.hints.length ? `<h2>Improve your alerts <span class="muted small">(optional)</span></h2>
      <div class="card"><ul class="plain">${d.hints.map((h) => `<li>${esc(h)}</li>`).join("")}</ul>
      <a href="#/profile">Update farm profile</a></div>` : ""}
    <p class="muted small" style="margin-top:24px">These are weather-based risk warnings, not confirmation of damage or disease.
      Thresholds are pilot placeholders pending agronomist review. Always follow local expert, regulatory and veterinary advice.</p>`);
  document.getElementById("refresh").onclick = async (e) => {
    e.target.disabled = true; e.target.textContent = "Refreshing…";
    try { await dashboard(null, true); } catch (err) { showError(err); }
  };
}

// ------------------------------------------------------------------ risk detail
async function riskDetail(id) {
  setTabs("dashboard");
  if (!(await requireAccount())) return;
  render(`<div class="spinner">Loading…</div>`);
  const a = await api(`/api/assessments/${id}`);
  render(`
    <p><a href="#/dashboard">← Dashboard</a></p>
    <div class="spread"><h1>${esc(a.title)}</h1>${levelBadge(a.level)}</div>
    <div class="card">
      <dl class="review">
        <dt>Affects</dt><dd>${esc(a.applies_to)}</dd>
        <dt>Time window</dt><dd>${fmtDay(a.window_start)} – ${fmtDay(a.window_end)}</dd>
        <dt>Priority score</dt><dd>${a.priority_score} <span class="muted small">(likelihood level × impact; not a probability of loss)</span></dd>
        <dt>Assessed</dt><dd>${fmtTime(a.assessed_at)} · valid until ${fmtTime(a.valid_until)}</dd>
        <dt>Rules</dt><dd>${esc(a.model_version)}</dd>
      </dl>
    </div>
    <h2>Why this appears</h2>
    <div class="card"><ul class="plain">${a.evidence.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></div>
    ${a.missing_inputs.length ? `<h2>Help us sharpen this alert</h2>
      <div class="card stack" id="followups">${a.missing_inputs.map((m, i) => `
        <div><b>${esc(m.question)}</b>
        <div class="chips" style="margin-top:6px">${m.options.map((o) =>
          `<button type="button" class="chip" data-i="${i}" data-v="${o}">${esc(humanize(o))}</button>`).join("")}</div></div>`).join("")}
        <p class="muted small" style="margin:0">Your answer is saved to your farm profile and the alert is re-checked.</p>
      </div>` : ""}
    <h2>What to do</h2>
    <div class="card">${a.recommendations.map((r) => `
      <div class="rec" data-rec="${r.id}">
        <span class="urg ${r.urgency}">${URGENCY[r.urgency]}</span>
        <p style="margin:2px 0 4px"><b>${esc(r.action)}</b></p>
        <p class="muted small" style="margin:0">${esc(r.rationale)}${r.applicability ? ` · Applies to: ${esc(r.applicability)}` : ""}</p>
        ${r.caveat ? `<p class="small" style="margin:4px 0 0">⚠️ ${esc(r.caveat)}</p>` : ""}
        ${r.urgency !== "info" ? feedbackControls(r) : ""}
      </div>`).join("")}</div>
    <h2>Limits of this alert</h2>
    <div class="card"><ul class="plain">${a.caveats.map((c) => `<li>${esc(c)}</li>`).join("")}
      <li>Thresholds are illustrative pilot values and must be reviewed by an agronomist for your region.</li></ul></div>`);

  document.querySelectorAll("#followups .chip").forEach((b) => b.onclick = async () => {
    const m = a.missing_inputs[Number(b.dataset.i)];
    b.disabled = true;
    await api(`/api/farms/${a.farm_id}/follow-up`, { method: "POST", body: { key: m.key, value: b.dataset.v, item: m.item || null } });
    // re-run assessment, then go to the new version of this hazard
    const d = await api(`/api/farms/${a.farm_id}/dashboard`);
    const next = d.assessments.find((x) => x.hazard === a.hazard);
    location.hash = next ? `#/risk/${next.id}` : "#/dashboard";
  });
  wireFeedback(document);
}

function feedbackControls(r) {
  const fb = r.feedback || {};
  const p = (v) => (v === true || v === 1 ? "true" : "false");
  const n = (v) => (v === false || v === 0 ? "true" : "false");
  return `
    <div class="fb">
      <button type="button" class="ghost" data-fb="useful" data-val="true" aria-pressed="${p(fb.useful)}">👍 Useful</button>
      <button type="button" class="ghost" data-fb="useful" data-val="false" aria-pressed="${n(fb.useful)}">👎 Not useful</button>
      <button type="button" class="ghost" data-fb="action_taken" data-val="true" aria-pressed="${p(fb.action_taken)}">✔ I did this</button>
    </div>
    <details style="margin-top:6px"><summary class="muted small">${fb.outcome_notes ? "Your note" : "Add a note about what happened"}</summary>
      <textarea data-note placeholder="e.g. Cleared the ditch; low field still flooded">${esc(fb.outcome_notes || "")}</textarea>
      <button type="button" class="secondary" data-savenote style="margin-top:6px">Save note</button>
    </details>`;
}

function wireFeedback(root) {
  root.querySelectorAll("[data-rec]").forEach((el) => {
    const id = el.dataset.rec;
    el.querySelectorAll("[data-fb]").forEach((b) => b.onclick = async () => {
      const key = b.dataset.fb;
      const pressed = b.getAttribute("aria-pressed") === "true";
      const val = pressed ? null : b.dataset.val === "true";
      await api(`/api/recommendations/${id}/feedback`, { method: "POST", body: { [key]: val } });
      el.querySelectorAll(`[data-fb=${key}]`).forEach((x) =>
        x.setAttribute("aria-pressed", String(val !== null && x.dataset.val === String(val))));
    });
    const save = el.querySelector("[data-savenote]");
    if (save) save.onclick = async () => {
      await api(`/api/recommendations/${id}/feedback`, { method: "POST", body: { outcome_notes: el.querySelector("[data-note]").value } });
      save.textContent = "Saved ✓";
    };
  });
}

// ------------------------------------------------------------------ history
async function history() {
  setTabs("history");
  if (!(await requireAccount())) return;
  const farm = await currentFarm();
  if (!farm) { location.hash = "#/"; return; }
  render(`<div class="spinner">Loading…</div>`);
  const { history: items } = await api(`/api/farms/${farm.id}/history`);
  render(`
    <h1>History</h1>
    <p class="muted">Past alerts, your feedback and the actions you recorded.</p>
    ${items.length ? items.map((a) => {
      const fb = a.recommendations.filter((r) => r.feedback);
      return `<article class="card risk ${a.level}">
        <div class="spread"><h3>${esc(a.title)}</h3>${levelBadge(a.level)}</div>
        <p class="muted small">Assessed ${fmtTime(a.assessed_at)} · window ${fmtDay(a.window_start)} – ${fmtDay(a.window_end)}</p>
        <p class="small">${esc(a.evidence[0])}</p>
        ${fb.length ? `<ul class="plain small">${fb.map((r) => `<li>${esc(r.action)} —
          ${r.feedback.useful === 1 ? "👍 useful" : r.feedback.useful === 0 ? "👎 not useful" : ""}
          ${r.feedback.action_taken ? " · ✔ done" : ""}${r.feedback.outcome_notes ? ` · “${esc(r.feedback.outcome_notes)}”` : ""}</li>`).join("")}</ul>` : ""}
        <a href="#/risk/${a.id}" class="small">Open</a>
      </article>`;
    }).join("") : `<div class="notice info">No elevated alerts recorded yet. Alerts and your feedback will appear here.</div>`}`);
}

// ------------------------------------------------------------------ profile (edit everything in one place)
async function profile() {
  setTabs("profile");
  if (!(await requireAccount())) return;
  const farm = await currentFarm();
  if (!farm) { location.hash = "#/"; return; }
  draft = farmToDraft(farm);
  const c = draft.conditions;
  const opt = (list, v) => `<option value="">Unknown / not set</option>` + list.map(([k, t]) =>
    `<option value="${k}" ${v === k ? "selected" : ""}>${t}</option>`).join("");
  render(`
    <h1>Farm profile</h1>
    <p class="muted">Review and update your farm details. Unknown answers are fine.</p>
    <div class="card">
      <h2 style="margin-top:0">Location, size and production</h2>
      <dl class="review">
        <dt>Location</dt><dd>${esc(draft.location_label || "—")}</dd>
        <dt>Size</dt><dd>${esc(label(SIZES, draft.size_category))}${draft.area_value ? ` · ${draft.area_value} ${esc(draft.area_unit)}` : ""}</dd>
        <dt>Production</dt><dd>${esc(draft.production_types.map((t) => label(PRODUCTION, t)).join(", ") || "—")}</dd>
        <dt>Crops / animals</dt><dd>${esc(draft.production_items.map((p) => p.name + (p.growth_stage ? ` (${humanize(p.growth_stage)})` : "")).join(", ") || "—")}</dd>
      </dl>
      <div class="row" style="margin-top:12px">
        <a class="btn secondary" href="#/setup/1">Edit location &amp; size</a>
        <a class="btn secondary" href="#/setup/2">Edit crops &amp; livestock</a>
      </div>
    </div>
    <form class="card" id="condform">
      <h2 style="margin-top:0">Water, soil and priorities</h2>
      <label for="water">Water access</label><select id="water">${opt(WATER, c.water_access)}</select>
      <label for="irr">Irrigation method</label><select id="irr">${opt([["drip", "Drip"], ["sprinkler", "Sprinkler"], ["flood_furrow", "Flood / furrow"], ["hand", "By hand / hose"], ["none", "None"]], c.irrigation_type)}</select>
      <label for="drain">Drainage after heavy rain</label><select id="drain">${opt([["good", "Good"], ["moderate", "Moderate"], ["poor", "Poor"], ["unknown", "Don't know"]], c.drainage)}</select>
      <label for="wlog">Waterlogged before?</label><select id="wlog">${opt([["yes", "Yes"], ["no", "No"], ["unknown", "Don't know"]], c.waterlogging_history)}</select>
      <label for="soil">Soil type</label><select id="soil">${opt([["sandy", "Sandy"], ["loam", "Loam"], ["clay", "Clay"], ["silt", "Silt"], ["peat", "Peat"], ["chalk", "Chalky"]], c.soil_type)}</select>
      <label for="concern">Main concern</label><select id="concern">${opt(CONCERNS, draft.main_concern)}</select>
      <div class="row" style="margin-top:16px"><button type="submit">Save changes</button><span id="saved" class="muted small"></span></div>
    </form>
    <div class="card">
      <h2 style="margin-top:0">Account</h2>
      <p>Signed in as <b>${esc(me.email)}</b></p>
      <button class="secondary" id="signout">Sign out</button>
    </div>
    <div class="card">
      <h2 style="margin-top:0">Your data</h2>
      <p class="muted small">Your farm's location is used only to fetch local weather. Deleting removes the farm profile,
        alerts, weather snapshots and feedback from our database.</p>
      <div class="row">
        <button class="danger" id="delfarm">Delete this farm</button>
        <button class="danger" id="delall">Delete all my data</button>
      </div>
    </div>`);
  document.getElementById("condform").onsubmit = async (e) => {
    e.preventDefault();
    const v = (id) => document.getElementById(id).value || null;
    await api(`/api/farms/${farm.id}`, { method: "PUT", body: {
      main_concern: v("concern"),
      conditions: { water_access: v("water"), irrigation_type: v("irr"), drainage: v("drain"),
        waterlogging_history: v("wlog"), soil_type: v("soil") },
    } });
    document.getElementById("saved").textContent = "Saved ✓ — alerts will be re-checked.";
  };
  document.getElementById("signout").onclick = async () => {
    await api("/api/auth/logout", { method: "POST" });
    store.set("agri_token", null); store.set("agri_farm", null); sessionPromise = null; me = null; draft = null;
    location.hash = "#/"; router();
  };
  document.getElementById("delfarm").onclick = async () => {
    if (!confirm("Delete this farm and all its alerts and feedback? This cannot be undone.")) return;
    await api(`/api/farms/${farm.id}`, { method: "DELETE" });
    store.set("agri_farm", null); draft = null; location.hash = "#/";
  };
  document.getElementById("delall").onclick = async () => {
    if (!confirm("Delete your account and all farm data? This cannot be undone.")) return;
    await api("/api/me", { method: "DELETE" });
    store.set("agri_token", null); store.set("agri_farm", null); sessionPromise = null; me = null; draft = null;
    location.hash = "#/"; router();
  };
}

// ------------------------------------------------------------------ sign in
async function signin() {
  setTabs(null);
  const m = await account();
  if (m.registered) { location.hash = "#/dashboard"; return; }
  render(`
    <h1>Sign in to HedgeRow</h1>
    <form class="card" id="signinform" novalidate>
      <label for="si_email">Email</label>
      <input type="email" id="si_email" autocomplete="email" required>
      <label for="si_pw">Password</label>
      <input type="password" id="si_pw" autocomplete="current-password" required>
      <div id="si_err"></div>
      <div class="row" style="margin-top:16px"><button type="submit" id="si_btn">Sign in</button></div>
    </form>
    <p class="muted">New to HedgeRow? <a href="#/setup/1">Set up your farm</a>. You'll create an account at the end.</p>`);
  document.getElementById("signinform").onsubmit = async (e) => {
    e.preventDefault();
    const btn = document.getElementById("si_btn"); btn.disabled = true;
    try {
      const r = await api("/api/auth/login", { method: "POST", noAuthRedirect: true, body: {
        email: document.getElementById("si_email").value, password: document.getElementById("si_pw").value } });
      store.set("agri_token", r.token); store.set("agri_farm", null); sessionPromise = null; draft = null;
      await account(true);
      const farm = await currentFarm();
      location.hash = !farm ? "#/setup/1" : farm.status === "complete" ? "#/dashboard" : `#/setup/${farm.onboarding_step || 1}`;
    } catch (err) {
      document.getElementById("si_err").innerHTML = `<div class="notice err">${esc(err.message)}</div>`;
      btn.disabled = false;
    }
  };
}
