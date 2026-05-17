# Hessenbot — Admin-Backend & Log-Ordner

Dieser Ordner (`logs/`) enthält die **Logdateien** des Bots (z. B. `meshbot.log`, optional `messages.log`). Die Dateien werden vom Hessenbot geschrieben und im **Admin-Backend** im Browser eingesehen — du musst sie nicht manuell öffnen.

Die **öffentliche Statistik** (`/`) ist ohne Login erreichbar. Alle Verwaltungsfunktionen liegen hinter **`/admin`**.

---

## Aktivierung

In `config.ini`:

```ini
[webAdmin]
enabled = True
host = 0.0.0.0
port = 5000
username = admin
password = hessenadmin
# Optional statt Passwort in der Datei:
# Umgebungsvariable HESSENBOT_WEB_PASSWORD setzen
secret_key =
# Optional: HESSENBOT_WEB_SECRET für stabile Sessions
log_dir =
# leer = dieser Ordner (logs/ im Projekt)
```

Bot neu starten. Im Log erscheint u. a.:

`Web UI listening on http://0.0.0.0:5000/ (stats) and http://0.0.0.0:5000/admin (login)`

| URL | Zugriff |
|-----|---------|
| `http://<host>:<port>/` | Statistik-Dashboard (öffentlich) |
| `http://<host>:<port>/admin` | Admin-Login |
| `http://<host>:<port>/befehle` | Mesh-Befehls-Hilfe (öffentlich) |

`/login` leitet auf `/admin` um.

---

## Anmeldung

- Benutzername und Passwort aus `[webAdmin]` (oder `HESSENBOT_WEB_PASSWORD`).
- Nach dem Login: **Übersicht** mit Host-Kennzahlen und den letzten Log-Warnungen/Fehlern.
- Navigation über die **Tabs** oben (BBS, NodeDB, Logs, …).

---

## Bereiche im Admin-Backend

### Übersicht (`/choose`)

Kurzer Einstieg: CPU/RAM/Platte des Hosts, zusammengefasste **WARN/ERROR**-Zeilen aus den Logs, Link zur öffentlichen Statistik.

### DM & News

| Tab | Pfad | Funktion |
|-----|------|----------|
| **DM** | `/dm` | Textdatei für die Bot-Direktnachricht / Alert-Text (`[fileMon]` → `file_path`, z. B. `alert.txt`) |
| **News** | `/news` | News-Datei für File-Monitor / `readnews` (`news_file_path`) |

Beide Seiten: Textarea, **Speichern** schreibt direkt auf die Datei (der laufende Bot nutzt sie je nach Modul).

### Messages (`/live/messages`)

Live-Ansicht von **`messages.log`** (letzte Zeilen, Auto-Refresh ca. 5 s).

Voraussetzung in `config.ini`:

```ini
[general]
LogMessagesToFile = True
```

Ohne diese Option zeigt die Seite einen Hinweis zur Aktivierung.

### NodeDB (`/nodes`)

- Alle Knoten der verbundenen Interfaces (Name, ID, letztes Signal, …).
- Suche/filterbar.
- **Knoten entfernen** (POST) — Eintrag aus der lokalen NodeDB des gewählten Interfaces.

### Mesh-Admins (`/mesh-admin`)

Verwaltung von **`bbs_admin_list`** in `config.ini` (Knoten-IDs, kommagetrennt). Diese Nodes dürfen u. a. fremde BBS-Beiträge löschen und erhalten erweiterte Rechte im Mesh.

### MOTD (`/motd`)

**Message of the Day** bearbeiten (`[general]` → `motd`). Entspricht dem Mesh-Befehl `!motd` (Admin kann per `motd $ …` auch im Funk ändern).

### Scheduler (`/scheduler`)

Geplante Aufgaben aus `[scheduler]` / `etc/custom_scheduler.py` einsehen und Intervalle anpassen (z. B. MOTD-Broadcast, `bbslink`, News, `sysinfo`).

### Umfragen (`/umfragen`)

Einfache Abstimmungen für das Mesh:

- **Neue Umfrage** — Frage, Antwortoptionen (eine pro Zeile), aktiv/geschlossen
- **Anzeigen** — Stimmen, Prozent, welche Knoten abgestimmt haben (Auszug)
- **Schließen/Aktivieren**, **Stimmen zurücksetzen**, **Löschen**

Daten: `data/polls.pkl`. Im Funk: `!poll`, `!poll liste`, `!poll <Nr>`, `!poll <Nr> <Option>`.

Konfiguration: `[polls] enabled`, `max_options`, `allow_revote` in `config.ini`.

### BBS (`/bbs`)

Öffentliches Bulletin Board (`data/bbsdb.pkl`):

- Liste, **Neue Nachricht**, **Lesen**, **Löschen**
- Absender **Node 0** = Eintrag über das Web-Admin → Anzeige als **Hessenbot (Meshhessen Web-Admin)**

**BBS-DMs** (`/bbs/dm`): Warteschlange `data/bbsdm.pkl` — anzeigen, anlegen, löschen (Zeile 0 ist interner Platzhalter).

Im **Statistik-Dashboard** (Tab „BBS“) siehst du dieselben Daten in Kartenform (öffentliche Posts + DM-Warteschlange aus den Logs).

### Banliste (`/banlist`)

`bbs_ban_list` pflegen — gebannte Knoten-IDs (Mesh-BBS und Bot-Schutz).

### Logs (`/logs`)

Listet alle Dateien in **`logs/`** (oder `[webAdmin] log_dir`). Klick auf eine Datei → **`/view/<dateiname>`** (Volltext im Browser).

Typische Dateien:

| Datei | Inhalt |
|-------|--------|
| `meshbot.log` | System-Log des Bots (Befehle, Warnungen, PKI, …) |
| `messages.log` | Kanal-/DM-Nachrichten (wenn `LogMessagesToFile = True`) |

---

## Logging-Einstellungen (für sinnvolle Logs)

```ini
[general]
SyslogToFile = True
sysloglevel = INFO
log_backup_count = 32
LogMessagesToFile = False
```

- **`SyslogToFile`** — schreibt nach `logs/meshbot.log` (für Admin-Logs und Dashboard-Auswertung).
- **`sysloglevel`** — `DEBUG` liefert mehr Detail, erzeugt größere Dateien.
- **`log_backup_count`** — Anzahl rotierender Tage (0 = alle behalten).

Details zur öffentlichen Statistik und Charts: Projekt-`README.md` und `static/portal/`.

---

## Sicherheit

- Admin-Port nicht unnötig ins Internet stellen; Firewall/VPN nutzen.
- Starkes Passwort oder `HESSENBOT_WEB_PASSWORD`; `secret_key` / `HESSENBOT_WEB_SECRET` setzen.
- `host = 127.0.0.1` nur lokaler Zugriff; `0.0.0.0` lauscht auf allen Interfaces.

---

## Legacy: HTML-Report (`report_generator5.py`)

Ältere **statische HTML-Reports** aus Log-Auswertung (nicht das Flask-Admin-UI):

```sh
./launch.sh html5
```

Ausgabe standardmäßig unter `etc/www/`. Das aktuelle Portal ersetzt diese Ansicht für den Alltag durch `/` und `/admin`.
