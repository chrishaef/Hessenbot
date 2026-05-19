#!/usr/bin/env python3
"""FAQ / Hilfe für Mesh-Nutzer (öffentliches Web-Portal)."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape as html_escape
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class FaqEntry:
    problem: str
    solution: str


@dataclass(frozen=True)
class FaqSection:
    title: str
    icon: str
    intro: str
    entries: Tuple[FaqEntry, ...]


def _sections() -> List[FaqSection]:
    return [
        FaqSection(
            "Keine Antwort vom Bot",
            "bi-chat-dots",
            (
                "Du hast einen Befehl gesendet, aber in der Meshtastic-App kommt nichts an? "
                "Oft liegt es an Direktnachrichten (DM), Verschlüsselung oder am Rückweg im Mesh — "
                "nicht daran, dass der Bot „offline“ wäre."
            ),
            (
                FaqEntry(
                    "Keine Antwort, obwohl andere den Bot erreichen",
                    (
                        "Sehr häufig ab Firmware 2.6+: <strong>veralteter Kontakt oder DM-Schlüssel (PKI)</strong>. "
                        "Lösung auf <strong>deinem Gerät</strong>: Bot in der Kontaktliste "
                        "<strong>löschen</strong> und <strong>neu hinzufügen</strong>, oder den Bot als "
                        "<strong>Favorit</strong> setzen, kurz warten, dann erneut eine DM senden "
                        "(z. B. <code>!ping</code>)."
                    ),
                ),
                FaqEntry(
                    "Befehl im Kanal gesendet — im Kanal keine Antwort",
                    (
                        "Viele Bots antworten auf Kanal-Befehle mit einer <strong>Direktnachricht (DM)</strong>. "
                        "Öffne in der App das <strong>DM-Postfach</strong> zum Bot-Knoten, nicht nur den Kanal."
                    ),
                ),
                FaqEntry(
                    "Weit entfernt vom Bot — nah dagegen klappt es",
                    (
                        "Dein Befehl muss den Bot erreichen <strong>und</strong> die Antwort muss zu dir zurück. "
                        "Über ein Internet-Gateway (MQTT) kann der Hinweg klappen, der Rückweg über Funk aber nicht. "
                        "Kurz testen, ob du den Bot per DM von einer näheren Position erreichst. "
                        "Zusätzlich PKI-Kontakt erneuern (siehe oben)."
                    ),
                ),
            ),
        ),
        FaqSection(
            "Befehle werden ignoriert",
            "bi-terminal",
            "",
            (
                FaqEntry(
                    "Bot reagiert gar nicht",
                    (
                        "Befehle beginnen meist mit <strong>!</strong>, z. B. <code>!ping</code> oder <code>!cmd</code>. "
                        "Nur die Zeile senden, die mit dem Befehl beginnt — kein Text davor. "
                        "Welche Befehle dieser Bot unterstützt, steht unter "
                        '<a href="/befehle">Befehle</a> und mit <code>!cmd</code> im Mesh.'
                    ),
                ),
                FaqEntry(
                    "„Bitte etwas langsamer“",
                    "Du hast zu viele Befehle in kurzer Zeit gesendet. Einige Sekunden warten und erneut versuchen.",
                ),
                FaqEntry(
                    "Im öffentlichen Standardkanal (ShortSlow) keine Reaktion",
                    (
                        "Dieser Bot hört <strong>nicht</strong> auf den öffentlichen Standardkanal. "
                        "Befehle bitte im <strong>MeshHessen Kanal</strong> senden oder als "
                        "<strong>DM</strong> direkt an den Bot richten."
                    ),
                ),
                FaqEntry(
                    "Hilfe zu einem Befehl",
                    (
                        "Viele Befehle erklären sich mit <strong>?</strong> am Ende, "
                        "z. B. <code>!metar?</code> oder <code>!cmd?</code>."
                    ),
                ),
            ),
        ),
        FaqSection(
            "Standort, Wetter & METAR",
            "bi-cloud-sun",
            "",
            (
                FaqEntry(
                    "!wx, !metar, !whereami: kein Standort / kein GPS",
                    (
                        "Der Bot nutzt die <strong>letzte bekannte Position deiner Node</strong> im Mesh. "
                        "GPS am Gerät aktivieren, Position freigeben und kurz warten, bis deine Node "
                        "im Netz sichtbar ist — danach Befehl erneut senden."
                    ),
                ),
                FaqEntry(
                    "!metar mit Flughafen-Kürzel",
                    (
                        "Mit ICAO-Code, z. B. <code>!metar EDDF</code>. "
                        "Ohne Argument: METAR des nächsten Flugplatzes zu deiner Position."
                    ),
                ),
            ),
        ),
        FaqSection(
            "BBS & private Nachrichten",
            "bi-inboxes",
            "",
            (
                FaqEntry(
                    "Private BBS-Nachricht (bbspost @…) kommt nicht an",
                    (
                        "BBS-Direktnachrichten werden <strong>zugestellt, wenn deine Node wieder im Mesh aktiv ist</strong> "
                        "(Store-and-Forward). Mit <code>!bbsinfo</code> siehst du wartende Mails. "
                        "Kommt nichts an: Bot-Kontakt auf deinem Gerät neu anlegen (wie bei normalen DMs)."
                    ),
                ),
                FaqEntry(
                    "Öffentlicher BBS-Beitrag nur auf einem Bot sichtbar",
                    (
                        "Öffentliche Beiträge liegen auf dem jeweiligen Bot. "
                        "Andere Bots zeigen sie nur, wenn euer Netz einen <strong>BBS-Link</strong> zwischen den Bots nutzt — "
                        "das richtet der Betreiber ein. Sonst nur lokal auf dem Bot, an den du geschickt hast."
                    ),
                ),
            ),
        ),
        FaqSection(
            "Statistik auf dieser Webseite",
            "bi-bar-chart-line",
            "",
            (
                FaqEntry(
                    "Meine Node erscheint nicht oder selten",
                    (
                        "Die Statistik zeigt Knoten und Daten, die <strong>dieser Bot</strong> im Funknetz "
                        "gehört oder empfangen hat. Weit weg oder selten aktiv — dann fehlst du vielleicht in der Liste. "
                        "Das ist normal und kein Fehler deines Geräts."
                    ),
                ),
                FaqEntry(
                    "Was bedeuten die Karten und Listen?",
                    (
                        "Übersicht über empfangene Nachrichten, Aktivität und bekannte Knoten aus Sicht des Bots — "
                        "kein Ersatz für die Meshtastic-App auf dem Handy oder Gerät."
                    ),
                ),
            ),
        ),
    ]


def _render_entry(entry: FaqEntry) -> str:
    return f"""
