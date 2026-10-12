/* HedgeRow — vanilla JS single-page app (no build step). */
"use strict";

// ------------------------------------------------------------------ constants
const PRODUCTION = [
  ["vegetables", "Vegetables"], ["fruit", "Fruit"], ["field_crops", "Field crops"], ["herbs", "Herbs"],
  ["flowers", "Flowers"], ["grass_pasture", "Grass / pasture"], ["hay_forage", "Hay / forage"],
  ["livestock", "Livestock / poultry"], ["other", "Other"],
];
const PLANT_TYPES = ["vegetables", "fruit", "field_crops", "herbs", "flowers"];
const PLANT_SUGGESTIONS = ["Carrots", "Beetroot", "Potatoes", "Onions", "Lettuce", "Cabbage", "Kale", "Broccoli",
  "Peas", "Broad beans", "Tomatoes", "Courgettes", "Spinach", "Strawberries", "Apples", "Wheat", "Barley",
  "Oilseed rape", "Pears", "Leeks", "Cucumbers", "Herbs"];
const LIVESTOCK_SUGGESTIONS = ["Cattle (beef)", "Cattle (dairy)", "Sheep", "Goats", "Pigs", "Chickens", "Ducks", "Horses"];
const WATER = [
  ["rainfall_only", "Rainfall only"], ["rain_and_irrigation", "Rainfall and irrigation"],
  ["mainly_irrigation", "Mainly irrigation"], ["other", "Other / not applicable"],
];
const CONCERNS = [
  ["weather", "Weather risks"], ["pests_diseases", "Pests / diseases"], ["soil_water", "Soil / water"],
  ["yield_costs", "Yield / costs"], ["livestock_health", "Livestock health"], ["general", "General advice"],
];
const PEST_USE = [["none", "I don't use any"], ["some", "Yes, I use some"], ["unsure", "Not sure"]];
const PEST_PER = ["per application", "per week", "per month", "per season", "per year"];
const PEST_SUGGESTIONS = ["Slug pellets (ferric phosphate)", "Glyphosate weedkiller", "Insecticidal soap / fatty acids",
  "Pyrethrum / pyrethrin spray", "Sulphur fungicide", "Bacillus thuringiensis (Bt)", "Nematodes (biological control)",
  "Plant oil spray", "Fungicide (other)", "Insecticide (other)", "Herbicide / weedkiller (other)"];
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
  crop: (p) => cropPage(Number(p[0])),
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
    conditions: { water_access: null, pesticide_use: null }, pesticides: [] };
}
function farmToDraft(f) {
  return { name: f.name || "", location_label: f.location_label, latitude: f.latitude, longitude: f.longitude,
    timezone: f.timezone, size_category: f.size_category, area_value: f.area_value, area_unit: f.area_unit || "ha",
    production_types: f.production_types || [], main_concern: f.main_concern,
    production_items: (f.production_items || []).map(({ type, name, area_or_count, unit, planting_date, growth_stage }) =>
      ({ type, name, area_or_count, unit, planting_date, growth_stage })),
    conditions: { ...f.conditions },
    pesticides: (f.pesticides || []).map(({ product, amount, unit, per, crop }) => ({ product, amount, unit, per, crop })) };
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
  const titles = { 1: "Where is your farm?", 2: "What do you grow or raise?", 3: "Water and crop protection",
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
    <label for="loc">UK postcode <span class="muted small">(or town)</span></label>
    <div class="row" style="flex-wrap:nowrap">
      <input type="search" id="loc" placeholder="e.g. CB2 1TN" autocomplete="postal-code">
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
        : `<p class="muted small">No matches. Check the postcode, try a nearby town, or enter coordinates.</p>`;
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
          <p class="muted small">Each crop gets its own page with tailored watering, sunlight and pest advice.</p>
          <div class="row" style="flex-wrap:nowrap">
            <input type="text" id="plantin" list="plantlist" placeholder="Start typing, e.g. Potatoes">
            <button type="button" class="secondary" id="plantadd">Add</button>
          </div>
          <datalist id="plantlist">${PLANT_SUGGESTIONS.map((s) => `<option value="${s}">`).join("")}</datalist>
          ${plants.length ? `
          <p style="margin:14px 0 4px"><b>When did you plant this crop?</b> <span class="muted small">(optional; used for growth stage and watering)</span></p>
          <ul class="plantlist">${plants.map((p) => `
            <li><span class="pl-name">${esc(p.name)}</span>
              <input type="date" max="${new Date().toISOString().slice(0, 10)}" data-date="${esc(p.name)}" value="${esc(p.planting_date || "")}"
                aria-label="Planting date for ${esc(p.name)}">
              <button type="button" class="ghost pl-rm" data-rm="${esc(p.name)}" aria-label="Remove ${esc(p.name)}">×</button></li>`).join("")}
          </ul>` : ""}
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
    body.querySelectorAll("[data-date]").forEach((inp) => inp.onchange = () => {
      const item = draft.production_items.find((p) => p.name === inp.dataset.date);
      if (item) item.planting_date = inp.value || null;
    });
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
  const paint = () => {
    const use = draft.conditions.pesticide_use;
    const crops = draft.production_items.filter((p) => p.type !== "livestock").map((p) => p.name);
    body.innerHTML = `
      <h3 style="margin-top:4px">How do you water your farm?</h3>
      <p class="muted small">This helps us interpret drought and rainfall risks.</p>
      ${WATER.map(([k, v]) => `<label class="choice"><input type="radio" name="water" value="${k}"
        ${draft.conditions.water_access === k ? "checked" : ""}>${v}</label>`).join("")}
      <h3 style="margin-top:24px">Which pesticides do you use, and how much?</h3>
      <p class="muted small">Include weedkillers, slug pellets, sprays and biological controls. We use this to suggest
        gentler alternatives on each crop page. Optional.</p>
      <div class="chips" id="puse">${PEST_USE.map(([k, v]) =>
        `<button type="button" class="chip" data-v="${k}" aria-pressed="${use === k}">${v}</button>`).join("")}</div>
      ${use === "some" ? `
        <div class="card">
          <div class="pest-form">
            <div class="pf-product"><label for="pp">Product</label>
              <input type="text" id="pp" list="pestlist" placeholder="e.g. Slug pellets (ferric phosphate)"></div>
            <div><label for="pa">Amount</label><input type="number" id="pa" min="0" step="any" placeholder="e.g. 50"></div>
            <div><label for="pu">Unit</label><select id="pu">${["ml", "L", "g", "kg"].map((u) => `<option>${u}</option>`).join("")}</select></div>
            <div><label for="pper">How often</label><select id="pper">${PEST_PER.map((x) => `<option>${x}</option>`).join("")}</select></div>
            ${crops.length ? `<div><label for="pc">On</label><select id="pc"><option value="">All crops</option>
              ${crops.map((c) => `<option>${esc(c)}</option>`).join("")}</select></div>` : ""}
          </div>
          <datalist id="pestlist">${PEST_SUGGESTIONS.map((x) => `<option value="${esc(x)}">`).join("")}</datalist>
          <button type="button" class="secondary" id="padd" style="margin-top:12px">Add pesticide</button>
          ${draft.pesticides.length ? `<ul class="pest-list">${draft.pesticides.map((p, i) => `
            <li><span><b>${esc(p.product)}</b>${p.amount != null ? ` · ${p.amount} ${esc(p.unit || "")} ${esc(p.per || "")}` : ""}
              ${p.crop ? `<span class="muted small"> · on ${esc(p.crop)}</span>` : ""}</span>
              <button type="button" class="ghost pl-rm" data-prm="${i}" aria-label="Remove ${esc(p.product)}">×</button></li>`).join("")}
          </ul>` : ""}
        </div>` : ""}`;
    body.querySelectorAll("input[name=water]").forEach((r) => r.onchange = () => { draft.conditions.water_access = r.value; });
    body.querySelector("#puse").onclick = (e) => {
      const b = e.target.closest(".chip"); if (!b) return;
      draft.conditions.pesticide_use = draft.conditions.pesticide_use === b.dataset.v ? null : b.dataset.v;
      if (draft.conditions.pesticide_use !== "some") draft.pesticides = [];
      paint();
    };
    body.querySelectorAll("[data-prm]").forEach((b) => b.onclick = () => {
      draft.pesticides.splice(Number(b.dataset.prm), 1); paint();
    });
    const add = () => {
      const product = body.querySelector("#pp").value.trim();
      if (!product) { body.querySelector("#pp").focus(); return; }
      const amount = parseFloat(body.querySelector("#pa").value);
      draft.pesticides.push({ product, amount: Number.isFinite(amount) ? amount : null,
        unit: Number.isFinite(amount) ? body.querySelector("#pu").value : null, per: body.querySelector("#pper").value,
        crop: body.querySelector("#pc")?.value || null });
      paint();
    };
    body.querySelector("#padd")?.addEventListener("click", add);
    body.querySelector("#pp")?.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); add(); } });
  };
  paint();
  return () => draft.conditions.water_access ? null : "Choose how you water your farm, or press Skip.";
}

