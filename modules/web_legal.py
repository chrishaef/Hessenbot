#!/usr/bin/env python3
"""Öffentliche Rechtsseiten: Impressum und Datenschutz (Angaben aus [webAdmin])."""

from __future__ import annotations

from html import escape as html_escape


def _cfg_get(st, key: str, default: str = "") -> str:
    try:
        if "webAdmin" in st.config and key in st.config["webAdmin"]:
            return (st.config["webAdmin"].get(key) or "").strip()
    except Exception:
        pass
    attr_map = {
        "impressumOperator": "web_admin_impressum_operator",
        "impressumAddress": "web_admin_impressum_address",
        "impressumEmail": "web_admin_impressum_email",
        "impressumPhone": "web_admin_impressum_phone",
        "impressumExtra": "web_admin_impressum_extra",
        "datenschutzExtra": "web_admin_datenschutz_extra",
    }
    attr = attr_map.get(key)
    if attr:
        return (getattr(st, attr, None) or default or "").strip()
    return (default or "").strip()


def impressum_is_configured(st) -> bool:
    return bool(_cfg_get(st, "impressumOperator") or _cfg_get(st, "impressumEmail"))


def _contact_block(st) -> tuple[str, str, str, str]:
    return (
        _cfg_get(st, "impressumOperator"),
        _cfg_get(st, "impressumAddress"),
        _cfg_get(st, "impressumEmail"),
        _cfg_get(st, "impressumPhone"),
    )


def _mailto(email: str) -> str:
    return (
        f'<a href="mailto:{html_escape(email, quote=True)}">{html_escape(email)}</a>'
    )


def _operator_dl(st) -> str:
    operator, address, email, phone = _contact_block(st)
    rows = []
    if operator:
        rows.append(
            f'<dt class="col-sm-3">Name / Betreiber</dt>'
            f'<dd class="col-sm-9">{html_escape(operator)}</dd>'
        )
    if address:
        addr_html = html_escape(address).replace("\n", "<br>")
        rows.append(
            f'<dt class="col-sm-3">Anschrift</dt>'
            f'<dd class="col-sm-9">{addr_html}</dd>'
        )
    if email:
        rows.append(
            f'<dt class="col-sm-3">E-Mail</dt>'
            f'<dd class="col-sm-9">{_mailto(email)}</dd>'
        )
    if phone:
        rows.append(
            f'<dt class="col-sm-3">Telefon</dt>'
            f'<dd class="col-sm-9">{html_escape(phone)}</dd>'
        )
    if not rows:
        return (
            '<p class="alert alert-warning">Kontaktdaten noch nicht hinterlegt '
            "(Admin → Einstellungen → Web-Admin).</p>"
        )
    return f'<dl class="row mb-0">{"".join(rows)}</dl>'