<div class="faq-entry mb-3 pb-3 border-bottom border-secondary-subtle">
  <h3 class="h6 text-success mb-2">
    <i class="bi bi-question-circle me-1"></i>{html_escape(entry.problem)}
  </h3>
  <div class="faq-answer text-muted small mb-0">{entry.solution}</div>
</div>"""


def render_faq_page_body(pki_result: Optional[dict] = None) -> str:
    """HTML body (inside portal wrapper) for /faq."""
    from modules.web_faq_pki_check import render_pki_checker_html

    intro = """
<div class="cmd-help-intro portal-card p-4 mb-4">
  <h1 class="h3 section-title mb-3">
    <i class="bi bi-life-preserver text-success me-2"></i>FAQ / Hilfe
  </h1>
  <p class="text-muted mb-0">
    Tipps für Nutzer im Meshhessen-Netz — Befehle im Funknetz, DMs und typische Stolpersteine.
    Alle Befehle: <a href="/befehle">Befehle</a>.
  </p>
</div>"""

    parts: List[str] = [
        intro,
        render_pki_checker_html(pki_result),
        '<div class="accordion cmd-help-accordion" id="faqHelpAccordion">',
    ]
    for sec_idx, section in enumerate(_sections()):
        collapse_id = f"faqSec{sec_idx}"
        expanded = sec_idx == 0
        entries_html = "".join(_render_entry(e) for e in section.entries)
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
      <i class="bi {html_escape(section.icon)} text-success me-2"></i>{html_escape(section.title)}
    </button>
  </h2>
  <div id="{collapse_id}" class="accordion-collapse collapse{show_cls}"
       data-bs-parent="#faqHelpAccordion">
    <div class="accordion-body pt-0">
      {sec_intro}
      {entries_html}
    </div>
  </div>
</div>"""
        )
    parts.append("</div>")
    return "\n".join(parts)
