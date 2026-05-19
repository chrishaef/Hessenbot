# Hessenbot

**Hessenbot** ist ein Meshtastic-Autoresponder für [Meshhessen](https://meshhessen.de) — ein Fork von [SpudGunMan/meshing-around](https://github.com/SpudGunMan/meshing-around) (`main`).

Der Bot antwortet auf Mesh-Befehle (meist mit `!` am Anfang), bietet BBS, Wetter, NINA/Katwarn-Warnungen, DM-Zustellüberwachung, ein Web-Dashboard und Werkzeuge für Netz und Community. Spiele, US-Warnsysteme (NOAA/FEMA/USGS) und das alte `modules/web`-Frontend wurden entfernt; der Fokus liegt auf **EU/DE** und dem Flask-Portal unter `static/portal/`.

![Example Use](etc/pong-bot.jpg "Example Use")

## Danksagung / Acknowledgements

Dieses Projekt wäre ohne **Kelly Keeton (K7MHI)** und alle Mitwirkenden an [**meshing-around**](https://github.com/SpudGunMan/meshing-around) nicht entstanden.

- Upstream: https://github.com/SpudGunMan/meshing-around  
- Fork-Basis: Branch `main` von meshing-around

Weitere Credits unten unter [Credits (Upstream)](#credits-upstream).

## Schnellstart

| Thema | Link |
|--------|------|
| Installation | [INSTALL.md](INSTALL.md) |
| Konfiguration | [config.template](config.template) → `config.ini` |
| Modul-Details | [modules/README.md](modules/README.md) |
| Befehlsreferenz (Web) | `/befehle` am laufenden Portal |
| FAQ | `/faq` am laufenden Portal |

```sh
git clone https://github.com/chrishaef/Hessenbot.git
cd Hessenbot
cp config.template config.ini
# config.ini anpassen (UTF-8), dann:
./bootstrap.sh   # oder install.sh — siehe INSTALL.md
./launch.sh mesh
```

**Wichtig für Meshhessen:** Der Bot ignoriert in der Regel den öffentlichen Standardkanal (ShortSlow). Befehle im **regionalen Kanal 1** (`#1MeshHessen`) senden oder als **DM** an den Bot.

## Was dieser Fork auszeichnet

### Meshhessen / Deutschland

- Betrieb im regionalen Kanal **1**; `defaultChannel` (oft 0 = ShortSlow) wird typischerweise **nicht** bedient (`ignoreDefaultChannel = True` in `config.template`)
- **NINA / Katwarn / DWD** über [warnung.bund.de](https://warnung.bund.de): `!warning`, `!dealert`, optional Broadcast
- **Wetter** über **Open-Meteo** (`!wx`, `!wxc`, `!uv`, `!blitz`, …)
- **Standort**: `!whereami`, `!loc` (mit Höhe), `!howfar`, `!map`, Repeater (`!rlist`)

### Ping & DM-Zustellung

- **`!ping` / `!pong` / `!test` / `!ack` / `!cq`**: QSL-Antwort im Format  
  `LongName [!nodeid] QSL @ "Ort" | N Hops LoRa|MQTT`
- **`wantAckOnDm`**: Mesh-ACK auf DM-Antworten; Fehlzustellungen (inkl. PKI) werden geloggt und im Admin/Dashboard ausgewertet
- Konfiguration: `[messagingSettings]` in `config.ini` (`wantAckOnDm`, `dmDeliveryFailAlertThreshold`)

### Web-UI (Flask)

| URL | Inhalt |
|-----|--------|
| `/` | Öffentliches Statistik-Dashboard (Charts, BBS, NodeDB, Leaderboard, DM-Zustellung 24h) |
| `/befehle` | Befehlsliste |
| `/faq` | Hilfe & PKI-Check |
| `/admin` | Login: BBS, DM, Logs, MOTD, Scheduler, NodeDB, Einstellungen, … |

- Einheitliche **Top-Navigation** (Statistik, Befehle, BBS, NodeDB, FAQ) in öffentlichem und Admin-Bereich
- Aktivierung: `[webAdmin] enabled = True` (siehe [config.template](config.template))

### Kernfunktionen (aus meshing-around, beibehalten)

- Keyword-Responder, Notfall-Stichwörter (112, …)
- **BBS** (Posten, Lesen, DM, Link zwischen Bots)
- **LLM** (Ollama / OpenWebUI, optional)
- **Solar / HF** (`!solar`, `!hfcond`, `!sun`, `!moon`, `!howtall`)
- Scheduler, File-Monitor, Sentry-Nähe, QRZ-Begrüßung, Inventar/Checklist (optional)
- Multi-Interface (bis zu 9 Radios), Nachrichten-Chunking (160 Zeichen)
- **Store & Forward**: `!messages` — letzte Nachrichten von Kanal 1 (`messagesChannel`, `messagesLimit` in `[general]`)

## Wichtige Mesh-Befehle (Auswahl)

| Befehl | Beschreibung |
|--------|----------------|
| `!cmd` | Kurze Befehlsliste (aktivierte Traps) |
| `!ping` / `!pong` / `!test` | QSL mit Ort, Hops, LoRa/MQTT |
| `!ack` | Wie Ping, Keyword ACK |
| `!warning` | NINA/Katwarn für **deinen** Standort (GPS der Node) |
| `!dealert` | Warnungen für `myRegionalKeysDE` |
| `!wx` / `!wxc` | Wetter (Open-Meteo) |
| `!whereami` | Ortsname (Geocoding) + Höhe falls übertragen |
| `!loc` | Letzte Position eines Knotens (NodeDB / Mesh-Karte) inkl. Höhe |
| `!howfar` / `!howfar reset` | Zurückgelegte Strecke seit letztem Aufruf |
| `!howtall <Schatten>` | Höhe per Sonnenwinkel (Schattenlänge in m/ft) |
| `!messages` | Letzte Nachrichten von Kanal 1 (ohne Bot-Befehle) |
| `!bbslist`, `!bbspost`, … | Bulletin Board |

Voraussetzungen in `config.ini` (Auszug):

```ini
[general]
defaultChannel = 0
ignoreDefaultChannel = True
messagesChannel = 1
messagesLimit = 5

[location]
enabled = True
enableDEalerts = True
UseMeteoWxAPI = True

[messagingSettings]
wantAckOnDm = True
dmDeliveryFailAlertThreshold = 3

[webAdmin]
enabled = True
```

`cmdBang = True` — Befehle beginnen mit `!`.

## Was in diesem Fork **nicht** mehr enthalten ist

- Spiele (Blackjack, DopeWars, Quiz, …) und `modules/games/`
- US-/UK-Alerts (NOAA EAS, FEMA iPAWS, USGS, UK-Scraper)
- Legacy-Webserver `modules/web.py` und `etc/www/` (Port 8420)
- `launch.sh game` / Display-Spiele

## Entwicklung & Plattform

Entwicklung und Betrieb typischerweise auf **Linux** (z. B. Raspberry Pi) mit aktueller **Meshtastic-Firmware**. Python **3.8+**; Abhängigkeiten: [requirements.txt](requirements.txt).

`config.ini` muss **UTF-8** sein (keine Windows-1252-Kommentare), sonst bricht der Start ab.

Bitte verantwortungsvoll nutzen und lokale Vorschriften für Funk/Meshtastic beachten. Der Bot protokolliert Traffic und kann Positionsdaten verarbeiten.

### Docker

Siehe [script/docker/README.md](script/docker/README.md).

### MQTT

Wie im Upstream: kein dedizierter MQTT-Code; Betrieb über `meshtasticd` + MQTT-verknüpfte Software-Nodes ist möglich. Siehe [Meshtastic MQTT-Doku](https://meshtastic.org/docs/software/integrations/mqtt/mosquitto/).

### Firmware: DM-Keys & Favoriten

Ab Firmware 2.6: PKC/DM-Keys — Favoriten für BBS-Admins (`script/addFav.py`, `favoriteNodeList`). Details in [INSTALL.md](INSTALL.md) und `/faq` (PKI-Check).

## Tests

```sh
python3 modules/test_bot.py
# Optionale API-Tests (Netzwerk):
touch .checkall && python3 modules/test_bot.py
```

## Lizenz & Haftung

Meshtastic® ist eine eingetragene Marke von Meshtastic LLC. Die Meshtastic-Softwarekomponenten stehen unter verschiedenen Lizenzen — siehe GitHub. **Keine Gewährleistung — Nutzung auf eigenes Risiko.**

## Credits (Upstream)

### Inspiration

- [MeshLink](https://github.com/Murturtle/MeshLink)
- [Meshtastic Python Examples](https://github.com/pdxlocations/meshtastic-Python-Examples)
- [Meshtastic Matrix Relay](https://github.com/geoffwhittington/meshtastic-matrix-relay)

### Tools

- [Node Slurper](https://github.com/SpudGunMan/node-slurper) (Node-Backup)
