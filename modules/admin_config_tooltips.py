#!/usr/bin/env python3
# Deutsche Tooltips: Was eine Einstellung am Bot-Verhalten ändert.

from __future__ import annotations

from typing import Dict, Tuple

TooltipKey = Tuple[str, str]

# Vollständige (Sektion, Schlüssel) → Verhalten am Mesh-Bot
BEHAVIOR: Dict[TooltipKey, str] = {
    # ── interface ──
    ("interface", "type"): "Wie der Bot mit dem Radio spricht: USB-Seriell (serial), Netzwerk (tcp) oder Bluetooth (ble).",
    ("interface", "port"): "USB-Port des Meshtastic-Geräts, falls type=serial (z. B. /dev/ttyACM0).",
    ("interface", "hostname"): "IP oder Hostname des Knotens, falls type=tcp — dort hängt der Bot per TCP.",
    ("interface", "mac"): "Bluetooth-Adresse des Geräts, falls type=ble.",
    ("interface2", "enabled"): "Zweites Radio parallel nutzen (z. B. zwei Geräte/Regionen).",
    ("interface2", "type"): "Verbindungsart für das zweite Radio (serial/tcp/ble).",
    ("interface2", "port"): "USB-Port des zweiten Geräts bei serial.",
    ("interface2", "hostname"): "IP/Hostname des zweiten Geräts bei tcp.",
    ("interface2", "mac"): "Bluetooth-MAC des zweiten Geräts bei ble.",
    # ── general ──
    ("general", "packetDedupEnabled"): "True: Gleiches Mesh-Paket nur einmal verarbeiten (z. B. wenn es per MQTT und UDP ankommt). UDP bleibt als Fallback aktiv.",
    ("general", "packetDedupTtlSeconds"): "Wie lange ein Paket als „schon gesehen“ gilt (Sekunden).",
    ("general", "packetDedupMaxEntries"): "Maximale Anzahl gespeicherter Paket-IDs; älteste fallen weg.",
    ("general", "respond_by_dm_only"): "Antworten gehen als DM an die anfragende Node — auch wenn der Befehl im Kanal kam.",
    ("general", "autoPingInChannel"): "True: !ping kann mehrere Folge-Pings auslösen; False: nur eine Antwort.",
    ("general", "defaultChannel"): "Nummer des öffentlichen Meshtastic-Kanals (LongFast oft 0). -1 = kein Standardkanal.",
    ("general", "ignoreDefaultChannel"): "True: Nachrichten/Befehle auf dem Standardkanal werden ignoriert.",
    ("general", "ignoreChannels"): "Diese Kanalnummern werden vom Bot komplett ignoriert (kommagetrennt).",
    ("general", "cmdBang"): "True: Nur Nachrichten mit führendem ! gelten als Befehl.",
    ("general", "explicitCmd"): "True: Nur bekannte Befehle werden ausgeführt — kein Zufallstreffer.",
    ("general", "favoriteNodeList"): "Favoriten-Knoten für Skripte wie addFav (dezimale IDs, kommagetrennt).",
    ("general", "motd"): "Standard-Text für MOTD und geplante MOTD-Sendungen; wird beim Start eingelesen.",
    ("general", "welcome_message"): "Text, den der Bot neuen Knoten als Begrüßung schickt (z. B. mit QRZ).",
    ("general", "whoami"): "True: Befehl !whoami zeigt Name, ID, Signal und Route der anfragenden Node.",
    ("general", "DadJokes"): "True: Witz-Befehle (joke) sind aktiv.",
    ("general", "DadJokesEmoji"): "True: Witze zusätzlich mit Emoji-Format.",
    ("general", "spaceWeather"): "True: Befehle sun, moon, solar, hfcond und ggf. satpass (mit API-Key) sind verfügbar.",
    ("general", "rssEnable"): "True: RSS-Feeds können per Befehl abgerufen werden.",
    ("general", "rssFeedURL"): "URLs der RSS-Feeds, kommagetrennt — Reihenfolge zu rssFeedNames.",
    ("general", "rssFeedNames"): "Kurznamen der Feeds in derselben Reihenfolge wie rssFeedURL.",
    ("general", "rssMaxItems"): "Wie viele RSS-Einträge pro Abruf maximal gesendet werden.",
    ("general", "rssTruncate"): "Maximale Zeichenlänge pro RSS-Eintrag in der Antwort.",
    ("general", "enableNewsAPI"): "True: Befehl für Schlagzeilen über NewsAPI.org (newsAPI_KEY nötig).",
    ("general", "newsAPI_KEY"): "API-Schlüssel von newsapi.org für Nachrichten-Headlines.",
    ("general", "newsAPIregion"): "Region für NewsAPI (z. B. de, us).",
    ("general", "sort_by"): "Sortierung der NewsAPI-Ergebnisse: relevancy, popularity oder publishedAt.",
    ("general", "wikipedia"): "True: Wikipedia-/Kiwix-Suche per Befehl ist aktiv.",
    ("general", "useKiwixServer"): "True: Lokaler Kiwix-Server statt Online-Wikipedia.",
    ("general", "kiwixURL"): "Adresse des Kiwix-Servers (z. B. http://127.0.0.1:8080).",
    ("general", "kiwixLibraryName"): "Name der Kiwix-Bibliothek auf dem Server.",
    ("general", "ollama"): "True: LLM-Anbindung (Ollama/OpenWebUI) für ask/askai ist aktiv.",
    ("general", "ollamaHostName"): "URL des Ollama-Servers für KI-Antworten.",
    ("general", "useOpenWebUI"): "True: Statt direktem Ollama wird die OpenWebUI-API genutzt.",
    ("general", "openWebUIURL"): "URL der OpenWebUI-Instanz.",
    ("general", "openWebUIAPIKey"): "API-Token für OpenWebUI, falls erforderlich.",
    ("general", "rawLLMQuery"): "True: Anfrage geht unverändert ans LLM; False: mit internem System-Prompt.",
    ("general", "llmReplyToNonCommands"): "True: Beliebige DMs können ans LLM gehen; False: nur ask/askai.",
    ("general", "llmUseWikiContext"): "True: LLM erhält automatisch Wikipedia/Kiwix-Kontext (RAG).",
    ("general", "StoreForward"): "True: Bot kann Nachrichten zwischenspeichern und später ausliefern.",
    ("general", "StoreLimit"): "Maximale Anzahl gespeicherter Nachrichten pro Node.",
    ("general", "reverseSF"): "True: Älteste gespeicherte Nachricht zuerst; False: neueste zuerst.",
    ("general", "enableCmdHistory"): "True: Befehle !history / lheard nutzen Verlauf.",
    ("general", "lheardCmdIgnoreNodes"): "Knoten-IDs, deren Befehle nicht im Verlauf erscheinen.",
    ("general", "lheardCmdIgnoreNode"): "Knoten-IDs, deren Befehle nicht im Verlauf erscheinen (älterer Schlüsselname).",
    ("general", "zuluTime"): "True: Zeiten in Antworten als 24h-Format; False: 12h mit AM/PM.",
    ("general", "urlTimeout"): "Sekunden, die der Bot maximal auf externe APIs (Wetter, NINA, …) wartet.",
    ("general", "leaderboardMeshMapEnable"): "True: !loc kann Daten von der Meshhessen-Karte einblenden.",
    ("general", "leaderboardMeshMapURL"): "URL der nodes.json der regionalen Mesh-Karte.",
    ("general", "LogMessagesToFile"): "True: Fremde Mesh-Nachrichten werden in messages.log geschrieben (Admin Live-Ansicht).",
    ("general", "SyslogToFile"): "True: Bot-Systemlogs landen in meshbot.log.",
    ("general", "sysloglevel"): "Wie ausführlich geloggt wird: DEBUG (sehr viel) bis CRITICAL (wenig).",
    ("general", "log_backup_count"): "Wie viele Tage Log-Dateien aufbewahrt werden (Rotation).",
    ("general", "dont_retry_disconnect"): "True: Bei Verbindungsabbruch beendet sich der Bot (für systemd-Neustart).",
    ("general", "enableEcho"): "True: echo-Befehl spiegelt Nachrichten zurück.",
    ("general", "echoChannel"): "Kanal, auf dem echo ohne @-Prefix antwortet.",
    # ── emergencyHandler ──
    ("emergencyHandler", "enabled"): "True: Bot erkennt Notfall-Wörter in Nachrichten und alarmiert konfigurierte Kanäle.",
    ("emergencyHandler", "alert_channel"): "Kanal, auf den Notfall-Hinweise (und ggf. Auto-Warnungen) gesendet werden.",
    ("emergencyHandler", "alert_interface"): "Welches Radio (Interface 1, 2, …) für Notfall-Sendungen genutzt wird.",
    # ── sentry ──
    ("sentry", "SentryEnabled"): "True: Bot meldet, wenn unbekannte Knoten in SentryRadius auftauchen.",
    ("sentry", "SentryInterface"): "Radio-Interface für Sentry-Meldungen.",
    ("sentry", "SentryChannel"): "Kanal für Sentry-Nähe-Meldungen.",
    ("sentry", "emailSentryAlerts"): "True: Sentry-Ereignisse zusätzlich per E-Mail (SMTP nötig).",
    ("sentry", "detectionSensorAlert"): "True: Externer GPIO-Sensor kann Sentry auslösen.",
    ("sentry", "sentryIgnoreList"): "Knoten-IDs, die Sentry ignoriert (kommagetrennt).",
    ("sentry", "sentryWatchList"): "Nur diese Knoten überwachen; leer = alle außer Ignore-Liste.",
    ("sentry", "SentryRadius"): "Entfernung in Metern — innerhalb davon gilt ein Knoten als „in der Nähe“.",
    ("sentry", "SentryHoldoff"): "Pause zwischen Sentry-Meldungen (× ca. 20 Sekunden).",
    ("sentry", "cmdShellSentryAlerts"): "True: Bei Sentry wird ein Shell-Skript auf dem Server gestartet.",
    ("sentry", "sentryAlertNear"): "Shell-Skript bei „Knoten nähert sich“.",
    ("sentry", "sentryAlertAway"): "Shell-Skript bei „Knoten entfernt sich“.",
    ("sentry", "highFlyingAlert"): "True: Meldung bei Knoten über highFlyingAlertAltitude.",
    ("sentry", "highFlyingAlertAltitude"): "Höhe in Metern — darüber wird „Highfly“ gemeldet.",
    ("sentry", "highflyOpenskynetwork"): "True: Bei Highfly optional Flugzeug von OpenSky prüfen.",
    ("sentry", "highFlyingAlertInterface"): "Radio für Highfly-Meldungen.",
    ("sentry", "highFlyingAlertChannel"): "Kanal für Highfly-Meldungen (9 = praktisch aus).",
    ("sentry", "highFlyingIgnoreList"): "Knoten-IDs ohne Highfly-Alarm (z. B. Ballons).",
    # ── bbs ──
    ("bbs", "enabled"): "True: Mesh-BBS (bbspost, bbsread, …) ist aktiv.",
    ("bbs", "bbs_ban_list"): "Gesperrte Knoten — kein BBS, keine Admin-Befehle.",
    ("bbs", "bbs_admin_list"): "Knoten mit Admin-Rechten (BBS löschen, x:-Befehle, erweiterte Rechte).",
    ("bbs", "bbslink_enabled"): "True: BBS-Sync mit anderen Knoten (bbslink).",
    ("bbs", "bbslink_whitelist"): "Nur diese Knoten dürfen bbslink; leer = alle erlaubt.",
    ("bbs", "bbsAPI_enabled"): "True: Externe Skripte dürfen BBS per API ansprechen.",
    # ── polls ──
    ("polls", "enabled"): "True: Umfragen mit !poll im Mesh; Ergebnis im Admin unter Umfragen.",
    ("polls", "max_options"): "Maximal so viele Antwortoptionen pro Umfrage.",
    ("polls", "allow_revote"): "True: Gleiche Node darf Stimme ändern; False: nur eine Abstimmung.",
    # ── location ──
    ("location", "enabled"): "True: Standort-Befehle (wxc, loc, repeater, …) sind aktiv.",
    ("location", "lat"): "Ersatz-Breitengrad, wenn eine anfragende Node kein GPS in der NodeDB hat.",
    ("location", "lon"): "Ersatz-Längengrad ohne GPS der anfragenden Node.",
    ("location", "fuzzConfigLocation"): "True: Nur dieser Config-Standort wird leicht zufällig verfälscht (Privatsphäre).",
    ("location", "fuzzItAll"): "True: Alle Standortangaben in Antworten werden verfälscht.",
    ("location", "locations_db"): "Datei für gespeicherte öffentliche/private Orte (!loc save …).",
    ("location", "public_location_admin_manage"): "True: Nur Admins dürfen öffentliche Orte anlegen.",
    ("location", "delete_public_locations_admins_only"): "True: Nur Admins löschen öffentliche Orte.",
    ("location", "useMetric"): "True: Wetter und Maße in metrischen Einheiten; False: imperial.",
    ("location", "repeaterLookup"): "Repeater-Suche: rbook, artsci oder False = aus.",
    ("location", "n2yoAPIKey"): "API-Key für !satpass — sonst keine Satelliten-Vorhersage.",
    ("location", "satList"): "Standard-Satellit für !satpass ohne Nummer (NORAD-IDs, kommagetrennt).",
    ("location", "UseMeteoWxAPI"): "True: !wx nutzt Open-Meteo; False: NOAA (USA).",
    ("location", "metar_enabled"): "True: !metar liefert METAR des nächsten Flugplatzes zu deinem Standort.",
    ("location", "enableDEalerts"): "True: !warning und !dealert (NINA/Katwarn/DWD) sind verfügbar.",
    ("location", "deAlertAutoBroadcast"): "False: Warnungen nur auf Anfrage. True: Bot sendet aktiv in Kanäle.",
    ("location", "myRegionalKeysDE"): "Regionen für !dealert und Hintergrund-Abfrage (ARS, kommagetrennt).",
    ("location", "eAlertBroadcastCh"): "Zusätzliche Kanäle für automatische DE-Warnungen; leer = keine Extra-Kanäle.",
    ("location", "alertDuration"): "Minuten zwischen automatischen NINA-Abfragen im Hintergrund.",
    # ── checklist, inventory, qrz, repeater ──
    ("checklist", "enabled"): "True: Check-in/Check-out-System für Einsätze ist aktiv.",
    ("checklist", "checklist_db"): "SQLite-Datei für Checklisten-Daten.",
    ("checklist", "reverse_in_out"): "True: Vertauscht Bedeutung von Check-in und Check-out.",
    ("checklist", "auto_approve"): "True: Neue Checklisten-Einträge ohne manuelle Freigabe.",
    ("inventory", "enabled"): "True: Inventar-/POS-Befehle sind aktiv.",
    ("inventory", "inventory_db"): "SQLite-Datei für Inventar.",
    ("inventory", "disable_penny"): "True: Beträge auf 5-Cent-Schritte runden (USA-Modus).",
    ("qrz", "enabled"): "True: Neue Knoten erhalten automatisch eine QRZ-Hallo-Nachricht.",
    ("qrz", "qrz_db"): "Datei für QRZ-Hallo-Historie.",
    ("qrz", "qrz_hello_string"): "Text der automatischen Begrüßung neuer Knoten.",
    ("qrz", "training"): "True: QRZ-Hallo wird nicht wirklich gesendet (Test).",
    ("repeater", "enabled"): "True: Repeater-Modus — Nachrichten zwischen Kanälen/Interfaces weiterleiten.",
    ("repeater", "repeater_channels"): "Kanäle, die auf anderen Interfaces rebroadcastet werden (Vorsicht!).",
    # ── scheduler, broadcasts ──
    ("scheduler", "enabled"): "True: Zeitgesteuerte Kanal-Nachrichten laut value/interval/time.",
    ("scheduler", "interface"): "Radio-Interface für Scheduler-Sendungen.",
    ("scheduler", "channel"): "Zielkanal für Scheduler-Nachrichten.",
    ("scheduler", "message"): "Text der geplanten Nachricht (wenn schedulerMotd=False).",
    ("scheduler", "schedulerMotd"): "True: Statt message wird der MOTD-Text gesendet.",
    ("scheduler", "value"): "Was geplant wird: day, hour, weather, news, sysinfo, solar, custom, …",
    ("scheduler", "interval"): "Wiederholung: bei day=Tage, hour/min=Stunden/Minuten — siehe Scheduler-Doku.",
    ("scheduler", "time"): "Uhrzeit HH:MM für tägliche oder Wochentags-Jobs.",
    ("motdBroadcast", "enabled"): "True: MOTD wird automatisch in einen Kanal gesendet (unabhängig vom Scheduler).",
    ("motdBroadcast", "interface"): "Radio für automatischen MOTD-Versand.",
    ("motdBroadcast", "channel"): "Kanal für automatischen MOTD-Versand.",
    ("motdBroadcast", "mode"): "Rhythmus: day, hour, min oder Wochentag mon…sun.",
    ("motdBroadcast", "interval"): "Alle N Tage/Stunden/Minuten je nach mode.",
    ("motdBroadcast", "time"): "Uhrzeit für tägliche/Wochentags-Sendung.",
    ("newsBroadcast", "enabled"): "True: Inhalt von news.txt wird periodisch in einen Kanal gesendet.",
    ("newsBroadcast", "interface"): "Radio für News-Broadcast.",
    ("newsBroadcast", "channel"): "Kanal für News-Broadcast.",
    ("newsBroadcast", "mode"): "Rhythmus des News-Versands (z. B. hour).",
    ("newsBroadcast", "interval"): "Intervall in Stunden/Minuten je nach mode.",
    ("newsBroadcast", "time"): "Optional feste Uhrzeit für News-Versand.",
    # ── radioMon ──
    ("radioMon", "dxspotter_enabled"): "True: dx-Befehl für DX-Cluster-Daten.",
    ("radioMon", "sigWatchBroadcastInterface"): "Interface für Funk-Erkennungs-Alerts.",
    ("radioMon", "sigWatchBroadcastCh"): "Kanal(e) für Hamlib-Signal-Alerts (kommagetrennt).",
    ("radioMon", "enabled"): "True: Hamlib überwacht Funkverkehr und meldet starke Signale.",
    ("radioMon", "rigControlServerAddress"): "Adresse von rigctld (Hamlib), z. B. localhost:4532.",
    ("radioMon", "signalDetectionThreshold"): "Mindest-SNR in dB — darüber wird ein Alert ausgelöst.",
    ("radioMon", "signalHoldTime"): "Sekunden, die das Signal über dem Schwellwert bleiben muss.",
    ("radioMon", "signalCooldown"): "Sekunden Pause, bevor erneut gemeldet werden kann.",
    ("radioMon", "signalCycleLimit"): "Max. Meldungen pro Cooldown-Zyklus.",
    ("radioMon", "voxDetectionEnabled"): "True: Mikrofon-VOX erkennt Sprache und kann melden/antworten.",
    ("radioMon", "voxDescription"): "Kurztext in VOX-Meldungen.",
    ("radioMon", "useLocalVoxModel"): "True: Lokales KI-Modell statt Cloud für VOX.",
    ("radioMon", "voxLanguage"): "Sprache für Spracherkennung (z. B. de-de).",
    ("radioMon", "voxInputDevice"): "Audio-Eingabegerät für VOX (default = System-Standard).",
    ("radioMon", "voxOnTrapList"): "True: Bestimmte Wörter (voxTrapList) lösen Befehle aus.",
    ("radioMon", "voxTrapList"): "Kommagetrennte Trigger-Wörter für VOX.",
    ("radioMon", "voxEnableCmd"): "True: VOX darf Wetter/Witz-Befehle auslösen.",
    ("radioMon", "meshagesTTS"): "True: Eingehende Nachrichten können vorgelesen werden (TTS).",
    ("radioMon", "ttsChannels"): "Kanäle, deren Nachrichten per TTS vorgelesen werden.",
    ("radioMon", "wsjtxDetectionEnabled"): "True: WSJT-X-Decode per UDP werden gemeldet.",
    ("radioMon", "wsjtxUdpServerAddress"): "UDP-Adresse von WSJT-X (Standard 127.0.0.1:2237).",
    ("radioMon", "wsjtxWatchedCallsigns"): "Nur diese Rufzeichen melden; leer = alle.",
    ("radioMon", "js8callDetectionEnabled"): "True: JS8Call-Nachrichten werden ins Mesh weitergegeben.",
    ("radioMon", "js8callServerAddress"): "TCP-Adresse der JS8Call-API.",
    ("radioMon", "js8callWatchedCallsigns"): "Gefilterte Rufzeichen für JS8Call; leer = alle.",
    # ── fileMon ──
    ("fileMon", "filemon_enabled"): "True: Änderungen an alert.txt lösen eine Mesh-Nachricht aus.",
    ("fileMon", "file_path"): "Datei, deren Inhalt überwacht wird (z. B. data/alert.txt).",
    ("fileMon", "broadcastCh"): "Kanal(e) für FileMon-Alerts (kommagetrennt).",
    ("fileMon", "enable_read_news"): "True: news-Befehl liest news_file_path.",
    ("fileMon", "news_file_path"): "Textdatei für !news / News-Broadcast.",
    ("fileMon", "news_random_line"): "True: news liefert eine zufällige Zeile.",
    ("fileMon", "news_block_mode"): "True: news liefert einen zufälligen Absatz (leerzeilengetrennt).",
    ("fileMon", "enable_runShellCmd"): "True: sysinfo kann Shell-Daten anhängen (sysEnv.sh).",
    ("fileMon", "allowXcmd"): "True: Admins können x:Shell-Befehle per DM senden — Sicherheitsrisiko.",
    ("fileMon", "twoFactor_enabled"): "True: x:-Befehle brauchen 2FA-Bestätigung.",
    ("fileMon", "twoFactor_timeout"): "Sekunden, in denen die 2FA-Antwort gültig ist.",
    # ── smtp ──
    ("smtp", "enableSMTP"): "True: Bot kann E-Mails senden (Notfall, Sentry, …).",
    ("smtp", "enableImap"): "True: E-Mail-Empfang per IMAP (experimentell).",
    ("smtp", "sysopEmails"): "Empfänger-Adressen für Sysop-Mails, kommagetrennt.",
    ("smtp", "SMTP_SERVER"): "SMTP-Server-Hostname.",
    ("smtp", "SMTP_PORT"): "SMTP-Port (587 = STARTTLS).",
    ("smtp", "FROM_EMAIL"): "Absender-Adresse der Bot-Mails.",
    ("smtp", "SMTP_AUTH"): "True: Anmeldung am SMTP-Server erforderlich.",
    ("smtp", "SMTP_USERNAME"): "SMTP-Benutzername.",
    ("smtp", "SMTP_PASSWORD"): "SMTP-Passwort.",
    ("smtp", "EMAIL_SUBJECT"): "Betreffzeile für Bot-E-Mails.",
    ("smtp", "IMAP_SERVER"): "IMAP-Server für eingehende Mail.",
    ("smtp", "IMAP_PORT"): "IMAP-Port (993 = SSL).",
    ("smtp", "IMAP_USERNAME"): "IMAP-Benutzername.",
    ("smtp", "IMAP_PASSWORD"): "IMAP-Passwort.",
    ("smtp", "IMAP_FOLDER"): "IMAP-Ordner (z. B. inbox).",
    # ── messagingSettings ──
    ("messagingSettings", "responseDelay"): "Sekunden Wartezeit vor jeder Bot-Antwort (weniger Kollisionen).",
    ("messagingSettings", "splitDelay"): "Pause zwischen Teilen einer langen mehrteiligen Antwort.",
    ("messagingSettings", "MESSAGE_CHUNK_SIZE"): "Max. Zeichen pro Mesh-Nachrichtenteil.",
    ("messagingSettings", "wantAck"): "True: Bot fordert Empfangsbestätigung für gesendete Teile.",
    ("messagingSettings", "maxBuffer"): "Max. Bytes für Puffertest/Auto-Ping-Nachrichtenlänge.",
    ("messagingSettings", "enableHopLogs"): "True: Hop-Anzahl wird in Logs/Antworten detaillierter protokolliert.",
    ("messagingSettings", "noisyNodeLogging"): "True: Knoten mit viel Telemetrie werden im Log gemeldet.",
    ("messagingSettings", "noisyTelemetryLimit"): "Ab wie vielen Telemetrie-Paketen ein Knoten „laut“ ist.",
    ("messagingSettings", "logMetaStats"): "True: Metadaten-Statistiken werden geloggt.",
    ("messagingSettings", "logSimulatorPackets"): "True: Simulator-Pakete extra loggen (sehr verbose).",
    ("messagingSettings", "DEBUGpacket"): "True: Alle Pakete detailliert loggen.",
    ("messagingSettings", "debugMetadata"): "True: Metadaten-Pakete nach Filter loggen.",
    ("messagingSettings", "metadataFilter"): "Port-Typen, die beim Metadata-Debug ausgeblendet werden.",
    ("messagingSettings", "autoBanEnabled"): "True: Bei Spam automatisch in Ban-Liste.",
    ("messagingSettings", "autoBanThreshold"): "Wie viele Verstöße bis Auto-Ban.",
    ("messagingSettings", "apiThrottleValue"): "API-Aufrufe pro Node bis Drosselung greift.",
    ("messagingSettings", "autoBanTimeframe"): "Zeitfenster in Sekunden für Auto-Ban-Zählung.",
    ("messagingSettings", "cmdRateLimitEnabled"): "True: Zu viele Befehle pro Node werden abgewiesen.",
    ("messagingSettings", "cmdRateLimitMax"): "Max. Befehle pro Node im Zeitfenster.",
    ("messagingSettings", "cmdRateLimitWindow"): "Zeitfenster in Sekunden für Befehls-Rate-Limit.",
    # ── dataPersistence ──
    ("dataPersistence", "enabled"): "True: BBS/Umfragen/Leaderboard werden periodisch auf Disk gesichert.",
    ("dataPersistence", "interval"): "Sekunden zwischen automatischen Speicher-Läufen.",
    # ── webAdmin ──
    ("webAdmin", "enabled"): "True: Web-UI unter /admin (Login); / zeigt öffentliche Statistik.",
    ("webAdmin", "host"): "IP, an die der Webserver bindet (0.0.0.0 = von überall erreichbar).",
    ("webAdmin", "port"): "TCP-Port des Web-Admin (z. B. 5000).",
    ("webAdmin", "secret_key"): "Schlüssel für sichere Browser-Sessions (zufällig, geheim halten).",
    ("webAdmin", "username"): "Benutzername für Admin-Login.",
    ("webAdmin", "password"): "Passwort für Admin-Login.",
    ("webAdmin", "alert_file"): "Optional anderer Pfad für alert.txt im Admin-Editor.",
    ("webAdmin", "news_file"): "Optional anderer Pfad für news.txt im Admin-Editor.",
    ("webAdmin", "log_dir"): "Ordner für Log-Anzeige im Admin; leer = logs/ im Bot-Verzeichnis.",
}

