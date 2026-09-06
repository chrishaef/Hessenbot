# Changelog

Notable changes for Hessenbot (Meshhessen). Format inspired by [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added

- **Positionsanfrage**: Fehlt bei ortsabhängigen Befehlen (`!wx`, `!blitz`, `!metar`, `!whereami`, `!map`, …) die Node-Position, fordert der Bot sie per Mesh an, wartet kurz und führt den Befehl automatisch nach; Timeout mit Hinweis auf Ort/Koordinaten
- **Channel-Test**: pro Kanal lange Antwort oder Emoji-Reaction (👍/✅), optional Hop-Ziffern-Reaction; Admin-UI
- **Befehls-Throttling**: Notify-once + teure-Befehl-Cooldowns; Admin-Seite **Limits**
- Config: `locationRequestEnabled`, `locationRequestTimeoutSec`, `locationRequestCooldownSec`

### Changed

- **Kein Bot-Standort-Fallback** mehr für Nutzer-Nodes (`get_node_location*` / Wetter & Co.)
- **DM-Befehle**: mit und ohne `!` (erstes Wort); im Kanal weiter nur mit `!` (außer Channel-Test `test`)
- Entfernt: Aliase `pong` / `pinging` / `testing`
- Unbekannte DMs: einmal Welcome, danach Hinweis mit 5-Min-Cooldown (statt kompletter Befehlsliste)

### Fixed

- DM: `!ping` und `ping` beide gültig (`messageTrap` strippt optionales `!`)
- Diverse Admin-/Dashboard- und Hop-/MQTT-Korrekturen (siehe Commits seit 1.1.0)

## [1.1.0] — 2026-09-04

### Added

- **Blitzwatch**: Nähe-Warnungen per DM/Kanal; Home + bis zu 3 Zusatzorte; Admin-UI (NodeDB-Liste, Suche, Editor); öffentliches Setup per DM-PIN (`!blitzwatch web` / `set` → `/mein-blitzwatch`)
- **Impressum & Datenschutz**: öffentliche Seiten `/impressum` und `/datenschutz`, Footer-Links, Felder unter Admin → Web-Admin
- **Standort-Args**: Ort, Koordinaten und Maidenhead-Grid für Standort-Befehle; Quelle (Node/Bot) in Antworten
- **Ping/Test**: Antwort mit Ort, Maidenhead, Hops, SNR oder MQTT
- **Admin Mesh**: Live-Chat (Kanal + DM), Mesh-DM aus NodeDB, Kanalbearbeitung in Node Settings, MOTD/Scheduler-UI mit Kanal-Dropdown
- **Admin Übersicht**: CPU-Temp und Auslastung mit Sparkline
- **Traceroute**: `!trace` mit Warteschlange und DM-Ergebnis
- **NodeDB**: persistente Node-DB, NODEINFO-Erfassung, PKI-Hilfen
- **Channel-Test**: In-Kanal-Antwort auf nacktes `test` auf konfigurierten Kanälen
- Repo-Metadaten: SECURITY, CONTRIBUTING, CODE_OF_CONDUCT, Issue/PR-Templates, Dependabot
- CI: pytest für Blitzwatch und Standort-Args auf Push/PR zu `main`

### Changed

- Install-/Service-Defaults auf **Hessenbot** / `/opt/Hessenbot`
- Docker-Image/-Compose auf `hessenbot`; Container-TZ `Europe/Berlin`
- Leeres Default-Admin-Passwort in `config.template` (bestehende Installs unverändert)
- Config-Schlüssel-Aliases (Template- und Legacy-Namen, z. B. `log_backup_count` / `LogBackupCount`)
- Blitzwatch-Hilfe und Mesh-Status klarer (`!blitzwatch` / `!blitzwatch?`)
- README und Modul-Übersicht an aktuelle Features angepasst
- Legacy pong-bot / tote Webserver-Pfade entfernt

### Fixed

- Kanal-PSK speichern (Bytes-Parsing); eingehende Kanal-Hashes → Slot-Index
- `publicUrl` / Impressum-Keys für bestehende `config.ini` nachziehen
- Viele Admin-Chat-/Dashboard-Dedup- und Layout-Probleme
- Ping/Hop-Zählung bei MQTT; Trace Rate-Limits und Self-Loops
- DWD-Warnungsausgabe; `!wx?` Kurzhilfe; diverse Scheduler/News- und Dashboard-Fixes
- CI: Config-Aliases ohne fehlerhaftes `SectionProxy.has_option`
- `!whereami` nur bei bekanntem Node-Standort (kein Bot-Adress-Fallback)
- **Mesh-DM**: Empfänger-Auflösung in laufenden Chats; Threads am Ziel-Node statt „Web-Admin“; eingehende DMs nicht mehr in allen Threads; stabile Thread-IDs über `[!hex]` in DM-Logs

## [1.0.0] — 2026-05-19

Erstes Hessenbot-Release für Meshhessen (QSL-Ping, Web-Portal, DE-Warnungen, NodeDB-Karten-Fallback u. a.). Details: GitHub Release `v1.0.0`.

## Earlier history

See Git commit history on `main` and upstream [meshing-around](https://github.com/SpudGunMan/meshing-around) for older changes.
