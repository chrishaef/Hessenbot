# Short Open-Meteo commands: !uv, !regen, !blitz (+ live strikes DMI / Blitzortung)
from __future__ import annotations

import json
import math
import time
from datetime import datetime

import requests

from modules.log import logger
from modules.settings import ERROR_FETCHING_DATA, NO_DATA_NOGPS
from modules.wx_meteo import format_wx_info_header, get_weather_data

trap_list_wx_extra = ("uv", "regen", "blitz")

_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_DMI_LIGHTNING_URL = (
    "https://opendataapi.dmi.dk/v2/lightningdata/collections/observation/items"
)
_BLITZORTUNG_URL = "https://data.blitzortung.org/Data/Protected/last_strikes.php"
_HTTP_HEADERS = {"User-Agent": "Hessenbot/1.0 (Meshtastic; lightning)"}
_THUNDER_WMO = frozenset({95, 96, 99})


def _coords_ok(lat, lon) -> tuple[float, float] | None:
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if int(lat_f) == 0 and int(lon_f) == 0:
        return None
    return lat_f, lon_f


def _uv_risk_de(uv: float) -> str:
    if uv < 3:
        return "niedrig"
    if uv < 6:
        return "mäßig"
    if uv < 8:
        return "hoch"
    if uv < 11:
        return "sehr hoch"
    return "extrem"


def _hour_label(iso_time: str) -> str:
    try:
        return datetime.fromisoformat(iso_time).strftime("%H:%M")
    except ValueError:
        return iso_time[-5:] if len(iso_time) >= 5 else iso_time


def get_uv(lat=0, lon=0) -> str:
    coords = _coords_ok(lat, lon)
    if not coords:
        return NO_DATA_NOGPS
    lat_f, lon_f = coords
    try:
        data = get_weather_data(
            _FORECAST_URL,
            {
                "latitude": lat_f,
                "longitude": lon_f,
                "daily": "uv_index_max,uv_index_clear_sky_max",
                "timezone": "auto",
                "forecast_days": 2,
            },
        )
        daily = data["daily"]
        today = float(daily["uv_index_max"][0])
        tomorrow = float(daily["uv_index_max"][1]) if len(daily["uv_index_max"]) > 1 else today
        clear = daily.get("uv_index_clear_sky_max")
        clear_today = float(clear[0]) if clear else today
    except Exception as e:
        logger.error(f"Error fetching UV data: {e}")
        return ERROR_FETCHING_DATA

    header = format_wx_info_header(lat_f, lon_f).replace("WX INFO", "UV")
    body = (
        f"Heute max {today:.1f} ({_uv_risk_de(today)}), "
        f"Morgen {tomorrow:.1f}. "
        f"Klarer Himmel: {clear_today:.1f}."
    )
    return f"{header}\n{body}"


def get_regen(lat=0, lon=0, hours: int = 18) -> str:
    coords = _coords_ok(lat, lon)
    if not coords:
        return NO_DATA_NOGPS
    lat_f, lon_f = coords
    hours = max(6, min(24, int(hours)))
    try:
        data = get_weather_data(
            _FORECAST_URL,
            {
                "latitude": lat_f,
                "longitude": lon_f,
                "hourly": "precipitation,precipitation_probability,weather_code",
                "timezone": "auto",
                "forecast_hours": hours,
            },
        )
        hourly = data["hourly"]
        times = hourly["time"]
        precip = hourly["precipitation"]
        prob = hourly["precipitation_probability"]
    except Exception as e:
        logger.error(f"Error fetching rain data: {e}")
        return ERROR_FETCHING_DATA

    header = format_wx_info_header(lat_f, lon_f).replace("WX INFO", "REGEN")
    lines: list[str] = []
    total = 0.0
    max_prob = 0
    for i, t in enumerate(times):
        mm = float(precip[i] or 0)
        p = int(prob[i] or 0)
        total += mm
        if p > max_prob:
            max_prob = p
        if mm >= 0.1 or p >= 35:
            lines.append(f"{_hour_label(t)} {mm:.1f}mm {p}%")

    if not lines:
        summary = f"Nächste {hours}h: kein relevanter Regen (max {max_prob}% Wahrscheinlichkeit)."
    else:
        shown = lines[:8]
        more = f" (+{len(lines) - 8})" if len(lines) > 8 else ""
        summary = f"Nächste {hours}h:\n" + "\n".join(shown) + more
        summary += f"\nSumme ~{total:.1f} mm."

    return f"{header}\n{summary}"


