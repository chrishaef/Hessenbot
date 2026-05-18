#!/usr/bin/env python3
"""FAQ / Hilfe für das öffentliche Web-Portal."""

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
                "Der Bot kann einen Befehl verarbeiten und im Log „Sending DM“ anzeigen — "
                "trotzdem siehst du in der App nichts. Das ist meist kein Absturz, "
                "sondern Zustellung oder Entschlüsselung auf deinem Gerät."
            ),
            (
                FaqEntry(
                    "DM kommt nicht an, obwohl der Bot antwortet (auch nur 1 Hop entfernt)",
                    (
                        "Sehr häufig: <strong>veralteter Kontakt / fehlender DM-Schlüssel (PKI)</strong> "
                        "ab Firmware 2.6+. Lösung: Bot in der Kontaktliste <strong>löschen</strong> und "
                        "<strong>neu hinzufügen</strong> (NodeInfo und öffentlicher Schlüssel werden neu "
                        "ausgetauscht). Alternativ: Bot als <strong>Favorit</strong> setzen, kurz warten, "
                        "dann erneut eine DM senden. Auf dem Bot-Server: betroffene Dezimal-Node-ID in "
                        "<code>favoriteNodeList</code> eintragen und <code>script/addFav.py</code> ausführen."
                    ),
                ),
                FaqEntry(
                    "Antwort nur im Kanal erwartet, aber nichts sichtbar",
                    (
                        "Viele Bots (auch Hessenbot) antworten standardmäßig per <strong>Direktnachricht (DM)</strong>, "
                        "wenn der Befehl im <strong>Kanal</strong> gesendet wurde "
                        "(<code>respond_by_dm_only = True</code>). "
                        "Lösung: In der App das <strong>DM-Postfach</strong> zum Bot-Knoten öffnen, nicht nur den Kanal."
                    ),
                ),
                FaqEntry(
                    "Nur entfernte Stationen betroffen, nah am Gateway geht es",
                    (
                        "Im Bot-Log beim Empfang prüfen: <strong>MQTT</strong> vs. <strong>Direct</strong> / Hop-Anzahl. "
                        "Kommt der Befehl per MQTT an, muss der Rückweg zum Bot-Knoten für dich existieren. "
                        "Ein PKI-Problem (siehe oben) kann unabhängig von der Entfernung auftreten."
                    ),
                ),
                FaqEntry(
                    "Im Log: „PKI Routing Error“ oder „PKI_UNKNOWN_PUBKEY“",
                    (
                        "Schlüsselaustausch in beide Richtungen anstoßen (Kontakt neu, Favorit, kurze DM). "
                        "Firmware von Bot und Client möglichst aktuell halten. "
                        "Details stehen in <code>meshbot.log</code> mit Hinweistext."
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
                        "Befehl oft mit <strong>!</strong> beginnen (<code>!ping</code>, <code>!cmd</code>) — "
                        "je nach <code>cmdBang</code>. Mit <code>explicitCmd</code> zählen nur Zeilen, "
                        "die mit einem bekannten Befehl <strong>beginnen</strong>. "
                        "Auf <a href=\"/befehle\">Befehle</a> prüfen, welche Module auf diesem Bot aktiv sind."
                    ),
                ),
                FaqEntry(
                    "„Bitte etwas langsamer“ / Rate-Limit",
                    "Zu viele Befehle in kurzer Zeit. Kurz warten und erneut senden.",
                ),
                FaqEntry(
                    "Befehl im Standardkanal (z. B. LongFast) wird ignoriert",
                    (
                        "Der Bot kann den <strong>öffentlichen Standardkanal</strong> ignorieren "
                        "(<code>ignoreDefaultChannel</code>). "
                        "Lösung: Befehl im regionalen Kanal senden oder per <strong>DM</strong> an den Bot."
                    ),
                ),
                FaqEntry(
                    "Nach Änderung an config.ini passiert nichts Neues",
                    (
                        "Viele Einstellungen erst nach <strong>Neustart des Bots</strong> aktiv "
                        "(systemd/Docker). Bei Unsicherheit Bot neu starten."
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
                    "!wx, !metar, !whereami liefern „kein GPS“ o. Ä.",
                    (
                        "Der Bot nutzt die <strong>letzte Position aus der NodeDB</strong> deiner Node — "
                        "ohne GPS oder ohne empfangenes Positions-Paket keine Koordinaten. "
                        "GPS aktivieren und kurz warten, bis Position im Mesh ankam."
                    ),
                ),
                FaqEntry(
                    "Doppelte oder unerwartete Antworten",
                    (
                        "Bei MQTT- und UDP-Gateway gleichzeitig kann dasselbe Paket doppelt ankommen — "
                        "der Bot filtert Duplikate (<code>packetDedupEnabled</code>). "
                        "Bot-Version aktuell halten."
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
                    "BBS-DM (bbspost @…) kommt nicht an",
                    (
                        "BBS-DMs sind <strong>Store-and-Forward</strong>: Zustellung, wenn deine Node wieder "
                        "im Mesh sendet. <code>!bbsinfo</code> prüfen. Gleiche PKI-Regeln wie bei DMs — "
                        "Kontakt zum Bot ggf. neu anlegen."
                    ),
                ),
                FaqEntry(
                    "Öffentlicher BBS-Beitrag fehlt auf anderem Bot",
                    (
                        "<code>bbslink</code> muss auf beiden Seiten erlaubt sein (Whitelist). "
                        "Ohne Link-Sync nur lokale Beiträge sichtbar."
                    ),
                ),
            ),
        ),
        FaqSection(
            "Web-Portal",
            "bi-globe",
            "",
            (
                FaqEntry(
                    "Statistik / NodeDB wirkt leer",
                    (
                        "Das Dashboard zeigt Daten, die <strong>dieser Bot-Knoten</strong> gehört hat. "
                        "Weit entfernte Nodes ohne Kontakt erscheinen ggf. nicht."
                    ),
                ),
                FaqEntry(
                    "Admin-Login funktioniert nicht",
                    (
                        "Zugangsdaten in <code>config.ini</code> unter <code>[webAdmin]</code>. "
                        "Nach Passwortänderung Web-Dienst neu starten."
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
    Häufige Fragen im Umgang mit dem Hessenbot (Meshhessen).
    Für alle Befehle siehe <a href="/befehle">Befehle</a>.
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
