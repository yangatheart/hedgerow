"""Scenario tests for the rule engine (PRD: 'tested with representative scenarios')."""
from app import risk_engine as re

TODAY = "2026-10-12"


def make_weather(rain=None, tmax=None, tmin=None, et0=None, past_rain=None, past_et0=None,
                 hourly_temp=15.0, hourly_rh=70.0):
    """7 past days + 7 forecast days of daily data, plus 7 forecast days of hourly data."""
    past_days = [f"2026-10-{d:02d}" for d in range(5, 12)]
    days = [f"2026-10-{d:02d}" for d in range(12, 19)]
    rain = rain or [0] * 7
    hours = [f"{d}T{h:02d}:00" for d in days for h in range(24)]
    temp = hourly_temp if isinstance(hourly_temp, list) else [hourly_temp] * len(hours)
    rh = hourly_rh if isinstance(hourly_rh, list) else [hourly_rh] * len(hours)
    return {
        "current": {"time": f"{TODAY}T10:00"},
        "daily": {
            "time": past_days + days,
            "precipitation_sum": (past_rain or [2] * 7) + rain,
            "temperature_2m_max": [18] * 7 + (tmax or [18] * 7),
            "temperature_2m_min": [8] * 7 + (tmin or [8] * 7),
            "et0_fao_evapotranspiration": (past_et0 or [2] * 7) + (et0 or [2] * 7),
        },
        "hourly": {"time": hours, "temperature_2m": temp, "relative_humidity_2m": rh},
    }


def farm(types=("vegetables",), items=(), concern=None):
    return {"production_types": list(types), "production_items": list(items), "main_concern": concern}


def by_hazard(results):
    return {a["hazard"]: a for a in results}


def test_no_weather_returns_nothing():
    assert re.assess(farm(), {}, None) == []


def test_heavy_rain_levels():
    r = by_hazard(re.assess(farm(), {}, make_weather(rain=[20, 20, 15, 0, 0, 0, 0])))
    assert r["heavy_rain"]["level"] == "high"  # 55 mm / 3 days
    r = by_hazard(re.assess(farm(), {}, make_weather(rain=[10, 8, 9, 0, 0, 0, 0])))
    assert r["heavy_rain"]["level"] == "medium"
    r = by_hazard(re.assess(farm(), {}, make_weather(rain=[1, 2, 1, 0, 0, 0, 0])))
    assert r["heavy_rain"]["level"] == "low"


def test_poor_drainage_raises_rain_level_and_asks_followup():
    w = make_weather(rain=[10, 8, 9, 0, 0, 0, 0])
    r = by_hazard(re.assess(farm(), {}, w))
    assert {m["key"] for m in r["heavy_rain"]["missing_inputs"]} == {"drainage", "waterlogging_history"}
    r = by_hazard(re.assess(farm(), {"drainage": "poor", "waterlogging_history": "no"}, w))
    assert r["heavy_rain"]["level"] == "high"
    assert r["heavy_rain"]["missing_inputs"] == []


def test_drought_and_irrigation():
    w = make_weather(rain=[0] * 7, past_rain=[0] * 7, et0=[4] * 7, past_et0=[4] * 7)  # 56 mm deficit
    r = by_hazard(re.assess(farm(), {"water_access": "rainfall_only"}, w))
    assert r["drought"]["level"] == "high"
    r = by_hazard(re.assess(farm(), {"water_access": "mainly_irrigation"}, w))
    assert r["drought"]["level"] == "medium"


def test_frost():
    r = by_hazard(re.assess(farm(), {}, make_weather(tmin=[5, 3, -3, 4, 5, 6, 7])))
    assert r["frost"]["level"] == "high"
    assert r["frost"]["recommendations"][0]["urgency"] == "now"


def test_crop_heat():
    r = by_hazard(re.assess(farm(), {}, make_weather(tmax=[25, 31, 36, 30, 28, 20, 20])))
    assert r["crop_heat"]["level"] == "high"


def test_livestock_only_gets_livestock_rules():
    r = by_hazard(re.assess(farm(types=["livestock"]), {}, make_weather(hourly_temp=33.0, hourly_rh=60.0)))
    assert "livestock_heat" in r and r["livestock_heat"]["level"] == "high"
    assert "frost" not in r and "crop_heat" not in r and "late_blight" not in r


def test_late_blight_only_for_named_susceptible_crops():
    humid = make_weather(hourly_temp=14.0, hourly_rh=95.0)
    r = by_hazard(re.assess(farm(items=[{"type": "vegetables", "name": "Carrots"}]), {}, humid))
    assert "late_blight" not in r
    r = by_hazard(re.assess(farm(items=[{"type": "vegetables", "name": "Potatoes"}]), {}, humid))
    assert r["late_blight"]["level"] == "high"
    assert r["late_blight"]["missing_inputs"][0]["key"] == "growth_stage"
    # no crop in the ground -> not elevated
    harvested = [{"type": "vegetables", "name": "Potatoes", "growth_stage": "harvested"}]
    r = by_hazard(re.assess(farm(items=harvested), {}, humid))
    assert r["late_blight"]["level"] == "low"


def test_blight_recommendation_never_prescribes_treatment():
    humid = make_weather(hourly_temp=14.0, hourly_rh=95.0)
    r = by_hazard(re.assess(farm(items=[{"type": "vegetables", "name": "Tomatoes"}]), {}, humid))
    text = " ".join(x["action"] for x in r["late_blight"]["recommendations"]).lower()
    assert "fungicide" not in text and "spray" not in text


def test_sorted_by_priority_and_every_assessment_is_complete():
    w = make_weather(rain=[30, 30, 0, 0, 0, 0, 0], tmin=[5] * 7)
    out = re.assess(farm(concern="soil_water"), {}, w)
    scores = [a["priority_score"] for a in out]
    assert scores == sorted(scores, reverse=True)
    for a in out:
        assert a["evidence"] and a["caveats"] and a["recommendations"] and a["valid_until"]
        assert a["level"] in re.LEVELS
        for rec in a["recommendations"]:
            assert rec["urgency"] in ("now", "soon", "monitor", "info")


def test_hints_do_not_invalidate_profile():
    hints = re.missing_hints(farm(types=["vegetables", "livestock"]), {})
    assert any("crop names" in h for h in hints)
    assert any("livestock species" in h for h in hints)