def render_impressum_page_body(st) -> str:
    """HTML body for /impressum."""
    extra = _cfg_get(st, "impressumExtra")
    operator, _address, email, _phone = _contact_block(st)

    if not impressum_is_configured(st):
        return """
<div class="portal-card p-4 mb-4">
  <h1 class="h3 section-title mb-3">
    <i class="bi bi-building text-success me-2"></i>Impressum
  </h1>
  <p class="alert alert-warning mb-0">
    Der Betreiber hat die Impressumsangaben noch nicht hinterlegt.
    Bitte in den Admin-Einstellungen unter <strong>Web-Admin</strong>
    mindestens <em>Betreiber</em> und <em>E-Mail</em> ausfüllen.
  </p>
</div>
"""

    content_resp = html_escape(operator) if operator else "der Betreiber dieses Portals"
    contact_mail = _mailto(email) if email else "die oben genannte Kontaktadresse"

    extra_block = ""
    if extra:
        extra_html = html_escape(extra).replace("\n", "<br>")
        extra_block = f"""
  <h2 class="h5 mt-4 mb-2">Weitere Hinweise</h2>
  <p class="text-muted small">{extra_html}</p>
"""

    return f"""
<div class="portal-card p-4 mb-4 legal-page">
  <h1 class="h3 section-title mb-3">
    <i class="bi bi-building text-success me-2"></i>Impressum
  </h1>
  <p class="text-muted small mb-4">
    Angaben gemäß §&nbsp;5 TMG und §&nbsp;18 Abs.&nbsp;2 MStV für dieses öffentlich
    erreichbare Web-Portal des Mesh-Bots <strong>Hessenbot</strong>.
  </p>

  <h2 class="h5 mb-2">Diensteanbieter</h2>
  {_operator_dl(st)}

  <h2 class="h5 mt-4 mb-2">Verantwortlich für den Inhalt</h2>
  <p class="text-muted small">
    Verantwortlich für journalistisch-redaktionelle Inhalte im Sinne von §&nbsp;18 Abs.&nbsp;2 MStV:
    {content_resp}.
  </p>

  <h2 class="h5 mt-4 mb-2">Kontakt</h2>
  <p class="text-muted small">
    Anfragen zum Betrieb dieses Portals bitte per E-Mail an {contact_mail}.
  </p>

  <h2 class="h5 mt-4 mb-2">Art des Angebots</h2>
  <p class="text-muted small">
    Dieses Angebot dient der Unterstützung des Amateurfunks bzw. eines lokalen
    Meshtastic-Netzes (Community-/Hobbyprojekt). Es handelt sich um kein
    gewerbliches Online-Angebot im Sinne eines Webshops. Soweit dennoch
    gesetzliche Kennzeichnungspflichten greifen, gelten die obigen Angaben.
  </p>

  <h2 class="h5 mt-4 mb-2">Haftung für Inhalte</h2>
  <p class="text-muted small">
    Die Inhalte dieses Portals wurden mit Sorgfalt erstellt. Für die Richtigkeit,
    Vollständigkeit und Aktualität der bereitgestellten Informationen
    (Statistiken, Node-Listen, Befehlshilfen, Blitz-/Wetterdaten u. Ä.) wird
    jedoch keine Gewähr übernommen. Die Nutzung erfolgt auf eigene Gefahr.
    Verbindliche Auskünfte, Alarmierungen oder Notrufe sind nicht Gegenstand
    dieses Angebots.
  </p>

  <h2 class="h5 mt-4 mb-2">Haftung für Links</h2>
  <p class="text-muted small">
    Dieses Portal enthält Links zu externen Websites Dritter (z. B. Meshhessen,
    GitHub, CDN-Ressourcen). Auf deren Inhalte haben wir keinen Einfluss;
    deshalb können wir für diese fremden Inhalte keine Gewähr übernehmen.
    Für die Inhalte der verlinkten Seiten ist stets der jeweilige Anbieter
    verantwortlich. Bei Bekanntwerden von Rechtsverletzungen werden derartige
    Links umgehend entfernt.
  </p>

  <h2 class="h5 mt-4 mb-2">Urheberrecht</h2>
  <p class="text-muted small">
    Texte, Gestaltung und Software dieses Portals unterliegen dem Urheberrecht.
    Der Quellcode von Hessenbot ist auf
    <a href="https://github.com/chrishaef/Hessenbot" target="_blank" rel="noopener noreferrer">GitHub</a>
    einsehbar und unterliegt den dort angegebenen Lizenzbedingungen.
    Beiträge von Nutzern im Mesh (BBS, Nachrichten) verbleiben beim jeweiligen
    Absender; die Anzeige erfolgt nur zur Darstellung im Netzbetrieb.
  </p>

  <h2 class="h5 mt-4 mb-2">Streitbeilegung</h2>
  <p class="text-muted small mb-0">
    Die Europäische Kommission stellt eine Plattform zur Online-Streitbeilegung (OS) bereit:
    <a href="https://ec.europa.eu/consumers/odr/" target="_blank" rel="noopener noreferrer">
      https://ec.europa.eu/consumers/odr/
    </a>.
    Wir sind nicht verpflichtet und nicht bereit, an Streitbeilegungsverfahren vor einer
    Verbraucherschlichtungsstelle teilzunehmen.
  </p>
  {extra_block}
  <hr class="my-4">
  <p class="small text-muted mb-0">
    Siehe auch: <a href="/datenschutz">Datenschutzhinweise</a>.
  </p>
</div>
"""


