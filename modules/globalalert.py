# helper functions to use location data for data outside US/north america
# K7MHI Kelly Keeton 2024

import json # pip install json
from typing import Optional
#from geopy.geocoders import Nominatim # pip install geopy
#import maidenhead as mh # pip install maidenhead
import requests # pip install requests
import bs4 as bs # pip install beautifulsoup4
#import xml.dom.minidom 
from modules.log import logger
from modules.settings import (
    urlTimeoutSeconds,
    NO_ALERTS,
    myRegionalKeysDE,
    MESSAGE_CHUNK_SIZE,
)

WARNING_NONE_MSG = "Keine Aktiven Nina oder Katwarn Meldungen"

trap_list_location_de = ("dealert", "warning")

# Official NINA API (nina.api.proxy.bund.dev no longer resolves).
NINA_API_BASE = "https://warnung.bund.de/api31"
GEMEINDEN_JSON_URL = "https://warnung.bund.de/assets/json/converted_gemeinden.json"

_gemeinden_points = None  # type: Optional[list]
# warning_id -> {"area": str, "description": str}
_warning_detail_cache: dict = {}


def _warning_id_from_item(item: dict) -> str:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    return str(payload.get("id") or item.get("id") or "").strip()


def _load_warning_detail(warning_id: str) -> dict:
    """Fetch and cache NINA warning detail. Returns dict with 'area' and 'description'."""
    if warning_id in _warning_detail_cache:
        return _warning_detail_cache[warning_id]
    result = {"area": "", "description": ""}
    try:
        url = f"{NINA_API_BASE}/warnings/{warning_id}.json"
        resp = requests.get(url, timeout=urlTimeoutSeconds)
        resp.raise_for_status()
        detail = resp.json()
        info = detail.get("info") or []
        if isinstance(info, list) and info:
            info0 = info[0]
            areas = info0.get("area") or []
            if isinstance(areas, list) and areas:
                result["area"] = areas[0].get("areaDesc", "")
            desc = (info0.get("description") or "").strip()
            instr = (info0.get("instruction") or "").strip()
            # Combine description + instruction, separated if both present
            if desc and instr:
                result["description"] = f"{desc}\nℹ️ {instr}"
            else:
                result["description"] = desc or instr
    except Exception as exc:
        logger.debug(f"NINA detail fetch failed for {warning_id}: {exc}")
    _warning_detail_cache[warning_id] = result
    return result


def _area_from_payload(item: dict) -> str:
    """Extract area directly from dashboard payload.data (no extra HTTP call)."""
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return str(data.get("area") or data.get("areaDesc") or "").strip()


def _description_from_payload(item: dict) -> str:
    """Extract description + instruction directly from dashboard payload.data."""
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    desc = str(data.get("description") or "").strip()
    instr = str(data.get("instruction") or "").strip()
    if desc and instr:
        return f"{desc}\nℹ️ {instr}"
    return desc or instr


def _fetch_warning_area(item: dict) -> str:
    """Return short areaDesc (max 60 chars). Uses payload.data first, detail API as fallback."""
    area = _area_from_payload(item)
    if not area:
        warning_id = _warning_id_from_item(item)
        if warning_id:
            area = _load_warning_detail(warning_id).get("area", "")
    if len(area) > 60:
        area = area[:59] + "…"
    return area


def _fetch_warning_description(item: dict) -> str:
    """Return full description text. Uses payload.data first, detail API as fallback."""
    desc = _description_from_payload(item)
    if not desc:
        warning_id = _warning_id_from_item(item)
        if warning_id:
            desc = _load_warning_detail(warning_id).get("description", "")
    return desc


def normalize_nina_ars(regional_key: str) -> str:
    """NINA dashboard data is only available at Kreisebene (last 7 ARS digits zeroed)."""
    key = (regional_key or "").strip()
    if not key.isdigit():
        return key
    if len(key) < 12:
        key = key.zfill(12)
    elif len(key) > 12:
        key = key[:12]
    if len(key) >= 7:
        return key[:-7] + "0000000"
    return key


