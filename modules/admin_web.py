#!/usr/bin/env python3
# Small Flask admin UI: edit alert/news files, browse logs, live messages.log view.
# Started in a background thread when [webAdmin] enabled in config.ini.

import glob
import os
import secrets
import threading
from html import escape as html_escape
from typing import List, Optional

from modules.paths import path_in_repo, repo_root

from flask import (
    Flask,
    flash,
    get_flashed_messages,
    redirect,
    render_template_string,
    request,
    url_for,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from markupsafe import Markup


def _abs_path(rel_or_abs: str) -> str:
    return path_in_repo(rel_or_abs)


def _messages_log_path(log_dir: str) -> str:
    """Path to the active messages log (handler path or logs/messages.log)."""
    try:
        from modules.log import msgLogger

        for handler in msgLogger.handlers:
            base = getattr(handler, "baseFilename", None)
            if base:
                return os.path.normpath(base)
    except Exception:
        pass
    base_dir = os.path.realpath(log_dir)
    primary = os.path.join(base_dir, "messages.log")
    if os.path.isfile(primary):
        return primary
    rotated: List[str] = sorted(
        glob.glob(os.path.join(base_dir, "messages.log*")),
        key=os.path.getmtime,
        reverse=True,
    )
    return rotated[0] if rotated else primary


def _read_messages_log_tail(log_path: str, max_lines: int = 500) -> str:
    with open(log_path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    zeilen = reversed(lines[-max_lines:] if len(lines) > max_lines else lines)
    gefiltert = []
    for z in zeilen:
        try:
            teile = z.strip().split(" | ")
            if len(teile) >= 4:
                if len(teile) > 0 and " " in teile[0]:
                    zeitstempel = teile[0].split(" ")[1].split(",")[0]
                else:
                    zeitstempel = "??:??:??"
                sender = teile[2] if len(teile) > 2 else "Unbekannt"
                nachricht = teile[3] if len(teile) > 3 else ""
                gefiltert.append(f"{zeitstempel} | {sender} | {nachricht}")
            else:
                gefiltert.append(z.strip())
        except Exception:
            gefiltert.append(f"[Fehler beim Parsen] → {z.strip()}")
    return "\n".join(gefiltert)


def _safe_log_file(log_dir: str, filename: str) -> Optional[str]:
    base = os.path.realpath(log_dir)
    cand = os.path.realpath(os.path.join(log_dir, os.path.basename(filename)))
    if not cand.startswith(base + os.sep):
        return None
    return cand if os.path.isfile(cand) else None


def create_app(
    *,
    alert_path: str,
    news_path: str,
    log_dir: str,
    admin_username: str,
    admin_password: str,
    secret_key: str,
):
    app = Flask(__name__)
    app.secret_key = secret_key

    dateien = {
        "direktnachricht": alert_path,
        "news": news_path,
    }
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "admin_login"

    class User(UserMixin):
        def __init__(self, uid):
            self.id = uid

    @login_manager.user_loader
    def load_user(user_id):
        return User(user_id)

    limiter = Limiter(get_remote_address, app=app, default_limits=[])

    dark_css = """
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
body {
  background-color: #0f1214;
  color: #e8edf2;
  font-family: system-ui, "Segoe UI", sans-serif;
  font-size: 1rem;
  line-height: 1.55;
  padding-top: 60px;
  -webkit-font-smoothing: antialiased;
}
.container {
  max-width: min(100vw - 1.5rem, 1320px);
  width: 100%;
  margin-left: auto;
  margin-right: auto;
  background-color: #1a1d21;
  color: #e8edf2;
  padding: clamp(1rem, 3vw, 2rem) clamp(1rem, 3vw, 2.25rem);
  border-radius: 12px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.45), 0 0 0 1px rgba(255, 255, 255, 0.04);
}
textarea, input[type="text"], input[type="password"], select.form-select, .form-control {
  background-color: #25292e;
  color: #eef4f8;
  border: 1px solid #3d444c;
}
textarea:focus, input[type="text"]:focus, input[type="password"]:focus,
select.form-select:focus, .form-control:focus {
  background-color: #2a2f35;
  color: #fff;
  border-color: #5c7dff;
  box-shadow: 0 0 0 0.2rem rgba(92, 125, 255, 0.2);
}
.btn-primary {
  background-color: #2563eb;
  border-color: #2563eb;
}
.btn-primary:hover {
  background-color: #1d4ed8;
  border-color: #1d4ed8;
}
a {
  color: #7dd3fc;
}
a:hover {
  color: #bae6fd;
}
.table-dark {
  --bs-table-bg: #22262c;
  --bs-table-color: #e8edf2;
  --bs-table-border-color: #3a4149;
  --bs-table-striped-bg: #262b32;
}
.alert { border-radius: 8px; padding: 12px 14px; margin-bottom: 1rem; font-size: 0.95rem; }
.alert-success { background: #16351a; border: 1px solid #2a7a38; color: #ccefd2; }
.alert-danger { background: #3d1818; border: 1px solid #8b3a3a; color: #fcd4d4; }
.alert-info { background: #162d3d; border: 1px solid #2f6a8f; color: #c8e7f5; }
.text-muted, .small.text-muted {
  color: #9fb0c0 !important;
}
small, .small {
  font-size: 0.92rem;
  line-height: 1.5;
  color: #c5d0db;
}
code {
  color: #f0c674;
  background: rgba(255, 255, 255, 0.06);
  padding: 0.1em 0.35em;
  border-radius: 4px;
  font-size: 0.9em;
}
.table-scroll {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin: 1rem 0;
  border-radius: 8px;
  border: 1px solid #343a42;
  background: #1e2228;
}
.table-scroll table { margin-bottom: 0; }
table.nodes-table {
  width: 100%;
  min-width: 640px;
  font-size: 0.95rem;
  border-collapse: collapse;
}
table.nodes-table thead th {
  background: #2a3038;
  color: #f1f5f9;
  font-weight: 600;
  padding: 12px 11px;
  text-align: left;
  vertical-align: bottom;
  border-color: #3a4149;
  white-space: nowrap;
}
table.nodes-table td {
  border-color: #3a4149 !important;
  padding: 10px 11px;
  vertical-align: top;
  color: #e8edf2;
  word-break: break-word;
  overflow-wrap: anywhere;
}
table.nodes-table tbody tr:hover td {
  background: rgba(125, 211, 252, 0.06);
}
table.nodes-table.table-bbs-dm {
  min-width: 820px;
}
table.nodes-table td.cell-bbs-preview,
table.nodes-table td.cell-dm-text {
  min-width: 14rem;
  max-width: min(52vw, 36rem);
  font-size: 0.93rem;
  line-height: 1.5;
  color: #dce7f0;
}
pre.admin-pre {
  white-space: pre-wrap;
  word-break: break-word;
  background-color: #25292e;
  color: #eef4f8;
  padding: 1rem 1.15rem;
  border-radius: 8px;
  border: 1px solid #3d444c;
  font-size: 0.95rem;
  line-height: 1.5;
}
h2 { color: #f8fafc; font-weight: 600; }
body.page-dashboard { padding-top: 0; }
body.page-login { padding-top: 2rem; }
.dash-header {
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: 1rem; padding: 1.25rem clamp(1rem, 3vw, 2.5rem);
  background: linear-gradient(135deg, #1a3a2a 0%, #1a2d4a 55%, #1a1d21 100%);
  border-bottom: 1px solid #2d3a44; box-shadow: 0 4px 20px rgba(0,0,0,0.35);
}
.dash-brand { display: flex; align-items: center; gap: 1rem; }
.dash-brand h1 { margin: 0; font-size: 1.75rem; color: #f8fafc; font-weight: 700; }
.dash-tagline { margin: 0; color: #9fb0c0; font-size: 0.95rem; }
.dash-logo { font-size: 2.5rem; line-height: 1; }
.btn-admin { white-space: nowrap; font-weight: 600; padding: 0.55rem 1.25rem; }
.dash-main {
  max-width: min(100vw - 1.5rem, 1320px); margin: 0 auto;
  padding: 1.5rem clamp(1rem, 3vw, 2rem) 2.5rem;
}
.stat-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 1rem; margin-bottom: 1.5rem;
}
.stat-card {
  background: #1e2228; border: 1px solid #343a42; border-radius: 10px;
  padding: 1rem 1.1rem; transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.stat-card:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(0,0,0,0.25); }
.stat-title { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; color: #9fb0c0; }
.stat-value { font-size: 1.65rem; font-weight: 700; color: #7dd3fc; margin: 0.25rem 0; }
.stat-sub { font-size: 0.82rem; color: #c5d0db; }
.dash-row {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1.25rem; margin-bottom: 1.25rem;
}
.dash-panel {
  background: #1a1d21; border: 1px solid #343a42; border-radius: 10px;
  padding: 1.15rem 1.25rem;
}
.dash-panel h2 { font-size: 1.05rem; margin-bottom: 0.75rem; color: #e8edf2; }
.dash-list { list-style: none; padding: 0; margin: 0; }
.dash-list li {
  padding: 0.45rem 0; border-bottom: 1px solid #2a3038;
  font-size: 0.9rem; color: #dce7f0; word-break: break-word;
}
.dash-list li:last-child { border-bottom: none; }
.dash-scroll { max-height: 220px; overflow-y: auto; }
.chart-panel canvas { max-height: 200px; }
.motd-box {
  background: #25292e; border-radius: 8px; padding: 0.85rem 1rem;
  border-left: 4px solid #2563eb; margin: 0; color: #eef4f8;
}
.login-wrap {
  max-width: 420px; margin: 2rem auto;
}
.login-hero {
  text-align: center; margin-bottom: 1.5rem;
}
.login-hero h1 { font-size: 1.6rem; color: #f8fafc; margin-bottom: 0.35rem; }
.login-hero p { color: #9fb0c0; margin: 0; }
.login-card {
  background: #1a1d21; border: 1px solid #343a42; border-radius: 12px;
  padding: 1.75rem; box-shadow: 0 8px 28px rgba(0,0,0,0.35);
}
.login-back { display: block; text-align: center; margin-top: 1.25rem; }
</style>
"""

    def _flash_markup():
        raw = """
{% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}
    {% for category, message in messages %}
      <div class="alert alert-{{ 'danger' if category == 'error' else 'success' if category == 'success' else 'info' }}">{{ message }}</div>
    {% endfor %}
  {% endif %}
{% endwith %}
"""
        return render_template_string(raw)

    @app.route("/")
    def index_dashboard():
        from modules.web_dashboard import collect_dashboard, render_dashboard_page

        try:
            data = collect_dashboard(log_dir)
            body = render_dashboard_page(data, admin_url=url_for("admin_login"))
        except Exception as e:
            body = f'<p class="alert alert-danger">Dashboard: {html_escape(str(e))}</p>'
        return render_template_string(
            dark_css + f'<body class="page-dashboard">{body}</body>'
        )

    @app.route("/login")
    @app.route("/admin/login")
    def login_legacy_redirect():
        return redirect(url_for("admin_login"), code=301)

    @limiter.limit("5 per minute")
    @app.route("/admin", methods=["GET", "POST"])
    def admin_login():
        if request.method == "GET" and current_user.is_authenticated:
            return redirect(url_for("choose"))
        error = ""
        if request.method == "POST":
            if (
                request.form.get("username") == admin_username
                and request.form.get("password") == admin_password
            ):
                login_user(User("admin"))
                return redirect(url_for("choose"))
            error = "Falsche Anmeldedaten."
        err_html = (
            f'<p class="alert alert-danger">{html_escape(error)}</p>' if error else ""
        )
        return render_template_string(
            dark_css
            + f"""
<body class="page-login">
  <div class="login-wrap">
    <div class="login-hero">
      <p class="dash-logo mb-2">📡</p>
      <h1>Hessenbot Admin</h1>
      <p>Geschützter Bereich — Nachrichten, NodeDB, BBS, Scheduler</p>
    </div>
    <div class="login-card">
      {err_html}
      <form method="post">
        <label class="form-label small text-muted">Benutzername</label>
        <input type="text" name="username" autocomplete="username"
               class="form-control mb-3" required>
        <label class="form-label small text-muted">Passwort</label>
        <input type="password" name="password" autocomplete="current-password"
               class="form-control mb-3" required>
        <input type="submit" value="Anmelden" class="btn btn-primary w-100">
      </form>
    </div>
    <a href="{{{{ url_for('index_dashboard') }}}}" class="login-back">← Zurück zur Statistik-Übersicht</a>
  </div>
</body>
"""
        )

    @app.route("/choose")
    @login_required
    def choose():
        return render_template_string(
            dark_css
            + """
    <div class="container text-center">
      <h2 class="mb-4">📂 Wähle eine Aktion</h2>
      <a href="{{ url_for('index_dashboard') }}"
         class="btn btn-outline-secondary mb-3 w-100">📊 Statistik-Übersicht (öffentlich)</a>
      <a href="{{url_for('edit', dateiname='direktnachricht')}}"
         class="btn btn-outline-light mb-3 w-100">
        ✉️ Direktnachricht bearbeiten
      </a>
      <a href="{{url_for('edit', dateiname='news')}}"
         class="btn btn-outline-light mb-3 w-100">
        📰 News bearbeiten
      </a>
      <a href="{{url_for('logs')}}"
         class="btn btn-outline-info mb-3 w-100">
        📁 Alle Logdateien anzeigen
      </a>
      <a href="{{url_for('live_messages')}}"
         class="btn btn-outline-success w-100">
        📡 Live-Log: messages.log
      </a>
      <hr class="border-secondary my-4">
      <h3 class="h6 text-secondary mb-3">Bot-Steuerung</h3>
      <a href="{{url_for('nodes_list')}}"
         class="btn btn-outline-warning mb-2 w-100">
        📶 NodeDB (Knoten anzeigen / entfernen)
      </a>
      <a href="{{url_for('motd_edit')}}"
         class="btn btn-outline-warning mb-2 w-100">
        💬 Message of the Day (MOTD)
      </a>
      <a href="{{url_for('scheduler_edit')}}"
         class="btn btn-outline-warning mb-2 w-100">
        ⏰ Geplante Nachrichten (Scheduler)
      </a>
      <a href="{{url_for('bbs_index')}}"
         class="btn btn-outline-warning mb-2 w-100">
        📋 BBS (öffentliche Nachrichten)
      </a>
      <a href="{{url_for('bbs_dm_index')}}"
         class="btn btn-outline-warning mb-2 w-100">
        ✉️ BBS-Direktnachrichten (DM)
      </a>
      <div class="mt-4">
        <a href="{{url_for('logout')}}" class="btn btn-secondary">🔒 Logout</a>
      </div>
    </div>
    """
        )

    @app.route("/edit/<dateiname>", methods=["GET", "POST"])
    @login_required
    def edit(dateiname):
        pfad = dateien.get(dateiname)
        if not pfad:
            return "Ungültiger Dateiname.", 404

        parent = os.path.dirname(pfad)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)

        if request.method == "POST":
            with open(pfad, "w", encoding="utf-8") as f:
                f.write(request.form.get("text", ""))

        if os.path.isfile(pfad):
            with open(pfad, encoding="utf-8") as f:
                inhalt = f.read()
        else:
            inhalt = ""

        return render_template_string(
            dark_css
            + f"""
    <div class="container">
      <h2 class="mb-4 text-center">📝 Datei: {dateiname.capitalize()}</h2>
      <form method="post">
        <textarea name="text" rows="20" class="form-control mb-3">{{{{ inhalt }}}}</textarea>
        <input type="submit" value="Speichern" class="btn btn-success w-100">
      </form>
      <div class="text-center mt-3">
        <a href="{{{{url_for('choose')}}}}" class="btn btn-outline-light">
          ⬅️ Zurück
        </a>
      </div>
    </div>
    """,
            inhalt=inhalt,
        )

    @app.route("/logs")
    @login_required
    def logs():
        try:
            if not os.path.isdir(log_dir):
                os.makedirs(log_dir, exist_ok=True)
            dateien_liste = [
                f
                for f in os.listdir(log_dir)
                if os.path.isfile(os.path.join(log_dir, f))
            ]
        except OSError:
            return "Fehler beim Lesen des Log-Ordners.", 500

        items = "".join(
            f'<a href="{url_for("view_log", filename=f)}" '
            f'class="btn btn-dark mb-2 w-100">📄 {f}</a>'
            for f in sorted(dateien_liste)
        )

        return render_template_string(
            dark_css
            + f"""
    <div class="container text-center">
      <h2 class="mb-4">📁 Alle Dateien im Log-Ordner</h2>
      {items if items else "<p>Keine Dateien gefunden.</p>"}
      <div class="mt-4">
        <a href="{{{{url_for('choose')}}}}" class="btn btn-outline-light">
          ⬅️ Zurück
        </a>
      </div>
    </div>
    """
        )

    @app.route("/view/<filename>")
    @login_required
    def view_log(filename):
        pfad = _safe_log_file(log_dir, filename)
        if not pfad:
            return "Datei nicht gefunden.", 404

        try:
            with open(pfad, encoding="utf-8") as f:
                inhalt = f.read()
        except OSError:
            inhalt = "[Fehler beim Öffnen der Datei]"

        return render_template_string(
            dark_css
            + f"""
    <div class="container">
      <h2 class="mb-4 text-center">📄 Datei: {filename}</h2>
      <pre class="admin-pre">{inhalt}</pre>
      <div class="text-center mt-3">
        <a href="{{{{url_for('logs')}}}}" class="btn btn-outline-light">
          ⬅️ Zurück zur Übersicht
        </a>
      </div>
    </div>
    """
        )

    @app.route("/live/messages")
    @login_required
    def live_messages():
        import modules.settings as st

        log_path = _messages_log_path(log_dir)
        hint = (
            f'<p class="small text-muted">Repo: <code>{html_escape(repo_root())}</code> · '
            f'Log: <code>{html_escape(log_path)}</code></p>'
        )
        if not st.log_messages_to_file:
            inhalt = (
                "Nachrichten-Log ist deaktiviert.\n\n"
                "In config.ini unter [general] setzen:\n"
                "  LogMessagesToFile = True\n\n"
                "Bot neu starten. Die Datei liegt dann unter logs/messages.log."
            )
        elif not os.path.isfile(log_path):
            inhalt = (
                f"Datei nicht gefunden:\n{log_path}\n\n"
                "Nach dem Aktivieren von LogMessagesToFile ein paar Mesh-Nachrichten senden, "
                "damit die Datei angelegt wird."
            )
        else:
            try:
                inhalt = _read_messages_log_tail(log_path)
                if not inhalt.strip():
                    inhalt = "(Datei ist leer — noch keine Nachrichten protokolliert.)"
            except PermissionError:
                inhalt = (
                    f"Keine Leserechte für:\n{log_path}\n\n"
                    f"Rechte setzen, z. B.:\n"
                    f"  sudo ./etc/set-permissions.sh <service-user> {repo_root()}"
                )
            except OSError as e:
                inhalt = f"Fehler beim Öffnen:\n{log_path}\n\n{e}"

        return render_template_string(
            dark_css
            + f"""
<meta http-equiv="refresh" content="5">
<div class="container">
  <h2 class="mb-4 text-center">📡 Bereinigte Live-Ansicht: messages.log</h2>
  {hint}
  <pre class="admin-pre">{html_escape(inhalt)}</pre>
  <div class="text-center mt-3">
    <a href="{{{{url_for('choose')}}}}"
       class="btn btn-outline-light">⬅️ Zurück</a>
  </div>
</div>
"""
        )

    @app.route("/nodes")
    @login_required
    def nodes_list():
        from modules import admin_web_ops as ops

        try:
            ifaces = ops.iter_radio_interfaces()
        except Exception as e:
            return (
                render_template_string(
                    dark_css
                    + _flash_markup()
                    + """
<div class="container">
  <p class="alert alert-danger">System-Modul: {{ err }}</p>
  <a href="{{ url_for('choose') }}" class="btn btn-outline-light">Zurück</a>
</div>
""",
                    err=str(e),
                ),
                500,
            )

        if not ifaces:
            body = '<p class="alert alert-info">Keine aktive Meshtastic-Schnittstelle (Bot läuft ohne Radio oder noch nicht verbunden).</p>'
        else:
            try:
                q = request.args.get("iface", type=int)
            except Exception:
                q = None
            iface_id = q if q in ifaces else ifaces[0]
            err, rows = ops.list_node_rows(iface_id)
            if err:
                body = f'<p class="alert alert-danger">{err}</p>'
            else:
                tab_parts = []
                for i in ifaces:
                    cls = "btn-light" if i == iface_id else "btn-outline-secondary"
                    tab_parts.append(
                        f'<a class="btn btn-sm {cls}" href="{url_for("nodes_list", iface=i)}">IF {i}</a>'
                    )
                tabs = " ".join(tab_parts)
                rows_html = []
                for r in rows:
                    del_btn = ""
                    if not r["is_self"]:
                        del_btn = (
                            f'<form method="post" action="{url_for("nodes_remove")}" style="display:inline" '
                            f'onsubmit="return confirm(\'Knoten {r["num"]} wirklich aus der NodeDB entfernen?\');">'
                            f'<input type="hidden" name="iface_id" value="{iface_id}">'
                            f'<input type="hidden" name="node_num" value="{r["num"]}">'
                            f'<button type="submit" class="btn btn-sm btn-danger">Entfernen</button></form>'
                        )
                    else:
                        del_btn = '<span class="text-muted">(lokal)</span>'
                    rows_html.append(
                        "<tr>"
                        f"<td><code>{r['num']}</code></td>"
                        f"<td><code>{r['node_id']}</code></td>"
                        f"<td>{r['shortName']}</td>"
                        f"<td>{r['longName']}</td>"
                        f"<td>{r['lastHeard']}</td>"
                        f"<td>{html_escape(str(r['snr']))}</td>"
                        f"<td>{del_btn}</td>"
                        "</tr>"
                    )
                body = f"""
<p class="small text-muted mb-2">Schnittstelle: {tabs}</p>
<p class="small">Entfernen sendet einen Admin-Befehl an dein lokales Gerät (wie meshtastic --remove-node).</p>
<div class="table-scroll"><table class="nodes-table table-dark table-bordered">
<thead><tr><th>Nr.</th><th>Node ID</th><th>Kurz</th><th>Lang</th><th>Zuletzt</th><th>SNR</th><th></th></tr></thead>
<tbody>{"".join(rows_html)}</tbody></table></div>"""

        return render_template_string(
            dark_css
            + _flash_markup()
            + """
<div class="container">
  <h2 class="mb-4">📶 Meshtastic NodeDB</h2>
  {{ body }}
  <div class="text-center mt-4">
    <a href="{{ url_for('choose') }}" class="btn btn-outline-light">Zurück</a>
  </div>
</div>
""",
            body=Markup(body),
        )

    @app.route("/nodes/remove", methods=["POST"])
    @login_required
    @limiter.limit("30 per minute")
    def nodes_remove():
        from modules import admin_web_ops as ops

        try:
            iface_id = int(request.form.get("iface_id", "1"))
            node_num = int(request.form.get("node_num", "0"))
        except ValueError:
            flash("Ungültige Parameter.", "error")
            return redirect(url_for("nodes_list"))
        if iface_id < 1 or iface_id > 9 or node_num <= 0:
            flash("Ungültige Parameter.", "error")
            return redirect(url_for("nodes_list", iface=iface_id))
        msg = ops.remove_node_from_radio(iface_id, node_num)
        if msg.startswith("Fehler") or msg.startswith("Der eigene") or msg.startswith("Interface"):
            flash(msg, "error")
        else:
            flash(msg, "success")
        return redirect(url_for("nodes_list", iface=iface_id))

    @app.route("/motd", methods=["GET", "POST"])
    @login_required
    def motd_edit():
        from modules import admin_web_ops as ops
        import modules.settings as st

        if request.method == "POST":
            text = request.form.get("motd", "")
            try:
                ops.save_motd_to_config(text)
            except Exception as e:
                flash(f"Speichern fehlgeschlagen: {e!s}", "error")
            else:
                flash("MOTD in config.ini gespeichert und im laufenden Bot übernommen.", "success")
            return redirect(url_for("motd_edit"))

        return render_template_string(
            dark_css
            + _flash_markup()
            + """
<div class="container">
  <h2 class="mb-4">💬 Message of the Day</h2>
  <form method="post">
    <textarea name="motd" rows="8" class="form-control mb-3">{{ motd }}</textarea>
    <input type="submit" value="Speichern" class="btn btn-success w-100">
  </form>
  <p class="small text-muted mt-3">Wird in <code>[general] motd</code> geschrieben; der Bot nutzt <code>my_settings.MOTD</code>.</p>
  <div class="text-center mt-3">
    <a href="{{ url_for('choose') }}" class="btn btn-outline-light">Zurück</a>
  </div>
</div>
""",
            motd=st.MOTD,
        )

    @app.route("/scheduler", methods=["GET", "POST"])
    @login_required
    def scheduler_edit():
        from modules import admin_web_ops as ops
        import modules.settings as st

        if request.method == "POST":
            prev_en = request.form.get("_prev_enabled") == "True"
            try:
                enabled = request.form.get("enabled") == "on"
                iface = int(request.form.get("interface", "1"))
                channel = int(request.form.get("channel", "0"))
            except ValueError:
                flash("Interface/Kanal ungültig.", "error")
                return redirect(url_for("scheduler_edit"))
            message = request.form.get("message", "")
            sched_motd = request.form.get("schedulerMotd") == "on"
            value = (request.form.get("value") or "").strip()
            interval = request.form.get("interval", "")
            sched_time = request.form.get("time", "")
            if not value:
                flash("Bitte einen Zeitplantyp aus der Liste wählen.", "error")
                return redirect(url_for("scheduler_edit"))
            try:
                ops.save_scheduler_to_config(
                    enabled, iface, channel, message, sched_motd, value, interval, sched_time
                )
            except Exception as e:
                flash(f"Speichern fehlgeschlagen: {e!s}", "error")
                return redirect(url_for("scheduler_edit"))

            import schedule

            if enabled:
                ops.rebuild_scheduler_jobs()
                flash("Scheduler-Einstellungen gespeichert; Jobliste wurde neu aufgebaut.", "success")
                if not prev_en:
                    flash(
                        "Hinweis: Wenn der Scheduler beim Start des Bots aus war, starte den Bot neu, damit der Zeitplan wirklich ausgeführt wird.",
                        "info",
                    )
            else:
                schedule.clear()
                flash("Scheduler deaktiviert; alle geplanten Jobs wurden entfernt.", "info")

            if prev_en != enabled:
                flash("Ein/Aus-Status geändert: bei unerwartetem Verhalten Bot einmal neu starten.", "info")

            return redirect(url_for("scheduler_edit"))

        prev = "True" if st.scheduler_enabled else "False"
        chk_en = " checked" if st.scheduler_enabled else ""
        chk_sm = " checked" if st.schedulerMotd else ""

        presets = [
            ("day", "Täglich / alle N Tage (day)"),
            ("hour", "Alle N Stunden (hour)"),
            ("min", "Alle N Minuten (min)"),
            ("mon", "Montags zur Uhrzeit (mon)"),
            ("tue", "Dienstags zur Uhrzeit (tue)"),
            ("wed", "Mittwochs zur Uhrzeit (wed)"),
            ("thu", "Donnerstags zur Uhrzeit (thu)"),
            ("fri", "Freitags zur Uhrzeit (fri)"),
            ("sat", "Samstags zur Uhrzeit (sat)"),
            ("sun", "Sonntags zur Uhrzeit (sun)"),
            ("joke", "Witz — Intervall = Minuten (joke)"),
            ("link", "bbslink — Intervall = Stunden (link)"),
            ("weather", "Wetter — täglich zur Uhrzeit (weather)"),
            ("news", "News — Intervall = Stunden (news)"),
            ("readrss", "RSS — Intervall = Stunden (readrss)"),
            ("mwx", "Marinewetter — täglich zur Uhrzeit (mwx)"),
            ("sysinfo", "Sysinfo — Intervall = Stunden (sysinfo)"),
            ("tide", "Gezeiten — täglich zur Uhrzeit (tide)"),
            ("solar", "Sonne — täglich zur Uhrzeit (solar)"),
            ("verse", "Bibelvers — täglich zur Uhrzeit (verse)"),
            ("custom", "Eigene Logik (custom, modules/custom_scheduler.py)"),
        ]
        cur_raw = (st.schedulerValue or "").strip()
        cur = cur_raw.lower()
        opt_parts = [
            '<select name="value" class="form-control mb-2" required>',
            '<option value="">— Zeitplantyp wählen —</option>',
        ]
        matched = False
        for v, lab in presets:
            sel = " selected" if cur == v else ""
            if sel:
                matched = True
            opt_parts.append(
                f'<option value="{html_escape(v, quote=True)}"{sel}>{html_escape(lab)}</option>'
            )
        if cur_raw and not matched:
            opt_parts.append(
                f'<option value="{html_escape(cur_raw.strip(), quote=True)}" selected>'
                f"Freitext: {html_escape(cur_raw.strip())}</option>"
            )
        opt_parts.append("</select>")
        schedule_select_html = Markup("".join(opt_parts))

        return render_template_string(
            dark_css
            + _flash_markup()
            + """
<div class="container">
  <h2 class="mb-4">⏰ Scheduler</h2>
  <form method="post">
    <input type="hidden" name="_prev_enabled" value="{{ prev }}">
    <div class="form-check mb-3">
      <input class="form-check-input" type="checkbox" name="enabled" id="sen"{{ chk_en|safe }}>
      <label class="form-check-label" for="sen">Scheduler aktiv</label>
    </div>
    <div class="row mb-2">
      <div class="col"><label>Interface (Radio)</label>
        <input type="number" name="interface" class="form-control" min="1" max="9" value="{{ iface }}"></div>
      <div class="col"><label>Kanal</label>
        <input type="number" name="channel" class="form-control" value="{{ chan }}"></div>
    </div>
    <div class="form-check mb-2">
      <input class="form-check-input" type="checkbox" name="schedulerMotd" id="sm"{{ chk_sm|safe }}>
      <label class="form-check-label" for="sm">MOTD als geplante Nachricht verwenden (statt Textfeld)</label>
    </div>
    <label>Nachricht (nur wenn MOTD-Haken aus)</label>
    <textarea name="message" rows="3" class="form-control mb-3">{{ msg }}</textarea>

    <label class="form-label fw-semibold">Zeitplantyp <span class="text-muted fw-normal">(config: value)</span></label>
    {{ schedule_select|safe }}

    <label class="form-label fw-semibold">Intervall <span class="text-muted fw-normal">(Zahl, config: interval)</span></label>
    <input type="number" name="interval" class="form-control mb-2" min="1" step="1"
           placeholder="z.B. 5" value="{{ ivl }}">
    <p class="small text-muted mb-2">
      <strong>day:</strong> ohne Uhrzeit = alle N Tage; mit Uhrzeit = alle N Tage zur gleichen Uhrzeit.
      <strong>hour / min:</strong> alle N Stunden bzw. Minuten.
      <strong>mon … sun:</strong> Uhrzeit unten setzen (HH:MM).
      <strong>joke:</strong> Minuten; <strong>link, news, readrss, sysinfo:</strong> Stunden.
      <strong>weather, mwx, tide, solar, verse:</strong> Uhrzeit Pflicht, Intervall oft egal (siehe Code).
    </p>

    <label class="form-label fw-semibold">Uhrzeit <span class="text-muted fw-normal">(HH:MM, config: time)</span></label>
    <input type="text" name="time" class="form-control mb-3" placeholder="z.B. 08:30" value="{{ tim }}"
           pattern="[0-2][0-9]:[0-5][0-9]" title="Format 00:00 bis 23:59">

    <details class="mb-3 p-3 rounded" style="background:#2a2a2a;border:1px solid #444;">
      <summary class="fw-semibold">Kurzübersicht (technisch: modules/scheduler.py)</summary>
      <table class="table table-sm table-dark mt-2 mb-0 small">
        <thead><tr><th>value</th><th>Intervall</th><th>Uhrzeit</th></tr></thead>
        <tbody>
          <tr><td>day</td><td>Tage (1=täglich)</td><td>optional, sonst nur Tagesabstand</td></tr>
          <tr><td>hour / min</td><td>Stunden bzw. Minuten</td><td>—</td></tr>
          <tr><td>mon … sun</td><td>—</td><td>erforderlich</td></tr>
          <tr><td>joke</td><td>Minuten</td><td>—</td></tr>
          <tr><td>link, news, readrss, sysinfo</td><td>Stunden</td><td>—</td></tr>
          <tr><td>weather, mwx, tide, solar, verse</td><td>(siehe Log)</td><td>erforderlich</td></tr>
        </tbody>
      </table>
    </details>

    <input type="submit" value="Speichern" class="btn btn-success w-100">
  </form>
  <p class="small text-muted mt-3">Vollständige Optionen: <code>config.template</code> → <code>[scheduler]</code>.</p>
  <div class="text-center mt-3">
    <a href="{{ url_for('choose') }}" class="btn btn-outline-light">Zurück</a>
  </div>
</div>
""",
            prev=prev,
            chk_en=chk_en,
            chk_sm=chk_sm,
            iface=st.schedulerInterface,
            chan=st.schedulerChannel,
            msg=st.schedulerMessage,
            ivl=st.schedulerInterval,
            tim=st.schedulerTime,
            schedule_select=schedule_select_html,
        )

    @app.route("/bbs")
    @login_required
    def bbs_index():
        import modules.bbstools as bbs
        import modules.settings as st

        hint = ""
        if not st.bbs_enabled:
            hint = (
                '<p class="alert alert-info">Das Mesh-BBS ist unter <code>[bbs] enabled = False</code> '
                "deaktiviert. Bearbeitung wirkt trotzdem auf die laufende Bot-Instanz und "
                f"<code>{html_escape(st.bbsdb)}</code>.</p>"
            )

        rows_html = []
        for m in bbs.bbs_messages:
            mid = m[0]
            subj = html_escape(str(m[1]))
            raw_body = m[2] if len(m) > 2 else ""
            preview = html_escape(raw_body[:120] + ("…" if len(raw_body) > 120 else ""))
            fn = m[3] if len(m) > 3 else 0
            when = html_escape(str(m[4])) if len(m) > 4 else ""
            try:
                fn_h = html_escape(hex(int(fn)))
            except (TypeError, ValueError):
                fn_h = html_escape(str(fn))
            del_form = (
                f'<form method="post" action="{url_for("bbs_delete", mid=mid)}" style="display:inline" '
                f'onsubmit="return confirm(\'Nachricht #{mid} wirklich löschen?\');">'
                '<button type="submit" class="btn btn-sm btn-danger">Löschen</button></form>'
            )
            rows_html.append(
                "<tr>"
                f"<td><code>{mid}</code></td><td>{subj}</td>"
                f'<td class="cell-bbs-preview">{preview}</td>'
                f"<td><code>{fn_h}</code></td><td>{when}</td>"
                f'<td><a class="btn btn-sm btn-outline-info" href="{url_for("bbs_read", mid=mid)}">'
                "Text</a> "
                f"{del_form}</td>"
                "</tr>"
            )
        table = "".join(rows_html) if rows_html else '<tr><td colspan="6">Keine Nachrichten.</td></tr>'

        body = (
            hint
            + f'<p><a class="btn btn-success mb-3" href="{url_for("bbs_new")}">Neue Nachricht</a></p>'
            + '<div class="table-scroll"><table class="nodes-table table-dark table-bordered">'
            + "<thead><tr><th>#</th><th>Betreff</th><th>Vorschau</th><th>Von (Node)</th><th>Zeit</th><th></th></tr></thead>"
            + f"<tbody>{table}</tbody></table></div>"
            + f'<p class="small text-muted">Speicher: <code>{html_escape(st.bbsdb)}</code> · '
            + f'<a href="{url_for("bbs_dm_index")}">BBS-DMs verwalten</a></p>'
        )

        return render_template_string(
            dark_css
            + _flash_markup()
            + """
<div class="container">
  <h2 class="mb-4">📋 BBS — öffentliche Nachrichten</h2>
  {{ body|safe }}
  <div class="text-center mt-3"><a href="{{ url_for('choose') }}" class="btn btn-outline-light">Zurück</a></div>
</div>
""",
            body=Markup(body),
        )

    @app.route("/bbs/read/<int:mid>")
    @login_required
    def bbs_read(mid):
        import modules.bbstools as bbs

        if mid < 1 or mid > len(bbs.bbs_messages):
            flash("Nachricht nicht gefunden.", "error")
            return redirect(url_for("bbs_index"))
        m = bbs.bbs_messages[mid - 1]
        subj = html_escape(str(m[1]))
        raw_body = m[2] if len(m) > 2 else ""
        body_esc = html_escape(raw_body)
        fn = m[3] if len(m) > 3 else 0
        try:
            fn_h = html_escape(hex(int(fn)))
        except (TypeError, ValueError):
            fn_h = html_escape(str(fn))
        when = html_escape(str(m[4])) if len(m) > 4 else ""
        return render_template_string(
            dark_css
            + _flash_markup()
            + f"""
<div class="container">
  <h2 class="mb-4">📋 BBS #{mid}</h2>
  <p><strong>Betreff:</strong> {subj}</p>
  <p><strong>Von:</strong> <code>{fn_h}</code> &nbsp; <strong>Zeit:</strong> {when}</p>
  <pre class="admin-pre">{body_esc}</pre>
  <div class="text-center mt-3">
    <a href="{{{{ url_for('bbs_index') }}}}" class="btn btn-outline-light">Zurück zur Liste</a>
  </div>
</div>
""",
        )

    @app.route("/bbs/new", methods=["GET", "POST"])
    @login_required
    def bbs_new():
        import modules.bbstools as bbs

        if request.method == "POST":
            subj = (request.form.get("subject") or "").strip()
            body_txt = request.form.get("body") or ""
            if not subj:
                flash("Betreff darf nicht leer sein.", "error")
            else:
                flash(bbs.bbs_post_message(subj, body_txt, 0), "success")
            return redirect(url_for("bbs_index"))

        return render_template_string(
            dark_css
            + _flash_markup()
            + """
<div class="container">
  <h2 class="mb-4">📋 Neue BBS-Nachricht</h2>
  <p class="small text-muted">Wird wie <code>bbspost</code> mit Absender-Node <code>0</code> (Web-Admin) eingetragen.</p>
  <form method="post">
    <label>Betreff</label>
    <input type="text" name="subject" class="form-control mb-3" required maxlength="500">
    <label>Text</label>
    <textarea name="body" rows="12" class="form-control mb-3"></textarea>
    <input type="submit" value="Veröffentlichen" class="btn btn-success w-100">
  </form>
  <div class="text-center mt-3">
    <a href="{{ url_for('bbs_index') }}" class="btn btn-outline-light">Abbrechen / Liste</a>
  </div>
</div>
""",
        )

    @app.route("/bbs/delete/<int:mid>", methods=["POST"])
    @login_required
    @limiter.limit("60 per minute")
    def bbs_delete(mid):
        from modules import bbstools as bbs

        ok, txt = bbs.bbs_delete_message_system(mid)
        flash(txt, "success" if ok else "error")
        return redirect(url_for("bbs_index"))

    @app.route("/bbs/dm")
    @login_required
    def bbs_dm_index():
        import modules.bbstools as bbs
        import modules.settings as st

        hint = ""
        if not st.bbs_enabled:
            hint = (
                '<p class="alert alert-info">BBS ist unter <code>[bbs] enabled = False</code> '
                "deaktiviert. Die DM-Liste im laufenden Bot kannst du hier trotzdem bearbeiten.</p>"
            )
        hint += (
            "<p class=\"small text-muted\">Format pro Zeile: <code>[Ziel-Node, Text, Absender-Node]</code>. "
            "Zeile <strong>0</strong> ist ein interner Platzhalter (wird in <code>bbsinfo</code> nicht mitgezählt) "
            "und kann nicht gelöscht werden. Datei: <code>data/bbsdm.pkl</code>.</p>"
        )

        rows_html = []
        for idx, row in enumerate(bbs.bbs_dm):
            to_n = row[0] if len(row) > 0 else 0
            text = row[1] if len(row) > 1 else ""
            from_n = row[2] if len(row) > 2 else 0
            try:
                to_h = html_escape(hex(int(to_n)))
            except (TypeError, ValueError):
                to_h = html_escape(str(to_n))
            try:
                from_h = html_escape(hex(int(from_n)))
            except (TypeError, ValueError):
                from_h = html_escape(str(from_n))
            preview = html_escape(text[:100] + ("…" if len(text) > 100 else ""))
            if idx == 0:
                actions = '<span class="text-muted">(Platzhalter)</span>'
            else:
                actions = (
                    f'<a class="btn btn-sm btn-outline-info" href="{url_for("bbs_dm_read", idx=idx)}">Text</a> '
                    f'<form method="post" action="{url_for("bbs_dm_delete", idx=idx)}" style="display:inline" '
                    f'onsubmit="return confirm(\'DM-Zeile {idx} wirklich löschen?\');">'
                    '<button type="submit" class="btn btn-sm btn-danger">Löschen</button></form>'
                )
            rows_html.append(
                "<tr>"
                f"<td><code>{idx}</code></td><td><code>{to_h}</code></td><td><code>{from_h}</code></td>"
                f'<td class="cell-dm-text">{preview}</td><td>{actions}</td>'
                "</tr>"
            )
        table = "".join(rows_html) if rows_html else '<tr><td colspan="5">Keine Einträge.</td></tr>'

        body = (
            hint
            + f'<p><a class="btn btn-success mb-3" href="{url_for("bbs_dm_new")}">Neue DM</a> '
            + f'<a class="btn btn-outline-secondary mb-3" href="{url_for("bbs_index")}">Öffentliches BBS</a></p>'
            + '<div class="table-scroll"><table class="nodes-table table-dark table-bordered table-bbs-dm">'
            + "<thead><tr><th>#</th><th>An (Node)</th><th>Von (Node)</th><th>Text</th><th></th></tr></thead>"
            + f"<tbody>{table}</tbody></table></div>"
        )

        return render_template_string(
            dark_css
            + _flash_markup()
            + """
<div class="container">
  <h2 class="mb-4">✉️ BBS — Direktnachrichten</h2>
  {{ body|safe }}
  <div class="text-center mt-3"><a href="{{ url_for('choose') }}" class="btn btn-outline-light">Zurück</a></div>
</div>
""",
            body=Markup(body),
        )

    @app.route("/bbs/dm/read/<int:idx>")
    @login_required
    def bbs_dm_read(idx):
        import modules.bbstools as bbs

        if idx < 0 or idx >= len(bbs.bbs_dm):
            flash("Eintrag nicht gefunden.", "error")
            return redirect(url_for("bbs_dm_index"))
        row = bbs.bbs_dm[idx]
        to_n, text, from_n = row[0], row[1] if len(row) > 1 else "", row[2] if len(row) > 2 else 0
        try:
            to_h = html_escape(hex(int(to_n)))
        except (TypeError, ValueError):
            to_h = html_escape(str(to_n))
        try:
            from_h = html_escape(hex(int(from_n)))
        except (TypeError, ValueError):
            from_h = html_escape(str(from_n))
        body_esc = html_escape(text)
        return render_template_string(
            dark_css
            + _flash_markup()
            + f"""
<div class="container">
  <h2 class="mb-4">✉️ BBS-DM Zeile #{idx}</h2>
  <p><strong>An:</strong> <code>{to_h}</code> &nbsp; <strong>Von:</strong> <code>{from_h}</code></p>
  <pre class="admin-pre">{body_esc}</pre>
  <div class="text-center mt-3">
    <a href="{{{{ url_for('bbs_dm_index') }}}}" class="btn btn-outline-light">Zurück zur Liste</a>
  </div>
</div>
""",
        )

    @app.route("/bbs/dm/new", methods=["GET", "POST"])
    @login_required
    def bbs_dm_new():
        import modules.bbstools as bbs

        if request.method == "POST":
            raw_to = (request.form.get("to_node") or "").strip()
            body_txt = request.form.get("body") or ""
            raw_from = (request.form.get("from_node") or "").strip() or "0"

            to_node = 0
            if raw_to.startswith("!") and len(raw_to) >= 2:
                try:
                    to_node = int(raw_to[1:], 16)
                except ValueError:
                    to_node = 0
            else:
                try:
                    to_node = int(raw_to)
                except ValueError:
                    to_node = 0

            try:
                from_node = int(raw_from)
            except ValueError:
                from_node = 0

            if to_node == 0:
                flash("Ziel-Node ungültig (Dezimal oder !hex, z. B. !1234abcd).", "error")
            elif not body_txt.strip():
                flash("Nachricht darf nicht leer sein.", "error")
            else:
                flash(bbs.bbs_post_dm(to_node, body_txt.strip(), from_node), "success")
            return redirect(url_for("bbs_dm_index"))

        return render_template_string(
            dark_css
            + _flash_markup()
            + """
<div class="container">
  <h2 class="mb-4">✉️ Neue BBS-DM</h2>
  <p class="small text-muted">Wie <code>bbspost @Ziel #Text</code>: Ziel als Dezimal-Node-ID oder Meshtastic-<code>!hex</code> (9 Zeichen).</p>
  <form method="post">
    <label>Ziel-Node</label>
    <input type="text" name="to_node" class="form-control mb-2" placeholder="z.B. 2813308004 oder !a1b2c3d4" required>
    <label>Absender-Node (optional, Standard 0 = Web)</label>
    <input type="text" name="from_node" class="form-control mb-3" value="0" placeholder="0">
    <label>Nachricht</label>
    <textarea name="body" rows="10" class="form-control mb-3" required></textarea>
    <input type="submit" value="Absenden" class="btn btn-success w-100">
  </form>
  <div class="text-center mt-3">
    <a href="{{ url_for('bbs_dm_index') }}" class="btn btn-outline-light">Abbrechen</a>
  </div>
</div>
""",
        )

    @app.route("/bbs/dm/delete/<int:idx>", methods=["POST"])
    @login_required
    @limiter.limit("60 per minute")
    def bbs_dm_delete(idx):
        from modules import bbstools as bbs

        ok, txt = bbs.bbs_delete_dm_at_index(idx)
        flash(txt, "success" if ok else "error")
        return redirect(url_for("bbs_dm_index"))

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("index_dashboard"))

    return app