def _blitz_settings():
    import modules.settings as st

    return (
        getattr(st, "blitz_live_data", True),
        max(25, min(400, int(getattr(st, "blitz_radius_km", 150)))),
        getattr(st, "blitzortung_user", "") or "",
        getattr(st, "blitzortung_password", "") or "",
    )


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p = math.pi / 180.0
    a = (
        0.5
        - math.cos((lat2 - lat1) * p) / 2
        + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    )
    return 2 * r * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def _compass_dir(lat1: float, lon1: float, lat2: float, lon2: float) -> str:
    """8-Punkt-Himmelsrichtung von (lat1,lon1) zum Ziel (lat2,lon2)."""
    p = math.pi / 180.0
    dlon = (lon2 - lon1) * p
    y = math.sin(dlon) * math.cos(lat2 * p)
    x = math.cos(lat1 * p) * math.sin(lat2 * p) - math.sin(lat1 * p) * math.cos(lat2 * p) * math.cos(dlon)
    deg = (math.degrees(math.atan2(y, x)) + 360) % 360
    dirs = ("N", "NO", "O", "SO", "S", "SW", "W", "NW")
    return dirs[int((deg + 22.5) // 45) % 8]


def _potential_word(max_lp: float) -> str:
    """Open-Meteo lightning_potential (J/kg) in Klartext."""
    if max_lp >= 2.0:
        return "hoch"
    if max_lp >= 0.8:
        return "erhöht"
    return "gering"


def _bbox_for_radius(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """west, south, east, north for DMI/Blitzortung."""
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.35, math.cos(math.radians(lat))))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


def _strike_records_from_features(
    features: list, lat: float, lon: float, radius_km: float
) -> list[dict]:
    out: list[dict] = []
    now = time.time()
    for feat in features:
        try:
            slon, slat = feat["geometry"]["coordinates"]
            km = _haversine_km(lat, lon, float(slat), float(slon))
        except (KeyError, TypeError, ValueError):
            continue
        if km > radius_km:
            continue
        props = feat.get("properties") or {}
        observed = props.get("observed") or ""
        age_min = None
        if observed:
            try:
                obs_dt = datetime.fromisoformat(observed.replace("Z", "+00:00"))
                age_min = max(0, int((now - obs_dt.timestamp()) / 60))
            except ValueError:
                pass
        out.append(
            {
                "lat": float(slat),
                "lon": float(slon),
                "km": km,
                "age_min": age_min,
                "dir": _compass_dir(lat, lon, float(slat), float(slon)),
            }
        )
    out.sort(key=lambda s: s["km"])
    return out


def _fetch_dmi_strikes(lat: float, lon: float, radius_km: float) -> tuple[list[dict], str]:
    west, south, east, north = _bbox_for_radius(lat, lon, radius_km)
    bbox = f"{west},{south},{east},{north}"
    for period, label in (
        ("latest-hour", "60 Min"),
        ("latest-10-minutes", "10 Min"),
    ):
        try:
            response = requests.get(
                _DMI_LIGHTNING_URL,
                params={
                    "bbox": bbox,
                    "period": period,
                    "limit": 500,
                    "sortorder": "observed,DESC",
                },
                timeout=25,
                headers=_HTTP_HEADERS,
            )
            response.raise_for_status()
            features = response.json().get("features") or []
        except Exception as e:
            logger.debug(f"DMI lightning ({period}): {e}")
            continue
        strikes = _strike_records_from_features(features, lat, lon, radius_km)
        if strikes:
            return strikes, f"DMI, {label}"
    return [], "DMI, 60 Min"


def _fetch_blitzortung_strikes(
    lat: float, lon: float, radius_km: float, user: str, password: str
) -> list[dict]:
    west, south, east, north = _bbox_for_radius(lat, lon, radius_km * 1.2)
    try:
        response = requests.get(
            _BLITZORTUNG_URL,
            params={
                "number": 500,
                "west": west,
                "east": east,
                "south": south,
                "north": north,
                "sig": 0,
            },
            auth=(user, password),
            timeout=25,
            headers=_HTTP_HEADERS,
        )
        response.raise_for_status()
    except Exception as e:
        logger.debug(f"Blitzortung API: {e}")
        return []

    now_ns = time.time_ns()
    out: list[dict] = []
    for line in response.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            slat = float(row["lat"])
            slon = float(row["lon"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        km = _haversine_km(lat, lon, slat, slon)
        if km > radius_km:
            continue
        age_min = None
        try:
            age_min = max(0, int((now_ns - int(row["time"])) / 1e9 / 60))
        except (KeyError, TypeError, ValueError):
            pass
        out.append(
            {
                "lat": slat,
                "lon": slon,
                "km": km,
                "age_min": age_min,
                "dir": _compass_dir(lat, lon, slat, slon),
            }
        )
    out.sort(key=lambda s: s["km"])
    return out


def _format_live_blitz(strikes: list[dict], source: str, radius_km: int) -> str:
    if not strikes:
        return f"Live ({source}): keine Einschläge <{radius_km} km."
    n = len(strikes)
    nearest = strikes[0]
    age = nearest.get("age_min")
    age_s = f", vor {age} min" if age is not None else ""
    direction = nearest.get("dir")
    dir_s = f" {direction}" if direction else ""
    line = f"Live ({source}): {n} Einschläge <{radius_km} km."
    line += f"\nNächster: {nearest['km']:.0f} km{dir_s}{age_s}."
    if n > 1:
        farthest = strikes[-1]
        line += f" Weitester: {farthest['km']:.0f} km."
    # Letzter (zeitlich neuester) Einschlag, sofern Zeitdaten vorliegen und er
    # nicht ohnehin schon der nächste ist.
    timed = [s for s in strikes if s.get("age_min") is not None]
    if timed:
        latest = min(timed, key=lambda s: s["age_min"])
        if latest is not nearest:
            l_dir = latest.get("dir")
            l_dir_s = f" {l_dir}" if l_dir else ""
            line += f"\nLetzter: {latest['km']:.0f} km{l_dir_s}, vor {latest['age_min']} min."
    return line


def _get_blitz_forecast(lat_f: float, lon_f: float, hours: int = 24) -> tuple[str, bool]:
    hours = max(12, min(48, int(hours)))
    data = get_weather_data(
        _FORECAST_URL,
        {
            "latitude": lat_f,
            "longitude": lon_f,
            "hourly": "weather_code,precipitation_probability,cape,lightning_potential",
            "timezone": "auto",
            "forecast_hours": hours,
        },
    )
    hourly = data["hourly"]
    times = hourly["time"]
    codes = hourly["weather_code"]
    cape = hourly.get("cape") or []
    lp = hourly.get("lightning_potential") or []

    storm_hours: list[str] = []
    max_lp = 0.0
    for i, t in enumerate(times):
        code = int(codes[i] or 0)
        lpi = float(lp[i] if i < len(lp) else 0)
        cp = float(cape[i] if i < len(cape) else 0)
        if lpi > max_lp:
            max_lp = lpi
        prob_h = int(hourly.get("precipitation_probability", [0] * len(times))[i] or 0)
        if code in _THUNDER_WMO or lpi >= 0.15 or (cp >= 800 and prob_h >= 40):
            storm_hours.append(_hour_label(t))

    if storm_hours:
        risk = f"Modell {hours}h: Risiko {storm_hours[0]}"
        if len(storm_hours) > 1:
            risk += f"–{storm_hours[-1]}"
        risk += f", Potenzial {_potential_word(max_lp)}."
        return risk, True
    return f"Modell {hours}h: kein Gewitter-Risiko.", False


def get_blitz(lat=0, lon=0, hours: int = 24) -> str:
    """Live-Einschläge (DMI / optional Blitzortung) + kurze Modell-Vorhersage."""
    coords = _coords_ok(lat, lon)
    if not coords:
        return NO_DATA_NOGPS
    lat_f, lon_f = coords

    header = format_wx_info_header(lat_f, lon_f).replace("WX INFO", "BLITZ")

    live_on, radius_km, bo_user, bo_pass = _blitz_settings()
    strikes: list[dict] = []
    source = ""
    if live_on:
        if bo_user and bo_pass:
            strikes = _fetch_blitzortung_strikes(lat_f, lon_f, radius_km, bo_user, bo_pass)
            if strikes:
                source = "Blitzortung.org"
        if not strikes:
            strikes, source = _fetch_dmi_strikes(lat_f, lon_f, radius_km)

    try:
        forecast, has_risk = _get_blitz_forecast(lat_f, lon_f, hours)
    except Exception as e:
        logger.error(f"Error fetching blitz forecast: {e}")
        forecast, has_risk = "Modell-Vorhersage nicht verfügbar.", None

    # Kompakter Ruhig-Fall: Live aktiv, keine Einschläge, kein Modell-Risiko
    if live_on and not strikes and has_risk is False:
        return f"{header}\nKeine Einschläge <{radius_km} km · {forecast}"

    parts = [header]
    if live_on:
        parts.append(_format_live_blitz(strikes, source, radius_km))
    parts.append(forecast)
    return "\n".join(parts)