def _alert_title(item: dict) -> str:
    title_obj = item.get("i18nTitle") or {}
    if isinstance(title_obj, dict):
        title = title_obj.get("de") or title_obj.get("en")
    else:
        title = None
    return (title or item.get("title") or "Warnung").strip()


def _alert_provider(item: dict) -> str:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    alert_id = str(payload.get("id") or item.get("id") or "").lower()
    if "katwarn" in alert_id:
        return "Katwarn"
    if alert_id.startswith("dwd") or ".dwd." in alert_id:
        return "DWD"
    if "mowas" in alert_id:
        return "MoWaS"
    return "NINA"


def _load_gemeinden_points() -> list[tuple[float, float, str]]:
    global _gemeinden_points
    if _gemeinden_points is not None:
        return _gemeinden_points
    try:
        response = requests.get(GEMEINDEN_JSON_URL, timeout=urlTimeoutSeconds)
        response.raise_for_status()
        raw = response.json()
    except Exception as exc:
        logger.warning(f"NINA gemeinden lookup failed: {exc}")
        _gemeinden_points = []
        return _gemeinden_points
    points: list[tuple[float, float, str]] = []
    entries = raw.values() if isinstance(raw, dict) else raw
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        rs = (entry.get("RS") or "").strip()
        pkt = entry.get("PKT") or ""
        if not rs or not pkt:
            continue
        try:
            glon, glat = (float(x) for x in pkt.split(",", 1))
        except (TypeError, ValueError):
            continue
        points.append((glat, glon, rs))
    _gemeinden_points = points
    logger.debug(f"NINA: loaded {len(points)} gemeinden for ARS lookup")
    return _gemeinden_points


def lat_lon_to_ars_kreis(lat, lon) -> Optional[str]:
    """Map coordinates to Kreis-level ARS via nearest Gemeinde centroid."""
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    points = _load_gemeinden_points()
    if not points:
        return None
    import geopy.distance

    best_rs = None
    best_m = None
    for glat, glon, rs in points:
        dist = geopy.distance.geodesic((lat_f, lon_f), (glat, glon)).m
        if best_m is None or dist < best_m:
            best_m = dist
            best_rs = rs
    if not best_rs:
        return None
    return normalize_nina_ars(best_rs)


def fetch_nina_dashboard(ars: str) -> list:
    url = f"{NINA_API_BASE}/dashboard/{ars}.json"
    response = requests.get(url, timeout=urlTimeoutSeconds)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise ValueError(f"unexpected response type {type(data).__name__}")
    return data


def format_nina_dashboard_alerts(
    data: list, max_alerts: int = 3, max_chars: int = 190
) -> str:
    lines: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        provider = _alert_provider(item)
        title = _alert_title(item)
        lines.append(f"🚨 {provider}: {title}")
        if len(lines) >= max_alerts:
            break
    if not lines:
        return NO_ALERTS
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


def get_nina_alerts_for_location(lat, lon, max_alerts: int = 3) -> str:
    """NINA/Katwarn/DWD warnings for the Kreis at the given coordinates."""
    ars = lat_lon_to_ars_kreis(lat, lon)
    if not ars:
        logger.warning(f"NINA: could not resolve ARS for {lat}, {lon}")
        return NO_ALERTS
    try:
        data = fetch_nina_dashboard(ars)
        return format_nina_dashboard_alerts(data, max_alerts=max_alerts)
    except requests.RequestException as exc:
        logger.warning(f"NINA DE alerts for {lat},{lon} (ARS {ars}): {exc}")
        return NO_ALERTS
    except Exception as exc:
        logger.warning(f"NINA DE alerts for {lat},{lon}: {exc}")
        return NO_ALERTS


