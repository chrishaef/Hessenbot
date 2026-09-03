#!/usr/bin/env python3
"""Öffentliche Impressums-Seite (Angaben aus [webAdmin])."""

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
    }
    attr = attr_map.get(key)
    if attr:
        return (getattr(st, attr, None) or default or "").strip()
    return (default or "").strip()


def impressum_is_configured(st) -> bool:
    return bool(_cfg_get(st, "impressumOperator") or _cfg_get(st, "impressumEmail"))


def render_impressum_page_body(st) -> str:
    """HTML body (inside portal wrapper) for /impressum."""
    operator = _cfg_get(st, "impressumOperator")
    address = _cfg_get(st, "impressumAddress")
    email = _cfg_get(st, "impressumEmail")
    phone = _cfg_get(st, "impressumPhone")
    extra = _cfg_get(st, "impressumExtra")

    if not impressum_is_configured(st):
        return """
<div class="portal-card p-4 mb-4">
  <h1 class="h3 section-title mb-3">
    <i class="bi bi-building text-success me-2"></i>Impressum
  </h1>
  <p class="alert alert-warning mb-0">
    Der Betreiber hat die Impressumsangaben noch nicht hinterlegt.
    Bitte in den Admin-Einstellungen unter <strong>Web-Admin</strong>
    die Felder <code>impressumOperator</code> und <code>impressumEmail</code> ausfüllen.
  </p>
</div>
"""

    rows = []
    if operator:
        rows.append(
            f"<dt class=\"col-sm-3\">Betreiber</dt>"
            f"<dd class=\"col-sm-9\">{html_escape(operator)}</dd>"
        )
    if address:
        addr_html = html_escape(address).replace("\n", "<br>")
        rows.append(
            f"<dt class=\"col-sm-3\">Anschrift</dt>"
            f"<dd class=\"col-sm-9\">{addr_html}</dd>"
        )
    if email:
        rows.append(
            f"<dt class=\"col-sm-3\">E-Mail</dt>"
            f"<dd class=\"col-sm-9\"><a href=\"mailto:{html_escape(email, quote=True)}\">"
            f"{html_escape(email)}</a></dd>"
        )
    if phone:
        rows.append(
            f"<dt class=\"col-sm-3\">Telefon</dt>"
            f"<dd class=\"col-sm-9\">{html_escape(phone)}</dd>"
        )

    extra_block = ""
    if extra:
        extra_html = html_escape(extra).replace("\n", "<br>")
        extra_block = f'<div class="mt-4 text-muted small">{extra_html}</div>'

    return f"""
<div class="portal-card p-4 mb-4">
  <h1 class="h3 section-title mb-3">
    <i class="bi bi-building text-success me-2"></i>Impressum
  </h1>
  <p class="text-muted small mb-4">
    Angaben gemäß §&nbsp;5 TMG / §&nbsp;18 MStV für dieses öffentlich erreichbare Bot-Portal.
  </p>
  <dl class="row mb-0">
    {''.join(rows)}
  </dl>
  {extra_block}
  <hr class="my-4">
  <p class="small text-muted mb-0">
    Diese Seite gehört zum Mesh-Bot <strong>Hessenbot</strong> (Amateurfunk / Meshtastic).
    Software: <a href="https://github.com/chrishaef/Hessenbot" target="_blank" rel="noopener noreferrer">GitHub</a>.
  </p>
</div>
"""
