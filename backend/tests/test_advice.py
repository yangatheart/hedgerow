"""Crop guide matching, growth stage, water/sun/temperature advice and the storm rule."""
from datetime import date

import pytest

from app import advice, crops, risk_engine
from tests.test_risk_engine import make_weather

TODAY = date(2026, 10, 12)


def summary(past_rain=0.3, past_et0=3.0, next_rain=(0,) * 7, next_et0=3.0, sun=6.0, tmin=8, tmax=18, estimated=()):
    days = [f"2026-10-{d:02d}" for d in range(12, 19)]
    past = [f"2026-10-{d:02d}" for d in range(5, 12)]
    return {
        "days": [{"date": d, "rain_mm": r, "et0_mm": next_et0, "sun_h": sun, "t_min": tmin, "t_max": tmax}
                 for d, r in zip(days, next_rain)],
        "past_days": [{"date": d, "rain_mm": past_rain / 7, "et0_mm": past_et0, "sun_h": sun} for d in past],
        "past_rain_mm": past_rain, "estimated": list(estimated),
    }


@pytest.mark.parametrize("text,key", [("Carrots", "carrot"), ("beet", "beetroot"), ("Maris Piper potatoes", "potato"),
                                       ("Cherry tomatoes", "tomato"), ("kale", "cabbage"), ("Strawberries", "strawberry")])
def test_match_crop(text, key):
    assert crops.match_crop(text)["key"] == key


def test_unknown_crop_gets_generic_profile():
    g = crops.match_crop("dragon fruit")
    assert g["key"] == "generic" and g["name"] == "Dragon Fruit"


def test_every_guide_entry_is_complete():
    for g in crops.GUIDE.values():
        assert g["sources"][0] is crops.FAO56 and g["pests"] and g["weather_tips"]
        assert 0 < g["kc"]["ini"] <= g["kc"]["mid"]


def test_growth_stage_from_planting_date():
    carrot = crops.GUIDE["carrot"]
    s = advice.growth_stage(carrot, "2026-08-31", TODAY)  # 42 days: development stage (20-50)
    assert s["stage"] == "development" and s["days"] == 42
    assert 0.7 < s["kc"] < 1.05
    assert s["harvest"] == {"from": "2026-11-19", "to": "2026-12-29"}
    assert advice.growth_stage(carrot, None, TODAY)["needs_planting_date"]


def test_water_top_up_when_little_rain():
    carrot = crops.GUIDE["carrot"]
    stage = {"kc": 1.0}
    w = advice.water_advice(carrot, stage, summary(), {"mm": 0.3, "station": "EA rain gauge E1", "distance_km": 3})
    # used 7 x 3.0 x 1.0 = 21 mm, rain 0.3 mm -> add ≈ 21 L/m²
    assert w["status"] == "water" and w["add_l_per_m2"] == 21 and w["waterings"] == 2
    assert "0.3 mm" in w["summary"] and "21 L" in w["summary"] and "EA rain gauge" in w["rain_source"]


def test_water_waits_for_forecast_rain_and_ok_when_wet():
    carrot = crops.GUIDE["carrot"]
    wait = advice.water_advice(carrot, {"kc": 1.0}, summary(next_rain=(10, 5, 0, 0, 0, 0, 0)), None)
    assert wait["status"] == "wait" and wait["add_l_per_m2"] == 0
    wet = advice.water_advice(carrot, {"kc": 1.0}, summary(past_rain=30), None)
    assert wet["status"] == "ok"


def test_water_uses_forecast_when_no_past_data():
    s = summary()
    s["past_days"], s["past_rain_mm"] = [], None
    w = advice.water_advice(crops.GUIDE["beetroot"], {"kc": 1.0}, s, {"mm": 2.0, "station": "g", "distance_km": 1})
    assert w["estimated"] and w["status"] == "water" and w["add_l_per_m2"] == 19


def test_sun_and_temperature():
    assert advice.sunlight_advice(crops.GUIDE["tomato"], summary(sun=2))["status"] == "low"
    assert advice.sunlight_advice(crops.GUIDE["lettuce"], summary(sun=4))["status"] == "ok"
    t = advice.temperature_advice(crops.GUIDE["courgette"], summary(tmin=4, tmax=20))
    assert t["status"] == "outside" and "4 °C" in t["summary"]


def test_storm_rule():
    w = make_weather()
    w["daily"]["weather_code"] = [3] * 7 + [3, 3, 95, 3, 3, 3, 3]
    w["daily"]["wind_gusts_10m_max"] = [20] * 7 + [30, 30, 60, 30, 30, 30, 30]
    farm = {"production_types": ["vegetables"], "production_items": [], "main_concern": None}
    storm = next(a for a in risk_engine.assess(farm, {}, w) if a["hazard"] == "storm")
    assert storm["level"] == "high" and "2026-10-14" in storm["evidence"][0]
    w["daily"]["weather_code"] = [3] * 14
    w["daily"]["wind_gusts_10m_max"] = [20] * 14
    calm = next(a for a in risk_engine.assess(farm, {}, w) if a["hazard"] == "storm")
    assert calm["level"] == "low"


def test_crop_advice_bundle_adds_crop_tips_to_alerts():
    alerts = [{"id": 1, "hazard": "storm", "title": "Storms and strong wind", "level": "high",
               "window_start": "2026-10-12", "window_end": "2026-10-18", "evidence": ["Thunder"],
               "recommendations": [{"action": "Stake tall crops", "urgency": "now"}]}]
    out = advice.crop_advice({"id": 5, "name": "Carrots", "type": "vegetables", "planting_date": "2026-08-31"},
                             crops.GUIDE["carrot"], summary(), None, alerts, TODAY)
    assert out["in_guide"] and out["water"]["status"] == "water"
    assert out["weather_ahead"][0]["crop_tip"] == crops.GUIDE["carrot"]["weather_tips"]["storm"]
