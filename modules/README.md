# Hessenbot — Modul-Übersicht

Python-Module für `mesh_bot.py` und das Flask-Web-Portal. Konfiguration erfolgt über `config.ini` (Vorlage: `config.template`).

## Kernmodule

| Modul | Aufgabe |
|-------|---------|
| `settings.py` | Liest `config.ini`, stellt globale Einstellungen bereit |
| `system.py` | Meshtastic-Interfaces, Senden/Empfangen, Trap-Listen, Hilfsfunktionen |
| `nodedb.py` | NodeDB-Zugriff, Namensauflösung, Standort-Cache |
| `packet_dedup.py` | Deduplizierung MQTT/UDP, Hop-Anreicherung |
| `log.py` | Logging, Formatierung |
| `scheduler.py` | Geplante Nachrichten (`[scheduler]`, optional `custom_scheduler.py`) |
| `locale_de.py` | Deutsche Hilfetexte und Befehlspräfixe |

## Meshhessen / Deutschland

| Modul | Aufgabe |
|-------|---------|
| `globalalert.py` | NINA/Katwarn/DWD — `!warning`, `!dealert` |
| `meteo_wx.py` | Open-Meteo — `!wx`, `!wxc`, `!uv`, `!regen` |
| `blitz.py` | Blitz live + Vorhersage — `!blitz` |
| `metar.py` | METAR-Flughafenwetter |
| `geocode.py` | Ortsauflösung, `!whereami`, Mesh-Karte |

## Web-Portal

| Modul | Aufgabe |
|-------|---------|
| `admin_web.py` | Flask-App: `/`, `/admin`, BBS, Logs, Einstellungen |
| `web_dashboard.py` | Statistik-Dashboard, Log-Auswertung |
| `web_commands_help.py` | Befehlsliste für `/befehle` |
| `admin_config_tooltips.py` | Tooltips im Admin-Einstellungs-Editor |

Aktivierung: `[webAdmin] enabled = True` in `config.ini`. Details: [logs/README.md](../logs/README.md).

## Optionale Features

| Modul | Befehle / Funktion |
|-------|-------------------|
| `bbs.py` | BBS — `!bbslist`, `!bbspost`, … |
| `polls.py` | Umfragen — `!poll` |
| `llm.py` | Ollama/OpenWebUI — `!askai` |
| `rss.py` | RSS/News — `!readrss`, `!latest` |
| `radio.py` | VOX/Radio-Monitor (Hamlib) |
| `qrz.py` | QRZ-Begrüßung |
| `sentry.py` | Sentry-Nähe |
| `checklist.py` / `inventory.py` | Check-in, Inventar |

## Tests

```sh
python3 modules/test_bot.py
```

Optionale Netzwerk-Tests: `touch .checkall && python3 modules/test_bot.py`

## Weitere Dokumentation

- [README.md](../README.md) — Projektüberblick und Befehle
- [INSTALL.md](../INSTALL.md) — Installation
- [config.template](../config.template) — alle Konfigurationsoptionen