# interface3…9 — gleiche Bedeutung wie interface2
for _n in range(3, 10):
    _sec = f"interface{_n}"
    BEHAVIOR.setdefault((_sec, "enabled"), f"Interface {_n} aktivieren.")
    BEHAVIOR.setdefault((_sec, "type"), f"Verbindungsart für Radio-Interface {_n}.")
    BEHAVIOR.setdefault((_sec, "port"), f"USB-Port für Interface {_n} (serial).")
    BEHAVIOR.setdefault((_sec, "hostname"), f"IP/Hostname für Interface {_n} (tcp).")
    BEHAVIOR.setdefault((_sec, "mac"), f"Bluetooth-MAC für Interface {_n} (ble).")

_SECTION_ENABLED: Dict[str, str] = {
    "interface2": "Schaltet das zweite Meshtastic-Radio ein oder aus.",
    "emergencyHandler": "Notfall-Erkennung in Nachrichten ein- oder ausschalten.",
    "bbs": "Gesamtes Mesh-BBS ein- oder ausschalten.",
    "polls": "Umfrage-Befehl !poll ein- oder ausschalten.",
    "location": "Standort-, Wetter- und Warn-Befehle ein- oder ausschalten.",
    "checklist": "Check-in-System ein- oder ausschalten.",
    "inventory": "Inventar-Befehle ein- oder ausschalten.",
    "qrz": "Automatische Begrüßung neuer Knoten ein- oder ausschalten.",
    "repeater": "Repeater-Weiterleitung ein- oder ausschalten.",
    "scheduler": "Zeitgesteuerte Nachrichten ein- oder ausschalten.",
    "motdBroadcast": "Automatischen MOTD-Kanal-Versand ein- oder ausschalten.",
    "newsBroadcast": "Automatischen News-Versand ein- oder ausschalten.",
    "radioMon": "Funk-Überwachung (Hamlib/VOX/WSJT) ein- oder ausschalten.",
    "fileMon": "Datei-Überwachung und Shell-Befehle ein- oder ausschalten.",
    "dataPersistence": "Automatisches Speichern von Bot-Daten ein- oder ausschalten.",
    "webAdmin": "Web-Admin-Oberfläche ein- oder ausschalten.",
}

