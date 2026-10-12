"""Free data sources: formulas, MET Norway conversion, rain-gauge summing, postcodes."""
import json
import os

import pytest

from app import risk_engine, sources, weather

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "met_cambridge.json")


def test_extraterrestrial_radiation_matches_fao56_example():
    # FAO-56 Example 8: 3 September (day 246), latitude 20°S -> Ra = 32.2 MJ/m²/day (= 13.1 mm/day)
    assert sources.extraterrestrial_radiation_mm(-20, 246) == pytest.approx(0.408 * 32.2, abs=0.15)


def test_day_length_matches_fao56_example():
    # FAO-56 Example 9: same date and latitude -> N = 11.7 hours
    assert sources.day_length_hours(-20, 246) == pytest.approx(11.7, abs=0.1)


def test_hargreaves_et0():
    # 0.0023 * (22.5 + 17.8) * sqrt(15) * 13.14 ≈ 4.7 mm/day
    assert sources.hargreaves_et0(30, 15, -20, 246) == pytest.approx(4.7, abs=0.1)


def test_symbol_codes():
    assert sources.symbol_to_code("heavyrainandthunder") == 95
    assert sources.symbol_to_code("rainshowersandthunder_day") == 95
    assert sources.symbol_to_code("lightrain") == 61
    assert sources.symbol_to_code("partlycloudy_night") == 2
    assert sources.symbol_to_code("clearsky_day") == 0


def test_met_norway_converts_to_internal_format():
    data = sources.met_to_internal(json.load(open(FIXTURE)), 52.2, "Europe/London")
    d = data["daily"]
    assert data["provider"] == "met.no"
    assert len(d["time"]) >= 7
    for key in ("temperature_2m_max", "precipitation_sum", "et0_fao_evapotranspiration", "sunshine_duration",
                "wind_gusts_10m_max", "weather_code"):
        assert len(d[key]) == len(d["time"])
    assert all(mx >= mn for mx, mn in zip(d["temperature_2m_max"], d["temperature_2m_min"]))
    assert all(0 <= s <= 24 * 3600 for s in d["sunshine_duration"])
    assert len(data["hourly"]["time"]) == len(data["hourly"]["temperature_2m"])
    # the whole risk engine and summary run unchanged on the converted data
    farm = {"production_types": ["vegetables", "livestock"],
            "production_items": [{"type": "vegetables", "name": "Potatoes"}], "main_concern": None}
    hazards = {a["hazard"] for a in risk_engine.assess(farm, {}, data)}
    assert {"heavy_rain", "frost", "late_blight", "livestock_heat", "storm"} <= hazards
    s = weather.summarize(data)
    assert s["provider"] == "met.no" and "sunshine_duration" in s["estimated"]
    assert s["days"] and s["days"][0]["sun_h"] is not None


def test_gauge_needs_a_nearly_complete_week():
    station = {"label": "Rainfall station", "notation": "E1", "lat": 52.27, "long": 0.0}
    full = [{"value": 0.2}] * 100 + [{"value": 0.0}] * 572
    r = sources.summarize_gauge(full, station, 52.2, 0.12)
    assert r["mm"] == 20.0 and r["station"] == "EA rain gauge E1" and r["distance_km"] > 5
    assert sources.summarize_gauge(full[:300], station, 52.2, 0.12) is None


def test_uk_postcode_detection():
    assert sources.is_uk_postcode("CB2 1TN") and sources.is_uk_postcode("sw1a1aa")
    assert not sources.is_uk_postcode("Cambridge")


def test_fallback_to_met_when_open_meteo_fails(monkeypatch):
    def fail(lat, lon):
        raise RuntimeError("429")
    monkeypatch.setattr(weather, "fetch_open_meteo", fail)
    monkeypatch.setattr(sources, "met_norway_forecast", lambda lat, lon, tz=None: {"provider": "met.no"})
    assert weather.fetch_forecast(52.2, 0.1)["provider"] == "met.no"
