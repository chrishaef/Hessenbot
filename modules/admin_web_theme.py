#!/usr/bin/env python3
# Portal layout — design aligned with MH-Landingpage & MQTT-Webinterface.

from __future__ import annotations

from html import escape as html_escape
from typing import List, Tuple

THEME_SCRIPT = """<script>(function(){var t=localStorage.getItem('theme');var dark=t==='dark'||(t!=='light'&&window.matchMedia('(prefers-color-scheme:dark)').matches);document.documentElement.setAttribute('data-bs-theme',dark?'dark':'light');}());</script>"""

THEME_TOGGLE_SCRIPT = """
<script>
(function () {
  var ICONS = { auto: 'bi-circle-half', dark: 'bi-moon-stars-fill', light: 'bi-sun-fill' };
  var TITLES = { auto: 'Automatisch – klicken für Dunkel', dark: 'Dunkel – klicken für Hell', light: 'Hell – klicken für Automatisch' };
  function getStored() { return localStorage.getItem('theme'); }
  function applyTheme() {
    var stored = getStored();
    var dark = stored === 'dark' || (stored !== 'light' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.setAttribute('data-bs-theme', dark ? 'dark' : 'light');
    var btn = document.getElementById('theme-toggle');
    if (btn) { var icon = btn.querySelector('i'); if (icon) icon.className = 'bi ' + ICONS[stored || 'auto']; btn.title = TITLES[stored || 'auto']; }
  }
  window.__themeToggle = function () {
    var cur = getStored();
    if (!cur) localStorage.setItem('theme', 'dark');
    else if (cur === 'dark') localStorage.setItem('theme', 'light');
    else localStorage.removeItem('theme');
    applyTheme();
  };
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme);
  applyTheme();
})();
</script>
"""

PORTAL_ASSETS = """
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">
<link rel="stylesheet" href="/static/portal/style.css">
"""

ADMIN_TABS: List[Tuple[str, str, str]] = [
    ("home", "Übersicht", "choose"),
    ("dm", "DM", "edit_dm"),
    ("news", "News", "edit_news"),
    ("messages", "Messages", "live_messages"),
    ("nodes", "NodeDB", "nodes_list"),
    ("nodesettings", "Node Settings", "node_settings_index"),
    ("meshadmin", "Admin", "mesh_admin_index"),
    ("motd", "MOTD", "motd_edit"),
    ("scheduler", "Scheduler", "scheduler_edit"),
    ("bbs", "BBS", "bbs_index"),
    ("polls", "Umfragen", "polls_index"),
    ("settings", "Einstellungen", "settings_index"),
    ("banlist", "Banliste", "banlist_index"),
    ("logs", "Logs", "logs"),
]


def portal_head(title: str = "Hessenbot") -> str:
    return THEME_SCRIPT + PORTAL_ASSETS + f"<title>{html_escape(title)}</title>"


def _dash_nav_link(label: str, icon: str, href: str, *, active: bool = False) -> str:
    active_cls = " dash-view-btn--active" if active else ""
    return f"""
        <li class="nav-item">
          <a class="btn btn-sm dash-view-btn{active_cls}" href="{html_escape(href)}">
            <i class="bi bi-{html_escape(icon)} me-1"></i>{html_escape(label)}
          </a>
        </li>"""


def _dash_nav_button(view: str, label: str, icon: str, *, active: bool = False) -> str:
    active_cls = " dash-view-btn--active" if active else ""
    pressed = "true" if active else "false"
    return f"""
        <li class="nav-item">
          <button type="button" class="btn btn-sm dash-view-btn{active_cls}"
                  data-dash-view="{html_escape(view)}" aria-pressed="{pressed}">
            <i class="bi bi-{html_escape(icon)} me-1"></i>{html_escape(label)}
          </button>
        </li>"""


