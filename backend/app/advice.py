"""Crop-specific advice: combines the crop guide, the planting date and local weather.

Pure functions (no DB / HTTP) so the maths can be unit-tested.
Water: crop water use = ET0 x Kc (FAO-56). 1 mm of water = 1 litre per square metre.
"""
from datetime import date, timedelta

STAGE_LABELS = {"initial": "Establishing", "development": "Growing", "mid": "Full growth",
                "late": "Ripening / maturing", "done": "Past typical harvest", "unknown": "Unknown"}


def _kc_at(guide: dict, day: int) -> tuple[str, float]:
    """FAO-56 crop coefficient curve: flat initial, linear rise, flat mid, linear fall."""
    s, kc = guide["stages"], guide["kc"]
    a = s["initial"]
    b = a + s["development"]
    c = b + s["mid"]
    d = c + s["late"]
    if day < a:
        return "initial", kc["ini"]
    if day < b:
        return "development", kc["ini"] + (kc["mid"] - kc["ini"]) * (day - a) / s["development"]
    if day < c:
        return "mid", kc["mid"]
    if day < d:
        return "late", kc["mid"] + (kc["end"] - kc["mid"]) * (day - c) / s["late"]
    return "done", kc["end"]


def growth_stage(guide: dict, planting_date: str | None, today: date) -> dict:
    perennial = guide.get("harvest_days") is None and guide["key"] != "generic"
    if perennial:
        active = 4 <= today.month <= 9
        key = "mid" if active else "initial"
        out = {"stage": key, "label": "In season" if active else "Dormant / slow growth",
               "kc": guide["kc"]["mid"] if active else guide["kc"]["ini"], "days": None, "harvest": None,
               "perennial": True}
        if planting_date:
            out["days"] = (today - date.fromisoformat(planting_date)).days
        return out
    if not planting_date:
        return {"stage": "unknown", "label": STAGE_LABELS["unknown"], "kc": guide["kc"]["mid"], "days": None,
                "harvest": None, "needs_planting_date": True}
    planted = date.fromisoformat(planting_date)
    days = max(0, (today - planted).days)
    key, kc = _kc_at(guide, days)
    harvest = None
    if guide.get("harvest_days"):
        lo, hi = guide["harvest_days"]
        harvest = {"from": (planted + timedelta(days=lo)).isoformat(), "to": (planted + timedelta(days=hi)).isoformat()}
    total = sum(guide["stages"].values())
    return {"stage": key, "label": STAGE_LABELS[key], "kc": round(kc, 2), "days": days, "harvest": harvest,
            "progress": min(1.0, round(days / total, 2)), "future": planted > today}


def water_advice(guide: dict, stage: dict, summary: dict, measured: dict | None) -> dict:
    """How much water to add this week, in mm (= litres per m²)."""
    name = guide["name"]
    kc = stage["kc"]
    nxt = summary.get("days", [])[:7]
    past = summary.get("past_days", [])
    et0_next = [d["et0_mm"] for d in nxt if d.get("et0_mm") is not None]
    estimated = "et0_fao_evapotranspiration" in summary.get("estimated", [])

    # Crop water use over the last 7 days.
    if len(past) >= 5 and all(d.get("et0_mm") is not None for d in past):
        et0_past = sum(d["et0_mm"] for d in past) * 7 / len(past)
        use_basis = "measured-weather model"
    elif et0_next:
        et0_past = sum(et0_next) / len(et0_next) * 7
        use_basis = "estimated from this week's forecast"
        estimated = True
    else:
        return {"status": "unavailable", "summary": "Not enough weather data to work out water needs."}
    use_mm = et0_past * kc

    # Rain over the last 7 days: measured gauge first, then the weather model.
    if measured:
        rain_mm, rain_source = measured["mm"], f"measured at {measured['station']} ({measured['distance_km']} km away)"
    elif summary.get("past_rain_mm") is not None:
        rain_mm, rain_source = summary["past_rain_mm"], "weather model for your location"
    else:
        rain_mm, rain_source = None, None

    rain_3d = sum(d.get("rain_mm") or 0 for d in nxt[:3])
    rain_7d = sum(d.get("rain_mm") or 0 for d in nxt)
    need_next = max(0.0, sum(et0_next) * kc - rain_7d) if et0_next else None
    out = {"kc": kc, "crop_use_mm": round(use_mm, 1), "rain_mm": rain_mm, "rain_source": rain_source,
           "use_basis": use_basis, "forecast_rain_3d_mm": round(rain_3d, 1), "forecast_rain_7d_mm": round(rain_7d, 1),
           "next_week_need_mm": round(need_next, 1) if need_next is not None else None, "estimated": estimated}

    if rain_mm is None:
        add = need_next or 0
        out.update(status="no_past_rain", add_l_per_m2=round(add),
                   summary=(f"We can't measure last week's rain here. Over the next 7 days {name.lower()} will use about "
                            f"{sum(et0_next) * kc:.0f} mm and {rain_7d:.1f} mm of rain is forecast, so plan to add about "
                            f"{add:.0f} L per m². Check the soil first: water if it's dry at finger depth."))
        return out

    deficit = use_mm - rain_mm
    out["deficit_mm"] = round(deficit, 1)
    if deficit <= 2:
        out.update(status="ok", add_l_per_m2=0,
                   summary=(f"{rain_mm:.1f} mm of rain fell in the last 7 days, covering the ≈{use_mm:.0f} mm your "
                            f"{name.lower()} used. No watering needed this week."))
    elif rain_3d >= 0.6 * deficit:
        out.update(status="wait", add_l_per_m2=0,
                   summary=(f"Only {rain_mm:.1f} mm of rain fell in the last 7 days against ≈{use_mm:.0f} mm used, "
                            f"but {rain_3d:.1f} mm is forecast in the next 3 days. Hold off watering and check again after the rain."))
    else:
        add = round(deficit)
        splits = max(1, min(3, round(add / 10)))
        out.update(status="water", add_l_per_m2=add, waterings=splits,
                   summary=(f"Only {rain_mm:.1f} mm of rain fell in the last 7 days, but your {name.lower()} used "
                            f"≈{use_mm:.0f} mm. Add about {add} L of water per m² this week"
                            + (f", split into {splits} waterings." if splits > 1 else ", in one good soak.")))
    return out