def get_warnings_for_location(lat, lon) -> str:
    parts = build_warning_messages(lat, lon, from_gps=True)
    return parts[0] if parts else WARNING_NONE_MSG


def _short_coord(lat, lon, digits: int = 2) -> str:
    return f"{float(lat):.{digits}f},{float(lon):.{digits}f}"


def _short_alert_title(title: str, max_len: int = 72) -> str:
    for prefix in (
        "Amtliche WARNUNG vor ",
        "Amtliche WARNSCHWELLENWERT ",
        "Entwarnung: ",
    ):
        if title.startswith(prefix):
            title = title[len(prefix):]
            break
    title = title.strip()
    if len(title) > max_len:
        return title[: max_len - 1] + "…"
    return title


def _split_mesh_chunks(text: str, max_len: int = None) -> list[str]:
    if max_len is None:
        max_len = MESSAGE_CHUNK_SIZE
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        split_at = remaining.rfind(" ", 0, max_len)
        if split_at <= 0:
            split_at = max_len
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    return chunks


def _warning_location_line(lat, lon, from_gps: bool) -> str:
    if from_gps:
        return "Standort: ✓"
    return f"Location: ✗ Fallback {_short_coord(lat, lon)}"


def _fetch_warning_items(lat, lon) -> list[dict]:
    ars = lat_lon_to_ars_kreis(lat, lon)
    if not ars:
        return []
    try:
        data = fetch_nina_dashboard(ars)
    except Exception as exc:
        logger.warning(f"NINA DE alerts for {lat},{lon} (ARS {ars}): {exc}")
        return []
    return [item for item in data if isinstance(item, dict)]


def build_warning_messages(lat, lon, from_gps: bool, max_alerts: int = 5, include_detail: bool = False) -> list[str]:
    """
    Mesh-sized reply parts for !warning.
    include_detail=True adds the full description text (for DM responses).
    """
    header = _warning_location_line(lat, lon, from_gps)
    items = _fetch_warning_items(lat, lon)

    if not items:
        body = f"{header}\n{WARNING_NONE_MSG}"
        return _split_mesh_chunks(body)

    messages: list[str] = []
    messages.extend(_split_mesh_chunks(header))

    for item in items[:max_alerts]:
        provider = _alert_provider(item)
        title = _short_alert_title(_alert_title(item))
        area = _fetch_warning_area(item)
        line = f"🚨 {provider}: {title}"
        if area:
            line += f"\n📍 {area}"
        messages.extend(_split_mesh_chunks(line))
        if include_detail:
            desc = _fetch_warning_description(item)
            if desc:
                messages.extend(_split_mesh_chunks(desc))

    if len(items) > max_alerts:
        more = f"+{len(items) - max_alerts} weitere"
        messages.extend(_split_mesh_chunks(more))

    return messages


def get_nina_alerts():
    alerts = []
    seen_ars: set[str] = set()
    seen_ids: set[str] = set()  # deduplicate across ARS regions by warning ID
    try:
        for regional_key in myRegionalKeysDE:
            raw = (regional_key or "").strip()
            if not raw:
                continue
            ars = normalize_nina_ars(raw)
            if ars in seen_ars:
                continue
            seen_ars.add(ars)
            url = f"{NINA_API_BASE}/dashboard/{ars}.json"
            try:
                response = requests.get(url, timeout=urlTimeoutSeconds)
                response.raise_for_status()
                data = response.json()
            except requests.RequestException as exc:
                logger.warning(f"NINA DE alerts for {raw} (ARS {ars}): {exc}")
                continue
            if not isinstance(data, list):
                logger.warning(f"NINA DE alerts for {raw}: unexpected response type {type(data).__name__}")
                continue
            for item in data:
                if not isinstance(item, dict):
                    continue
                payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
                warning_id = str(payload.get("id") or item.get("id") or "")
                if warning_id and warning_id in seen_ids:
                    continue
                if warning_id:
                    seen_ids.add(warning_id)
                provider = _alert_provider(item)
                title = _alert_title(item)
                area = _fetch_warning_area(item)
                line = f"🚨 {provider}: {title}"
                if area:
                    line += f"\n📍 {area}"
                alerts.append(line)
        return "\n".join(alerts) if alerts else NO_ALERTS
    except Exception as e:
        logger.warning("Error getting NINA DE alerts: " + str(e))
        return NO_ALERTS