def portal_navbar(
    *,
    active: str = "stats",
    admin_href: str | None = None,
    commands_href: str = "/befehle",
    faq_href: str = "/faq",
    dash_view_tabs: bool = False,
) -> str:
    admin_btn = ""
    if admin_href:
        admin_btn = (
            f'<a class="btn btn-success btn-sm" href="{html_escape(admin_href)}">'
            '<i class="bi bi-shield-lock me-1"></i>Admin</a>'
        )
    chref = commands_href or "/befehle"
    fhref = faq_href or "/faq"
    # Öffentlich: Statistik-Seite nutzt Buttons für BBS/NodeDB-Umschaltung; sonst einheitliche Link-Leiste.
    if dash_view_tabs and active == "stats":
        nav_primary = f"""
      <ul class="navbar-nav me-auto align-items-center gap-1 dash-view-nav">
        {_dash_nav_button("stats", "Statistik", "bar-chart-line", active=True)}
        {_dash_nav_link("Befehle", "terminal", chref)}
        {_dash_nav_button("bbs", "BBS", "inboxes")}
        {_dash_nav_button("nodedb", "NodeDB", "diagram-3")}
        {_dash_nav_link("FAQ/Hilfe", "life-preserver", fhref)}
      </ul>"""
    else:
        nav_primary = f"""
      <ul class="navbar-nav me-auto align-items-center gap-1 dash-view-nav">
        {_dash_nav_link("Statistik", "bar-chart-line", "/", active=(active == "stats"))}
        {_dash_nav_link("Befehle", "terminal", chref, active=(active == "commands"))}
        {_dash_nav_link("BBS", "inboxes", "/#bbs")}
        {_dash_nav_link("NodeDB", "diagram-3", "/#nodedb")}
        {_dash_nav_link("FAQ/Hilfe", "life-preserver", fhref, active=(active == "faq"))}
      </ul>"""
    return f"""
<nav class="navbar navbar-expand-lg sticky-top portal-navbar" data-bs-theme="dark">
  <div class="container-fluid px-3">
    <a class="navbar-brand d-flex align-items-center gap-2" href="/">
      <i class="bi bi-broadcast-pin text-success fs-4"></i>
      <span class="fw-semibold">Hessenbot</span>
    </a>
    <button class="navbar-toggler border-0" type="button" data-bs-toggle="collapse"
            data-bs-target="#portalNav" aria-label="Navigation">
      <span class="navbar-toggler-icon"></span>
    </button>
    <div class="collapse navbar-collapse" id="portalNav">
{nav_primary}
      <ul class="navbar-nav align-items-center gap-2">
        <li class="nav-item">
          <button id="theme-toggle" type="button" class="btn btn-link nav-link px-2"
                  onclick="window.__themeToggle()"><i class="bi bi-circle-half"></i></button>
        </li>
        <li class="nav-item">{admin_btn}</li>
      </ul>
    </div>
  </div>
</nav>
"""


def portal_footer() -> str:
    return '<footer class="portal-footer"><span>Hessenbot - powered by Meshhessen.de</span></footer>'


def portal_particles_html() -> str:
    return (
        '<div class="bg-canvas" aria-hidden="true"><canvas id="particles"></canvas></div>'
        '<script src="/static/portal/particles.js"></script>'
    )


def portal_shell_start(
    *,
    title: str,
    body_class: str = "particles-page",
    active_nav: str = "stats",
    admin_href: str | None = None,
    particles: bool = True,
    dash_view_tabs: bool = False,
) -> str:
    extra = " particles-page" if particles else ""
    bg = portal_particles_html() if particles else ""
    nav = portal_navbar(
        active=active_nav, admin_href=admin_href, dash_view_tabs=dash_view_tabs
    )
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {portal_head(title)}
</head>
<body class="{html_escape(body_class)}{extra}">
{bg}
{nav}
"""


def portal_shell_end() -> str:
    return (
        portal_footer()
        + '<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>'
        + THEME_TOGGLE_SCRIPT
        + "</body></html>"
    )


def render_admin_tabs(active: str) -> str:
    parts = ['<nav class="admin-tab-bar" aria-label="Admin-Navigation">']
    for tab_id, label, endpoint in ADMIN_TABS:
        cls = "admin-tab admin-tab--active" if active == tab_id else "admin-tab"
        parts.append(
            f'<a href="{{{{ url_for(\'{endpoint}\') }}}}" class="{cls}">{html_escape(label)}</a>'
        )
    parts.append('<span class="admin-tab-spacer"></span>')
    parts.append(
        '<a href="{{ url_for(\'logout\') }}" class="admin-tab admin-tab--logout">Logout</a>'
    )
    parts.append("</nav>")
    return "".join(parts)


def admin_inner_wrap(inner_html: str, *, page_title: str, active_tab: str = "home") -> str:
    return f"""
<div class="portal-wrapper portal-wrapper--admin">
  <main class="portal-main">
    <div class="home-content portal-admin-content py-4">
      <h1 class="h3 section-title mb-3">
        <i class="bi bi-gear-wide-connected text-success me-2"></i>{html_escape(page_title)}
      </h1>
      {render_admin_tabs(active_tab)}
      <div class="portal-card">
        {inner_html}
      </div>
    </div>
  </main>
</div>
"""
