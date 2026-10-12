"""Versioned, transparent rule-based risk engine (PRD section 6).

Pure functions: farm profile + weather payload in, assessments out. No DB or HTTP here,
so rules can be unit-tested and updated independently of the UI.

IMPORTANT: thresholds below are illustrative pilot placeholders and must be reviewed
by an agronomist for the chosen pilot region before real-world use.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone

MODEL_VERSION = "rules-2026.10-v1"

THRESHOLDS = {
    "rain_3day_high_mm": 50, "rain_3day_medium_mm": 25,
    "rain_1day_high_mm": 30, "rain_1day_medium_mm": 15,
    "deficit_high_mm": 35, "deficit_medium_mm": 20,   # ET0 minus rainfall over 14 days
    "crop_heat_high_c": 35, "crop_heat_medium_c": 30,
    "thi_high": 79, "thi_medium": 72,                  # livestock temperature-humidity index
    "frost_high_c": -2, "frost_medium_c": 0, "frost_low_c": 2,
}

LEVELS = ["low", "medium", "high"]
LEVEL_LIKELIHOOD = {"low": 1, "medium": 2, "high": 3}
PLANT_TYPES = {"vegetables", "fruit", "field_crops", "herbs", "flowers"}
FORAGE_TYPES = {"grass_pasture", "hay_forage"}
BLIGHT_CROPS = {"potato", "potatoes", "tomato", "tomatoes"}
# Hazards each main concern cares about most (used only for ordering ties).
CONCERN_HAZARDS = {
    "weather": {"heavy_rain", "frost", "crop_heat", "livestock_heat", "drought"},
    "pests_diseases": {"late_blight"},
    "soil_water": {"heavy_rain", "drought"},
    "livestock_health": {"livestock_heat"},
    "yield_costs": {"drought", "frost", "crop_heat"},
}


@dataclass
class Rec:
    action: str
    rationale: str
    urgency: str  # now | soon | monitor | info
    applicability: str = ""
    caveat: str = ""


@dataclass
class Assessment:
    hazard: str
    title: str
    level: str
    applies_to: str
    window_start: str
    window_end: str
    evidence: list[str]
    caveats: list[str]
    missing_inputs: list[dict] = field(default_factory=list)
    recommendations: list[Rec] = field(default_factory=list)
    impact: int = 2  # 1..3, used for priority score
    priority_score: int = 0
    valid_until: str = ""

    def to_dict(self):
        d = asdict(self)
        return d


def bump(level: str, by: int) -> str:
    return LEVELS[max(0, min(len(LEVELS) - 1, LEVELS.index(level) + by))]


def _series(data, block, key):
    return (data.get(block) or {}).get(key) or []


def _future_daily(data, today: str):
    d = data.get("daily") or {}
    idx = [i for i, t in enumerate(d.get("time", [])) if t >= today]
    past = [i for i, t in enumerate(d.get("time", [])) if t < today]
    return d, idx, past


def _num(v):
    return 0.0 if v is None else float(v)


def thi(temp_c: float, rh: float) -> float:
    """Temperature-humidity index (NRC 1971 formulation, common in livestock heat-stress work)."""
    return 0.8 * temp_c + (rh / 100.0) * (temp_c - 14.4) + 46.4


# --------------------------------------------------------------------------- rules

def rule_heavy_rain(farm, cond, data, today):
    d, idx, _ = _future_daily(data, today)
    if len(idx) < 3:
        return None
    nxt = idx[:3]
    rain = [_num(d["precipitation_sum"][i]) for i in nxt]
    total, peak = sum(rain), max(rain)
    t = THRESHOLDS
    if total >= t["rain_3day_high_mm"] or peak >= t["rain_1day_high_mm"]:
        level = "high"
    elif total >= t["rain_3day_medium_mm"] or peak >= t["rain_1day_medium_mm"]:
        level = "medium"
    else:
        level = "low"
    evidence = [f"Forecast rainfall next 72 h: {total:.1f} mm (wettest day {peak:.1f} mm).",
                f"Rule: medium ≥ {t['rain_3day_medium_mm']} mm/3 days or ≥ {t['rain_1day_medium_mm']} mm/day; "
                f"high ≥ {t['rain_3day_high_mm']} mm/3 days or ≥ {t['rain_1day_high_mm']} mm/day."]
    missing = []
    drainage = (cond or {}).get("drainage")
    history = (cond or {}).get("waterlogging_history")
    if level != "low" and (drainage == "poor" or history == "yes"):
        level = bump(level, 1)
        evidence.append("Level raised: you reported poor drainage or a history of waterlogging.")
    if not drainage:
        missing.append({"key": "drainage", "question": "How well does your land drain after heavy rain?",
                        "options": ["good", "moderate", "poor", "unknown"]})
    if not history:
        missing.append({"key": "waterlogging_history", "question": "Has this land been waterlogged before?",
                        "options": ["yes", "no", "unknown"]})
    recs = []
    if level == "high":
        recs = [Rec("Check and clear drains, ditches and culverts before the rain arrives.",
                    "Heavy rainfall is forecast; blocked drainage increases waterlogging risk.", "now"),
                Rec("Delay heavy field operations (spraying, harvesting, tillage) until soils drain.",
                    "Working wet soil causes compaction and rutting.", "soon"),
                Rec("Move livestock and stored feed away from low-lying, flood-prone areas.",
                    "Low ground collects runoff first.", "soon", "Livestock / stored feed"),
                Rec("After the rain, walk low-lying areas and record any standing water.",
                    "Observations improve future alerts for your farm.", "monitor")]
    elif level == "medium":
        recs = [Rec("Check that drains and field outlets are clear.",
                    "Moderate rainfall is forecast and could pond in low spots.", "soon"),
                Rec("Plan field work around the wettest day.",
                    f"Wettest forecast day: {peak:.1f} mm.", "monitor")]
    else:
        recs = [Rec("No action needed for rainfall right now.", "Forecast rainfall is below alert thresholds.", "info")]
    return Assessment("heavy_rain", "Heavy rainfall / waterlogging", level, "Whole farm",
                      d["time"][nxt[0]], d["time"][nxt[-1]], evidence,
                      ["Forecast rainfall is uncertain, especially for convective showers.",
                       "This is a risk warning, not confirmation that damage will occur."],
                      missing, recs, impact=3 if level == "high" else 2)


def rule_drought(farm, cond, data, today):
    d, idx, past = _future_daily(data, today)
    if not idx:
        return None
    window = past[-7:] + idx[:7]
    rain = sum(_num(d["precipitation_sum"][i]) for i in window)
    et0 = sum(_num(d["et0_fao_evapotranspiration"][i]) for i in window)
    deficit = et0 - rain
    t = THRESHOLDS
    level = "high" if deficit >= t["deficit_high_mm"] else "medium" if deficit >= t["deficit_medium_mm"] else "low"
    evidence = [f"Past 7 days + next 7 days: rainfall {rain:.1f} mm vs reference evapotranspiration {et0:.1f} mm.",
                f"Estimated water deficit: {deficit:.1f} mm (medium ≥ {t['deficit_medium_mm']} mm, high ≥ {t['deficit_high_mm']} mm)."]
    water = (cond or {}).get("water_access")
    missing = []
    irrigated = water in ("rain_and_irrigation", "mainly_irrigation")
    if irrigated and level != "low":
        level = bump(level, -1)
        evidence.append("Level lowered: irrigation is available on this farm.")
    if not water or water == "other":
        missing.append({"key": "water_access", "question": "Is irrigation available on this farm?",
                        "options": ["rainfall_only", "rain_and_irrigation", "mainly_irrigation"]})
    if not (cond or {}).get("soil_moisture_observation"):
        missing.append({"key": "soil_moisture_observation", "question": "How does the soil feel at root depth right now?",
                        "options": ["wet", "moist", "dry", "very_dry", "not_checked"]})
    obs = (cond or {}).get("soil_moisture_observation")
    if obs in ("dry", "very_dry") and level != "high":
        level = bump(level, 1)
        evidence.append(f"Level raised: you observed {obs.replace('_', ' ')} soil.")
    elif obs in ("wet", "moist") and level != "low":
        level = bump(level, -1)
        evidence.append(f"Level lowered: you observed {obs} soil.")
    if level == "high":
        recs = [Rec("Check soil moisture at root depth in your most sensitive crops.",
                    "A significant water deficit is building.", "now"),
                Rec("Prioritise irrigation for crops at flowering or fruit set." if irrigated else
                    "Prioritise any available water for the most sensitive, highest-value crops.",
                    "These stages are most yield-sensitive to water stress.", "soon"),
                Rec("Consider mulching and avoid unnecessary cultivation to conserve soil moisture.",
                    "Reduces evaporation from bare soil.", "soon")]
    elif level == "medium":
        recs = [Rec("Check soil moisture in shallow-rooted crops in the next few days.",
                    "Evapotranspiration is exceeding rainfall.", "soon"),
                Rec("Plan irrigation timing for cooler parts of the day." if irrigated else
                    "Watch for wilting during the afternoon.", "Early signs of water stress.", "monitor")]
    else:
        recs = [Rec("No action needed for drought right now.", "Rainfall is broadly keeping pace with crop water use.", "info")]
    return Assessment("drought", "Drought / water deficit", level, _plants_label(farm),
                      d["time"][window[0]], d["time"][window[-1]], evidence,
                      ["Uses reference evapotranspiration (grass); actual crop water use depends on crop and stage.",
                       "Soil water-holding capacity is not yet included."],
                      missing, recs, impact=2)


def rule_crop_heat(farm, cond, data, today):
    d, idx, _ = _future_daily(data, today)
    nxt = idx[:5]
    if not nxt:
        return None
    tmax = max(_num(d["temperature_2m_max"][i]) for i in nxt)
    hot_days = [d["time"][i] for i in nxt if _num(d["temperature_2m_max"][i]) >= THRESHOLDS["crop_heat_medium_c"]]
    t = THRESHOLDS
    level = "high" if tmax >= t["crop_heat_high_c"] else "medium" if tmax >= t["crop_heat_medium_c"] else "low"
    evidence = [f"Highest forecast temperature next 5 days: {tmax:.1f} °C.",
                f"Days ≥ {t['crop_heat_medium_c']} °C: {len(hot_days)}." + (f" ({', '.join(hot_days)})" if hot_days else ""),
                f"Rule: medium ≥ {t['crop_heat_medium_c']} °C, high ≥ {t['crop_heat_high_c']} °C."]
    if level == "high":
        recs = [Rec("Irrigate early in the morning ahead of the hottest days, where water is available.",
                    "Well-watered plants tolerate heat better.", "now"),
                Rec("Avoid transplanting, spraying or other plant stress during peak heat.",
                    "Extra stress during heat increases damage.", "soon"),
                Rec("Use shade netting for sensitive vegetables or nursery plants if you have it.",
                    "Reduces leaf and fruit temperature.", "soon", "Vegetables, herbs, flowers")]
    elif level == "medium":
        recs = [Rec("Check crops for wilting in the afternoons and water if soils are dry.",
                    "Warm conditions increase water demand.", "monitor")]
    else:
        recs = [Rec("No action needed for crop heat stress.", "Temperatures are below alert thresholds.", "info")]
    return Assessment("crop_heat", "Heat stress (crops)", level, _plants_label(farm),
                      d["time"][nxt[0]], d["time"][nxt[-1]], evidence,
                      ["Heat tolerance varies widely by crop and growth stage; thresholds are generic."],
                      [], recs, impact=2)


def rule_frost(farm, cond, data, today):
    d, idx, _ = _future_daily(data, today)
    nxt = idx[:7]
    if not nxt:
        return None
    tmin_i = min(nxt, key=lambda i: _num(d["temperature_2m_min"][i]))
    tmin = _num(d["temperature_2m_min"][tmin_i])
    t = THRESHOLDS
    if tmin <= t["frost_high_c"]:
        level = "high"
    elif tmin <= t["frost_medium_c"]:
        level = "medium"
    else:
        level = "low"
    evidence = [f"Lowest forecast air temperature next 7 days: {tmin:.1f} °C on {d['time'][tmin_i]}.",
                f"Rule: medium ≤ {t['frost_medium_c']} °C, high ≤ {t['frost_high_c']} °C (air temperature at 2 m)."]
    if level == "low" and tmin <= t["frost_low_c"]:
        evidence.append("Near-frost: ground frost is possible on clear, still nights even when air stays above 0 °C.")
    if level == "high":
        recs = [Rec("Cover frost-sensitive crops and seedlings with fleece the evening before.",
                    "Air frost is forecast.", "now"),
                Rec("Delay planting out tender crops until after the cold spell.",
                    "Young plants are most vulnerable.", "soon"),
                Rec("Protect exposed water pipes and troughs.", "Freezing temperatures can damage supply.", "soon")]
    elif level == "medium":
        recs = [Rec("Have fleece or covers ready for sensitive crops.", "Temperatures near 0 °C are forecast.", "soon"),
                Rec("Check the forecast again the afternoon before the cold night.", "Frost forecasts sharpen closer to the date.", "monitor")]
    else:
        recs = [Rec("Watch for ground frost on clear, still nights." if tmin <= t["frost_low_c"] else
                    "No action needed for frost.", "Minimum temperatures are above air-frost thresholds.",
                    "monitor" if tmin <= t["frost_low_c"] else "info")]
    return Assessment("frost", "Frost", level, _plants_label(farm),
                      d["time"][nxt[0]], d["time"][nxt[-1]], evidence,
                      ["Frost pockets and valley bottoms can be several degrees colder than the forecast point."],
                      [], recs, impact=3 if level == "high" else 2)


def rule_livestock_heat(farm, cond, data, today):
    h = data.get("hourly") or {}
    times = h.get("time", [])
    idx = [i for i, t in enumerate(times) if t[:10] >= today][: 24 * 5]
    if not idx:
        return None
    vals = [(thi(_num(h["temperature_2m"][i]), _num(h["relative_humidity_2m"][i])), times[i]) for i in idx]
    peak, peak_t = max(vals)
    t = THRESHOLDS
    hours_med = sum(1 for v, _ in vals if v >= t["thi_medium"])
    level = "high" if peak >= t["thi_high"] else "medium" if peak >= t["thi_medium"] else "low"
    evidence = [f"Peak temperature-humidity index (THI) next 5 days: {peak:.0f} at {peak_t.replace('T', ' ')}.",
                f"Hours at THI ≥ {t['thi_medium']}: {hours_med}.",
                f"Rule: medium THI ≥ {t['thi_medium']}, high THI ≥ {t['thi_high']} (cattle-based reference)."]
    if level == "high":
        recs = [Rec("Ensure plentiful clean drinking water and extra trough space.", "Water intake rises sharply in heat.", "now"),
                Rec("Provide shade and ventilation; avoid moving or handling animals in the hottest hours.",
                    "Handling adds heat load.", "now"),
                Rec("Watch for panting, drooling or lethargy and contact your vet if animals show distress.",
                    "Early signs of heat stress.", "monitor",
                    caveat="This is weather-based guidance, not veterinary advice.")]
    elif level == "medium":
        recs = [Rec("Check water supply and shade availability.", "Mild heat stress conditions are forecast.", "soon")]
    else:
        recs = [Rec("No action needed for livestock heat stress.", "THI is below alert thresholds.", "info")]
    return Assessment("livestock_heat", "Heat stress (livestock)", level, _livestock_label(farm),
                      times[idx[0]][:10], times[idx[-1]][:10], evidence,
                      ["THI thresholds differ by species, breed and housing; this uses a generic reference.",
                       "Not veterinary advice."],
                      [], recs, impact=3 if level == "high" else 2)


def rule_late_blight(farm, cond, data, today):
    """Hutton criteria (UK late-blight warning): two consecutive days, each with min temp ≥ 10 °C
    and ≥ 6 hours of relative humidity ≥ 90%. Only for potato / tomato."""
    crops = [p["name"] for p in farm.get("production_items", []) if p["name"].strip().lower() in BLIGHT_CROPS]
    if not crops:
        return None
    h = data.get("hourly") or {}
    by_day: dict[str, dict] = {}
    for i, ts in enumerate(h.get("time", [])):
        day = ts[:10]
        if day < today:
            continue
        rec = by_day.setdefault(day, {"tmin": 99.0, "humid_hours": 0})
        rec["tmin"] = min(rec["tmin"], _num(h["temperature_2m"][i]))
        if _num(h["relative_humidity_2m"][i]) >= 90:
            rec["humid_hours"] += 1
    days = sorted(by_day)[:7]
    qualifying = [d for d in days if by_day[d]["tmin"] >= 10 and by_day[d]["humid_hours"] >= 6]
    near = [d for d in days if by_day[d]["tmin"] >= 8 and by_day[d]["humid_hours"] >= 4]
    consecutive = any(
        (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days == 1
        for a, b in zip(qualifying, qualifying[1:])
    )
    if consecutive:
        level = "high"
    elif qualifying or len(near) >= 2:
        level = "medium"
    else:
        level = "low"
    evidence = [f"Forecast days meeting a Hutton-criteria day (min ≥ 10 °C and ≥ 6 h RH ≥ 90%): {len(qualifying)}"
                + (f" ({', '.join(qualifying)})" if qualifying else "") + ".",
                "Rule: two consecutive qualifying days = high (Hutton period); one qualifying day or near-misses = medium."]
    missing = []
    stages = [p.get("growth_stage") for p in farm.get("production_items", []) if p["name"].strip().lower() in BLIGHT_CROPS]
    if not any(stages):
        missing.append({"key": "growth_stage", "question": f"What growth stage is your {crops[0].lower()} crop at?",
                        "options": ["not_planted", "emerging", "growing", "flowering", "harvested"], "item": crops[0]})
    if any(s in ("not_planted", "harvested") for s in stages) and all(s in ("not_planted", "harvested") for s in stages if s):
        level = "low"
        evidence.append("Level set to low: no susceptible crop currently in the ground.")
    if level == "high":
        recs = [Rec("Inspect potato/tomato leaves and stems for blight lesions, especially in humid, sheltered spots.",
                    "Weather favours late-blight spread.", "now"),
                Rec("Discuss protection options with your agronomist or adviser before the period starts.",
                    "Weather-driven warning; treatment choice must follow local, expert-reviewed guidance.", "soon",
                    caveat="Do not apply any treatment based on this weather signal alone.")]
    elif level == "medium":
        recs = [Rec("Check crops for early blight symptoms over the next few days.",
                    "Conditions are approaching blight-favourable thresholds.", "monitor")]
    else:
        recs = [Rec("No blight-favourable weather period forecast.", "Humidity/temperature criteria not met.", "info")]
    return Assessment("late_blight", "Late blight weather risk", level, ", ".join(crops),
                      days[0] if days else today, days[-1] if days else today, evidence,
                      ["Indicates weather favourable to late blight, not that disease is present.",
                       "Hutton criteria were developed for UK conditions; validate for your region."],
                      missing, recs, impact=3)


def _plants_label(farm):
    names = [p["name"] for p in farm.get("production_items", []) if p["type"] != "livestock"]
    return ", ".join(names) if names else "Crops and plants"


def _livestock_label(farm):
    names = [p["name"] for p in farm.get("production_items", []) if p["type"] == "livestock"]
    return ", ".join(names) if names else "Livestock"


# --------------------------------------------------------------------------- engine

def applicable_rules(farm) -> list:
    types = set(farm.get("production_types") or [])
    rules = []
    has_plants = bool(types & PLANT_TYPES)
    if types & (PLANT_TYPES | FORAGE_TYPES) or "livestock" in types:
        rules.append(rule_heavy_rain)
    if types & (PLANT_TYPES | FORAGE_TYPES):
        rules.append(rule_drought)
    if has_plants:
        rules += [rule_crop_heat, rule_frost, rule_late_blight]
    if "livestock" in types:
        rules.append(rule_livestock_heat)
    if not rules:  # "other" only: still give general weather hazards
        rules = [rule_heavy_rain, rule_frost]
    return rules


def assess(farm: dict, conditions: dict | None, weather: dict | None, now: datetime | None = None) -> list[dict]:
    """Run all applicable rules. Returns [] if no weather data (never guesses)."""
    if not weather:
        return []
    now = now or datetime.now(timezone.utc)
    today = ((weather.get("current") or {}).get("time") or now.isoformat())[:10]
    valid_until = (now + timedelta(hours=12)).isoformat(timespec="seconds")
    concern = CONCERN_HAZARDS.get(farm.get("main_concern") or "", set())
    out = []
    for rule in applicable_rules(farm):
        a = rule(farm, conditions or {}, weather, today)
        if a is None:
            continue
        a.priority_score = LEVEL_LIKELIHOOD[a.level] * a.impact + (1 if a.hazard in concern and a.level != "low" else 0)
        a.valid_until = valid_until
        out.append(a.to_dict())
    out.sort(key=lambda a: -a["priority_score"])
    return out


def missing_hints(farm: dict, conditions: dict | None) -> list[str]:
    """FR-10: optional details that would improve assessments (never 'invalid profile')."""
    hints = []
    cond = conditions or {}
    types = set(farm.get("production_types") or [])
    items = farm.get("production_items") or []
    if types & PLANT_TYPES and not [p for p in items if p["type"] != "livestock"]:
        hints.append("Add crop names (e.g. potatoes, wheat) for crop-specific checks such as late blight.")
    if "livestock" in types and not [p for p in items if p["type"] == "livestock"]:
        hints.append("Add livestock species to tailor heat-stress guidance.")
    if types & (PLANT_TYPES | FORAGE_TYPES) and not cond.get("drainage"):
        hints.append("Tell us about drainage to sharpen heavy-rainfall alerts.")
    named = {p["name"].strip().lower() for p in items if p["type"] != "livestock"}
    if named and not named & BLIGHT_CROPS:
        hints.append("Disease-risk checks are currently available for potatoes and tomatoes only.")
    return hints
