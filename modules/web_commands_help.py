#!/usr/bin/env python3
"""Public Mesh-Befehls-Hilfe für das Web-Portal (Nutzer-Dokumentation)."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape as html_escape
from typing import Callable, List, Optional

import modules.settings as st


@dataclass(frozen=True)
class CommandEntry:
    cmd: str
    description: str
    example: str = ""
    enabled: Optional[Callable[[], bool]] = None


@dataclass(frozen=True)
class CommandSection:
    title: str
    icon: str
    intro: str
    commands: tuple[CommandEntry, ...]
    section_enabled: Optional[Callable[[], bool]] = None


def _prefix() -> str:
    return "!" if getattr(st, "cmdBang", False) else ""


def _cmd(
    cmd: str,
    description: str,
    *,
    enabled: Optional[Callable[[], bool]] = None,
) -> CommandEntry:
    """Eine Tabellenzeile pro Befehl oder Syntax-Variante."""
    return CommandEntry(cmd, description, enabled=enabled)


def _sections() -> List[CommandSection]:
    p = _prefix()

    return [
        CommandSection(
            "Grundlagen",
            "bi-lightning-charge",
            "Diese Befehle sind fast immer verfügbar. Sende sie im Mesh-Kanal oder per DM an den Bot.",
            (
                _cmd(f"{p}cmd", "Kurze Liste der auf deinem Bot aktivierten Befehle."),
                _cmd(
                    f"{p}cmd?",
                    "Hilfe zu einem Befehl (ersetze cmd durch den Befehlsnamen, z. B. metar?).",
                ),
                _cmd(
                    f"{p}ping",
                    "QSL-Antwort: LongName [NodeID] @ Bot-Standort | Hops LoRa/MQTT.",
                    enabled=lambda: getattr(st, "ping_enabled", True),
                ),
                _cmd(
                    f"{p}pong",
                    "Wie ping — QSL mit Ort, Hops und Verbindungstyp.",
                    enabled=lambda: getattr(st, "ping_enabled", True),
                ),
                _cmd(
                    f"{p}pinging",
                    "Alias für ping.",
                    enabled=lambda: getattr(st, "ping_enabled", True),
                ),
                _cmd(
                    f"{p}testing",
                    "Alias für ping.",
                    enabled=lambda: getattr(st, "ping_enabled", True),
                ),
                _cmd(
                    f"{p}test",
                    "Alias für ping.",
                    enabled=lambda: getattr(st, "ping_enabled", True),
                ),
                _cmd(
                    f"{p}cq",
                    "Alias für ping.",
                    enabled=lambda: getattr(st, "ping_enabled", True),
                ),
                _cmd(
                    f"{p}trace",
                    "Traceroute zu dir — Ergebnis (Hops, SNR) per DM.",
                    enabled=lambda: getattr(st, "ping_enabled", True),
                ),
                _cmd(
                    f"{p}trace MHH",
                    "Traceroute zu einer anderen Station (Kurzname, Dezimal-ID oder !hex).",
                    enabled=lambda: getattr(st, "ping_enabled", True),
                ),
                _cmd(
                    f"{p}echo",
                    "Echo-Test: Text nach dem Befehl wird zurückgesendet.",
                    enabled=lambda: getattr(st, "enableEcho", False),
                ),
                _cmd(
                    f"{p}echo Hallo",
                    "Beispiel für echo mit beliebigem Text.",
                    enabled=lambda: getattr(st, "enableEcho", False),
                ),
                _cmd(
                    f"{p}motd",
                    "Message of the Day — Begrüßungstext des Bots.",
                    enabled=lambda: getattr(st, "motd_enabled", True),
                ),
            ),
        ),
        CommandSection(
            "Knoten & Position",
            "bi-geo-alt",
            (
                "Standortdaten stammen aus der Meshtastic-NodeDB (GPS am Gerät). Ohne GPS kann der Bot keine "
                "Koordinaten liefern.\n\n"
                f"Entfernungen messen: Mit aktivem GPS sendest du {p}map <Name> — der Bot antwortet mit Richtung "
                "und Distanz zu einem zuvor gespeicherten Ort (bezogen auf deine aktuelle Position). "
                f"{p}howfar summiert die zurückgelegte Strecke seit dem letzten Aufruf (erneut senden aktualisiert "
                f"den Zähler; {p}howfar reset setzt den Startpunkt zurück).\n\n"
                f"Standorte speichern: An der gewünschten Position {p}map save <Name> [Beschreibung] (nur für dich) "
                f"oder {p}map save public <Name> [Beschreibung] (für alle). {p}map list zeigt deine Einträge, "
                f"{p}map delete <Name> entfernt einen Ort. {p}map public <Name> fragt einen öffentlichen Ort ab."
            ),
            (
                _cmd(
                    f"{p}whoami",
                    "Infos zu deiner Node: ID, Name, Signal, ggf. letzte GPS-Koordinaten.",
                    enabled=lambda: getattr(st, "whoami_enabled", True),
                ),
                _cmd(
                    f"{p}whois",
                    "Infos zu einer anderen Node (ohne Argument: Kurzinfo).",
                    enabled=lambda: getattr(st, "whoami_enabled", True),
                ),
                _cmd(
                    f"{p}whois Kurzname",
                    "Infos zu einer bestimmten Node (Name, Dezimal-ID oder !hex). Admins sehen mehr.",
                    enabled=lambda: getattr(st, "whoami_enabled", True),
                ),
                _cmd(
                    f"{p}loc",
                    "Letzte Position inkl. übertragener Höhe (m/ft), aus NodeDB oder Mesh-Karten-JSON.",
                    enabled=lambda: getattr(st, "location_enabled", False),
                ),
                _cmd(
                    f"{p}loc Kurzname",
                    "Position einer anderen Node (Name/ID).",
                    enabled=lambda: getattr(st, "location_enabled", False),
                ),
                _cmd(
                    f"{p}whereami",
                    "Ortstext zu deiner Position (Geocoding), plus Höhe falls übertragen.",
                    enabled=lambda: getattr(st, "location_enabled", False),
                ),
                _cmd(
                    f"{p}map save Name",
                    "Aktuelle Position privat speichern (optional Beschreibung).",
                    enabled=lambda: getattr(st, "location_enabled", False),
                ),
                _cmd(
                    f"{p}map save public Name",
                    "Aktuelle Position öffentlich speichern (für alle sichtbar).",
                    enabled=lambda: getattr(st, "location_enabled", False),
                ),
                _cmd(
                    f"{p}map list",
                    "Gespeicherte Orte auflisten.",
                    enabled=lambda: getattr(st, "location_enabled", False),
                ),
                _cmd(
                    f"{p}map Name",
                    "Entfernung und Richtung zu einem gespeicherten Ort (von deiner GPS-Position).",
                    enabled=lambda: getattr(st, "location_enabled", False),
                ),
                _cmd(
                    f"{p}map public Name",
                    "Öffentlichen Ort abfragen (Entfernung/Richtung).",
                    enabled=lambda: getattr(st, "location_enabled", False),
                ),
                _cmd(
                    f"{p}map delete Name",
                    "Eigenen gespeicherten Ort löschen.",
                    enabled=lambda: getattr(st, "location_enabled", False),
                ),
                _cmd(
                    f"{p}howfar",
                    "Zurückgelegte Strecke seit dem letzten Aufruf (erneuter Aufruf aktualisiert den Zähler).",
                    enabled=lambda: getattr(st, "location_enabled", False),
                ),
                _cmd(
                    f"{p}howfar reset",
                    "Startpunkt für die Streckenmessung zurücksetzen.",
                    enabled=lambda: getattr(st, "location_enabled", False),
                ),
            ),
            section_enabled=lambda: getattr(st, "location_enabled", False)
            or getattr(st, "whoami_enabled", True),
        ),
        CommandSection(
            "Wetter & Warnungen (DE/EU)",
            "bi-cloud-lightning-rain",
            "Wetter über Open-Meteo. Warnungen über warnung.bund.de (NINA/Katwarn/DWD).",
            (
                _cmd(
                    f"{p}wx",
                    "Wettervorhersage für deinen Standort (Open-Meteo).",
                    enabled=lambda: getattr(st, "location_enabled", False)
                    and getattr(st, "use_meteo_wxApi", True),
                ),
                _cmd(
                    f"{p}metar",
                    "METAR des nächsten Flugplatzes zu deinem Standort.",
                    enabled=lambda: getattr(st, "location_enabled", False)
                    and getattr(st, "metar_enabled", True),
                ),
                _cmd(
                    f"{p}metar EDDF",
                    "METAR für einen ICAO-Flugplatz (4 Buchstaben, z. B. EDDF, ETHF).",
                    enabled=lambda: getattr(st, "location_enabled", False)
                    and getattr(st, "metar_enabled", True),
                ),
                _cmd(
                    f"{p}metar?",
                    "Erklärung des Aufbaus einer METAR-Meldung.",
                    enabled=lambda: getattr(st, "location_enabled", False)
                    and getattr(st, "metar_enabled", True),
                ),
                _cmd(
                    f"{p}uv",
                    "UV-Index heute und morgen für deinen Standort (Open-Meteo).",
                    enabled=lambda: getattr(st, "location_enabled", False)
                    and getattr(st, "use_meteo_wxApi", True)
                    and getattr(st, "wx_extra_commands", True),
                ),
                _cmd(
                    f"{p}regen",
                    "Stündlicher Regen für die nächsten Stunden (Open-Meteo).",
                    enabled=lambda: getattr(st, "location_enabled", False)
                    and getattr(st, "use_meteo_wxApi", True)
                    and getattr(st, "wx_extra_commands", True),
                ),
                _cmd(
                    f"{p}blitz",
                    "Live-Blitze im Umkreis (DMI EU; optional Blitzortung.org) plus kurze Gewitter-Vorhersage.",
                    enabled=lambda: getattr(st, "location_enabled", False)
                    and getattr(st, "use_meteo_wxApi", True)
                    and getattr(st, "wx_extra_commands", True),
                ),
                _cmd(
                    f"{p}warning",
                    "Aktive Warnungen für den Kreis deiner GPS-Position.",
                    enabled=lambda: getattr(st, "enableDEalerts", False),
                ),
                _cmd(
                    f"{p}dealert",
                    "Warnungen für konfigurierte Regionen (Broadcast).",
                    enabled=lambda: getattr(st, "enableDEalerts", False),
                ),
            ),
            section_enabled=lambda: getattr(st, "location_enabled", False)
            or getattr(st, "enableDEalerts", False),
        ),
        CommandSection(
            "Repeater & Himmel",
            "bi-broadcast",
            "",
            (
                CommandEntry(
                    f"{p}rlist",
                    "Repeater in der Nähe deines Standorts.",
                    enabled=lambda: getattr(st, "location_enabled", False)
                    and bool(getattr(st, "repeater_lookup", False)),
                ),
                CommandEntry(
                    f"{p}sun",
                    "Sonnenauf-/untergang.",
                    enabled=lambda: getattr(st, "solar_conditions_enabled", False),
                ),
                CommandEntry(
                    f"{p}moon",
                    "Mondphase.",
                    enabled=lambda: getattr(st, "solar_conditions_enabled", False),
                ),
                CommandEntry(
                    f"{p}solar",
                    "Weltraumwetter / Sonnenaktivität.",
                    enabled=lambda: getattr(st, "solar_conditions_enabled", False),
                ),
                CommandEntry(
                    f"{p}hfcond",
                    "HF-Bandenbedingungen.",
                    enabled=lambda: getattr(st, "solar_conditions_enabled", False),
                ),
                CommandEntry(
                    f"{p}satpass",
                    "Nächster Satellitenüberflug (N2YO-API-Key nötig).",
                    enabled=lambda: getattr(st, "solar_conditions_enabled", False)
                    and bool(getattr(st, "n2yoAPIKey", "")),
                ),
            ),
            section_enabled=lambda: getattr(st, "location_enabled", False)
            or getattr(st, "solar_conditions_enabled", False),
        ),
        CommandSection(
            "Bulletin Board (BBS)",
            "bi-inboxes",
            (
                "Öffentliches BBS (bbsdb) und private BBS-DMs (bbsdm, Store-and-Forward). "
                "DMs werden zugestellt, sobald die Ziel-Node wieder im Mesh aktiv ist (Präfix „Mail:“)."
            ),
            (
                _cmd(f"{p}bbshelp", "Kurzliste aller BBS-Befehle (auch im Mesh)."),
                _cmd(f"{p}bbslist", "Öffentliche Beiträge mit Nummern [#1], [#2], …"),
                _cmd(
                    f"{p}bbspost $Betreff #Text",
                    "Öffentlichen Beitrag schreiben ($ = Betreff, # = Text).",
                ),
                _cmd(
                    f"{p}bbspost @Empfänger #Text",
                    "Private BBS-DM an eine Node (Empfänger: Kurzname, Dezimal-ID oder !hex).",
                ),
                _cmd(
                    f"{p}bbsread #Nr",
                    "Öffentlichen Beitrag anhand der Nummer aus bbslist lesen.",
                ),
                _cmd(
                    f"{p}bbsdelete #Nr",
                    "Eigenen öffentlichen Beitrag löschen (Admins: alle Beiträge).",
                ),
                _cmd(
                    f"{p}bbsinfo",
                    "Anzahl öffentlicher Beiträge und wartender BBS-DMs.",
                ),
                _cmd(
                    f"{p}ping @Kurzname",
                    "Kurze BBS-DM an eine Node (wenn BBS aktiv; gleiche Queue wie bbspost @…).",
                ),
                _cmd(
                    f"{p}bbslink",
                    "Bot-zu-Bot-Sync: öffentliche Beiträge anfragen (Whitelist, bbslink_enabled).",
                    enabled=lambda: getattr(st, "bbs_link_enabled", False),
                ),
                _cmd(
                    f"{p}bbslink 0",
                    "Sync ab Beitrags-ID 0 (alle öffentlichen Beiträge vom Peer-Bot).",
                    enabled=lambda: getattr(st, "bbs_link_enabled", False),
                ),
                _cmd(
                    f"{p}bbsack",
                    "Bestätigung beim bbslink-Sync (Antwort auf die nächste Nachricht vom Peer-Bot).",
                    enabled=lambda: getattr(st, "bbs_link_enabled", False),
                ),
            ),
            section_enabled=lambda: getattr(st, "bbs_enabled", False),
        ),
        CommandSection(
            "Umfragen",
            "bi-bar-chart-steps",
            "Abstimmungen im Mesh. Anlegen und Auswertung im Admin-Backend unter „Umfragen“.",
            (
                _cmd(
                    f"{p}poll",
                    "Aktive Umfragen anzeigen.",
                    enabled=lambda: getattr(st, "polls_enabled", False),
                ),
                _cmd(
                    f"{p}poll liste",
                    "Alle Umfragen (auch geschlossene).",
                    enabled=lambda: getattr(st, "polls_enabled", False),
                ),
                _cmd(
                    f"{p}poll 1",
                    "Frage, Optionen und Stimmenzahlen der Umfrage Nr. 1.",
                    enabled=lambda: getattr(st, "polls_enabled", False),
                ),
                _cmd(
                    f"{p}poll 1 2",
                    "Für Umfrage 1 Option 2 wählen (eine Stimme pro Knoten).",
                    enabled=lambda: getattr(st, "polls_enabled", False),
                ),
            ),
            section_enabled=lambda: getattr(st, "polls_enabled", False),
        ),
        CommandSection(
            "Nachrichten & Feeds",
            "bi-newspaper",
            "",
            (
                CommandEntry(
                    f"{p}readnews",
                    "Text aus der News-Datei des Bots.",
                    enabled=lambda: getattr(st, "read_news_enabled", False),
                ),
                CommandEntry(
                    f"{p}readrss",
                    "RSS-Feed-Auszug.",
                    enabled=lambda: getattr(st, "rssEnable", False),
                ),
                CommandEntry(
                    f"{p}latest",
                    "Schlagzeilen (NewsAPI.org, API-Key nötig).",
                    enabled=lambda: getattr(st, "enableNewsAPI", False),
                ),
            ),
        ),
        CommandSection(
            "Netz & Status",
            "bi-hdd-network",
            "",
            (
                _cmd(
                    f"{p}sysinfo",
                    "Systeminfos zum Bot-Host.",
                    enabled=lambda: getattr(st, "sitrep_enabled", False),
                ),
                _cmd(
                    f"{p}sitrep",
                    "Zuletzt gehörte Knoten / Lagebild.",
                    enabled=lambda: getattr(st, "sitrep_enabled", False),
                ),
                _cmd(
                    f"{p}lheard",
                    "Knoten-Liste (ähnlich Sitrep).",
                    enabled=lambda: getattr(st, "sitrep_enabled", False),
                ),
                _cmd(
                    f"{p}leaderboard",
                    "Extremwerte aus dem Mesh (Temperatur, Akku, Höhe; optional regionale Karten-JSON).",
                    enabled=lambda: getattr(st, "sitrep_enabled", False),
                ),
                _cmd(
                    f"{p}leaderboard reset",
                    "Leaderboard-Liste löschen (nur Admins).",
                    enabled=lambda: getattr(st, "sitrep_enabled", False),
                ),
                _cmd(
                    f"{p}messages",
                    "Letzte Nachrichten von Kanal 1 (Meshhessen, messagesChannel), ohne Bot-Befehle.",
                ),
                _cmd(
                    f"{p}history",
                    "Verlauf deiner letzten Befehle.",
                    enabled=lambda: getattr(st, "enableCmdHistory", False),
                ),
            ),
        ),
        CommandSection(
            "DX-Cluster",
            "bi-antenna",
            "",
            (
                _cmd(
                    f"{p}dx",
                    "DX-Spots abfragen (alle oder gefiltert).",
                    enabled=lambda: getattr(st, "dxspotter_enabled", True),
                ),
                _cmd(
                    f"{p}dx band=20m",
                    "DX-Spots nur für ein Band (z. B. band=20m, band=40m).",
                    enabled=lambda: getattr(st, "dxspotter_enabled", True),
                ),
            ),
            section_enabled=lambda: getattr(st, "dxspotter_enabled", True),
        ),
        CommandSection(
            "KI-Assistent",
            "bi-robot",
            "Benötigt lokalen Ollama-Server.",
            (
                _cmd(f"{p}ask:", "Frage an das lokale LLM (Text direkt nach dem Doppelpunkt)."),
                _cmd(
                    f"{p}ask: Was ist Meshtastic?",
                    "Beispiel: Frage an Ollama mit freiem Text.",
                ),
                _cmd(f"{p}askai", "Alternative Trigger für dasselbe LLM."),
            ),
            section_enabled=lambda: getattr(st, "llm_enabled", False),
        ),
        CommandSection(
            "Inventar & Checkliste",
            "bi-clipboard-check",
            "Optionale Module für Veranstaltungen / Lagerverwaltung.",
            (
                _cmd(
                    f"{p}checkin",
                    "Check-in (Checklisten-Modul).",
                    enabled=lambda: getattr(st, "checklist_enabled", False),
                ),
                _cmd(
                    f"{p}checkout",
                    "Check-out (Checklisten-Modul).",
                    enabled=lambda: getattr(st, "checklist_enabled", False),
                ),
                _cmd(
                    f"{p}checklist",
                    "Checklisten-Status anzeigen.",
                    enabled=lambda: getattr(st, "checklist_enabled", False),
                ),
                _cmd(
                    f"{p}approvecl",
                    "Checkliste genehmigen (Admin/Moderation).",
                    enabled=lambda: getattr(st, "checklist_enabled", False),
                ),
                _cmd(
                    f"{p}denycl",
                    "Checkliste ablehnen.",
                    enabled=lambda: getattr(st, "checklist_enabled", False),
                ),
                _cmd(
                    f"{p}itemlist",
                    "Inventarliste anzeigen.",
                    enabled=lambda: getattr(st, "inventory_enabled", False),
                ),
                _cmd(
                    f"{p}item",
                    "Artikel-Details abfragen.",
                    enabled=lambda: getattr(st, "inventory_enabled", False),
                ),
                _cmd(
                    f"{p}itemloan",
                    "Artikel ausleihen.",
                    enabled=lambda: getattr(st, "inventory_enabled", False),
                ),
                _cmd(
                    f"{p}itemreturn",
                    "Ausgeliehenen Artikel zurückgeben.",
                    enabled=lambda: getattr(st, "inventory_enabled", False),
                ),
                _cmd(
                    f"{p}itemsell",
                    "Artikel verkaufen (Mini-POS).",
                    enabled=lambda: getattr(st, "inventory_enabled", False),
                ),
                _cmd(
                    f"{p}itemadd",
                    "Artikel zum Inventar hinzufügen.",
                    enabled=lambda: getattr(st, "inventory_enabled", False),
                ),
                _cmd(
                    f"{p}itemremove",
                    "Artikel aus dem Inventar entfernen.",
                    enabled=lambda: getattr(st, "inventory_enabled", False),
                ),
                _cmd(
                    f"{p}cartadd",
                    "Artikel in den Warenkorb legen.",
                    enabled=lambda: getattr(st, "inventory_enabled", False),
                ),
                _cmd(
                    f"{p}cartlist",
                    "Warenkorb anzeigen.",
                    enabled=lambda: getattr(st, "inventory_enabled", False),
                ),
                _cmd(
                    f"{p}cartbuy",
                    "Warenkorb kaufen (Mini-POS).",
                    enabled=lambda: getattr(st, "inventory_enabled", False),
                ),
                _cmd(
                    f"{p}cartclear",
                    "Warenkorb leeren.",
                    enabled=lambda: getattr(st, "inventory_enabled", False),
                ),
            ),
            section_enabled=lambda: getattr(st, "checklist_enabled", False)
            or getattr(st, "inventory_enabled", False),
        ),
        CommandSection(
            "Notfall-Stichworte",
            "bi-exclamation-triangle",
            "Löst eine Notfall-Antwort aus — nur in echten Notfällen verwenden.",
            (
                CommandEntry(f"{p}112", "Notfall-Hinweis (EU)."),
                CommandEntry(f"{p}emergency", "Notfall-Hinweis."),
                CommandEntry(f"{p}police", "Notfall-Hinweis."),
                CommandEntry(f"{p}fire", "Notfall-Hinweis."),
                CommandEntry(f"{p}ambulance", "Notfall-Hinweis."),
            ),
            section_enabled=lambda: getattr(st, "emergency_responder_enabled", False),
        ),
    ]


def _entry_enabled(entry: CommandEntry) -> bool:
    if entry.enabled is None:
        return True
    try:
        return bool(entry.enabled())
    except Exception:
        return False


def _section_visible(section: CommandSection) -> bool:
    if section.section_enabled is not None:
        try:
            if not section.section_enabled():
                return False
        except Exception:
            return False
    return any(_entry_enabled(e) for e in section.commands)


def _render_entry_row(entry: CommandEntry) -> str:
    if not _entry_enabled(entry):
        return ""
    cmd = html_escape(entry.cmd)
    desc = html_escape(entry.description)
    ex = ""
    if entry.example:
        ex = f' <code class="cmd-help-example">{html_escape(entry.example)}</code>'
    return f"<tr><td class=\"cmd-help-cmd\"><code>{cmd}</code></td><td>{desc}{ex}</td></tr>"


def render_commands_page_body() -> str:
    """HTML body (inside portal wrapper) for /befehle."""
    p = html_escape(_prefix())
    bang = getattr(st, "cmdBang", False)
    explicit = getattr(st, "explicitCmd", True)
    if bang and explicit:
        usage = (
            "Sende Befehle mit <strong>!</strong> am Anfang, z. B. <code>!ping</code>. "
            "Nur Zeilen, die mit einem bekannten Befehl beginnen, werden verarbeitet."
        )
    elif bang:
        usage = "Befehle mit <strong>!</strong>, z. B. <code>!cmd</code>."
    else:
        usage = "Befehle ohne Ausrufezeichen, z. B. <code>ping</code> (je nach Bot-Konfiguration)."

    intro = f"""