def get_wxUKgov():
    # get UK weather warnings, these look icky
    url = 'https://www.metoffice.gov.uk/weather/guides/rss'
    url = 'https://www.metoffice.gov.uk/public/data/PWSCache/WarningsRSS/Region/nw'
    try:
        # get UK weather warnings
        url = 'https://www.metoffice.gov.uk/weather/guides/rss'
        response = requests.get(url, timeout=urlTimeoutSeconds)
        soup = bs.BeautifulSoup(response.content, 'xml')
        
        items = soup.find_all('item')
        alerts = []
        
        for item in items:
            title = item.find('title').get_text(strip=True)
            description = item.find('description').get_text(strip=True)
            alerts.append(f"🚨 {title}: {description}")
        
        return "\n".join(alerts) if alerts else NO_ALERTS
    except Exception as e:
        logger.warning("Error getting UK weather warnings: " + str(e))
        return NO_ALERTS
    
    
def get_floodUKgov():
    # get UK flood warnings, there is so much I need a locals help
    url = 'https://environment.data.gov.uk/flood-widgets/rss/feed-England.xml'
    
    return NO_ALERTS

def get_crimeUKgov(lat, lon):
    """
    Fetches recent street crime data from UK Police API for given lat/lon.
    Returns a summary string or NO_ALERTS. -- pay for use?
    """
    date = datetime.datetime.now().strftime("%Y-%m")
    url = f'https://data.police.uk/api/crimes-street/all-crime?date={date}&lat={lat}&lng={lon}'
    try:
        response = requests.get(url, timeout=urlTimeoutSeconds)
        if not response.ok or not response.text.strip():
            return NO_ALERTS
        crimes = response.json()
        if not crimes:
            return NO_ALERTS
        # Summarize the first few crimes
        summaries = []
        for crime in crimes[:3]:
            category = crime.get("category", "Unknown")
            outcome = crime.get("outcome_status", {}).get("category", "No outcome")
            location = crime.get("location", {}).get("street", {}).get("name", "Unknown location")
            summaries.append(f"{category.title()} at {location} ({outcome})")
        return "\n".join(summaries)
    except Exception as e:
        logger.warning(f"Error fetching UK crime data: {e}")
        return NO_ALERTS

def get_crime_stopsUKgov(lat, lon):
    """
    Fetches recent stop-and-search data from UK Police API for given lat/lon.
    Returns a summary string or NO_ALERTS. -- pay for use?
    """
    date = datetime.datetime.now().strftime("%Y-%m")
    url = f'https://data.police.uk/api/stops-street?date={date}&lat={lat}&lng={lon}'
    try:
        response = requests.get(url, timeout=urlTimeoutSeconds)
        if not response.ok or not response.text.strip():
            return NO_ALERTS
        stops = response.json()
        if not stops:
            return NO_ALERTS
        # Summarize the first few stops
        summaries = []
        for stop in stops[:3]:  # Limit to first 3 stops for brevity
            summary = (
                f"Date: {stop.get('datetime', 'N/A')}, "
                f"Outcome: {stop.get('outcome', 'N/A')}, "
                f"Ethnicity: {stop.get('self_defined_ethnicity', 'N/A')}, "
                f"Gender: {stop.get('gender', 'N/A')}, "
                f"Location: {stop.get('location', {}).get('street', {}).get('name', 'N/A')}"
            )
            summaries.append(summary)
        return "\n".join(summaries)
    except Exception as e:
        return NO_ALERTS
