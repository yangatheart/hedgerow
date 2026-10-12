"""Free extra data sources, all mapped into the same shapes the rest of the app already uses.

- MET Norway Locationforecast: fallback forecast when Open-Meteo is unavailable (e.g. rate-limited).
- Environment Agency rain gauges (England): measured rainfall for the past 7 days.
- postcodes.io: exact coordinates for UK postcodes.
- Hargreaves ET0 and day length: small formulas used when the forecast source lacks them.
"""
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

USER_AGENT = "HedgeRow/0.1 github.com/yangatheart/hedgerow"  # MET Norway requires an identifying UA
MET_URL = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
EA_STATIONS_URL = "https://environment.data.gov.uk/flood-monitoring/id/stations"
POSTCODES_URL = "https://api.postcodes.io/postcodes"
UK_POSTCODE = re.compile(r"^\s*([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\s*$", re.I)

# MET symbol_code (without _day/_night) -> WMO weather code used by Open-Meteo
_SYMBOLS = [("thunder", 95), ("heavysleet", 67), ("sleet", 66), ("heavysnow", 75), ("snow", 71),
            ("heavyrain", 65), ("lightrain", 61), ("rain", 63), ("fog", 45), ("partlycloudy", 2), ("cloudy", 3),
            ("fair", 1), ("clearsky", 0)]


def symbol_to_code(symbol: str | None) -> int | None:
    if not symbol:
        return None
    s = symbol.split("_")[0]
    if s.endswith("showers") or s.endswith("showersandthunder"):
        return 95 if "thunder" in s else 80
    for key, code in _SYMBOLS:
        if key in s:
            return code
    return None


# --------------------------------------------------------------------------- formulas

def day_length_hours(lat: float, doy: int) -> float:
    """Astronomical day length (FAO-56 eq. 34)."""
    phi = math.radians(lat)
    dec = 0.409 * math.sin(2 * math.pi * doy / 365 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(dec))))
    return 24 / math.pi * ws


def extraterrestrial_radiation_mm(lat: float, doy: int) -> float:
    """Ra (FAO-56 eq. 21), expressed as equivalent evaporation in mm/day (x 0.408)."""
    phi = math.radians(lat)
    dr = 1 + 0.033 * math.cos(2 * math.pi * doy / 365)
    dec = 0.409 * math.sin(2 * math.pi * doy / 365 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(dec))))
    ra = (24 * 60 / math.pi) * 0.0820 * dr * (
        ws * math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.sin(ws))
    return 0.408 * ra


def hargreaves_et0(tmax: float, tmin: float, lat: float, doy: int) -> float:
    """Reference evapotranspiration, mm/day (FAO-56 eq. 52). Used when ET0 isn't supplied."""
    tmean = (tmax + tmin) / 2
    return max(0.0, 0.0023 * (tmean + 17.8) * math.sqrt(max(0.0, tmax - tmin)) * extraterrestrial_radiation_mm(lat, doy))


# --------------------------------------------------------------------------- MET Norway