<div class="cmd-help-intro portal-card p-4 mb-4">
  <h1 class="h3 section-title mb-3">
    <i class="bi bi-terminal text-success me-2"></i>Mesh-Befehle
  </h1>
  <p class="text-muted mb-0">{usage}</p>
</div>
"""

    parts: List[str] = [intro, '<div class="accordion cmd-help-accordion" id="cmdHelpAccordion">']
    sec_idx = 0
    for section in _sections():
        if not _section_visible(section):
            continue
        rows = "".join(_render_entry_row(e) for e in section.commands)
        if not rows.strip():
            continue
        collapse_id = f"cmdSec{sec_idx}"
        expanded = sec_idx == 0
        sec_idx += 1
        title = html_escape(section.title)
        icon = html_escape(section.icon)
        sec_intro = ""
        if section.intro:
            sec_intro = f'<p class="text-muted small mb-3">{html_escape(section.intro)}</p>'
        btn_cls = "" if expanded else " collapsed"
        show_cls = " show" if expanded else ""
        parts.append(
            f"""
<div class="accordion-item portal-card border mb-2 overflow-hidden">
  <h2 class="accordion-header">
    <button class="accordion-button{btn_cls}" type="button"
            data-bs-toggle="collapse" data-bs-target="#{collapse_id}"
            aria-expanded="{"true" if expanded else "false"}" aria-controls="{collapse_id}">
      <i class="bi {icon} text-success me-2"></i>{title}
    </button>
  </h2>
  <div id="{collapse_id}" class="accordion-collapse collapse{show_cls}"
       data-bs-parent="#cmdHelpAccordion">
    <div class="accordion-body pt-0">
      {sec_intro}
      <div class="table-responsive">
        <table class="table table-sm table-hover cmd-help-table mb-0">
          <thead><tr><th>Befehl</th><th>Beschreibung</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </div>
  </div>
</div>
"""
        )

    parts.append("</div>")
    if sec_idx == 0:
        parts.append(
            '<p class="text-muted portal-card p-4">Keine Befehlsmodule aktiv — prüfe <code>config.ini</code>.</p>'
        )
    return "\n".join(parts)
