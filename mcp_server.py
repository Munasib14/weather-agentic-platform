"""
Local MCP server (stdio transport) exposing the weather platform's tools.

Tools
-----
geocode_location     -> OpenStreetMap Nominatim   (place name -> coordinates)
get_forecast         -> Open-Meteo                (current conditions)
get_daily_forecast   -> Open-Meteo                (multi-day outlook)
assess_weather_risk  -> deterministic rules       (drone / travel risk)

IMPORTANT: with stdio, stdout is the protocol channel. Only log to stderr.
"""
import os
import sys
import json
import time
import asyncio
import httpx

# Works with the new v2 MCPServer if present, otherwise falls back to FastMCP (v1.x)
try:
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:
    from mcp.server.fastmcp import FastMCP as _Server

mcp = _Server("WeatherGateway")

NOMINATIM_URL = os.getenv("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
OPEN_METEO_URL = os.getenv("OPEN_METEO_URL", "https://api.open-meteo.com/v1/forecast")
USER_AGENT = os.getenv(
    "NOMINATIM_USER_AGENT",
    "WeatherPlatformIntelligenceApp/2026.1.0 (contact: developer@domain.com)",
)

# Nominatim policy: max ~1 request/second. Enforced per server process.
_nominatim_lock = asyncio.Lock()
_last_nominatim_call = 0.0


def _log(msg: str) -> None:
    print(f"[MCP] {msg}", file=sys.stderr, flush=True)


# ------------------------------------------------------------------
# TOOL 1: geocoding (Nominatim)
# ------------------------------------------------------------------
@mcp.tool()
async def geocode_location(query: str, limit: int = 3) -> str:
    """Convert a place name into coordinates using OpenStreetMap Nominatim.

    Returns JSON: {"query", "results": [{"display_name", "latitude", "longitude", "type"}]}.
    If "results" is empty, try another spelling, the local/English name, or add a
    country/state (e.g. "Pune, India") and call again.
    """
    global _last_nominatim_call
    limit = max(1, min(int(limit), 5))
    _log(f"geocode_location(query={query!r}, limit={limit})")

    async with _nominatim_lock:
        wait = 1.1 - (time.monotonic() - _last_nominatim_call)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": USER_AGENT}) as client:
                resp = await client.get(
                    NOMINATIM_URL, params={"q": query, "format": "json", "limit": limit}
                )
        except Exception as e:
            return json.dumps({"error": f"Nominatim request failed: {type(e).__name__}: {e}"})
        finally:
            _last_nominatim_call = time.monotonic()

    if resp.status_code != 200:
        return json.dumps({"error": f"Nominatim returned HTTP {resp.status_code}"})

    try:
        items = resp.json()
    except Exception:
        return json.dumps({"error": "Nominatim returned invalid JSON"})

    results = [
        {
            "display_name": it.get("display_name"),
            "latitude": float(it["lat"]),
            "longitude": float(it["lon"]),
            "type": it.get("type"),
        }
        for it in items
        if "lat" in it and "lon" in it
    ]
    payload = {"query": query, "results": results}
    if not results:
        payload["hint"] = "No match. Try another spelling, the English name, or add a country/state."
    return json.dumps(payload)


# ------------------------------------------------------------------
# TOOL 2: current weather (Open-Meteo)
# ------------------------------------------------------------------
@mcp.tool()
async def get_forecast(latitude: float, longitude: float) -> str:
    """Get CURRENT weather (temperature, humidity, wind, precipitation) for coordinates
    from Open-Meteo. Returns JSON."""
    _log(f"get_forecast({latitude}, {longitude})")
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(OPEN_METEO_URL, params=params)
    except Exception as e:
        return json.dumps({"error": f"Open-Meteo request failed: {type(e).__name__}: {e}"})
    if resp.status_code != 200:
        return json.dumps({"error": f"Open-Meteo returned HTTP {resp.status_code}"})

    cur = resp.json().get("current", {})
    return json.dumps({
        "source": "Open-Meteo",
        "latitude": latitude,
        "longitude": longitude,
        "time": cur.get("time"),
        "temperature_c": cur.get("temperature_2m"),
        "humidity_pct": cur.get("relative_humidity_2m"),
        "wind_speed_kmh": cur.get("wind_speed_10m"),
        "precipitation_mm": cur.get("precipitation"),
    })


# ------------------------------------------------------------------
# TOOL 3: multi-day outlook (Open-Meteo)
# ------------------------------------------------------------------
@mcp.tool()
async def get_daily_forecast(latitude: float, longitude: float, days: int = 3) -> str:
    """Get a DAILY outlook (max/min temperature, total precipitation, max wind) for the
    next 1-7 days from Open-Meteo. Use for 'tomorrow', 'this weekend', 'next few days'."""
    days = max(1, min(int(days), 7))
    _log(f"get_daily_forecast({latitude}, {longitude}, days={days})")
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
        "forecast_days": days,
        "timezone": "auto",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(OPEN_METEO_URL, params=params)
    except Exception as e:
        return json.dumps({"error": f"Open-Meteo request failed: {type(e).__name__}: {e}"})
    if resp.status_code != 200:
        return json.dumps({"error": f"Open-Meteo returned HTTP {resp.status_code}"})

    d = resp.json().get("daily", {})
    rows = []
    for i, day in enumerate(d.get("time", [])):
        rows.append({
            "date": day,
            "temp_max_c": d.get("temperature_2m_max", [None] * 99)[i],
            "temp_min_c": d.get("temperature_2m_min", [None] * 99)[i],
            "precipitation_mm": d.get("precipitation_sum", [None] * 99)[i],
            "wind_max_kmh": d.get("wind_speed_10m_max", [None] * 99)[i],
        })
    return json.dumps({"source": "Open-Meteo", "latitude": latitude, "longitude": longitude, "days": rows})


# ------------------------------------------------------------------
# TOOL 4: deterministic risk rules
# ------------------------------------------------------------------
@mcp.tool()
async def assess_weather_risk(
    temperature_c: float,
    wind_speed_kmh: float,
    precipitation_mm: float,
    humidity_pct: float = 50.0,
) -> str:
    """Rule-based drone-flight / outdoor-travel risk assessment for given conditions.
    Returns JSON: {"risk_level": LOW|MODERATE|HIGH, "drone_flight": OK|CAUTION|NO-GO, "alerts": [...]}.
    Heuristic thresholds, not official aviation guidance."""
    _log(f"assess_weather_risk(T={temperature_c}, wind={wind_speed_kmh}, precip={precipitation_mm}, hum={humidity_pct})")
    alerts, level = [], 0

    if wind_speed_kmh >= 40:
        alerts.append(f"Wind {wind_speed_kmh} km/h exceeds the safe limit for most consumer drones (~38 km/h)")
        level = max(level, 2)
    elif wind_speed_kmh >= 25:
        alerts.append(f"Strong/gusty wind ({wind_speed_kmh} km/h): flying is difficult")
        level = max(level, 1)

    if precipitation_mm >= 2.5:
        alerts.append(f"Heavy precipitation ({precipitation_mm} mm): unsafe for flying and reduces road safety")
        level = max(level, 2)
    elif precipitation_mm >= 0.1:
        alerts.append(f"Rain ({precipitation_mm} mm): most consumer drones are not waterproof")
        level = max(level, 1)

    if temperature_c >= 42 or temperature_c <= -10:
        alerts.append(f"Extreme temperature ({temperature_c}°C): battery and health risk")
        level = max(level, 2)
    elif temperature_c >= 36 or temperature_c <= 0:
        alerts.append(f"Temperature ({temperature_c}°C) may affect battery performance and comfort")
        level = max(level, 1)

    if humidity_pct >= 90:
        alerts.append(f"Very high humidity ({humidity_pct}%): possible fog or reduced visibility")
        level = max(level, 1)

    return json.dumps({
        "risk_level": ["LOW", "MODERATE", "HIGH"][level],
        "drone_flight": ["OK", "CAUTION", "NO-GO"][level],
        "alerts": alerts or ["All Clear"],
    })


if __name__ == "__main__":
    mcp.run(transport="stdio")