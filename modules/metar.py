# METAR for nearest airport (aviationweather.gov API)
import math

trap_list_metar = ("metar",)
import requests
from modules.log import logger
from modules.settings import ERROR_FETCHING_DATA, NO_DATA_NOGPS

AWC_METAR_URL = "https://aviationweather.gov/api/data/metar"
AWC_USER_AGENT = "Hessenbot/1.0 (Meshtastic; METAR)"
# minLat, minLon, maxLat, maxLon — search radius in degrees, expanded until hits
_BBOX_DELTAS = (0.35, 0.7, 1.4, 2.8, 5.6, 11.0)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p = math.pi / 180.0
    a = (
        0.5
        - math.cos((lat2 - lat1) * p) / 2
        + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    )
    return 2 * r * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def _station_label(name: str | None) -> str:
    if not name:
        return ""
    return name.split(",")[0].strip()


def format_metar_header(lat, lon, icao: str, station_name: str, dist_km: float) -> str:
    """Erste Zeile für !metar: QTH wie bei !wx, nächster Flugplatz."""
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return f"METAR @ {icao}"
    qth = ""
    if int(lat_f) != 0 or int(lon_f) != 0:
        try:
            from modules.locationdata import get_place_name

            place = get_place_name(lat_f, lon_f)
            if place and place != "?":
                qth = f"QTH {place} | "
        except Exception:
            pass
    label = _station_label(station_name) or icao
    return f"METAR @ {qth}{icao} {label} ({dist_km:.0f} km)"


def _fetch_metar_bbox(min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> list:
    bbox = f"{min_lat:.4f},{min_lon:.4f},{max_lat:.4f},{max_lon:.4f}"
    response = requests.get(
        AWC_METAR_URL,
        params={"format": "json", "bbox": bbox},
        timeout=25,
        headers={"User-Agent": AWC_USER_AGENT},
    )
    if response.status_code == 204 or not response.text.strip():
        return []
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else []


def _nearest_metar_station(lat: float, lon: float) -> tuple[dict, float] | None:
    best = None
    best_km = None
    for delta in _BBOX_DELTAS:
        stations = _fetch_metar_bbox(lat - delta, lon - delta, lat + delta, lon + delta)
        if not stations:
            continue
        for st in stations:
            try:
                slat = float(st["lat"])
                slon = float(st["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            km = _haversine_km(lat, lon, slat, slon)
            if best_km is None or km < best_km:
                best_km = km
                best = st
        if best is not None:
            return best, best_km
    return None


def get_metar(lat=0, lon=0) -> str:
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        lat_f, lon_f = 0.0, 0.0
    if int(lat_f) == 0 and int(lon_f) == 0:
        return NO_DATA_NOGPS

    try:
        found = _nearest_metar_station(lat_f, lon_f)
    except Exception as e:
        logger.error(f"Error fetching METAR data: {e}")
        return ERROR_FETCHING_DATA

    if not found:
        return "Kein METAR-Flugplatz in der Nähe gefunden."

    station, dist_km = found
    icao = station.get("icaoId") or station.get("id") or "?"
    raw = (station.get("rawOb") or "").strip()
    if not raw:
        return ERROR_FETCHING_DATA

    header = format_metar_header(lat_f, lon_f, icao, station.get("name"), dist_km)
    return f"{header}\n{raw}"
