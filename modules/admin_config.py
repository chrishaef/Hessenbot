#!/usr/bin/env python3
# Web-Admin: config.ini als Formular bearbeiten (alle Sektionen/Keys).

from __future__ import annotations

import html
import re
from typing import List, Optional, Tuple

from modules.admin_config_tooltips import field_tooltip

SECTION_ORDER = [
    "general",
    "interface",
    "emergencyHandler",
    "sentry",
    "bbs",
    "polls",
    "location",
    "checklist",
    "inventory",
    "qrz",
    "repeater",
    "scheduler",
    "motdBroadcast",
    "newsBroadcast",
    "radioMon",
    "fileMon",
    "smtp",
    "messagingSettings",
    "dataPersistence",
    "webAdmin",
]

SECTION_TITLES = {
    "general": "Allgemein",
    "interface": "Radio Interface 1",
    "emergencyHandler": "Notfall-Handler",
    "sentry": "Sentry / Nähe",
    "bbs": "Bulletin Board",
    "polls": "Umfragen",
    "location": "Standort & Warnungen",
    "checklist": "Checkliste",
    "inventory": "Inventar",
    "qrz": "QRZ-Begrüßung",
    "repeater": "Repeater",
    "scheduler": "Scheduler",
    "motdBroadcast": "MOTD-Versand",
    "newsBroadcast": "News-Versand",
    "radioMon": "Funk-Monitor",
    "fileMon": "Datei-Monitor",
    "smtp": "E-Mail",
    "messagingSettings": "Nachrichten",
    "dataPersistence": "Datenspeicher",
    "webAdmin": "Web-Admin",
}

FIELD_LABELS = {
    ("location", "enableDEalerts"): "NINA/Katwarn/DWD aktiv (!warning, !dealert)",
    ("location", "deAlertAutoBroadcast"): "Automatisch in Kanäle senden",
    ("location", "myRegionalKeysDE"): "ARS-Regionen (!dealert / Auto-Broadcast)",
    ("location", "eAlertBroadcastCh"): "Zusätzliche Kanäle (kommagetrennt)",
    ("location", "alertDuration"): "Abfrage-Intervall (Minuten)",
    ("location", "metar_enabled"): "METAR !metar (nächster Flugplatz)",
    ("location", "UseMeteoWxAPI"): "Wetter !wx (Open-Meteo statt NOAA)",
    ("general", "respond_by_dm_only"): "Antworten nur per DM",
    ("general", "spaceWeather"): "Weltraumwetter (sun, satpass, …)",
}

PASSWORD_KEYS = frozenset(
    {
        "password",
        "SMTP_PASSWORD",
        "IMAP_PASSWORD",
        "openWebUIAPIKey",
        "n2yoAPIKey",
        "newsAPI_KEY",
        "secret_key",
    }
)

_BOOL_RE = re.compile(r"^(true|false|yes|no)$", re.I)


def field_name(section: str, key: str) -> str:
    return f"cfg__{section}__{key}"


def parse_field_name(name: str) -> Optional[Tuple[str, str]]:
    if not name.startswith("cfg__"):
        return None
    parts = name[5:].split("__", 1)
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def is_bool_value(value: str) -> bool:
    return bool(_BOOL_RE.match((value or "").strip()))


def ordered_sections(config) -> List[str]:
    seen = set(config.sections())
    out = [s for s in SECTION_ORDER if s in seen]
    for s in sorted(seen):
        if s.startswith("interface") and s != "interface" and s not in out:
            out.append(s)
    for s in sorted(seen):
        if s not in out:
            out.append(s)
    return out


def section_title(section: str) -> str:
    if section in SECTION_TITLES:
        return SECTION_TITLES[section]
    if section.startswith("interface"):
        n = section.replace("interface", "") or "1"
        return f"Radio Interface {n}"
    return section


def field_label(section: str, key: str) -> str:
    return FIELD_LABELS.get((section, key), key)


def _tooltip_attr(section: str, key: str) -> str:
    tip = field_tooltip(section, key).strip()
    if not tip:
        return ""
    return (
        f' data-bs-toggle="tooltip" data-bs-placement="top" '
        f'data-bs-title="{html.escape(tip, quote=True)}"'
    )


