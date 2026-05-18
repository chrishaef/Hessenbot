#!/usr/bin/env python3
# Deutsche Tooltips für Admin-Einstellungen (aus config.template + Kurztexte).

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Tuple

from modules.paths import path_in_repo

TooltipKey = Tuple[str, str]

# Explizite deutsche Erklärungen (Vorrang vor Template-Kommentar)
TOOLTIP_DE: Dict[TooltipKey, str] = {
    ("interface", "type"): "Verbindungstyp: serial (USB), tcp (IP/Hostname) oder ble.",
    ("interface", "hostname"): "IP oder Hostname des Meshtastic-Geräts (tcp), z. B. 192.168.1.1:4403.",
    ("interface", "port"): "Serieller Port (Linux: /dev/ttyACM0, Windows: COM3).",
    ("interface", "mac"): "Bluetooth-MAC für BLE-Verbindung.",
    ("interface2", "enabled"): "Zweites Radio aktivieren (Multi-Radio).",
    ("general", "respond_by_dm_only"): "True: Bot antwortet per DM, auch wenn der Befehl im Kanal kam (!warning usw.).",
    ("general", "autoPingInChannel"): "False: Nur ein Ping pro Anfrage; True: mehrere Auto-Pings im Kanal.",
    ("general", "defaultChannel"): "Öffentlicher Standardkanal (LongFast = 0). -1 = keiner.",
    ("general", "ignoreDefaultChannel"): "True: Befehle auf dem Standardkanal ignorieren.",
    ("general", "ignoreChannels"): "Kommagetrennte Kanäle, die der Bot ignoriert.",
    ("general", "cmdBang"): "True: Befehle müssen mit ! beginnen.",
    ("general", "explicitCmd"): "True: Nur bekannte Befehle werden ausgewertet.",
    ("general", "motd"): "Message of the Day — Text bei MOTD/Scheduler, wird beim Start geladen.",
    ("general", "welcome_message"): "Begrüßung neuer Knoten (QRZ/Willkommen).",
    ("general", "spaceWeather"): "Weltraumwetter: !sun, !moon, !solar, !hfcond, !satpass (mit n2yo-Key).",
    ("general", "leaderboardMeshMapEnable"): "!loc: Daten von map.meshhessen.de einblenden.",
    ("general", "LogMessagesToFile"): "Mesh-Nachrichten in messages.log (für Admin Live-Ansicht).",
    ("general", "sysloglevel"): "Log-Level: DEBUG (viel) bis CRITICAL (wenig).",
    ("emergencyHandler", "enabled"): "Reagiert auf Notfall-Schlüsselwörter (SOS, emergency …).",
    ("emergencyHandler", "alert_channel"): "Kanal für Notfall-Hinweise und (bei Auto-Broadcast) DE-Warnungen.",
    ("emergencyHandler", "alert_interface"): "Radio-Interface für Notfall-Versand.",
    ("location", "enableDEalerts"): "NINA/Katwarn/DWD: Befehle !warning und !dealert.",
    ("location", "deAlertAutoBroadcast"): "False: nur auf Anfrage per !warning/!dealert. True: periodisch in Kanäle.",
    ("location", "myRegionalKeysDE"): "ARS-Regionen für !dealert und Auto-Abfrage (kommagetrennt).",
    ("location", "eAlertBroadcastCh"): "Zusätzliche Kanäle für Auto-Warnungen; leer = keine.",
    ("location", "n2yoAPIKey"): "API-Key von n2yo.com für !satpass (Satellitenüberflüge).",
    ("location", "satList"): "NORAD-IDs für !satpass ohne Argument (z. B. 25544 = ISS).",
    ("location", "UseMeteoWxAPI"): "Open-Meteo statt NOAA für !wxc (für DE sinnvoll).",
    ("location", "lat"): "Fallback-Breitengrad, wenn eine Node kein GPS hat.",
    ("location", "lon"): "Fallback-Längengrad, wenn eine Node kein GPS hat.",
    ("polls", "enabled"): "Umfragen mit !poll im Mesh; Verwaltung unter Admin → Umfragen.",
    ("polls", "max_options"): "Maximale Antwortoptionen pro Umfrage.",
    ("polls", "allow_revote"): "True: Knoten dürfen ihre Stimme ändern.",
    ("bbs", "bbs_admin_list"): "Node-IDs (dezimal oder !hex) mit Admin-Rechten.",
    ("bbs", "bbs_ban_list"): "Gesperrte Knoten — keine BBS-/Bot-Nutzung.",
    ("webAdmin", "enabled"): "Flask-Admin unter /admin (Statistik unter / bleibt öffentlich).",
    ("webAdmin", "secret_key"): "Session-Signatur; alternativ Umgebungsvariable HESSENBOT_WEB_SECRET.",
    ("webAdmin", "password"): "Login-Passwort; besser HESSENBOT_WEB_PASSWORD in der Umgebung.",
    ("fileMon", "filemon_enabled"): "Überwacht alert.txt und sendet bei Änderung in Kanal/DM.",
    ("fileMon", "enable_runShellCmd"): "Shell-Daten für !sysinfo (script/sysEnv.sh).",
    ("fileMon", "allowXcmd"): "Gefährlich: x:-Shell-Befehle per DM (nur für Admins).",
    ("messagingSettings", "responseDelay"): "Pause vor Antwort (Kollisionsvermeidung auf dem Mesh).",
    ("messagingSettings", "splitDelay"): "Pause zwischen mehrteiligen Antworten.",
    ("messagingSettings", "cmdRateLimitEnabled"): "Begrenzt Befehle pro Knoten und Zeitfenster.",
}