// Step 4 — main concern
function stepConcern(body) {
  radioStep(body, CONCERNS, draft.main_concern, (v) => { draft.main_concern = v; },
    "We'll put related alerts first on your dashboard.");
  return () => draft.main_concern ? null : "Choose an option, or press Skip.";
}

function pestSummary(f) {
  const use = (f.conditions || {}).pesticide_use;
  if (use === "none") return "None";
  if (use === "unsure") return "Not sure";
  return (f.pesticides || []).map((p) => p.product + (p.amount != null ? ` (${p.amount} ${p.unit || ""} ${p.per || ""})`.replace(/\s+\)/, ")") : "")).join(", ");
}

// Step 5 — review
function stepReview(body) {
  const items = (t) => draft.production_items.filter((p) => (t === "livestock") === (p.type === "livestock"))
    .map((p) => p.name + (p.area_or_count ? ` (${p.area_or_count})` : "") + (p.planting_date ? ` (planted ${fmtDay(p.planting_date)})` : "")).join(", ");
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
      ${row("Pesticides", pestSummary(draft), 3)}
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

// The page is drawn as one carrot: feathery leaves in front of a hedgerow and vegetable rows above ground
// (weather), then a long watercolour-style root with gentle bends runs down through the below-ground
// sections and fades into a fine tip. All inline SVG, no images.

// Feathery carrot tops: thin stems fanning out, each with small lobed leaflets.
function frondsSVG() {
  const stems = [[-46, 104, "a"], [-32, 126, "b"], [-16, 142, "a"], [-4, 152, "b"], [9, 146, "a"],
                 [22, 134, "b"], [36, 118, "a"], [50, 98, "b"]];
  let out = "";
  for (const [lean, h, tone] of stems) {
    const x2 = 60 + lean, y2 = 160 - h, cx = 60 + lean * 0.2, cy = 160 - h * 0.6;
    const at = (t) => [(1 - t) ** 2 * 60 + 2 * (1 - t) * t * cx + t * t * x2, (1 - t) ** 2 * 160 + 2 * (1 - t) * t * cy + t * t * y2];
    out += `<path d="M60 160 Q${cx} ${cy} ${x2} ${y2}" stroke="var(--stem-${tone})" stroke-width="1.8" fill="none" stroke-linecap="round"/>`;
    // pinnate leaflets: small lobed sprigs along the upper part of each stem
    for (let i = 0; i < 7; i++) {
      const t = 0.38 + i * 0.09, [x, y] = at(t), side = i % 2 ? 1 : -1, size = 8.5 - i * 0.7;
      const ang = lean * 0.6 + side * 55;
      out += `<g transform="translate(${x.toFixed(1)} ${y.toFixed(1)}) rotate(${ang.toFixed(0)})" fill="var(--leaf-${i % 3 ? tone : "a"})">
        <path d="M0 0 L${size * 1.6} 0" stroke="var(--stem-${tone})" stroke-width=".8"/>
        <ellipse cx="${size * 0.7}" cy="${-size * 0.28}" rx="${size * 0.42}" ry="${size * 0.24}" transform="rotate(-25 ${size * 0.7} ${-size * 0.28})"/>
        <ellipse cx="${size * 0.7}" cy="${size * 0.28}" rx="${size * 0.42}" ry="${size * 0.24}" transform="rotate(25 ${size * 0.7} ${size * 0.28})"/>
        <ellipse cx="${size * 1.35}" cy="${-size * 0.18}" rx="${size * 0.36}" ry="${size * 0.2}" transform="rotate(-20 ${size * 1.35} ${-size * 0.18})"/>
        <ellipse cx="${size * 1.35}" cy="${size * 0.18}" rx="${size * 0.36}" ry="${size * 0.2}" transform="rotate(20 ${size * 1.35} ${size * 0.18})"/>
        <ellipse cx="${size * 1.85}" cy="0" rx="${size * 0.38}" ry="${size * 0.22}"/></g>`;
    }
    out += `<g transform="translate(${x2} ${y2}) rotate(${lean * 0.8 - 90})" fill="var(--leaf-${tone})">
      <ellipse cx="4" cy="-2.5" rx="4" ry="2.2" transform="rotate(-25 4 -2.5)"/><ellipse cx="4" cy="2.5" rx="4" ry="2.2" transform="rotate(25 4 2.5)"/>
      <ellipse cx="8" cy="0" rx="4" ry="2.3"/></g>`;
  }
  return `<svg class="fronds" viewBox="0 0 120 160" aria-hidden="true" focusable="false"><g opacity=".93">${out}</g></svg>`;
}

// Hedgerow along the back, rows of vegetables in front. Kept quiet and low.
function sceneSVG() {
  let hedge = "M0 70";
  for (let x = 0; x <= 1200; x += 40) hedge += ` Q${x + 20} ${48 + ((x * 7) % 17)} ${x + 40} ${62 + ((x * 3) % 11)}`;
  hedge += " L1200 92 L0 92 Z";
  let hedge2 = "M0 78";
  for (let x = 0; x <= 1200; x += 28) hedge2 += ` Q${x + 14} ${62 + ((x * 5) % 13)} ${x + 28} ${72 + ((x * 11) % 9)}`;
  hedge2 += " L1200 92 L0 92 Z";
  let berries = "";
  for (let x = 37; x < 1200; x += 83) berries += `<circle cx="${x}" cy="${66 + (x % 9)}" r="1.8"/><circle cx="${x + 4}" cy="${68 + (x % 7)}" r="1.5"/>`;
  let rows = "";
  [[100, 9, 1], [110, 12, 1.25], [121, 15, 1.5]].forEach(([y, gap, sc], r) => {
    rows += `<path d="M0 ${y + 3} H1200" stroke="var(--furrow)" stroke-width="${1.2 * sc}" opacity=".55"/>`;
    for (let x = (r * 5) % gap; x < 1200; x += gap * 2.2) {
      rows += `<g transform="translate(${x.toFixed(1)} ${y}) scale(${sc})"><ellipse cx="-2.2" cy="0" rx="2.6" ry="1.4" transform="rotate(-30)"/>
        <ellipse cx="2.2" cy="0" rx="2.6" ry="1.4" transform="rotate(30)"/><ellipse cx="0" cy="-1.6" rx="1.4" ry="2.4"/></g>`;
    }
  });
  return `<svg class="scene" viewBox="0 0 1200 128" preserveAspectRatio="xMidYMax slice" aria-hidden="true" focusable="false">
    <rect x="0" y="86" width="1200" height="42" fill="var(--field)"/>
    <path d="${hedge}" fill="var(--hedge-2)"/><path d="${hedge2}" fill="var(--hedge-1)"/>
    <g fill="var(--berry)" opacity=".75">${berries}</g>
    <g fill="var(--rowleaf)">${rows}</g></svg>`;
}

// The root: drawn in a 0..80 x 0..1000 box and stretched to the height of the section.
function rootSVG() {
  const N = 120, left = [], right = [];
  const centre = (t) => 40 + Math.sin(t * Math.PI * 2.4 + 0.5) * (3 + 12 * t) + Math.sin(t * 9) * 1.4;
  const half = (t) => {
    const shoulder = Math.min(1, Math.sqrt(t / 0.0025));           // short rounded top (stretched later)
    return Math.max(0.5, 22 * shoulder * Math.pow(1 - t, 0.8));
  };
  for (let i = 0; i <= N; i++) {
    const t = i === 1 ? 0.0006 : i === 2 ? 0.0015 : i / N, y = t * 1000, c = centre(t), w = half(t);
    left.push(`${(c - w).toFixed(2)} ${y.toFixed(1)}`);
    right.push(`${(c + w * 0.94).toFixed(2)} ${y.toFixed(1)}`);
  }
  const body = `M${left[0]} L${left.slice(1).join(" L")} L${right.reverse().join(" L")} Z`;
  // ridges: short curved strokes across the body, irregularly spaced
  let ridges = "";
  for (let y = 18; y < 920; y += 16 + ((y * 13) % 19)) {
    const t = y / 1000, c = centre(t), w = half(t);
    // short slanted notches, alternating sides, like the growth rings on a real root
    const leftSide = Math.round(y / 7) % 2 === 0;
    const from = leftSide ? c - w * 0.92 : c + w * 0.05, to = leftSide ? c - w * 0.25 : c + w * 0.85;
    ridges += `<path d="M${from.toFixed(1)} ${y} Q${((from + to) / 2).toFixed(1)} ${y - 1.5} ${to.toFixed(1)} ${y + 2.5}"/>`;
  }
  // fine root hairs from the edges
  let hairs = "";
  for (let y = 120; y < 960; y += 70 + ((y * 11) % 50)) {
    const t = y / 1000, c = centre(t), w = half(t), side = (y / 10) % 2 > 1 ? 1 : -1;
    const x0 = c + side * w, len = 10 + ((y * 5) % 9);
    hairs += `<path d="M${x0.toFixed(1)} ${y} q${side * len * 0.6} ${len * 0.5} ${side * len} ${len * 1.6}"/>`;
  }
  // highlight down the lit side
  let hl = "";
  for (let i = 1; i <= 60; i++) {
    const t = i / 80, c = centre(t), w = half(t);
    hl += `${i === 1 ? "M" : " L"}${(c - w * 0.42).toFixed(2)} ${(t * 1000).toFixed(1)}`;
  }
  return `<svg class="root" viewBox="0 0 80 1000" preserveAspectRatio="none" aria-hidden="true" focusable="false">
    <defs>
      <linearGradient id="rootfill" x1="0" x2="1" y1="0" y2="0">
        <stop offset="0" stop-color="var(--carrot-3)"/><stop offset=".3" stop-color="var(--carrot-1)"/>
        <stop offset=".5" stop-color="var(--carrot-hi)"/><stop offset=".78" stop-color="var(--carrot-2)"/>
        <stop offset="1" stop-color="var(--carrot-3)"/></linearGradient>
      <linearGradient id="rootfade" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0" stop-color="#fff" stop-opacity="1"/><stop offset=".86" stop-color="#fff" stop-opacity="1"/>
        <stop offset="1" stop-color="#fff" stop-opacity=".35"/></linearGradient>
      <mask id="rootmask"><rect width="80" height="1000" fill="url(#rootfade)"/></mask>
    </defs>
    <g mask="url(#rootmask)">
      <path d="${body}" fill="url(#rootfill)"/>
      <path d="${hl}" fill="none" stroke="var(--carrot-hi)" stroke-width="2.4" opacity=".55" vector-effect="non-scaling-stroke"/>
      <g fill="none" stroke="var(--carrot-line)" stroke-width="1" stroke-linecap="round" opacity=".38" vector-effect="non-scaling-stroke">${ridges}</g>
      <g fill="none" stroke="var(--hair)" stroke-width=".9" stroke-linecap="round" opacity=".7" vector-effect="non-scaling-stroke">${hairs}</g>
    </g></svg>`;
}

function plant(above, belowSections) {
  return `
    <div class="plant">
      <div class="above">${sceneSVG()}<div class="above-content">${above}</div></div>
      <div class="soil-line" aria-hidden="true">${frondsSVG()}</div>
      <div class="below">
        ${rootSVG()}
        ${belowSections.filter(Boolean).map((sec) => `<section class="rootsec">${sec}</section>`).join("")}
      </div>
    </div>`;
}

function weatherBlock(w) {
  if (w.status === "unavailable") {
    return `<div class="notice err"><b>Weather data unavailable.</b> ${esc(w.error || "")}
      Risk assessments and crop advice can't be generated without a forecast. Try refreshing later.</div>`;
  }
  const s = w.summary, c = s.current;
  const est = (k) => s.estimated.includes(k);
  return `
    ${w.status === "stale" ? `<div class="notice warn"><b>Weather data may be out of date</b> (last updated ${fmtTime(w.fetched_at)}).
      ${esc(w.error || "")} Alerts below are based on this older forecast.</div>` : ""}
    <div class="card">
      <div class="spread"><h2 style="margin:0">Weather now</h2><span class="muted small">${esc(c.condition)}</span></div>
      <div class="wx-now"><span class="temp">${Math.round(c.temperature)}°C</span>
        <span class="muted">Humidity ${Math.round(c.humidity)}% · Wind ${Math.round(c.wind_speed)} km/h · Rain ${c.precipitation ?? 0} mm</span></div>
      <div class="days" style="margin-top:12px">${s.days.map((d) => `
        <div class="day"><b>${fmtDay(d.date).split(",")[0]}</b>${Math.round(d.t_max)}° / ${Math.round(d.t_min)}°
          <div class="muted">💧 ${(d.rain_mm ?? 0).toFixed(1)} mm${d.rain_prob != null ? ` · ${d.rain_prob}%` : ""}</div>
          ${d.sun_h != null ? `<div class="muted">☀️ ${d.sun_h} h</div>` : ""}</div>`).join("")}</div>
      <p class="muted small" style="margin:8px 0 0">Forecast: ${esc(s.provider)}${est("sunshine_duration") ? " (sunshine estimated from cloud cover)" : ""} · updated ${ago(w.fetched_at)}</p>
    </div>
    ${sunRainBlock(w)}`;
}

function sunRainBlock(w) {
  const s = w.summary, m = w.measured_rain;
  const next7rain = s.days.reduce((t, d) => t + (d.rain_mm || 0), 0);
  const nextSun = s.days.filter((d) => d.sun_h != null);
  const sunEst = s.estimated.includes("sunshine_duration");
  const rainPast = m ? `<b>${m.mm} mm</b> <span class="muted small">measured at ${esc(m.station)}, ${m.distance_km} km away</span>`
    : s.past_rain_mm != null ? `<b>${s.past_rain_mm} mm</b> <span class="muted small">weather model for your postcode</span>`
    : `<span class="muted">Not available here</span>`;
  const sunPast = s.past_sun_h != null ? `<b>${s.past_sun_h} h</b> <span class="muted small">(${(s.past_sun_h / 7).toFixed(1)} h a day)</span>`
    : `<span class="muted">Not available from the current source</span>`;
  return `
    <div class="card sunrain">
      <h2 style="margin-top:0">Sun and rain</h2>
      <div class="sr-grid">
        <div><span class="sr-k">💧 Rain, last 7 days</span>${rainPast}</div>
        <div><span class="sr-k">💧 Rain, next 7 days</span><b>${next7rain.toFixed(1)} mm</b> <span class="muted small">forecast</span></div>
        <div><span class="sr-k">☀️ Sunshine, last 7 days</span>${sunPast}</div>
        <div><span class="sr-k">☀️ Sunshine, next 7 days</span>${nextSun.length ? `<b>${(nextSun.reduce((t, d) => t + d.sun_h, 0) / nextSun.length).toFixed(1)} h a day</b>
          <span class="muted small">${sunEst ? "estimated" : "forecast"}</span>` : `<span class="muted">—</span>`}</div>
      </div>
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

function cropWidget(c) {
  const water = c.water_status === "water" ? `💧 Add ${c.add_l_per_m2} L per m² this week`
    : c.water_status === "wait" ? "💧 Hold off: rain is due" : c.water_status === "ok" ? "💧 No watering needed"
    : c.water_status === "no_past_rain" ? `💧 Plan ~${c.add_l_per_m2} L per m²` : "💧 Water: no data";
  return `
    <a class="crop-widget" href="#/crop/${c.id}">
      <span class="cw-emoji" aria-hidden="true">${c.emoji}</span>
      <span class="cw-name">${esc(c.name)}</span>
      <span class="cw-stage">${c.needs_planting_date ? "Add planting date" : esc(c.stage)}</span>
      <span class="cw-water">${water}</span>
      ${c.alerts ? `<span class="cw-alert">⚠️ ${c.alerts} weather alert${c.alerts > 1 ? "s" : ""}</span>` : ""}
      ${c.in_guide ? "" : `<span class="cw-note">General advice (not in guide)</span>`}
    </a>`;
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
  const ok = d.weather.status !== "unavailable";
  const above = `
    <div class="spread">
      <div><h1 style="margin-bottom:2px">${esc(f.name || "My farm")}</h1>
        <p class="muted small">📍 ${esc(f.location_label)} · ${f.production_types.map((t) => label(PRODUCTION, t)).join(", ") || "No production types yet"}</p></div>
      <button class="secondary" id="refresh">Refresh</button>
    </div>
    <p class="muted small">Risks checked ${d.assessed_at ? fmtTime(d.assessed_at) : "—"} · rules ${esc(d.model_version)}</p>
    ${weatherBlock(d.weather)}
    ${ok ? `<h2>Weather ahead</h2>${elevated.length ? elevated.map(riskCard).join("")
      : `<div class="notice info">✅ No storms, frost, heat, flooding or drought risk in the next 7 days.</div>`}` : ""}`;
  const below = [
    d.crops.length ? `<h2>Your crops</h2><div class="crop-grid">${d.crops.map(cropWidget).join("")}</div>`
      : `<h2>Your crops</h2><div class="card"><p>Add your crops to get a page for each one with tailored watering, sunlight and pest advice.</p>
         <a class="btn secondary" href="#/setup/2">Add crops</a></div>`,
    ok && actions.length ? `<h2>Top actions</h2><div class="card"><ul class="actions-list">${actions.map((r) => `
      <li><span class="urg ${r.urgency}">${URGENCY[r.urgency]}</span> · <span class="muted small">${esc(r.hazard)}</span><br>
      <a href="#/risk/${r.aid}" style="color:inherit;text-decoration:none">${esc(r.action)}</a></li>`).join("")}</ul></div>` : "",
    ok && low.length ? `<h2>Checked: no elevated risk</h2><div class="card"><ul class="actions-list">${low.map((a) => `
      <li class="spread"><span>${esc(a.title)} <span class="muted small">· ${esc(a.evidence[0])}</span></span>
      <a href="#/risk/${a.id}" class="small">Details</a></li>`).join("")}</ul></div>` : "",
    d.hints.length ? `<h2>Improve your advice <span class="small">(optional)</span></h2>
      <div class="card"><ul class="plain">${d.hints.map((h) => `<li>${esc(h)}</li>`).join("")}</ul>
      <a href="#/profile">Update farm profile</a></div>` : "",
    `<p class="small soil-note">These are weather-based warnings and general guidance, not confirmation of damage or disease.
      Thresholds and crop values are pending agronomist review. Always follow local expert, regulatory and veterinary advice.</p>`,
  ];
  render(plant(above, below));
  document.getElementById("refresh").onclick = async (e) => {
    e.target.disabled = true; e.target.textContent = "Refreshing…";
    try { await dashboard(null, true); } catch (err) { showError(err); }
  };
}

// ------------------------------------------------------------------ crop page visuals
const GLASS_FULL_L = 25;   // a full glass = 25 L per m² (a very dry week)

function waterHeadline(w) {
  if (!w || w.status === "unavailable") return "Not enough weather data to work out watering.";
  if (w.status === "ok") return "No watering needed this week";
  if (w.status === "wait") return "Hold off: rain is on the way";
  const cans = w.add_l_per_m2 / 10;
  return `Add ${w.add_l_per_m2} L of water per m² this week
    <span class="sub">≈ ${cans < 1 ? "under one" : cans.toFixed(cans < 3 ? 1 : 0)} 10-litre watering can${cans >= 1.05 ? "s" : ""} for every square metre${w.waterings > 1 ? `, in ${w.waterings} waterings` : ""}</span>`;
}

function glassSVG(w) {
  const litres = w && (w.status === "water" || w.status === "no_past_rain") ? w.add_l_per_m2 : 0;
  const f = Math.max(0, Math.min(1, litres / GLASS_FULL_L));
  const top = 18, bottom = 150, h = (bottom - top) * f, y = bottom - h;
  const label = w && w.status === "wait" ? "rain due" : `${litres} L/m²`;
  return `<figure class="glass" role="img" aria-label="Water glass ${Math.round(f * 100)}% full: ${esc(label)}">
    <svg viewBox="0 0 120 170">
      <defs><clipPath id="glassin"><path d="M20 16 L100 16 L92 150 Q91 156 85 156 L35 156 Q29 156 28 150 Z"/></clipPath>
        <linearGradient id="waterfill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="var(--water-1)"/><stop offset="1" stop-color="var(--water-2)"/></linearGradient></defs>
      <g clip-path="url(#glassin)">
        <rect x="0" y="0" width="120" height="170" fill="var(--glass-bg)"/>
        ${f > 0 ? `<path class="wave" d="M0 ${y.toFixed(1)} Q15 ${(y - 4).toFixed(1)} 30 ${y.toFixed(1)} T60 ${y.toFixed(1)} T90 ${y.toFixed(1)} T120 ${y.toFixed(1)} V170 H0 Z" fill="url(#waterfill)"/>` : ""}
      </g>
      ${[0.25, 0.5, 0.75].map((m) => `<line x1="88" x2="96" y1="${(bottom - (bottom - top) * m).toFixed(1)}" y2="${(bottom - (bottom - top) * m).toFixed(1)}" stroke="var(--glass-edge)" stroke-width="1"/>`).join("")}
      <path d="M18 12 L102 12 L93 151 Q92 160 85 160 L35 160 Q28 160 27 151 Z" fill="none" stroke="var(--glass-edge)" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M30 24 L36 140" stroke="#fff" stroke-width="3" opacity=".45" stroke-linecap="round"/>
    </svg>
    <figcaption>${esc(label)}</figcaption></figure>`;
}

function meter(value, lo, hi, min, max, unitLabel) {
  const pct = (v) => Math.max(0, Math.min(100, ((v - min) / (max - min)) * 100));
  return `<div class="meter"><div class="meter-track">
      <span class="meter-band" style="left:${pct(lo)}%;width:${pct(hi) - pct(lo)}%"></span>
      ${Array.isArray(value) ? `<span class="meter-span" style="left:${pct(value[0])}%;width:${Math.max(1.5, pct(value[1]) - pct(value[0]))}%"></span>`
        : `<span class="meter-dot" style="left:${pct(value)}%"></span>`}
    </div><div class="meter-scale"><span>${min}${unitLabel}</span><span>${max}${unitLabel}</span></div></div>`;
}

function sunMeter(sun, g) {
  if (!sun || sun.status === "unavailable") return `<p>☀️ Sunshine data isn't available here.</p>`;
  const v = sun.past_avg_h ?? sun.next_avg_h;
  return `<div class="gauge"><p class="headline">☀️ ${v.toFixed(1)} h of sun a day <span class="pill ${sun.status === "ok" ? "good" : "warn"}">${sun.status === "ok" ? "Enough" : "A bit low"}</span></p>
    ${meter(v, g.sun_hours * 0.75, 14, 0, 14, " h")}
    <p class="small muted">Green = enough for ${esc(g.name.toLowerCase())} (needs ~${g.sun_hours} h)${sun.estimated ? " · estimated from cloud cover" : ""}</p>
    <details><summary>What this means</summary><p class="small">${esc(sun.summary)}</p></details></div>`;
}

function tempMeter(t, g) {
  if (!t || t.status === "unavailable") return "";
  const [lo, hi] = t.forecast;
  return `<div class="gauge"><p class="headline">🌡️ ${Math.round(lo)}–${Math.round(hi)} °C this week <span class="pill ${t.status === "ok" ? "good" : "warn"}">${t.status === "ok" ? "Just right" : "Outside ideal"}</span></p>
    ${meter([lo, hi], g.temp_c.min, g.temp_c.max, -5, 35, "°")}
    <p class="small muted">Green = ideal ${g.temp_c.min}–${g.temp_c.max} °C · orange bar = this week's forecast</p>
    <details><summary>What this means</summary><p class="small">${esc(t.summary)}</p></details></div>`;
}

// Gentler alternatives for common product types (general guidance only).
const GENTLER = [
  [/glyphosate|herbicide|weedkiller/i, "Mulch, hoe on dry days, and use cover crops to keep weeds down without herbicide."],
  [/ferric/i, "Already one of the lower-impact slug controls. Nematodes and beer traps can cut how much you need."],
  [/metaldehyde|slug/i, "Nematodes (Phasmarhabditis) or ferric phosphate pellets, plus beer traps and evening hand-picking."],
  [/pyrethr|insecticide|cypermethrin|lambda/i, "Insect mesh or fleece, encourage ladybirds and hoverflies, or fatty-acid / plant-oil sprays."],
  [/fungicide|copper|sulphur|sulfur/i, "Resistant varieties, wider spacing for airflow, watering at the base, and removing infected leaves."],
];

function pesticideSection(d, item) {
  const use = d.pesticide_use, list = d.pesticides || [];
  if (use === "none") return `<h2>Your pesticides</h2><div class="card"><p>🌿 You told us you don't use pesticides. The bio-friendly options below fit that approach.</p></div>`;
  if (!list.length) return `<h2>Your pesticides</h2><div class="card"><p class="muted">No pesticides recorded for ${esc(item.name.toLowerCase())}.</p>
    <a href="#/setup/3">Add what you use</a></div>`;
  return `<h2>Your pesticides</h2><div class="card"><ul class="pest-list">${list.map((p) => {
      const alt = GENTLER.find(([re]) => re.test(p.product));
      return `<li><span><b>${esc(p.product)}</b>${p.amount != null ? ` · ${p.amount} ${esc(p.unit || "")} ${esc(p.per || "")}` : ""}
        ${p.crop ? "" : `<span class="muted small"> · all crops</span>`}
        ${alt ? `<br><span class="small">🌿 Gentler option: ${esc(alt[1])}</span>` : ""}</span></li>`;
    }).join("")}</ul>
    <p class="small muted" style="margin:8px 0 0">Always stay within the label's maximum dose and number of applications.
      Check approval on the <a href="https://secure.pesticides.gov.uk/pestreg/" target="_blank" rel="noopener">HSE register</a>.
      <a href="#/setup/3">Edit</a></p></div>`;
}

// ------------------------------------------------------------------ crop landing page
async function cropPage(itemId) {
  setTabs("dashboard");
  if (!(await requireAccount())) return;
  const farm = await currentFarm();
  if (!farm) { location.hash = "#/"; return; }
  render(`<div class="spinner">Loading crop advice…</div>`);
  const d = await api(`/api/farms/${farm.id}/crops/${itemId}`);
  const a = d.advice, g = a.guide, st = a.stage, item = a.item;
  const ok = d.weather.status !== "unavailable";
  const today = new Date().toISOString().slice(0, 10);
  const w = a.water || {};
  const above = `
    <p><a href="#/dashboard">← Dashboard</a></p>
    <div class="crop-hero">
      <span class="crop-emoji" aria-hidden="true">${g.emoji}</span>
      <div><h1 style="margin:0">${esc(item.name)}</h1>
        <p class="muted small" style="margin:0">${a.in_guide ? `Matched to our guide: ${esc(g.name)}` : "Not in our crop guide yet: general vegetable values used"}
          · 📍 ${esc(d.farm.location_label)}</p></div>
    </div>
    <div class="card">
      <div class="spread"><h2 style="margin:0">Growth stage</h2><span class="badge lvl-low">${esc(st.label)}</span></div>
      ${st.perennial ? `<p class="muted small" style="margin-top:8px">Perennial crop: stage follows the season.</p>` : ""}
      ${st.days != null && !st.perennial ? `<p style="margin:8px 0 4px">${st.future ? "Planned" : `${st.days} days since planting`}
        ${st.progress != null ? ` · ${Math.round(st.progress * 100)}% through a typical season` : ""}</p>
        <div class="bar" aria-hidden="true"><span style="width:${Math.round((st.progress || 0) * 100)}%"></span></div>` : ""}
      ${st.harvest ? `<p style="margin:8px 0 0">🧺 Expected harvest: <b>${fmtDay(st.harvest.from)} – ${fmtDay(st.harvest.to)}</b></p>` : ""}
      <form class="row" id="pdform" style="margin-top:12px">
        <label for="pdate" style="margin:0">When did you plant this crop?</label>
        <input type="date" id="pdate" max="${today}" value="${esc(item.planting_date || "")}" style="width:auto">
        <button type="submit" class="secondary">Save</button>
      </form>
      ${st.needs_planting_date ? `<p class="small muted" style="margin:6px 0 0">Add the planting date to get stage-specific watering.</p>` : ""}
    </div>
    ${ok ? sunRainBlock(d.weather) : weatherBlock(d.weather)}
    ${ok ? `<h2>Weather ahead for your ${esc(item.name.toLowerCase())}</h2>
      ${a.weather_ahead.length ? a.weather_ahead.map((x) => `
        <article class="card risk ${x.level}">
          <div class="spread"><h3>${esc(x.title)}</h3>${levelBadge(x.level)}</div>
          <p class="muted small">${fmtDay(x.window[0])} – ${fmtDay(x.window[1])}</p>
          <p>${esc(x.evidence)}</p>
          ${x.crop_tip ? `<p><b>For ${esc(item.name.toLowerCase())}:</b> ${esc(x.crop_tip)}</p>` : ""}
          ${x.actions.length ? `<ul class="plain">${x.actions.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
          ${x.assessment_id ? `<a href="#/risk/${x.assessment_id}" class="small">Full alert →</a>` : ""}
        </article>`).join("") : `<div class="notice info">✅ No storms, frost, heat, flooding or drought risk in the next 7 days.</div>`}` : ""}`;
  const below = [
    ok ? `<h2>Water</h2>
      <div class="card water-card">
        ${glassSVG(w)}
        <div class="water-text">
          <p class="headline">${waterHeadline(w)}</p>
          <p>${esc(w.summary || "")}</p>
          ${w.crop_use_mm != null ? `<details><summary>How we worked this out</summary><ul class="plain small muted">
            <li>Your ${esc(item.name.toLowerCase())} used ≈${w.crop_use_mm} mm of water in the last 7 days
              (reference evaporation × crop factor ${w.kc}${w.estimated ? ", estimated" : ""}).</li>
            <li>Rain: ${w.rain_mm != null ? `${w.rain_mm} mm, ${esc(w.rain_source)}` : "not available"}.</li>
            <li>Forecast rain: ${w.forecast_rain_3d_mm} mm in the next 3 days, ${w.forecast_rain_7d_mm} mm in 7 days.</li>
            <li>1 mm of water = 1 litre per square metre. A full glass here means 25 L/m², a very dry week.</li>
            <li>Check the soil at finger depth before watering.</li></ul></details>` : ""}
        </div>
      </div>` : "",
    ok ? `<h2>Sunlight and temperature</h2>
      <div class="card">
        ${sunMeter(a.sun, g)}
        ${tempMeter(a.temperature, g)}
      </div>` : "",
    `<h2>Growing guide</h2>
      <div class="card">
        <div class="facts">
          <div><span>☀️</span><b>~${g.sun_hours} h</b><small>sun a day</small></div>
          <div><span>🌡️</span><b>${g.temp_c.min}–${g.temp_c.max} °C</b><small>ideal range</small></div>
          <div><span>🧪</span><b>pH ${esc(g.ph)}</b><small>soil</small></div>
          ${g.harvest_days ? `<div><span>🧺</span><b>${g.harvest_days[0]}–${g.harvest_days[1]} days</b><small>to harvest</small></div>` : ""}
          <div><span>💧</span><b>${g.kc.ini} → ${g.kc.mid} → ${g.kc.end}</b><small>water factor (FAO-56)</small></div>
        </div>
        <p style="margin:12px 0 0">${esc(g.notes)}</p>
      </div>`,
    pesticideSection(d, item),
    `<h2>Pests and bio-friendly protection</h2>
      <div class="card pests">${g.pests.map((p) => `
        <details><summary><b>${esc(p.name)}</b><span class="muted small">${esc(p.signs)}</span></summary>
          <p class="try-first">✅ <b>Try first:</b> ${esc(p.controls[0])}</p>
          ${p.controls.length > 1 ? `<ul class="plain">${p.controls.slice(1).map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}
        </details>`).join("")}
        <p class="small muted" style="margin:10px 0 0">Tap a pest to see what to do.</p></div>`,
    `<h2>For a better yield</h2>
      <div class="card"><ul class="yield-list">${g.feeds.map((x) => `<li><b>${esc(x.name)}</b><span>${esc(x.use)}</span></li>`).join("")}</ul>
      <p class="small muted" style="margin:8px 0 0">⚠️ ${esc(d.caveat)}</p></div>`,
    `<h2>Sources</h2>
      <div class="card"><details><summary>Where this advice comes from (${g.sources.length})</summary>
        <ul class="plain small">${g.sources.map((x) => `<li>${x.url
          ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a>` : esc(x.title)}</li>`).join("")}</ul></details>
      <p class="small muted" style="margin:8px 0 0">Crop values compiled from published guidance; pending agronomist review.</p></div>`,
  ];
  render(plant(above, below));
  document.getElementById("pdform").onsubmit = async (e) => {
    e.preventDefault();
    const v = document.getElementById("pdate").value;
    await api(`/api/farms/${farm.id}/items/${item.id}`, { method: "PUT", body: { planting_date: v || null } });
    cropPage(itemId);
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
        <dt>Pesticides</dt><dd>${esc(pestSummary(draft) || "Not provided")}</dd>
      </dl>
      <div class="row" style="margin-top:12px">
        <a class="btn secondary" href="#/setup/1">Edit location &amp; size</a>
        <a class="btn secondary" href="#/setup/2">Edit crops &amp; livestock</a>
        <a class="btn secondary" href="#/setup/3">Edit pesticides</a>
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
