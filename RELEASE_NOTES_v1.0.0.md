# Hessenbot v1.0.0 — Meshhessen Release

Erstes Release des Hessenbot-Forks für den Betrieb im [Meshhessen](https://meshhessen.de)-Netz.

## Highlights

- **QSL-Ping-Antworten** (`!ping`, `!pong`, `!test`, …): LongName, Node-ID, Bot-Standort, Hops, LoRa/MQTT
- **DM-Zustellüberwachung** mit Mesh-ACK (`wantAckOnDm`), Log-Auswertung, Dashboard und Admin-Anzeige
- **Web-Portal**: öffentliches Dashboard, Befehle, FAQ/PKI-Check, Admin-Backend mit einheitlicher Navigation
- **DE-Warnungen** (NINA/Katwarn), Open-Meteo-Wetter, `!loc` mit übertragener Höhe
- **`!messages`**: konfigurierbar Kanal 1 / Meshhessen, Standard 5 Nachrichten
- **NodeDB-Karten-Fallback** für Positionen ohne GPS in der NodeDB

## Konfiguration (neu / wichtig)

In `config.ini` unter `[general]` ergänzen bzw. prüfen:

```ini
messagesChannel = 1
messagesLimit = 5
ignoreDefaultChannel = True
```

Unter `[messagingSettings]`:

```ini
wantAckOnDm = True
dmDeliveryFailAlertThreshold = 3
```

`config.ini` als **UTF-8** speichern.

## Fixes

- `handle_howfar` / `handle_howtall` wieder implementiert
- Portal-Navigation Admin/öffentlich vereinheitlicht
- FAQ-Hinweis ShortSlow vs. MeshHessen-Kanal

## Installation

Siehe [README.md](README.md) und [INSTALL.md](INSTALL.md).