SETTINGS_TOOLTIP_SCRIPT = """
<script>
(function () {
  function initCfgTooltips() {
    if (typeof bootstrap === 'undefined') return;
    document.querySelectorAll('#admin-settings-form [data-bs-toggle="tooltip"]').forEach(function (el) {
      var existing = bootstrap.Tooltip.getInstance(el);
      if (existing) existing.dispose();
      new bootstrap.Tooltip(el, {
        delay: { show: 250, hide: 80 },
        trigger: 'hover focus',
        customClass: 'cfg-field-tooltip'
      });
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCfgTooltips);
  } else {
    initCfgTooltips();
  }
})();
</script>
"""


def build_settings_form_html(config) -> str:
    chunks: List[str] = [
        '<p class="text-muted small">'
        "Alle Werte aus <code>config.ini</code>. Viele Einstellungen gelten sofort nach Speichern; "
        "Interface- oder Log-Level-Änderungen ggf. Bot neu starten. "
        "Fahre mit der Maus über einen Feldnamen (ⓘ) für eine Kurzerklärung."
        "</p>",
        '<form method="post" id="admin-settings-form">',
        '<div id="settingsAccordion" class="accordion">',
    ]

    for idx, section in enumerate(ordered_sections(config)):
        sec_title = html.escape(section_title(section))
        collapse_id = f"cfgSec{idx}"
        btn_cls = "accordion-button" if idx == 0 else "accordion-button collapsed"
        collapse_cls = "accordion-collapse collapse show" if idx == 0 else "accordion-collapse collapse"
        chunks.append('<div class="accordion-item">')
        chunks.append(
            f'<h2 class="accordion-header">'
            f'<button class="{btn_cls}" type="button" data-bs-toggle="collapse" '
            f'data-bs-target="#{collapse_id}">{sec_title}</button></h2>'
        )
        chunks.append(
            f'<div id="{collapse_id}" class="{collapse_cls}" data-bs-parent="#settingsAccordion">'
            f'<div class="accordion-body"><div class="row g-3">'
        )

        for key in config[section]:
            raw = config[section][key]
            fname = field_name(section, key)
            label = html.escape(field_label(section, key))
            tip_attr = _tooltip_attr(section, key)
            label_html = (
                f'<label class="form-label small mb-1 cfg-field-label"{tip_attr}>'
                f'<span class="cfg-field-label__text">{label}</span>'
                f'<i class="bi bi-info-circle cfg-field-label__icon" aria-hidden="true"></i>'
                f"</label>"
            )

            if key in PASSWORD_KEYS:
                inp = (
                    f'<input type="password" class="form-control form-control-sm" '
                    f'name="{html.escape(fname)}" autocomplete="new-password" '
                    f'placeholder="(leer = unverändert)">'
                )
            elif is_bool_value(raw):
                low = raw.strip().lower()
                sel_true = "selected" if low in ("true", "yes") else ""
                sel_false = "selected" if low in ("false", "no") else ""
                inp = (
                    f'<select class="form-select form-select-sm" name="{html.escape(fname)}">'
                    f'<option value="True" {sel_true}>True</option>'
                    f'<option value="False" {sel_false}>False</option>'
                    f"</select>"
                )
            elif len(raw) > 80 or "\n" in raw:
                inp = (
                    f'<textarea class="form-control form-control-sm font-monospace" '
                    f'name="{html.escape(fname)}" rows="3">{html.escape(raw)}</textarea>'
                )
            else:
                inp = (
                    f'<input type="text" class="form-control form-control-sm" '
                    f'name="{html.escape(fname)}" value="{html.escape(raw)}">'
                )

            chunks.append(f'<div class="col-md-6 col-lg-4">{label_html}{inp}</div>')

        chunks.append("</div></div></div>")

    chunks.append("</div>")
    chunks.append(
        '<div class="mt-4">'
        '<button type="submit" class="btn btn-success">Einstellungen speichern</button>'
        "</div></form>"
    )
    chunks.append(SETTINGS_TOOLTIP_SCRIPT)
    return "".join(chunks)


def apply_form_to_config(config, form, *, config_file: str) -> None:
    """POST-Formular in config.ini schreiben (Passwort-Felder leer = unverändert)."""
    for name, value in form.items():
        parsed = parse_field_name(name)
        if not parsed:
            continue
        section, key = parsed
        if section not in config:
            config[section] = {}
        if key in PASSWORD_KEYS and not (value or "").strip():
            continue
        config[section][key] = (value or "").strip()

    with open(config_file, "w", encoding="utf-8") as fh:
        config.write(fh)