# Gleicher Key in mehreren Sektionen — Kurztext nach Schlüsselname
KEY_TOOLTIP_DE: Dict[str, str] = {
    "enabled": "Funktion oder Modul ein- (True) oder ausschalten (False).",
    "interface": "Meshtastic-Radio-Interface (1 = erstes Gerät).",
    "channel": "Kanalnummer für ausgehende Nachrichten.",
    "type": "Verbindungsart: serial, tcp oder ble.",
    "port": "Serieller Port oder TCP-Port.",
    "hostname": "IP/Hostname des Meshtastic-Geräts (bei tcp).",
    "mac": "Bluetooth-MAC-Adresse (bei ble).",
    "mode": "Zeitplan-Modus: day, hour, min, mon … sun.",
    "interval": "Intervall — Bedeutung hängt vom Modus ab (Tage/Stunden/Minuten).",
    "time": "Uhrzeit HH:MM (24h) für tägliche/Wochentags-Pläne.",
    "message": "Text für geplante Kanal-Nachricht.",
    "schedulerMotd": "True: MOTD statt message senden.",
    "value": "Scheduler-Typ: day, hour, weather, news, sysinfo, solar, custom …",
    "training": "True: QRZ-Hallo wird nicht gesendet (Testmodus).",
    "password": "Geheimnis — in Git committen vermeiden.",
    "secret_key": "Flask-Session-Schlüssel (zufällig, lang).",
    "host": "Bind-Adresse des Web-Admin (0.0.0.0 = alle Interfaces).",
}

_EN_TO_DE = [
    (r"\benable or disable\b", "Ein-/Ausschalten"),
    (r"\bif False\b", "Bei False"),
    (r"\bif True\b", "Bei True"),
    (r"\bcomma[- ]separated list\b", "Kommagetrennte Liste"),
    (r"\bchannel to send\b", "Kanal für Nachrichten"),
    (r"\binterface to send\b", "Interface für Versand"),
    (r"\blist of\b", "Liste von"),
    (r"\bignored nodes\b", "ignorierte Knoten"),
    (r"\badmin nodes\b", "Admin-Knoten"),
    (r"\bbanned nodes\b", "gesperrte Knoten"),
    (r"\bdetect anyone close\b", "Knoten in der Nähe erkennen"),
    (r"\bdelay in seconds\b", "Verzögerung in Sekunden"),
    (r"\bwait time\b", "Wartezeit"),
    (r"\blogging level\b", "Log-Level"),
    (r"\b24 hour clock\b", "24-Stunden-Zeitformat"),
]


def _germanize_comment(text: str) -> str:
    if not text or not text.strip():
        return ""
    s = text.strip()
    if re.search(r"[äöüÄÖÜß]|Meshhessen|NINA|Kanal|Umfrage|Admin", s):
        return s
    for pattern, repl in _EN_TO_DE:
        s = re.sub(pattern, repl, s, flags=re.I)
    return s


@lru_cache(maxsize=1)
def _template_comments() -> Dict[TooltipKey, str]:
    path = Path(path_in_repo("config.template"))
    out: Dict[TooltipKey, str] = {}
    section: str | None = None
    pending: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.rstrip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            pending = []
            continue
        if line.startswith("#"):
            pending.append(line[1:].strip())
            continue
        if "=" in line and line.strip() and section:
            key = line.split("=", 1)[0].strip()
            if pending:
                out[(section, key)] = " ".join(pending)
            pending = []
    return out


def field_tooltip(section: str, key: str) -> str:
    """Deutscher Tooltip-Text für ein Config-Feld."""
    sk = (section, key)
    if sk in TOOLTIP_DE:
        return TOOLTIP_DE[sk]
    if key in KEY_TOOLTIP_DE and key not in _AMBIGUOUS_KEYS:
        return KEY_TOOLTIP_DE[key]
    raw = _template_comments().get(sk, "")
    if raw:
        de = _germanize_comment(raw)
        if de:
            return de
    return f"Einstellung «{key}» in [{section}]. Details in config.template."


# Keys, deren Bedeutung je Sektion unterschiedlich ist — kein generischer KEY-Fallback
_AMBIGUOUS_KEYS = frozenset(
    {"enabled", "interface", "channel", "interval", "time", "message", "type", "port"}
)