_KEY_BEHAVIOR: Dict[str, str] = {
    "enabled": "Schaltet die zugehörige Funktion ein (True) oder komplett aus (False).",
    "interface": "Nummer des Meshtastic-Radios (1 = primär, 2 = zweites Gerät).",
    "channel": "Meshtastic-Kanalnummer, auf den der Bot sendet.",
    "interval": "Abstand zwischen Wiederholungen — Einheit hängt vom Modus/Scheduler ab.",
    "time": "Uhrzeit im Format HH:MM für geplante Sendungen.",
    "mode": "Zeitraster: day, hour, min oder Wochentag (mon…sun).",
    "message": "Nachrichtentext für den geplanten Versand.",
}


def _infer_behavior(section: str, key: str) -> str:
    """Letzter Fallback: aus Schlüsselname ableiten, ohne Config-Verweise."""
    k = key.lower()
    if "password" in k or "secret" in k or "apikey" in k or k.endswith("_key"):
        return "Geheimer Schlüssel oder Zugangsdaten — nur serverseitig schützen."
    if "url" in k or "hostname" in k or "address" in k:
        return "Netzwerk-Adresse oder URL für diese Funktion."
    if "path" in k or k.endswith("_db") or k.endswith("db"):
        return "Pfad zur Datendatei auf dem Server, die der Bot nutzt."
    if "list" in k or k.endswith("list"):
        return "Kommagetrennte Liste von Knoten-IDs oder Werten."
    if k.startswith("ignore") or "ban" in k:
        return "Einträge, die der Bot ignorieren oder sperren soll."
    if "threshold" in k or "limit" in k or "max" in k or "count" in k:
        return "Schwellwert oder Obergrenze für dieses Verhalten."
    if "delay" in k or "timeout" in k or "hold" in k:
        return "Zeit in Sekunden für Verzögerung oder Timeout."
    if "radius" in k or "altitude" in k:
        return "Entfernung oder Höhe in Metern als Auslöse-Schwelle."
    return f"Steuert Aspekt «{key}» im Modul [{section}] des Bots."


def field_tooltip(section: str, key: str) -> str:
    """Deutscher Tooltip: Auswirkung auf das Bot-Verhalten."""
    sk: TooltipKey = (section, key)
    if sk in BEHAVIOR:
        return BEHAVIOR[sk]
    if key == "enabled" and section in _SECTION_ENABLED:
        return _SECTION_ENABLED[section]
    if key in _KEY_BEHAVIOR and key not in {"enabled", "interface", "channel"}:
        return _KEY_BEHAVIOR[key]
    return _infer_behavior(section, key)
