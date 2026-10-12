"""Weather ingestion. Isolated from risk logic and UI.

Open-Meteo first (free, no key); MET Norway as a free fallback when Open-Meteo is unavailable
(it rate-limits shared cloud IPs). Both are stored in the same Open-Meteo-shaped format.

Every snapshot is stored with source + fetch time so freshness can be shown (FR-04).
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import httpx

from . import sources

SOURCE = "open-meteo.com"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
STALE_AFTER = timedelta(hours=6)  # older snapshots are shown as stale
REFRESH_AFTER = timedelta(hours=1)  # don't refetch more often than this
HEADERS = {"User-Agent": sources.USER_AGENT}
PROVIDER = os.environ.get("WEATHER_PROVIDER", "auto")  # auto | openmeteo | met
_rain_cache: dict[tuple, tuple[datetime, dict | None]] = {}
log = logging.getLogger("uvicorn.error")


def _get(url: str, params: dict, timeout: float) -> httpx.Response:
    """GET with a few retries on rate limits (429) and server errors, which shared cloud IPs hit often."""
    for attempt in range(3):
        r = httpx.get(url, params=params, timeout=timeout, headers=HEADERS)
        if r.status_code != 429 and r.status_code < 500:
            break
        log.warning("Weather API %s returned %s (attempt %d): %s", url, r.status_code, attempt + 1, r.text[:200])
        time.sleep(1.5 * (attempt + 1))
    if r.is_error:
        log.error("Weather API %s failed with %s: %s", url, r.status_code, r.text[:300])
    r.raise_for_status()
    return r


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def geocode(query: str, count: int = 6) -> list[dict]:
    if sources.is_uk_postcode(query):
        return sources.postcode_lookup(query)
    r = _get(GEOCODE_URL, {"name": query, "count": count, "language": "en"}, timeout=10)
    out = []
    for g in r.json().get("results", []) or []:
        parts = [g.get("name"), g.get("admin1"), g.get("country")]
        out.append({
            "label": ", ".join(p for p in parts if p),
            "latitude": g["latitude"],
            "longitude": g["longitude"],
            "timezone": g.get("timezone"),
        })
    return out


def fetch_forecast(lat: float, lon: float, tz_name: str | None = None) -> dict:
    """Forecast in the internal (Open-Meteo-shaped) format, from the first provider that works."""
    if PROVIDER == "met":
        return sources.met_norway_forecast(lat, lon, tz_name)
    try:
        return fetch_open_meteo(lat, lon)
    except Exception as e:
        if PROVIDER == "openmeteo":
            raise
        log.warning("Open-Meteo failed (%r); falling back to MET Norway", e)
        return sources.met_norway_forecast(lat, lon, tz_name)


def fetch_open_meteo(lat: float, lon: float) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": "auto",
        "past_days": 7,
        "forecast_days": 7,
        "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,weather_code",
        "hourly": "temperature_2m,relative_humidity_2m,precipitation",
        "daily": ",".join([
            "temperature_2m_max", "temperature_2m_min", "precipitation_sum",
            "precipitation_probability_max", "et0_fao_evapotranspiration",
            "relative_humidity_2m_mean", "weather_code", "sunshine_duration", "wind_gusts_10m_max",
        ]),
    }
    data = _get(FORECAST_URL, params, timeout=15).json()
    data["provider"] = SOURCE
    data["estimated"] = []
    return data


def measured_rain(lat: float, lon: float) -> dict | None:
    """Past-7-day measured rain from the nearest EA gauge (England), cached for an hour."""
    key = (round(lat, 3), round(lon, 3))
    hit = _rain_cache.get(key)
    if hit and utcnow() - hit[0] < REFRESH_AFTER:
        return hit[1]
    try:
        value = sources.measured_rain_7d(lat, lon)
    except Exception as e:
        log.warning("Rain gauge lookup failed: %r", e)
        value = None
    _rain_cache[key] = (utcnow(), value)
    return value


def latest_snapshot(conn, farm_id: int):
    return conn.execute(
        "SELECT * FROM weather_snapshots WHERE farm_id=? ORDER BY fetched_at DESC LIMIT 1", (farm_id,)
    ).fetchone()


def get_weather(conn, farm, force: bool = False) -> dict:
    """Return {status, snapshot_id, fetched_at, data, error}.

    status: fresh | stale | unavailable. Falls back to the last good snapshot on errors.
    """
    if farm["latitude"] is None or farm["longitude"] is None:
        return {"status": "unavailable", "error": "Farm location not set", "data": None,
                "snapshot_id": None, "fetched_at": None}

    snap = latest_snapshot(conn, farm["id"])
    same_place = snap is not None and snap["latitude"] == farm["latitude"] and snap["longitude"] == farm["longitude"]
    now = utcnow()
    error = None

    needs_fetch = force or not same_place or now - datetime.fromisoformat(snap["fetched_at"]) > REFRESH_AFTER
    if needs_fetch:
        try:
            data = fetch_forecast(farm["latitude"], farm["longitude"], farm.get("timezone"))
            source = data.get("provider", SOURCE)
            cur = conn.execute(
                "INSERT INTO weather_snapshots(farm_id, source, latitude, longitude, fetched_at, payload) VALUES (?,?,?,?,?,?)",
                (farm["id"], source, farm["latitude"], farm["longitude"], iso(now), json.dumps(data)),
            )
            conn.commit()
            return {"status": "fresh", "snapshot_id": cur.lastrowid, "fetched_at": iso(now),
                    "data": data, "error": None, "source": source}
        except Exception as e:  # network/API failure: fall back safely
            code = getattr(getattr(e, "response", None), "status_code", None)
            error = f"Weather service unavailable ({code or type(e).__name__})"
            log.error("Forecast fetch failed for farm %s: %r", farm["id"], e)

    if not same_place:
        return {"status": "unavailable", "error": error or "No weather data yet", "data": None,
                "snapshot_id": None, "fetched_at": None}

    fetched = datetime.fromisoformat(snap["fetched_at"])
    status = "stale" if now - fetched > STALE_AFTER else "fresh"
    return {"status": status, "snapshot_id": snap["id"], "fetched_at": snap["fetched_at"],
            "data": json.loads(snap["payload"]), "error": error, "source": snap["source"]}


WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Rain showers",
    81: "Rain showers", 82: "Violent rain showers", 85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail",
}


def _col(d: dict, key: str, i: int):
    vals = d.get(key) or []
    return vals[i] if i < len(vals) else None


def summarize(data: dict) -> dict:
    """Compact weather summary for the dashboard: now, the next 7 days, and the past 7 days."""
    cur = data.get("current", {}) or {}
    d = data.get("daily", {}) or {}
    today = cur.get("time", "")[:10]
    days, past = [], []
    for i, day in enumerate(d.get("time", [])):
        sun = _col(d, "sunshine_duration", i)
        row = {
            "date": day,
            "t_max": d["temperature_2m_max"][i],
            "t_min": d["temperature_2m_min"][i],
            "rain_mm": d["precipitation_sum"][i],
            "rain_prob": _col(d, "precipitation_probability_max", i),
            "sun_h": round(sun / 3600, 1) if sun is not None else None,
            "gust_kmh": _col(d, "wind_gusts_10m_max", i),
            "et0_mm": _col(d, "et0_fao_evapotranspiration", i),
            "condition": WEATHER_CODES.get(_col(d, "weather_code", i), ""),
        }
        (past if day < today else days).append(row)
    past = past[-7:]
    return {
        "current": {
            "temperature": cur.get("temperature_2m"),
            "humidity": cur.get("relative_humidity_2m"),
            "precipitation": cur.get("precipitation"),
            "wind_speed": cur.get("wind_speed_10m"),
            "condition": WEATHER_CODES.get(cur.get("weather_code"), ""),
            "time": cur.get("time"),
        },
        "days": days[:7],
        "past_days": past,
        "past_rain_mm": round(sum(p["rain_mm"] or 0 for p in past), 1) if past else None,
        "past_sun_h": round(sum(p["sun_h"] or 0 for p in past), 1) if past and all(p["sun_h"] is not None for p in past) else None,
        "provider": data.get("provider", SOURCE),
        "estimated": data.get("estimated", []),
        "timezone": data.get("timezone"),
    }