def render_datenschutz_page_body(st) -> str:
    """HTML body for /datenschutz (DSGVO-orientierte Hinweise)."""
    operator, address, email, phone = _contact_block(st)
    extra = _cfg_get(st, "datenschutzExtra")

    if impressum_is_configured(st):
        verantw = _operator_dl(st)
    else:
        verantw = """
<p class="alert alert-warning">
  Der Verantwortliche ist noch nicht hinterlegt. Bitte Impressumsfelder unter
  Admin → Einstellungen → Web-Admin ausfüllen.
</p>
"""

    contact_line = _mailto(email) if email else "die im Impressum genannte Adresse"

    extra_block = ""
    if extra:
        extra_html = html_escape(extra).replace("\n", "<br>")
        extra_block = f"""
  <h2 class="h5 mt-4 mb-2">Zusätzliche Hinweise des Betreibers</h2>
  <p class="text-muted small">{extra_html}</p>
"""

    return f"""
<div class="portal-card p-4 mb-4 legal-page">
  <h1 class="h3 section-title mb-3">
    <i class="bi bi-shield-lock text-success me-2"></i>Datenschutzhinweise
  </h1>
  <p class="text-muted small mb-4">
    Informationen zur Verarbeitung personenbezogener Daten beim Besuch dieses
    Portals und bei der Nutzung des zugehörigen Mesh-Bots (Hessenbot),
    orientiert an der DSGVO.
  </p>

  <h2 class="h5 mb-2">1. Verantwortlicher</h2>
  {verantw}
  <p class="text-muted small mt-2">
    Kontakt in Datenschutzfragen: {contact_line}.
    Vollständige Anbieterangaben: <a href="/impressum">Impressum</a>.
  </p>

  <h2 class="h5 mt-4 mb-2">2. Hosting / Bereitstellung</h2>
  <p class="text-muted small">
    Dieses Web-Portal wird vom oben genannten Betreiber betrieben (typischerweise
    auf demselben System wie der Mesh-Bot). Beim Aufruf der Seiten werden technisch
    notwendige Verbindungsdaten (u. a. IP-Adresse, Zeitpunkt, angeforderte URL,
    User-Agent) durch den Webserver bzw. vorgelagerte Systeme verarbeitet, soweit
    das für den Betrieb, die Sicherheit und die Fehleranalyse erforderlich ist
    (Art.&nbsp;6 Abs.&nbsp;1 lit.&nbsp;f DSGVO).
  </p>

  <h2 class="h5 mt-4 mb-2">3. Welche Daten verarbeiten wir?</h2>
  <ul class="text-muted small">
    <li>
      <strong>Mesh-Kommunikationsdaten:</strong> Node-IDs, Kurznamen/Langnamen,
      Positionsangaben (soweit im Mesh sichtbar), SNR/RSSI/Hop-Informationen sowie
      Inhalte von Befehlen und Nachrichten, die der Bot empfängt oder beantwortet.
    </li>
    <li>
      <strong>Protokolldateien:</strong> Betriebslogs (z. B. <code>meshbot.log</code>)
      und optional Nachrichtenlogs — zur Fehlersuche, Statistik und Administration.
    </li>
    <li>
      <strong>Öffentliche Statistik / NodeDB / BBS:</strong> Auszüge aus empfangenen
      Mesh-Daten und ggf. BBS-Beiträgen auf dem öffentlichen Dashboard.
    </li>
    <li>
      <strong>Blitzwatch:</strong> Von dir gesetzte Präferenzen (An/Aus, Radien,
      Home-/Zusatzorte) werden der jeweiligen Node-ID zugeordnet und in einer
      lokalen Datenbank gespeichert.
    </li>
    <li>
      <strong>Web-Sitzungen:</strong> Für den Admin-Login und die zeitlich begrenzte
      Blitzwatch-Web-Freischaltung (PIN aus der Bot-DM) werden Session-Cookies
      gesetzt. Die PIN selbst wird nur kurzzeitig und gehasht vorgehalten.
    </li>
    <li>
      <strong>Rate-Limiting:</strong> Zur Abwehr von Missbrauch können IP-Adressen
      kurzzeitig in Verbindung mit Anfragelimits verarbeitet werden.
    </li>
  </ul>

  <h2 class="h5 mt-4 mb-2">4. Zwecke und Rechtsgrundlagen</h2>
  <ul class="text-muted small">
    <li>
      Betrieb des Mesh-Bots und des Informationsportals
      (Art.&nbsp;6 Abs.&nbsp;1 lit.&nbsp;f DSGVO — berechtigtes Interesse am Netzbetrieb
      und an der Bereitstellung von Community-Funktionen).
    </li>
    <li>
      Erfüllung deiner Anfragen/Befehle im Mesh bzw. Web
      (Art.&nbsp;6 Abs.&nbsp;1 lit.&nbsp;b DSGVO, soweit ein Nutzungsverhältnis besteht,
      sonst lit.&nbsp;f).
    </li>
    <li>
      Sicherheit, Missbrauchsabwehr, Fehleranalyse
      (Art.&nbsp;6 Abs.&nbsp;1 lit.&nbsp;f DSGVO).
    </li>
  </ul>

  <h2 class="h5 mt-4 mb-2">5. Speicherdauer</h2>
  <p class="text-muted small">
    Logs und Mesh-Metadaten werden so lange aufbewahrt, wie es für Betrieb,
    Statistik und Nachvollziehbarkeit erforderlich ist, und danach gelöscht oder
    rotiert (konfigurierbare Log-Rotation). Blitzwatch-Einstellungen bleiben
    gespeichert, bis du sie zurücksetzt oder der Betreiber sie entfernt.
    Session-Cookies enden mit dem Browser-Ende bzw. nach Ablauf der Sitzung
    (Blitzwatch-Webzugang typischerweise ca. 1&nbsp;Stunde). Web-PINs verfallen
    nach kurzer Zeit (ca. 15&nbsp;Minuten) und sind einmalig.
  </p>

  <h2 class="h5 mt-4 mb-2">6. Empfänger / Dritte</h2>
  <p class="text-muted small">
    Eine Weitergabe personenbezogener Daten an Dritte findet nicht zu Werbezwecken statt.
    Daten können im Mesh sichtbar sein (Funk/MQTT), soweit du sie selbst sendest oder
    dein Gerät sie ausstrahlt. Für die Darstellung dieses Portals können externe
    Ressourcen geladen werden (z. B. CSS/Icons über CDN-Anbieter). Dabei kann die
    IP-Adresse an den jeweiligen CDN-Betreiber übermittelt werden.
  </p>

  <h2 class="h5 mt-4 mb-2">7. Cookies</h2>
  <p class="text-muted small">
    Es werden technisch notwendige Cookies für Sessions (Admin-Login, Blitzwatch-Web)
    sowie ggf. ein lokaler Theme-Schalter (<code>localStorage</code> im Browser)
    verwendet. Tracking-, Werbe- oder Analyse-Cookies setzen wir nicht ein.
  </p>

  <h2 class="h5 mt-4 mb-2">8. Deine Rechte</h2>
  <p class="text-muted small">
    Du hast nach Maßgabe der DSGVO insbesondere Rechte auf Auskunft, Berichtigung,
    Löschung, Einschränkung der Verarbeitung, Datenübertragbarkeit sowie Widerspruch
    gegen Verarbeitungen auf Grundlage von Art.&nbsp;6 Abs.&nbsp;1 lit.&nbsp;f DSGVO.
    Außerdem besteht ein Beschwerderecht bei einer Datenschutzaufsichtsbehörde.
    Zur Ausübung deiner Rechte genügt eine formlose Nachricht an {contact_line}.
  </p>

  <h2 class="h5 mt-4 mb-2">9. Pflicht zur Bereitstellung</h2>
  <p class="text-muted small">
    Die Nutzung des öffentlichen Portals ist ohne Login möglich. Für geschützte
    Funktionen (Admin, Blitzwatch-Web) sind die genannten technischen Daten
    erforderlich; ohne Session/PIN können diese Funktionen nicht genutzt werden.
  </p>

  <h2 class="h5 mt-4 mb-2">10. Aktualität</h2>
  <p class="text-muted small mb-0">
    Diese Hinweise können angepasst werden, wenn sich Funktionen des Portals oder
    Rechtslagen ändern. Es gilt die jeweils hier veröffentlichte Fassung.
  </p>
  {extra_block}
  <hr class="my-4">
  <p class="small text-muted mb-0">
    Siehe auch: <a href="/impressum">Impressum</a>.
  </p>
</div>
"""