def start_admin_web_background():
    """Spawn Flask app in a daemon thread (call from mesh_bot after settings load)."""
    from modules.log import logger
    import modules.settings as my_settings

    if not my_settings.web_admin_enabled:
        return

    pw = os.environ.get("HESSENBOT_WEB_PASSWORD", my_settings.web_admin_password)
    if not pw:
        logger.error(
            "Web admin: enabled but no password; set [webAdmin] password or HESSENBOT_WEB_PASSWORD."
        )
        return

    sk = os.environ.get("HESSENBOT_WEB_SECRET", my_settings.web_admin_secret_key)
    if not sk:
        sk = secrets.token_hex(32)
        logger.warning(
            "Web admin: no secret_key / HESSENBOT_WEB_SECRET; using a random session key (restarts log you out)."
        )

    alert_p = (
        _abs_path(my_settings.web_admin_alert_file)
        if my_settings.web_admin_alert_file
        else _abs_path(my_settings.file_monitor_file_path)
    )
    news_p = (
        _abs_path(my_settings.web_admin_news_file)
        if my_settings.web_admin_news_file
        else _abs_path(my_settings.news_file_path)
    )
    log_d = (
        _abs_path(my_settings.web_admin_log_dir)
        if my_settings.web_admin_log_dir
        else _abs_path("logs")
    )

    app = create_app(
        alert_path=alert_p,
        news_path=news_p,
        log_dir=log_d,
        admin_username=my_settings.web_admin_username,
        admin_password=pw,
        secret_key=sk,
    )

    host = my_settings.web_admin_host
    port = my_settings.web_admin_port

    def run():
        app.run(
            host=host,
            port=port,
            debug=False,
            use_reloader=False,
            threaded=True,
        )

    threading.Thread(target=run, daemon=True, name="web_admin").start()
    logger.info(
        f"Web UI listening on http://{host}:{port}/ (stats) and http://{host}:{port}/admin (login)"
    )
