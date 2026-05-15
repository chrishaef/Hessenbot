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


def _sections() -> List[CommandSection]:
    p = _prefix()

    return [
        CommandSection(
            "Grundlagen",
            "bi-lightning-charge",
            "Diese Befehle sind fast immer verfügbar. Sende sie im Mesh-Kanal oder per DM an den Bot.",
            (
                CommandEntry(f"{p}cmd", "Kurze Liste der auf deinem Bot aktivierten Befehle."),
                CommandEntry(
                    f"{p}ping",
                    "Testet die Verbindung; Antwort mit SNR, RSSI und Hop-Anzahl.",
                    f"{p}ping",
                    enabled=lambda: getattr(st, "ping_enabled", True),
                ),
                CommandEntry(
                    f"{p}pong",
                    "Kurze Ping-Antwort.",
                    enabled=lambda: getattr(st, "ping_enabled", True),
                ),
                CommandEntry(
                    f"{p}echo",
                    "Gibt deinen Text zurück (Echo-Test).",
                    f"{p}echo Hallo",
                    enabled=lambda: getattr(st, "enableEcho", False),
                ),
                CommandEntry(
                    f"{p}motd",
                    "Message of the Day — Begrüßungstext des Bots.",
                    enabled=lambda: getattr(st, "motd_enabled", True),
                ),
            ),
        ),
        CommandSection(
            "Knoten & Position",
            "bi-geo-alt",
            "Standortdaten kommen aus der Meshtastic-NodeDB (GPS der Knoten). Ohne GPS meldet der Bot das.",
            (
                CommandEntry(
                    f"{p}whoami",
                    "Infos zu deiner Node: ID, Name, Signal, ggf. letzte GPS-Koordinaten.",
                    enabled=lambda: getattr(st, "whoami_enabled", True),
                ),
                CommandEntry(
                    f"{p}whois",
                    "Infos zu einer anderen Node (Name/ID). Admins sehen mehr Details.",
                    f"{p}whois Kurzname",
                    enabled=lambda: getattr(st, "whoami_enabled", True),
                ),
                CommandEntry(
                    f"{p}loc",
                    "Letzte GPS-Position aus der NodeDB (eigene Node oder Name/!hex/Dezimal-ID).",
                    f"{p}loc HB9ABC",
                    enabled=lambda: getattr(st, "location_enabled", False),
                ),
                CommandEntry(
                    f"{p}whereami",
                    "Ortstext zu deiner aktuellen Position (Geocoding).",
                    enabled=lambda: getattr(st, "location_enabled", False),
                ),
                CommandEntry(
                    f"{p}map",
                    "Gespeicherte Orte: speichern, Entfernung/Richtung, Liste.",
                    f"{p}map help",
                    enabled=lambda: getattr(st, "location_enabled", False),
                ),
                CommandEntry(
                    f"{p}howfar",
                    "Zurückgelegte Strecke seit dem letzten GPS-Punkt (Tracking).",
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
                CommandEntry(
                    f"{p}wx",
                    "Wettervorhersage für deinen Standort.",
                    enabled=lambda: getattr(st, "location_enabled", False)
                    and getattr(st, "use_meteo_wxApi", True),
                ),
                CommandEntry(
                    f"{p}wxc",
                    "Wetter in metrischen Einheiten.",
                    enabled=lambda: getattr(st, "use_meteo_wxApi", True),
                ),
                CommandEntry(
                    f"{p}warning",
                    "Aktive Warnungen für den Kreis deiner GPS-Position.",
                    enabled=lambda: getattr(st, "enableDEalerts", False),
                ),
                CommandEntry(
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
            "Öffentliche Notizen und Bot-zu-Bot-Sync im Mesh.",
            (
                CommandEntry(f"{p}bbshelp", "Hilfe zu allen BBS-Befehlen."),
                CommandEntry(f"{p}bbslist", "Liste der BBS-Beiträge."),
                CommandEntry(f"{p}bbspost", "Neuen Beitrag.", f"{p}bbspost $Titel #Text"),
                CommandEntry(f"{p}bbsread", "Beitrag lesen.", f"{p}bbsread 1"),
                CommandEntry(f"{p}bbsdelete", "Eigene Beiträge löschen."),
                CommandEntry(f"{p}bbslink", "BBS mit anderen Bots synchronisieren."),
                CommandEntry(f"{p}bbsinfo", "Statistik zum BBS."),
            ),
            section_enabled=lambda: getattr(st, "bbs_enabled", False),
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
                CommandEntry(f"{p}verse", "Zufälliger Bibelvers (wenn bible.txt vorhanden)."),
            ),
        ),
        CommandSection(
            "Netz & Status",
            "bi-hdd-network",
            "",
            (
                CommandEntry(
                    f"{p}sysinfo",
                    "Systeminfos zum Bot-Host.",
                    enabled=lambda: getattr(st, "sitrep_enabled", False),
                ),
                CommandEntry(
                    f"{p}sitrep",
                    "Zuletzt gehörte Knoten / Lagebild.",
                    enabled=lambda: getattr(st, "sitrep_enabled", False),
                ),
                CommandEntry(
                    f"{p}lheard",
                    "Knoten-Liste (ähnlich Sitrep).",
                    enabled=lambda: getattr(st, "sitrep_enabled", False),
                ),
                CommandEntry(
                    f"{p}leaderboard",
                    "Aktivitäts-Rangliste.",
                    enabled=lambda: getattr(st, "sitrep_enabled", False),
                ),
                CommandEntry(f"{p}messages", "Letzte empfangene Nachrichten."),
                CommandEntry(
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
                CommandEntry(
                    f"{p}dx",
                    "DX-Spots abfragen.",
                    f"{p}dx band=20m",
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
                CommandEntry(f"{p}ask:", "Frage an das lokale LLM.", f"{p}ask: Was ist Meshtastic?"),
                CommandEntry(f"{p}askai", "Alternative Trigger für LLM."),
            ),
            section_enabled=lambda: getattr(st, "llm_enabled", False),
        ),
        CommandSection(
            "Inventar & Checkliste",
            "bi-clipboard-check",
            "Optionale Module für Veranstaltungen / Lagerverwaltung.",
            (
                CommandEntry(
                    f"{p}checklist",
                    "Check-in/out und Genehmigungen.",
                    enabled=lambda: getattr(st, "checklist_enabled", False),
                ),
                CommandEntry(
                    f"{p}itemlist",
                    "Inventar / Mini-POS (weitere item*-Befehle).",
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
  <p class="text-muted mb-2">{usage}</p>
  <p class="text-muted small mb-0">
    Übersicht der <strong>Hessenbot</strong>-Funktionen für Mesh-Nutzer.
    Aktive Befehle hängen von <code>config.ini</code> ab — Kurzliste im Feld mit
    <code>{p}cmd</code>. Antworten sind oft auf ca. 160 Zeichen begrenzt.
  </p>
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