def sunlight_advice(guide: dict, summary: dict) -> dict:
    past = [d["sun_h"] for d in summary.get("past_days", []) if d.get("sun_h") is not None]
    nxt = [d["sun_h"] for d in summary.get("days", [])[:7] if d.get("sun_h") is not None]
    estimated = "sunshine_duration" in summary.get("estimated", [])
    if not past and not nxt:
        return {"status": "unavailable", "summary": "Sunshine data isn't available for this location."}
    need = guide["sun_hours"]
    past_avg = sum(past) / len(past) if past else None
    next_avg = sum(nxt) / len(nxt) if nxt else None
    basis = past_avg if past_avg is not None else next_avg
    status = "ok" if basis >= need * 0.75 else "low"
    when = "last 7 days" if past_avg is not None else "forecast, next 7 days"
    if status == "ok":
        text = f"About {basis:.1f} h of sunshine a day ({when}), which suits {guide['name'].lower()} (needs ~{need} h)."
    else:
        text = (f"Only about {basis:.1f} h of sunshine a day ({when}); {guide['name'].lower()} does best with ~{need} h. "
                "Growth may slow. Thin crowded plants, keep weeds down and avoid shading from tall crops or hedges.")
        if basis < 3 and summary.get("days") and summary["days"][0]["date"][5:7] in ("10", "11", "12", "01", "02"):
            text += " Low winter light is normal; this is no cause for alarm."
    return {"status": status, "need_h": need, "past_avg_h": round(past_avg, 1) if past_avg is not None else None,
            "next_avg_h": round(next_avg, 1) if next_avg is not None else None, "estimated": estimated, "summary": text}


def temperature_advice(guide: dict, summary: dict) -> dict:
    nxt = summary.get("days", [])[:7]
    if not nxt:
        return {"status": "unavailable", "summary": "No forecast available."}
    lo, hi = guide["temp_c"]["min"], guide["temp_c"]["max"]
    tmin = min(d["t_min"] for d in nxt)
    tmax = max(d["t_max"] for d in nxt)
    notes = []
    if tmin < lo:
        notes.append(f"nights down to {tmin:.0f} °C are below the {lo} °C {guide['name'].lower()} prefer, so growth will slow")
    if tmax > hi:
        notes.append(f"days up to {tmax:.0f} °C are above the ideal {hi} °C, so watch for stress or bolting")
    status = "ok" if not notes else "outside"
    text = (f"Next 7 days: {tmin:.0f}–{tmax:.0f} °C, within the {lo}–{hi} °C range this crop likes."
            if not notes else f"Next 7 days: {'; '.join(notes)}.")
    return {"status": status, "range": [lo, hi], "forecast": [tmin, tmax], "summary": text}


def weather_ahead(guide: dict, assessments: list[dict]) -> list[dict]:
    """Elevated farm-wide weather alerts, with this crop's own measure added."""
    tip_keys = {"heavy_rain": "heavy_rain", "drought": "drought", "frost": "frost", "crop_heat": "heat",
                "storm": "storm"}
    out = []
    for a in assessments:
        if a["level"] == "low" or a["hazard"] not in tip_keys:
            continue
        tip = guide.get("weather_tips", {}).get(tip_keys[a["hazard"]])
        actions = [r["action"] for r in a.get("recommendations", []) if r.get("urgency") != "info"][:2]
        out.append({"assessment_id": a.get("id"), "title": a["title"], "level": a["level"],
                    "window": [a["window_start"], a["window_end"]], "evidence": a["evidence"][0],
                    "crop_tip": tip, "actions": actions})
    return out


def crop_advice(item: dict, guide: dict, summary: dict | None, measured: dict | None, assessments: list[dict],
                today: date) -> dict:
    stage = growth_stage(guide, item.get("planting_date"), today)
    out = {
        "item": {k: item.get(k) for k in ("id", "name", "type", "planting_date", "growth_stage")},
        "guide": {k: guide[k] for k in ("key", "name", "emoji", "sun_hours", "temp_c", "ph", "harvest_days",
                                         "notes", "pests", "feeds", "sources", "kc", "stages")},
        "in_guide": guide["key"] != "generic",
        "stage": stage,
    }
    if summary:
        out["water"] = water_advice(guide, stage, summary, measured)
        out["sun"] = sunlight_advice(guide, summary)
        out["temperature"] = temperature_advice(guide, summary)
    out["weather_ahead"] = weather_ahead(guide, assessments)
    return out
