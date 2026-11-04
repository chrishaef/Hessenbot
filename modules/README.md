# Hessenbot — Modul-Übersicht

Python-Module für `mesh_bot.py` und das Flask-Web-Portal. Konfiguration über `config.ini` (Vorlage: [`config.template`](../config.template)).

## Kernmodule

| Modul | Aufgabe |
|-------|---------|
| `settings.py` | Liest `config.ini`, stellt globale Einstellungen bereit |
| `system.py` | Meshtastic-Interfaces, Senden/Empfangen, Trap-Listen, Hilfsfunktionen |
| `nodedb.py` | Persistente NodeDB, Namensauflösung, `list_nodes()` |
| `packet_dedup.py` | Deduplizierung MQTT/UDP, Hop-Anreicherung |
| `log.py` | Logging, Formatierung |
| `scheduler.py` | Geplante Nachrichten (`[scheduler]`, optional `custom_scheduler.py`) |
| `locale_de.py` | Deutsche Hilfetexte und Befehlspräfixe |

## Meshhessen / Deutschland

| Modul | Aufgabe |
|-------|---------|
| `globalalert.py` | NINA/Katwarn/DWD — `!warning`, `!dealert` |
| `wx_meteo.py` | Open-Meteo — `!wx` |
| `wx_extra.py` | `!uv`, `!regen`, `!blitz` |
| `blitzwatch.py` | Nähe-Warnung — Home + Zusatzorte, Mesh + Web-PIN |
| `metar.py` | METAR-Flughafenwetter |
| `locationdata.py` | Standort-Args, Map-Orte, Geocoding-Helfer |
| `location_request.py` | Positionsanfrage per Mesh wenn Node-GPS fehlt; Pending/Timeout |

## Web-Portal

| Modul | Aufgabe |
|-------|---------|
| `admin_web.py` | Flask-App: öffentlich + `/admin` |
| `admin_web_ops.py` | Admin-Helfer (NodeDB, Kanäle, Blitzwatch-UI, …) |
| `admin_web_theme.py` | Portal-Shell, Navbar, Footer |
| `web_dashboard.py` | Statistik-Dashboard |
| `web_commands_help.py` | `/befehle`; Blitzwatch-Guide für `/mein-blitzwatch` |
| `web_faq_help.py` | `/faq` |
| `web_legal.py` | `/impressum`, `/datenschutz` |
| `admin_config.py` / `admin_config_tooltips.py` | Einstellungsformular + Tooltips |

Aktivierung: `[webAdmin] enabled = True` in `config.ini`. Logs liegen unter `logs/` (Anzeige im Admin-Tab **Logs**).

## Optionale Features

| Modul | Befehle / Funktion |
|-------|-------------------|
| `bbstools.py` | BBS — `!bbslist`, `!bbspost`, … |
| `polls.py` | Umfragen — `!poll` |
| `llm.py` | Ollama/OpenWebUI — `!askai` |
| `rss.py` | RSS/News — `!readrss`, `!latest` |
| `qrz.py` | QRZ-Begrüßung |
| `checklist.py` / `inventory.py` | Check-in, Inventar |

## Tests

```sh
python3 -m pytest modules/test_blitzwatch.py modules/test_location_request.py -q
python3 modules/test_bot.py
```

Optionale Netzwerk-Tests: `touch .checkall && python3 modules/test_bot.py`

## Weitere Dokumentation

- [README.md](../README.md) — Projektüberblick und Befehle
- [INSTALL.md](../INSTALL.md) — Installation
- [CONTRIBUTING.md](../CONTRIBUTING.md) — Mitwirken
- [SECURITY.md](../SECURITY.md) — Sicherheitsmeldungen
- [CHANGELOG.md](../CHANGELOG.md) — Änderungen
- [config.template](../config.template) — alle Konfigurationsoptionen
