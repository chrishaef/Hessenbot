# Deutsche Nutzertexte — Hessenbot für Meshhessen

BOT_NAME = "Hessenbot"
MESH_ORG = "Meshhessen"
BBS_WEB_ADMIN_SENDER = f"{BOT_NAME} ({MESH_ORG} Web-Admin)"
HELP_PREFIX = f"{BOT_NAME} ({MESH_ORG}) · !cmd?: "

WMO_WEATHER_DE = {
    0: "Klar",
    1: "Überwiegend bewölkt",
    2: "Teilweise bewölkt",
    3: "Bedeckt",
    5: "Dunst",
    10: "Nebel",
    45: "Nebel",
    48: "Gefrierender Nebel",
    51: "Nieselregen leicht",
    53: "Nieselregen mäßig",
    55: "Nieselregen stark",
    56: "Gefrierender Nieselregen leicht",
    57: "Gefrierender Nieselregen mäßig",
    61: "Regen leicht",
    63: "Regen mäßig",
    65: "Regen stark",
    66: "Gefrierender Regen leicht",
    67: "Gefrierender Regen stark",
    71: "Schnee leicht",
    73: "Schnee mäßig",
    75: "Schnee stark",
    77: "Schneegriesel",
    78: "Eiskristalle",
    79: "Eisregen",
    80: "Regenschauer leicht",
    81: "Regenschauer mäßig",
    82: "Regenschauer stark",
    85: "Schneeschauer",
    86: "Schneeschauer stark",
    95: "Gewitter",
    96: "Gewitter mit Hagel",
    97: "Starkes Gewitter",
    99: "Schweres Gewitter mit Hagel",
}


def wmo_weather_de(code: int) -> str:
    return WMO_WEATHER_DE.get(code, "Unbekannt")


def wind_direction_de(degrees: float) -> str:
    if degrees < 22.5:
        return "N"
    if degrees < 67.5:
        return "NO"
    if degrees < 112.5:
        return "O"
    if degrees < 157.5:
        return "SO"
    if degrees < 202.5:
        return "S"
    if degrees < 247.5:
        return "SW"
    if degrees < 292.5:
        return "W"
    if degrees < 337.5:
        return "NW"
    return "N"


WEEKDAY_DE_SHORT = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")

# N2YO liefert englische Himmelsrichtungen (16-Punkt)
COMPASS_EN_TO_DE = {
    "N": "N",
    "NNE": "NNO",
    "NE": "NO",
    "ENE": "ONO",
    "E": "O",
    "ESE": "OSO",
    "SE": "SO",
    "SSE": "SSO",
    "S": "S",
    "SSW": "SSW",
    "SW": "SW",
    "WSW": "WSW",
    "W": "W",
    "WNW": "WNW",
    "NW": "NW",
    "NNW": "NNW",
}


def compass_label_de(label: str) -> str:
    if not label:
        return "?"
    return COMPASS_EN_TO_DE.get(label.strip().upper(), label.strip().upper())


def format_mesh_local_time(ts_unix: float) -> str:
    from datetime import datetime

    dt = datetime.fromtimestamp(ts_unix)
    wd = WEEKDAY_DE_SHORT[dt.weekday()]
    return f"{wd} {dt.day:02d}.{dt.month:02d}. {dt.hour:02d}:{dt.minute:02d}"


def duration_seconds_de(seconds: float) -> str:
    sec = int(round(seconds))
    if sec < 60:
        return f"{sec} Sek."
    minutes = sec // 60
    if minutes < 60:
        return f"{minutes} Min."
    hours, rem = divmod(minutes, 60)
    if rem:
        return f"{hours} Std. {rem} Min."
    return f"{hours} Std."
