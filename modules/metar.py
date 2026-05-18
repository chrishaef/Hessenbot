# METAR for nearest airport or by ICAO (aviationweather.gov API)
import math
import re

import requests
from modules.log import logger
from modules.settings import ERROR_FETCHING_DATA, NO_DATA_NOGPS

trap_list_metar = ("metar",)

AWC_METAR_URL = "https://aviationweather.gov/api/data/metar"
AWC_USER_AGENT = "Hessenbot/1.0 (Meshtastic; METAR)"
# minLat, minLon, maxLat, maxLon — search radius in degrees, expanded until hits
_BBOX_DELTAS = (0.35, 0.7, 1.4, 2.8, 5.6, 11.0)
_ICAO_RE = re.compile(r"^[A-Z]{4}$")

def get_metar_decode_help() -> str:
    """Erklärung METAR-Aufbau für !metar? (Zeilen → Chunking im Mesh)."""
    return (
        "METAR — Aufbau (Beispiel):\n"
        "METAR EDDF 182120Z AUTO VRB02KT CAVOK 09/08 Q1016 NOSIG\n"
        "METAR/SPECI = Routine / besondere Meldung\n"
        "EDDF = ICAO-Flughafen\n"
        "182120Z = Tag+Zeit UTC (18., 21:20Z)\n"
        "AUTO/KOR = automatisch / korrigiert\n"
        "Wind: dddssKT (27015KT) oder VRB02KT\n"
        "Sicht: 9999 (m) oder CAVOK\n"
        "Wolken: FEW/SCT/BKN/OVC + Höhe (ft)\n"
        "09/08 = Temperatur/Taupunkt °C\n"
        "Q1016 = QNH hPa | A3001 = Altimeter inHg\n"
        "NOSIG/TEMPO/BECMG = Trend\n"
        "Befehle: !metar | !metar EDDF"
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


def _station_label(name: str | None) -> str:
    if not name:
        return ""
    return name.split(",")[0].strip()


def normalize_icao(code: str) -> str | None:
    if not code:
        return None
    icao = code.strip().upper()
    if _ICAO_RE.match(icao):
        return icao
    return None


def parse_metar_icao_from_message(message: str) -> str | None:
    """Extract ICAO from '!metar EDDF' / 'metar eddf' (first arg after command)."""
    if not message:
        return None
    text = message.strip()
    if text.endswith("?"):
        return None
    parts = text.split()
    if len(parts) < 2:
        return None
    cmd = parts[0].lstrip("!").lower()
    if cmd != "metar":
        return None
    return normalize_icao(parts[1])


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


def format_metar_header_icao(icao: str, station_name: str | None) -> str:
    label = _station_label(station_name) or icao
    return f"METAR @ {icao} {label}"


def _format_metar_response(header: str, station: dict) -> str:
    raw = (station.get("rawOb") or "").strip()
    if not raw:
        return ERROR_FETCHING_DATA
    return f"{header}\n{raw}"


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


def _fetch_metar_by_icao(icao: str) -> dict | None:
    response = requests.get(
        AWC_METAR_URL,
        params={"format": "json", "ids": icao},
        timeout=25,
        headers={"User-Agent": AWC_USER_AGENT},
    )
    if response.status_code == 204 or not response.text.strip():
        return None
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list) and data:
        return data[0]
    return None


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


def get_metar_by_icao(icao: str) -> str:
    code = normalize_icao(icao)
    if not code:
        return "Ungültiger ICAO-Code (4 Buchstaben, z.B. EDDF)."

    try:
        station = _fetch_metar_by_icao(code)
    except Exception as e:
        logger.error(f"Error fetching METAR for {code}: {e}")
        return ERROR_FETCHING_DATA

    if not station:
        return f"Kein METAR für {code} verfügbar."

    icao_out = station.get("icaoId") or station.get("id") or code
    header = format_metar_header_icao(icao_out, station.get("name"))
    return _format_metar_response(header, station)


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
    header = format_metar_header(lat_f, lon_f, icao, station.get("name"), dist_km)
    return _format_metar_response(header, station)
