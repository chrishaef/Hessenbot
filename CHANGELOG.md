# Changelog

Notable changes for Hessenbot (Meshhessen). Format inspired by [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Changed

- **Admin Übersicht**: aufgeräumt — Erklärtexte unter „Verbindung“, `!sysinfo`/sysEnv.sh- und thermal-zone/vcgencmd-Hinweise bei CPU-Last/-Temperatur sowie der Tab-Hinweis am Seitenende entfernt (Statusanzeigen und Messwerte bleiben); engere Abstände

### Added

- **Node Settings mit Companion-Parität**: Unter-Tabs für alle `Config`-/`ModuleConfig`-Bereiche der lokalen Node (Gerät, Position, Energie, Netzwerk, Display, LoRa, Bluetooth, Sicherheit; MQTT, Seriell, Ext. Benachrichtigung, Store & Forward, Range Test, Telemetrie, Canned Messages, Audio, Remote Hardware, Neighbor Info, Umgebungslicht, Detection Sensor, Paxcounter, Statusnachricht, Traffic Management, TAK), plus Benutzer (HAM-Modus, nicht anschreibbar), Canned-Message-Texte, Klingelton und Administration (Uhrzeit, Neustart, Herunterfahren, NodeDB-/Werksreset). Formulare werden aus den Protobuf-Deskriptoren erzeugt, deutsche Labels; gefährliche Felder (Region, Preset, Sendeleistung > 14 dBm, TX aus, Duty-Cycle, Managed Mode, …) und Resets nur mit Bestätigung, keine stille Begrenzung
- **Kanäle**: Positionsgenauigkeit und „stumm“ je Kanal-Slot
- **Remote-Zugriff auf meshtasticd** (`script/install/remote-access.sh`, INSTALL.md): optionaler UFW-Helfer, der Port 4403 nur für das LAN-Subnetz oder `tailscale0` freigibt (`status|lan|tailscale|close`); Sicherheits- und Ein-Client-Hinweise (meshtasticd bedient nur einen TCP-Client gleichzeitig, kein Auth/TLS)
- **Pi-4-Installer (nativ)**: `bootstrap.sh` + `script/install/wizard.sh` für Raspberry Pi 4, RAK6421/RAK13302 Slot 1 (EU_868), Trixie, `meshtasticd` (OBS) + Bot als systemd-Dienste; Preset-/Kanal-Abfrage (#1 Mesh Hessen, optional HessenTest), TX erst nach Antennenbestätigung, `--dry-run`, `--revert`, Reboot-Resume; `install.sh --nope` mit Bestätigung und Backup; `bootstrap.sh --legacy` für das alte Verhalten
- **Node Settings — Absicherung**: CSRF-Token in allen Node-Settings-Formularen (Anfragen ohne gültiges Token ändern nichts), Session-/Remember-Cookie `SameSite=Lax`; vor jedem Schreiben wird der Bereich frisch von der Node gelesen und bei zwischenzeitlicher Änderung abgelehnt (statt veraltete Cache-Werte zurückzuschreiben); Link „Neu von der Node laden“; Canned-Message-Texte und Klingelton werden nur auf Klick gelesen (kein Blockieren beim Tab-Wechsel); veraltete Felder (z. B. `device.is_managed`) nur noch Anzeige; unbekannte Formular-Aktionen werden abgelehnt
- **Admin Übersicht – Verbindung**: Live-Status (Poll alle 5 s, `GET /api/admin/link-status`) für Hardware/meshtasticd (Interface verbunden, Reconnect, letztes Paket) und MQTT (am Node aktiviert, Pakete über MQTT-Transport zuletzt empfangen)
- **BBS-DM Lesebestätigung** (Issue #9): `bbspost ack @Empfänger #Text` verlangt Nutzer-ACK per `ack <id>`; Mesh-/Node-Empfang (`wantAckOnDm`) und Nutzer-Bestätigung getrennt; Absender-Status-DMs; Config `bbsDmUserAckEnabled`, Retry/Max/Expire, Admin-Spalten + Checkbox
- **Service-API**: `POST /api/v1/dm` / `GET /api/v1/whoami` für externe Dienste (z. B. MQTT-Webadmin Watchcat); Admin-Tab **API** (Enable, Key einmalig erzeugen, Doku, Request-Log); Token als SHA-256-Hash (`api_token_hash`), Schalter `api_enabled`, optional Env `HESSENBOT_API_TOKEN`; Rate-Limit 30/min; Audit in `logs/service_api.log`


- **Positionsanfrage**: Fehlt bei ortsabhängigen Befehlen (`!wx`, `!blitz`, `!metar`, `!whereami`, `!map`, …) die Node-Position, fordert der Bot sie per Mesh an, wartet kurz und führt den Befehl automatisch nach; Timeout mit Hinweis auf Ort/Koordinaten
- **Channel-Test**: pro Kanal lange Antwort oder Emoji-Reaction (👍/✅), optional Hop-Ziffern-Reaction; Admin-UI
- **Befehls-Throttling**: Notify-once + teure-Befehl-Cooldowns; Admin-Seite **Limits**
- Config: `locationRequestEnabled`, `locationRequestTimeoutSec`, `locationRequestCooldownSec`

### Changed

- **`bootstrap.sh`**: klont/aktualisiert jetzt `/opt/Hessenbot` und startet den Wizard (bisher: venv + `config.ini` im aktuellen Verzeichnis); das alte Verhalten gibt es mit `bootstrap.sh --legacy`
- **Pi-4-Installer**: Antworten werden bei jedem Lauf gespeichert (Ablehnen der Wiederverwendung fragt alles neu); Node wird nach dem Schreiben zurückgelesen (Kanäle, Region, Preset, TX-Leistung, TX-Gate, mit zweitem Durchlauf, weil die Firmware TX beim ersten Setzen der Region aktiviert); Admin-Pakete werden gedrosselt gesendet (sonst verwirft die Node sie); apt ohne Conffile-Prompts und mit dpkg-Lock-Timeout; `MACAddressSource` via `config.d`; vorhandene Node-Identität muss vor dem Start bestätigt werden; Resume-Dienst bleibt bis zum Erfolg und zeigt Fehler beim Login; OBS-Schlüssel-Fingerprint gepinnt; GPS ist in dieser Version nicht Teil des Wizards; Hardware-Rückfrage ohne EEPROM-Treffer standardmäßig „nein“ (`--confirm-hardware`); Warnung + Bestätigung für das kurze TX-Fenster bei „Antenne: nein“ (`--accept-tx-window`, `tx_power` 1 dBm bis zur Freigabe); Rückfragen auch bei „Antworten wiederverwenden“; bei TX-Gate-Verletzung wird `meshtasticd` gestoppt; fehlgeschlagener Resume startet nicht bei jedem Boot erneut; abgewähltes HessenTest wird auf der Node deaktiviert (nur wenn Kanal #2 noch „HessenTest“ heißt)
- **Pi-4-Installer LoRa-Konfiguration**: übernimmt die RAK6421+RAK13302-Konfiguration von SMLunchen 1:1 als `/etc/meshtasticd/available.d/lora-hat-rak-6421-pi-hat.yaml` (SX1262, `CS: 8`, IRQ 22, Reset 16, Busy 24, `DIO3_TCXO_VOLTAGE`, `DIO2_AS_RF_SWITCH`, spidev0.0; kein `Enable_Pins`/`SX126X_ANT_SW`/`SX126X_MAX_POWER`) statt des Standard-Presets `lora-RAK6421-13302-slot1.yaml`; Boot-Block um `i2c_vc`/`i2c0` (HAT-EEPROM) erweitert; `MACAddressSource` nutzt `end0` (Fallback `eth0`); Selbsttest wertet `SX126x init result` aus
- **Pi-4-Installer Sendeleistung**: kein eigener `tx_power`-Cap des Installers mehr (statt 27 dBm minus Antennengewinn; die Firmware begrenzt ohne HAM-Modus selbst auf das Regionslimit, EU_868 ca. 27 dBm). Wizard/`--tx-power` nimmt 0–30 dBm oder `max` (Volllast), Default 14 dBm. `0` heißt Regions-Maximum der Firmware (nicht „aus“) und wird wie ein hoher Wert behandelt. Werte über 14 dBm und 0 zeigen eine Warnung (EU-868-Grenzwerte, zusätzliche PA-Verstärkung der RAK13302) und brauchen eine Bestätigung (`--accept-tx-power` bei `--yes`); nichts wird still begrenzt
- **Web-Admin Node Settings**: neue Sektion „Sendeleistung (LoRa)“ zum Lesen/Setzen von `lora.tx_power` (0–30 dBm) auf der lokalen Node; Werte über 14 dBm und 0 (Regions-Maximum) zeigen die EU-868/PA-Warnung und brauchen eine Bestätigung
- **Kein Bot-Standort-Fallback** mehr für Nutzer-Nodes (`get_node_location*` / Wetter & Co.)
- **DM-Befehle**: mit und ohne `!` (erstes Wort); im Kanal weiter nur mit `!` (außer Channel-Test `test`)
- Entfernt: Aliase `pong` / `pinging` / `testing`
- Unbekannte DMs: einmal Welcome, danach Hinweis mit 5-Min-Cooldown (statt kompletter Befehlsliste)

### Fixed

- **Node Settings (Übersicht)**: Namen speichern setzte den Amateurfunk-Status (`is_licensed`) und „nicht anschreibbar“ (`is_unmessagable`) der Node stillschweigend zurück; Rollenwechsel auf Router/Repeater/Tracker/Sensor/Hidden braucht jetzt auch in der Übersicht eine Bestätigung
- **Node Settings (Sicherheit)**: Neuer privater Schlüssel leert den öffentlichen Schlüssel, damit die Firmware ihn neu ableitet (vorher blieb das alte Paar inkonsistent); keine irreführende „leeren“-Option mehr für den privaten Schlüssel
- **Node Settings (LoRa)**: Sendeleistung 0 bedeutet Regionsmaximum (EU_868: 27 dBm) und braucht auch im LoRa-Tab eine Bestätigung; Übersicht und LoRa-Tab nutzen dieselbe Prüfung und denselben Warntext
- **Node Settings (Benutzer)**: HAM-Modus warnt vor den Firmware-Folgen (PSKs aller Kanäle inkl. Meshhessen werden gelöscht, Admin-Kanal aus, neues Schlüsselpaar) und verlangt zusätzlich das Wort „HAM“; Namensänderung aktualisiert sofort die Anzeige
- **`!readnews`**: Führendes `!` wird vor der Quellen-Auswertung entfernt — sonst wurde `!` als Quellenname gelesen (`data/!_news.txt`) und fälschlich „No news for you!“ geliefert (DM und Kanal)
- **News-Versand (ACP)**: Zeitplan-Hinweise/`config.template`/Tooltips an MOTD-Versand angeglichen (inkl. mehrerer Uhrzeiten)
- **ACP Einstellungen**: Speichern schrieb `config.ini` per `ConfigParser.write()` und flattente dabei alle Keys auf Kleinbuchstaben; Formular-POST aktualisiert jetzt nur übermittelte `cfg__*`-Felder (übrige Keys bleiben), Schreibweg stellt camelCase aus `config.template` wieder her
- **Öffentliches Dashboard**: Crash „Dashboard: 0“ nach BBS-DM mit Lesebestätigung — Queue-Zeilen sind seit Issue #9 Dicts; Render griff noch per `row[0]`/`row[2]` zu (`KeyError(0)`). Nutzt jetzt `dm_to`/`dm_from`, isoliert BBS-DM-Fehler vom Rest der Seite
- **Blitzwatch**: `dictionary changed size during iteration` im Poll-Zyklus — Snapshot von `iface.nodes` vor dem Walk (MQTT kann Nodes parallel hinzufügen)
- **`!trace`**: ROUTING_APP-NAKs (z. B. mit `route_request`) nicht mehr als `RouteDiscovery` parsen — verhindert `Trace fehlgeschlagen: Error parsing message with type 'meshtastic.protobuf.RouteDiscovery'`; klarere DE-Hinweise bei Routing-Fehler / unlesbarer Antwort
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