def _get(url, params=None, timeout=15):
    r = httpx.get(url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.json()


def met_norway_forecast(lat: float, lon: float, tz_name: str | None = None) -> dict:
    return met_to_internal(_get(MET_URL, {"lat": round(lat, 4), "lon": round(lon, 4)}), lat, tz_name)


def met_to_internal(payload: dict, lat: float, tz_name: str | None = None) -> dict:
    """Convert MET Locationforecast JSON into the Open-Meteo-shaped dict the app uses.

    MET steps are hourly for ~2.5 days, then 6-hourly; 6-hour steps are spread over 6 hourly slots.
    Sunshine is estimated from cloud cover; gusts are estimated from mean wind.
    """
    tz = ZoneInfo(tz_name) if tz_name else ZoneInfo("Europe/London")
    hourly = {"time": [], "temperature_2m": [], "relative_humidity_2m": [], "precipitation": []}
    cloud_by_hour: list[float] = []
    wind_by_hour: list[float] = []
    symbols_by_day: dict[str, list[int]] = defaultdict(list)
    series = payload["properties"]["timeseries"]
    for i, step in enumerate(series):
        t = datetime.fromisoformat(step["time"].replace("Z", "+00:00"))
        nxt = datetime.fromisoformat(series[i + 1]["time"].replace("Z", "+00:00")) if i + 1 < len(series) else t + timedelta(hours=6)
        span = max(1, min(6, round((nxt - t).total_seconds() / 3600)))
        inst = step["data"]["instant"]["details"]
        block = step["data"].get("next_1_hours") if span == 1 else step["data"].get("next_6_hours")
        block = block or step["data"].get("next_6_hours") or step["data"].get("next_12_hours") or {}
        precip = (block.get("details") or {}).get("precipitation_amount") or 0.0
        code = symbol_to_code((block.get("summary") or {}).get("symbol_code"))
        for h in range(span):
            local = (t + timedelta(hours=h)).astimezone(tz)
            hourly["time"].append(local.strftime("%Y-%m-%dT%H:00"))
            hourly["temperature_2m"].append(inst.get("air_temperature"))
            hourly["relative_humidity_2m"].append(inst.get("relative_humidity"))
            hourly["precipitation"].append(round(precip / span, 2))
            cloud_by_hour.append(inst.get("cloud_area_fraction") or 0.0)
            wind_by_hour.append((inst.get("wind_speed") or 0.0) * 3.6)  # m/s -> km/h
            if code is not None:
                symbols_by_day[local.strftime("%Y-%m-%d")].append(code)

    days = sorted({t[:10] for t in hourly["time"]})
    daily = {k: [] for k in ["time", "temperature_2m_max", "temperature_2m_min", "precipitation_sum",
                             "precipitation_probability_max", "et0_fao_evapotranspiration",
                             "relative_humidity_2m_mean", "weather_code", "sunshine_duration",
                             "wind_gusts_10m_max"]}
    for day in days:
        idx = [i for i, t in enumerate(hourly["time"]) if t.startswith(day)]
        if len(idx) < (6 if day == days[0] else 18):  # keep today (even if partial); drop a stub last day
            continue
        temps = [hourly["temperature_2m"][i] for i in idx if hourly["temperature_2m"][i] is not None]
        tmax, tmin = max(temps), min(temps)
        doy = datetime.fromisoformat(day).timetuple().tm_yday
        daylight = [i for i in idx if 6 <= int(hourly["time"][i][11:13]) < 20]
        cloud = sum(cloud_by_hour[i] for i in daylight) / max(1, len(daylight))
        codes = symbols_by_day.get(day, [])
        rain = sum(hourly["precipitation"][i] for i in idx)
        daily["time"].append(day)
        daily["temperature_2m_max"].append(round(tmax, 1))
        daily["temperature_2m_min"].append(round(tmin, 1))
        daily["precipitation_sum"].append(round(rain, 1))
        daily["precipitation_probability_max"].append(None)
        daily["et0_fao_evapotranspiration"].append(round(hargreaves_et0(tmax, tmin, lat, doy), 2))
        daily["relative_humidity_2m_mean"].append(
            round(sum(hourly["relative_humidity_2m"][i] or 0 for i in idx) / len(idx)))
        daily["weather_code"].append(max(codes) if codes else None)
        daily["sunshine_duration"].append(round(day_length_hours(lat, doy) * (1 - cloud / 100) * 3600))
        daily["wind_gusts_10m_max"].append(round(max(wind_by_hour[i] for i in idx) * 1.5, 1))

    first = series[0]
    first_block = first["data"].get("next_1_hours") or first["data"].get("next_6_hours") or {}
    cur_time = datetime.fromisoformat(first["time"].replace("Z", "+00:00")).astimezone(tz)
    inst = first["data"]["instant"]["details"]
    return {
        "provider": "met.no",
        "estimated": ["sunshine_duration", "et0_fao_evapotranspiration", "wind_gusts_10m_max"],
        "timezone": str(tz),
        "current": {
            "time": cur_time.strftime("%Y-%m-%dT%H:%M"),
            "temperature_2m": inst.get("air_temperature"),
            "relative_humidity_2m": inst.get("relative_humidity"),
            "precipitation": (first_block.get("details") or {}).get("precipitation_amount", 0.0),
            "wind_speed_10m": round((inst.get("wind_speed") or 0) * 3.6, 1),
            "weather_code": symbol_to_code((first_block.get("summary") or {}).get("symbol_code")),
        },
        "hourly": hourly,
        "daily": daily,
    }


# --------------------------------------------------------------------------- Environment Agency rain gauges

def _distance_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def measured_rain_7d(lat: float, lon: float, now: datetime | None = None) -> dict | None:
    """Rainfall measured at the nearest working EA gauge (England only) over the last 7 days.

    Returns {mm, station, distance_km, readings, since} or None if no complete record is nearby.
    """
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stations = _get(EA_STATIONS_URL, {"parameter": "rainfall", "lat": lat, "long": lon, "dist": 15}).get("items", [])
    stations = [s for s in stations if isinstance(s.get("lat"), (int, float)) and isinstance(s.get("long"), (int, float))]
    stations.sort(key=lambda s: _distance_km(lat, lon, s["lat"], s["long"]))
    for s in stations[:4]:
        items = _get(f"{EA_STATIONS_URL}/{s['notation']}/readings", {"since": since, "_limit": 2000}).get("items", [])
        result = summarize_gauge(items, s, lat, lon)
        if result:
            return result
    return None


def summarize_gauge(items: list[dict], station: dict, lat: float, lon: float) -> dict | None:
    """Sum 15-minute readings; require >= 85% of the week to be present to count as a real measurement."""
    values = [i["value"] for i in items if isinstance(i.get("value"), (int, float)) and i["value"] >= 0]
    expected = 7 * 24 * 4
    if len(values) < 0.85 * expected:
        return None
    return {
        "mm": round(sum(values), 1),
        "station": (f"EA rain gauge {station.get('notation')}" if (station.get("label") or "").lower() in ("", "rainfall station")
                    else station.get("label")),
        "station_id": station.get("notation"),
        "distance_km": round(_distance_km(lat, lon, station["lat"], station["long"]), 1),
        "coverage": round(min(1.0, len(values) / expected), 2),
    }


# --------------------------------------------------------------------------- postcodes.io

def is_uk_postcode(text: str) -> bool:
    return bool(UK_POSTCODE.match(text or ""))


def postcode_lookup(text: str) -> list[dict]:
    pc = re.sub(r"\s+", "", text).upper()
    try:
        r = _get(f"{POSTCODES_URL}/{pc}", timeout=10)["result"]
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return []
        raise
    area = r.get("admin_ward") or r.get("parish") or r.get("admin_district")
    return [{
        "label": ", ".join(p for p in [r["postcode"], area, r.get("admin_district") if area != r.get("admin_district") else None, r.get("country")] if p),
        "latitude": r["latitude"], "longitude": r["longitude"], "timezone": "Europe/London",
        "postcode": r["postcode"], "country": r.get("country"),
    }]
