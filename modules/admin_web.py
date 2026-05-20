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
from modules.admin_web_theme import (
    ADMIN_TABS,
    portal_shell_end,
    portal_shell_start,
)

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
    app = Flask(
        __name__,
        static_folder=path_in_repo("static"),
        static_url_path="/static",
    )
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

    def _admin_tabs_html(active: str) -> str:
        parts = ['<nav class="admin-tab-bar" aria-label="Admin-Navigation">']
        for tab_id, label, endpoint in ADMIN_TABS:
            cls = "admin-tab admin-tab--active" if active == tab_id else "admin-tab"
            parts.append(
                f'<a href="{url_for(endpoint)}" class="{cls}">{html_escape(label)}</a>'
            )
        parts.append('<span class="admin-tab-spacer"></span>')
        parts.append(
            f'<a href="{url_for("logout")}" class="admin-tab admin-tab--logout">Logout</a>'
        )
        parts.append("</nav>")
        return "".join(parts)

    def _render_admin_page(inner_html: str, *, title: str, active_tab: str) -> str:
        block = f"""
<div class="portal-wrapper portal-wrapper--admin">
  <main class="portal-main">
    <div class="home-content portal-admin-content py-4">
      <h1 class="h3 section-title mb-3">
        <i class="bi bi-gear-wide-connected text-success me-2"></i>{html_escape(title)}
      </h1>
      {_admin_tabs_html(active_tab)}
      <div class="portal-card">
        {inner_html}
      </div>
    </div>
  </main>
</div>
"""
        return (
            portal_shell_start(
                title=f"{title} – Hessenbot",
                particles=False,
                active_nav="admin",
            )
            + block
            + portal_shell_end()
        )

    def _render_admin_template(template: str, *, title: str, active_tab: str, **ctx):
        body = render_template_string(template, **ctx)
        return _render_admin_page(_flash_markup() + str(body), title=title, active_tab=active_tab)

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

    def _render_faq_page(pki_result=None):
        from modules.web_faq_help import render_faq_page_body

        body = render_faq_page_body(pki_result)
        return (
            portal_shell_start(
                title="FAQ / Hilfe – Hessenbot",
                active_nav="faq",
                particles=True,
                admin_href=url_for(
                    "choose" if current_user.is_authenticated else "admin_login"
                ),
            )
            + '<div class="portal-wrapper portal-wrapper--stats"><main class="portal-main">'
            + '<div class="home-content container-fluid py-4 cmd-help-page">'
            + body
            + "</div></main></div>"
            + portal_shell_end()
        )

    @app.route("/faq")
    @app.route("/hilfe")
    def faq_help():
        return _render_faq_page()

    @limiter.limit("20 per minute")
    @app.route("/faq/pki-check", methods=["POST"])
    def faq_pki_check():
        from modules.web_faq_pki_check import scan_pki_log_for_node

        node_raw = (request.form.get("node_id") or "").strip()
        result = scan_pki_log_for_node(node_raw, log_dir)
        result["node_input"] = node_raw
        return _render_faq_page(result)

    @app.route("/befehle")
    @app.route("/commands")
    def commands_help():
        from modules.web_commands_help import render_commands_page_body

        body = render_commands_page_body()
        return (
            portal_shell_start(
                title="Befehle – Hessenbot",
                active_nav="commands",
                particles=True,
                admin_href=url_for(
                    "choose" if current_user.is_authenticated else "admin_login"
                ),
            )
            + '<div class="portal-wrapper portal-wrapper--stats"><main class="portal-main">'
            + '<div class="home-content container-fluid py-4 cmd-help-page">'
            + body
            + "</div></main></div>"
            + portal_shell_end()
        )

    @app.route("/")
    def index_dashboard():
        from modules.web_dashboard import collect_dashboard, render_dashboard_page

        try:
            data = collect_dashboard(log_dir)
            body = render_dashboard_page(data)
        except Exception as e:
            body = f'<p class="alert alert-danger">Dashboard: {html_escape(str(e))}</p>'
        return (
            portal_shell_start(
                title="Statistik – Hessenbot",
                active_nav="stats",
                particles=True,
                dash_view_tabs=True,
                admin_href=url_for(
                    "choose" if current_user.is_authenticated else "admin_login"
                ),
            )
            + '<div class="portal-wrapper portal-wrapper--stats"><main class="portal-main">'
            + '<div class="home-content container-fluid py-4">'
            + body
            + "</div></main></div>"
            + portal_shell_end()
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
        login_inner = f"""
<div class="login-page-center">
  <div class="login-card-wrap w-100" style="max-width:420px">
    <div class="card shadow-sm">
      <div class="card-body p-4">
        <div class="text-center mb-4">
          <i class="bi bi-shield-lock text-success display-6"></i>
          <h1 class="h4 mt-2 mb-1">Hessenbot Admin</h1>
          <p class="text-muted small mb-0">NodeDB, BBS, Scheduler, Logs</p>
        </div>
        {err_html}
        <form method="post">
          <label class="form-label small">Benutzername</label>
          <input type="text" name="username" autocomplete="username"
                 class="form-control mb-3" required>
          <label class="form-label small">Passwort</label>
          <input type="password" name="password" autocomplete="current-password"
                 class="form-control mb-3" required>
          <button type="submit" class="btn btn-success w-100">Anmelden</button>
        </form>
        <p class="text-center mt-3 mb-0">
          <a href="{url_for('index_dashboard')}" class="small text-muted">
            <i class="bi bi-arrow-left me-1"></i>Zur Statistik
          </a>
        </p>
      </div>
    </div>
  </div>
</div>
"""
        return (
            portal_shell_start(
                title="Admin – Hessenbot",
                body_class="page-login",
                active_nav="admin",
                particles=False,
            )
            + login_inner
            + portal_shell_end()
        )

    @app.route("/choose")
    @login_required
    def choose():
        from modules.web_dashboard import (
            collect_dashboard,
            render_admin_log_alerts_html,
            render_host_metrics_html,
        )

        dash = collect_dashboard(log_dir)
        alerts_html = render_admin_log_alerts_html(dash["log"])
        dm_admin_block = ""
        if dash.get("want_ack_on_dm") and dash.get("dm_delivery_24h") is not None:
            from modules.dm_delivery_stats import render_dm_delivery_stats_html

            dm_admin_block = f"""
<h3 class="h6 section-title mb-3"><i class="bi bi-envelope-check me-2 text-success"></i>DM-Zustellung (24h)</h3>
{render_dm_delivery_stats_html(dash["dm_delivery_24h"])}
<hr class="my-4">
"""
        host_block = f"""
{dm_admin_block}
<h3 class="h6 section-title mb-3"><i class="bi bi-pc-display me-2 text-success"></i>Host</h3>
{render_host_metrics_html()}
<hr class="my-4">
<h3 class="h6 section-title mb-3"><i class="bi bi-exclamation-triangle me-2 text-warning"></i>Log-Warnungen &amp; Fehler</h3>
{alerts_html}
<hr class="my-4">
"""
        return _render_admin_template(
            host_block
            + """
<p class="text-muted small mb-0">
  DM, News, Messages, NodeDB, MOTD, Scheduler, BBS, Einstellungen, Banliste und Logs erreichst du über die Tabs oben.
</p>
<p class="text-center mt-4 mb-0">
  <a href="{{ url_for('index_dashboard') }}" class="btn btn-sm btn-link text-muted">
    <i class="bi bi-bar-chart me-1"></i>Öffentliche Statistik
  </a>
</p>
""",
            title="Übersicht",
            active_tab="home",
        )

    def _render_text_file_editor(
        dateiname: str,
        *,
        active_tab: str,
        page_title: str,
        file_hint: str = "",
    ):
        pfad = dateien.get(dateiname)
        if not pfad:
            return "Ungültiger Dateiname.", 404

        parent = os.path.dirname(pfad)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)

        if request.method == "POST":
            try:
                with open(pfad, "w", encoding="utf-8") as f:
                    f.write(request.form.get("text", ""))
            except OSError as e:
                from modules import admin_web_ops as ops

                if getattr(e, "errno", None) == 13:
                    flash(ops.runtime_file_permission_hint(pfad), "error")
                else:
                    flash(f"Speichern fehlgeschlagen: {e!s}", "error")
                return redirect(request.url)
            flash(f"{page_title} gespeichert.", "success")
            return redirect(request.url)

        if os.path.isfile(pfad):
            with open(pfad, encoding="utf-8") as f:
                inhalt = f.read()
        else:
            inhalt = ""

        hint_html = ""
        if file_hint:
            hint_html = f'<p class="text-muted small mb-3">{html_escape(file_hint)}</p>'
        path_line = (
            f'<p class="text-muted small mb-3">Datei: <code>{html_escape(pfad)}</code></p>'
        )

        return _render_admin_template(
            f"""
{path_line}
{hint_html}
<form method="post">
  <textarea name="text" rows="22" class="form-control font-monospace mb-3">{{ inhalt }}</textarea>
  <button type="submit" class="btn btn-success">Speichern</button>
</form>
""",
            title=page_title,
            active_tab=active_tab,
            inhalt=inhalt,
        )

    @app.route("/dm", methods=["GET", "POST"])
    @login_required
    def edit_dm():
        return _render_text_file_editor(
            "direktnachricht",
            active_tab="dm",
            page_title="DM",
            file_hint="Direktnachricht des Bots (Alert-Text).",
        )

    @app.route("/news", methods=["GET", "POST"])
    @login_required
    def edit_news():
        from modules import admin_web_ops as ops
        import modules.settings as st

        dateiname = "news"
        pfad = dateien.get(dateiname)
        if not pfad:
            return "Ungültiger Dateiname.", 404

        parent = os.path.dirname(pfad)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)

        if request.method == "POST":
            try:
                enabled, iface, channel, mode, interval, sched_time = ops.parse_broadcast_schedule_form(
                    request.form
                )
            except ValueError:
                flash("Interface/Kanal ungültig.", "error")
                return redirect(url_for("edit_news"))
            if enabled:
                err = ops.validate_broadcast_schedule(mode, interval, sched_time)
                if err:
                    flash(err, "error")
                    return redirect(url_for("edit_news"))
            try:
                with open(pfad, "w", encoding="utf-8") as f:
                    f.write(request.form.get("text", ""))
                ops.save_news_broadcast_to_config(
                    enabled, iface, channel, mode, interval, sched_time
                )
                ops.rebuild_scheduler_jobs()
            except OSError as e:
                if getattr(e, "errno", None) == 13:
                    flash(ops.runtime_file_permission_hint(pfad), "error")
                else:
                    flash(f"Speichern fehlgeschlagen: {e!s}", "error")
                return redirect(url_for("edit_news"))
            except Exception as e:
                flash(f"Speichern fehlgeschlagen: {e!s}", "error")
                return redirect(url_for("edit_news"))
            flash("News und Versandzeit gespeichert.", "success")
            return redirect(url_for("edit_news"))

        if os.path.isfile(pfad):
            with open(pfad, encoding="utf-8") as f:
                inhalt = f.read()
        else:
            inhalt = ""

        bc_form = ops.broadcast_schedule_form_html(
            enabled=st.news_broadcast_enabled,
            iface=st.news_broadcast_interface,
            channel=st.news_broadcast_channel,
            mode=st.news_broadcast_mode,
            interval=st.news_broadcast_interval,
            sched_time=st.news_broadcast_time,
            config_section="newsBroadcast",
        )
        path_line = (
            f'<p class="text-muted small mb-3">Datei: <code>{html_escape(pfad)}</code></p>'
        )
        return _render_admin_template(
            f"""
{path_line}
<p class="text-muted small mb-3">News-Text für <code>!readnews</code> und automatischen Versand.</p>
<form method="post">
  <h2 class="h5 mb-3">News-Text</h2>
  <textarea name="text" rows="22" class="form-control font-monospace mb-3">{{ inhalt }}</textarea>
"""
            + bc_form
            + """
  <button type="submit" class="btn btn-success w-100">Speichern</button>
</form>
""",
            title="News",
            active_tab="news",
            inhalt=inhalt,
        )

    @app.route("/edit/<dateiname>", methods=["GET", "POST"])
    @login_required
    def edit(dateiname):
        if dateiname == "direktnachricht":
            return redirect(url_for("edit_dm"))
        if dateiname == "news":
            return redirect(url_for("edit_news"))
        return "Ungültiger Dateiname.", 404

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

        return _render_admin_template(
            f"""
<div class="text-center">
  <p class="text-muted small mb-3">Ordner: <code>{html_escape(log_dir)}</code></p>
  {items if items else "<p>Keine Dateien gefunden.</p>"}
</div>
""",
            title="Logdateien",
            active_tab="logs",
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

        return _render_admin_template(
            f"""
<div class="admin-log-view">
  <p class="text-muted small mb-2">Datei: <code>{html_escape(filename)}</code></p>
  <pre class="admin-pre">{html_escape(inhalt)}</pre>
</div>
""",
            title=f"Log: {filename}",
            active_tab="logs",
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

        return _render_admin_template(
            f"""
<div class="admin-log-view">
<meta http-equiv="refresh" content="5">
  {hint}
  <pre class="admin-pre">{html_escape(inhalt)}</pre>
</div>
""",
            title="Messages",
            active_tab="messages",
        )

    @app.route("/nodes")
    @login_required
    def nodes_list():
        from modules import admin_web_ops as ops

        try:
            ifaces = ops.iter_radio_interfaces()
        except Exception as e:
            return (_render_admin_template("""
  <p class="alert alert-danger">System-Modul: {{ err }}</p>
  <a href="{{ url_for('nodes_list') }}" class="btn btn-outline-secondary btn-sm">Zurück</a>
""",
                    title="NodeDB",
                    active_tab="nodes",
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
                        f"<tr{ops.nodedb_row_search_attr(r)}>"
                        f"<td><code>{r['num']}</code></td>"
                        f"<td><code>{r['node_id']}</code></td>"
                        f"<td>{r['shortName']}</td>"
                        f"<td>{r['longName']}</td>"
                        f"<td>{r['location_html']}</td>"
                        f"<td>{r['lastHeard']}</td>"
                        f"<td>{html_escape(str(r['snr']))}</td>"
                        f"<td>{del_btn}</td>"
                        "</tr>"
                    )
                body = f"""
<p class="small text-muted mb-2">Schnittstelle: {tabs}</p>
<p class="small">Entfernen sendet einen Admin-Befehl an dein lokales Gerät (wie meshtastic --remove-node).</p>
<div class="nodedb-search-block">
{ops.nodedb_search_toolbar_html()}
<div class="table-scroll"><table class="nodes-table table-dark table-bordered">
<thead><tr><th>Nr.</th><th>Node ID</th><th>Kurz</th><th>Lang</th><th>Standort</th><th>Zuletzt</th><th>SNR</th><th></th></tr></thead>
<tbody>{"".join(rows_html)}
<tr class="nodedb-search-empty" hidden><td colspan="8" class="text-muted small">Keine Treffer für die Suche.</td></tr>
</tbody></table></div>
</div>
<script src="/static/portal/nodedb-search.js"></script>"""

        return _render_admin_template("""
  {{ body }}
""",
            title="NodeDB",
            active_tab="nodes",
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

    @app.route("/node-settings", methods=["GET", "POST"])
    @login_required
    @limiter.limit("20 per minute", methods=["POST"])
    def node_settings_index():
        from modules import admin_web_ops as ops

        try:
            ifaces = ops.iter_radio_interfaces()
        except Exception as e:
            return (
                _render_admin_template(
                    """
  <p class="alert alert-danger">System-Modul: {{ err }}</p>
""",
                    title="Node Settings",
                    active_tab="nodesettings",
                    err=str(e),
                ),
                500,
            )

        redirect_kw: dict = {}
        if not ifaces:
            body = (
                '<p class="alert alert-info">Keine aktive Meshtastic-Schnittstelle '
                "(Bot läuft ohne Radio oder noch nicht verbunden).</p>"
            )
        else:
            try:
                q = request.args.get("iface", type=int)
            except Exception:
                q = None
            iface_id = q if q in ifaces else ifaces[0]
            redirect_kw["iface"] = iface_id

            if request.method == "POST":
                try:
                    post_iface = int(request.form.get("iface_id") or "0")
                except (TypeError, ValueError):
                    post_iface = 0
                if post_iface in ifaces:
                    iface_id = post_iface
                    redirect_kw["iface"] = iface_id
                ok, msg = ops.apply_local_node_settings(iface_id, request.form)
                flash(msg, "success" if ok else "error")
                return redirect(url_for("node_settings_index", **redirect_kw))

            err, settings = ops.fetch_local_node_settings(iface_id)
            if err or not settings:
                body = f'<p class="alert alert-danger">{html_escape(err or "Unbekannter Fehler")}</p>'
            else:
                body = ops.build_node_settings_html(
                    settings,
                    iface_id=iface_id,
                    ifaces=ifaces,
                    form_action=url_for("node_settings_index"),
                )

        return _render_admin_template(
            """
  {{ body }}
""",
            title="Node Settings",
            active_tab="nodesettings",
            body=Markup(body),
        )

    @app.route("/mesh-admin", methods=["GET", "POST"])
    @login_required
    def mesh_admin_index():
        from modules import admin_web_ops as ops

        iface_q = request.args.get("iface", type=int)
        redirect_kw = {"iface": iface_q} if iface_q else {}

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            current = ops.read_mesh_admin_list()
            try:
                post_iface = int(request.form.get("iface_id") or "0")
            except (TypeError, ValueError):
                post_iface = 0
            if post_iface > 0:
                redirect_kw["iface"] = post_iface

            if action == "add":
                nid = ops.normalize_ban_node_id(request.form.get("node_id", ""))
                if not nid:
                    flash("Ungültige Knoten-ID (Dezimalzahl oder !xxxxxxxx).", "error")
                elif nid in current:
                    flash(f"Knoten {nid} ist bereits Mesh-Admin.", "info")
                else:
                    current.append(nid)
                    try:
                        ops.save_mesh_admin_list(current)
                    except OSError as e:
                        flash(f"Speichern fehlgeschlagen: {e!s}", "error")
                    else:
                        flash(f"Knoten {nid} als Mesh-Admin eingetragen.", "success")
            elif action == "remove":
                nid = (request.form.get("node_id") or "").strip()
                if nid in current:
                    current = [x for x in current if x != nid]
                    try:
                        ops.save_mesh_admin_list(current)
                    except OSError as e:
                        flash(f"Speichern fehlgeschlagen: {e!s}", "error")
                    else:
                        flash(f"Knoten {nid} ist kein Mesh-Admin mehr.", "success")
                else:
                    flash("Knoten ist kein Mesh-Admin.", "error")
            elif action == "save":
                lines = (request.form.get("admin_list_text") or "").splitlines()
                merged = [ln.strip() for ln in lines if ln.strip()]
                try:
                    ops.save_mesh_admin_list(merged)
                except OSError as e:
                    flash(f"Speichern fehlgeschlagen: {e!s}", "error")
                else:
                    flash(f"Mesh-Admin-Liste gespeichert ({len(merged)} Einträge).", "success")
            else:
                flash("Unbekannte Aktion.", "error")
            return redirect(url_for("mesh_admin_index", **redirect_kw))

        admins = ops.read_mesh_admin_list()
        admin_set = set(admins)

        admin_rows = []
        for nid in sorted(admins, key=lambda x: int(x) if x.isdigit() else 0):
            label = html_escape(ops.ban_node_label(nid))
            try:
                hex_h = html_escape(f"!{int(nid):08x}")
            except (TypeError, ValueError):
                hex_h = html_escape(nid)
            admin_rows.append(
                "<tr>"
                f"<td><code>{html_escape(nid)}</code></td>"
                f"<td><code>{hex_h}</code></td>"
                f"<td>{label}</td>"
                f'<td><form method="post" style="display:inline" '
                f'onsubmit="return confirm(\'Mesh-Admin {html_escape(nid)} entfernen?\');">'
                '<input type="hidden" name="action" value="remove">'
                f'<input type="hidden" name="node_id" value="{html_escape(nid)}">'
                '<button type="submit" class="btn btn-sm btn-outline-danger">Entfernen</button>'
                "</form></td>"
                "</tr>"
            )
        admin_table = (
            "".join(admin_rows)
            if admin_rows
            else '<tr><td colspan="4">Noch keine Mesh-Admins eingetragen.</td></tr>'
        )
        list_text = "\n".join(admins)

        nodedb_block = (
            '<p class="alert alert-info">Keine aktive Meshtastic-Schnittstelle — '
            "NodeDB-Auswahl nicht verfügbar. Knoten-ID manuell eintragen.</p>"
        )
        try:
            ifaces = ops.iter_radio_interfaces()
        except Exception as e:
            nodedb_block = f'<p class="alert alert-danger">{html_escape(str(e))}</p>'
            ifaces = []

        if ifaces:
            q = request.args.get("iface", type=int)
            iface_id = q if q in ifaces else ifaces[0]
            err, rows = ops.list_node_rows(iface_id)
            if err:
                nodedb_block = f'<p class="alert alert-danger">{html_escape(err)}</p>'
            else:
                tab_parts = []
                for i in ifaces:
                    cls = "btn-light" if i == iface_id else "btn-outline-secondary"
                    tab_parts.append(
                        f'<a class="btn btn-sm {cls}" href="{url_for("mesh_admin_index", iface=i)}">IF {i}</a>'
                    )
                tabs = " ".join(tab_parts)
                node_rows = []
                for r in rows:
                    num = str(r["num"])
                    if r["is_self"]:
                        admin_cell = '<span class="text-muted">(lokal)</span>'
                    elif num in admin_set:
                        admin_cell = (
                            '<span class="badge bg-success me-1">Admin</span>'
                            f'<form method="post" style="display:inline">'
                            '<input type="hidden" name="action" value="remove">'
                            f'<input type="hidden" name="node_id" value="{html_escape(num)}">'
                            f'<input type="hidden" name="iface_id" value="{iface_id}">'
                            '<button type="submit" class="btn btn-sm btn-outline-danger">Entfernen</button>'
                            "</form>"
                        )
                    else:
                        admin_cell = (
                            f'<form method="post" style="display:inline">'
                            '<input type="hidden" name="action" value="add">'
                            f'<input type="hidden" name="node_id" value="{html_escape(num)}">'
                            f'<input type="hidden" name="iface_id" value="{iface_id}">'
                            '<button type="submit" class="btn btn-sm btn-success">+ Admin</button>'
                            "</form>"
                        )
                    node_rows.append(
                        f"<tr{ops.nodedb_row_search_attr(r)}>"
                        f"<td><code>{r['num']}</code></td>"
                        f"<td><code>{r['node_id']}</code></td>"
                        f"<td>{r['shortName']}</td>"
                        f"<td>{r['longName']}</td>"
                        f"<td>{r['location_html']}</td>"
                        f"<td>{admin_cell}</td>"
                        "</tr>"
                    )
                nodedb_block = f"""
<p class="small text-muted mb-2">Aus NodeDB (Schnittstelle): {tabs}</p>
<div class="nodedb-search-block">
{ops.nodedb_search_toolbar_html()}
<div class="table-scroll"><table class="nodes-table table-dark table-bordered">
<thead><tr><th>Nr.</th><th>Node ID</th><th>Kurz</th><th>Lang</th><th>Standort</th><th>Admin</th></tr></thead>
<tbody>{"".join(node_rows) if node_rows else '<tr><td colspan="6">Keine Knoten in der NodeDB.</td></tr>'}
<tr class="nodedb-search-empty" hidden><td colspan="6" class="text-muted small">Keine Treffer für die Suche.</td></tr>
</tbody></table></div>
</div>
<script src="/static/portal/nodedb-search.js"></script>"""

        body = (
            '<p class="small text-muted">'
            "Mesh-Admins (<code>[bbs] bbs_admin_list</code>) dürfen u. a. fremde BBS-Beiträge löschen, "
            "<code>bannode</code> per DM nutzen und weitere Admin-Befehle. "
            "Web-Login (<code>[webAdmin]</code>) ist davon getrennt.</p>"
            "<h2 class=\"h5 section-title mt-3\">Aktuelle Mesh-Admins</h2>"
            '<form method="post" class="row g-2 align-items-end mb-3">'
            '<input type="hidden" name="action" value="add">'
            '<div class="col-md-8">'
            '<label class="form-label small">Knoten-ID manuell</label>'
            '<input type="text" name="node_id" class="form-control" '
            'placeholder="Dezimal-ID oder !a1b2c3d4" required>'
            "</div>"
            '<div class="col-md-4">'
            '<button type="submit" class="btn btn-success w-100">Als Admin hinzufügen</button>'
            "</div></form>"
            '<div class="table-scroll"><table class="nodes-table table-dark table-bordered">'
            "<thead><tr><th>Node-ID</th><th>Hex</th><th>Anzeige</th><th></th></tr></thead>"
            f"<tbody>{admin_table}</tbody></table></div>"
            '<form method="post" class="mt-3">'
            '<input type="hidden" name="action" value="save">'
            '<label class="form-label small">Liste bearbeiten (eine Node-ID pro Zeile)</label>'
            f'<textarea name="admin_list_text" rows="6" class="form-control font-monospace mb-2">'
            f"{html_escape(list_text)}</textarea>"
            '<button type="submit" class="btn btn-success">Speichern</button>'
            "</form>"
            '<h2 class="h5 section-title mt-4">Aus NodeDB übernehmen</h2>'
            f"{nodedb_block}"
        )

        return _render_admin_template(
            """
  {{ body|safe }}
""",
            title="Mesh-Admin",
            active_tab="meshadmin",
            body=Markup(body),
        )

    @app.route("/motd", methods=["GET", "POST"])
    @login_required
    def motd_edit():
        from modules import admin_web_ops as ops
        import modules.settings as st

        if request.method == "POST":
            text = request.form.get("motd", "")
            try:
                enabled, iface, channel, mode, interval, sched_time = ops.parse_broadcast_schedule_form(
                    request.form
                )
            except ValueError:
                flash("Interface/Kanal ungültig.", "error")
                return redirect(url_for("motd_edit"))
            if enabled:
                err = ops.validate_broadcast_schedule(mode, interval, sched_time)
                if err:
                    flash(err, "error")
                    return redirect(url_for("motd_edit"))
            try:
                ops.save_motd_to_config(text)
                ops.save_motd_broadcast_to_config(
                    enabled, iface, channel, mode, interval, sched_time
                )
                ops.rebuild_scheduler_jobs()
            except Exception as e:
                flash(f"Speichern fehlgeschlagen: {e!s}", "error")
            else:
                flash("MOTD und Versandzeit gespeichert.", "success")
                if enabled and not (
                    st.scheduler_enabled or st.news_broadcast_enabled
                ):
                    flash(
                        "Hinweis: Zeitplan läuft nur, wenn der Bot läuft. Nach erstem Aktivieren ggf. Bot neu starten.",
                        "info",
                    )
            return redirect(url_for("motd_edit"))

        bc_form = ops.broadcast_schedule_form_html(
            enabled=st.motd_broadcast_enabled,
            iface=st.motd_broadcast_interface,
            channel=st.motd_broadcast_channel,
            mode=st.motd_broadcast_mode,
            interval=st.motd_broadcast_interval,
            sched_time=st.motd_broadcast_time,
            config_section="motdBroadcast",
        )
        return _render_admin_template(
            """
  <form method="post">
    <h2 class="h5 mb-3">MOTD-Text</h2>
    <textarea name="motd" rows="8" class="form-control mb-3">{{ motd }}</textarea>
"""
            + bc_form
            + """
    <button type="submit" class="btn btn-success w-100">Speichern</button>
  </form>
  <p class="small text-muted mt-3">Text in <code>[general] motd</code>; Versand in <code>[motdBroadcast]</code>.</p>
""",
            title="MOTD",
            active_tab="motd",
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

            ops.rebuild_scheduler_jobs()
            if enabled:
                flash("Scheduler-Einstellungen gespeichert; Jobliste wurde neu aufgebaut.", "success")
                if not prev_en:
                    flash(
                        "Hinweis: Wenn der Scheduler beim Start des Bots aus war, starte den Bot neu, damit der Zeitplan wirklich ausgeführt wird.",
                        "info",
                    )
            else:
                flash(
                    "Allgemeiner Scheduler deaktiviert. MOTD-/News-Versand bleibt aktiv, falls dort eingeschaltet.",
                    "info",
                )

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

        return _render_admin_template("""
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
      <strong>weather, mwx, tide, solar:</strong> Uhrzeit Pflicht, Intervall oft egal (siehe Code).
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
          <tr><td>weather, mwx, tide, solar</td><td>(siehe Log)</td><td>erforderlich</td></tr>
        </tbody>
      </table>
    </details>

    <input type="submit" value="Speichern" class="btn btn-success w-100">
  </form>
  <p class="small text-muted mt-3">Vollständige Optionen: <code>config.template</code> → <code>[scheduler]</code>.</p>
""",
            title="Scheduler",
            active_tab="scheduler",
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

    @app.route("/banlist", methods=["GET", "POST"])
    @login_required
    def banlist_index():
        from modules import admin_web_ops as ops
        import modules.settings as st

        ban_path = ops.ban_list_file_path()

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            current = ops.read_ban_list_file()
            if not current:
                current = list(st.bbs_ban_list)

            if action == "add":
                nid = ops.normalize_ban_node_id(request.form.get("node_id", ""))
                if not nid:
                    flash("Ungültige Knoten-ID (Dezimalzahl oder !xxxxxxxx).", "error")
                elif nid in current:
                    flash(f"Knoten {nid} steht bereits auf der Banliste.", "info")
                else:
                    current.append(nid)
                    try:
                        ops.save_ban_list(current)
                    except OSError as e:
                        flash(f"Speichern fehlgeschlagen: {e!s}", "error")
                    else:
                        flash(f"Knoten {nid} zur Banliste hinzugefügt.", "success")
            elif action == "remove":
                nid = (request.form.get("node_id") or "").strip()
                if nid in current:
                    current = [x for x in current if x != nid]
                    try:
                        ops.save_ban_list(current)
                    except OSError as e:
                        flash(f"Speichern fehlgeschlagen: {e!s}", "error")
                        return redirect(url_for("banlist_index"))
                    auto = getattr(st, "autoBanlist", None)
                    if isinstance(auto, list) and nid in auto:
                        auto.remove(nid)
                        try:
                            from modules.system import save_autoBanList
                            save_autoBanList()
                        except Exception:
                            pass
                    flash(f"Knoten {nid} von der Banliste entfernt.", "success")
                else:
                    flash("Knoten nicht auf der Banliste.", "error")
            elif action == "save":
                lines = (request.form.get("ban_list_text") or "").splitlines()
                merged = [ln.strip() for ln in lines if ln.strip()]
                try:
                    ops.save_ban_list(merged)
                except OSError as e:
                    flash(f"Speichern fehlgeschlagen: {e!s}", "error")
                else:
                    flash(f"Banliste gespeichert ({len(merged)} Einträge).", "success")
            elif action == "reload":
                ops.reload_ban_list_runtime()
                flash("Banliste von der Datei neu geladen.", "success")
            else:
                flash("Unbekannte Aktion.", "error")
            return redirect(url_for("banlist_index"))

        banned = ops.read_ban_list_file()
        if not banned:
            banned = ops.reload_ban_list_runtime()

        rows_html = []
        for nid in sorted(banned, key=lambda x: int(x) if x.isdigit() else 0):
            label = html_escape(ops.ban_node_label(nid))
            try:
                hex_h = html_escape(f"!{int(nid):08x}")
            except (TypeError, ValueError):
                hex_h = html_escape(nid)
            rows_html.append(
                "<tr>"
                f"<td><code>{html_escape(nid)}</code></td>"
                f"<td><code>{hex_h}</code></td>"
                f"<td>{label}</td>"
                f'<td><form method="post" style="display:inline" '
                f'onsubmit="return confirm(\'Knoten {html_escape(nid)} von der Banliste entfernen?\');">'
                f'<input type="hidden" name="action" value="remove">'
                f'<input type="hidden" name="node_id" value="{html_escape(nid)}">'
                '<button type="submit" class="btn btn-sm btn-danger">Entfernen</button>'
                "</form></td>"
                "</tr>"
            )
        table = (
            "".join(rows_html)
            if rows_html
            else '<tr><td colspan="4">Keine gesperrten Knoten.</td></tr>'
        )

        auto_rows = getattr(st, "autoBanlist", None) or []
        auto_html = ""
        if auto_rows:
            auto_items = "".join(
                f"<li><code>{html_escape(str(n))}</code></li>"
                for n in auto_rows
                if str(n).strip()
            )
            auto_html = (
                '<div class="alert alert-secondary mt-3 mb-0">'
                "<strong>Auto-Ban (laufende Sitzung):</strong> "
                f"{len(auto_rows)} Knoten · wird beim Neustart zurückgesetzt, "
                "steht nicht in <code>bbs_ban_list.txt</code>."
                f'<ul class="small mb-0 mt-2">{auto_items}</ul></div>'
            )

        list_text = "\n".join(banned)
        body = (
            f'<p class="small text-muted">Datei: <code>{html_escape(ban_path)}</code> · '
            f"Config: <code>[bbs] bbs_ban_list</code> · "
            f"{len(banned)} Eintrag/Einträge</p>"
            '<form method="post" class="row g-2 align-items-end mb-3">'
            '<input type="hidden" name="action" value="add">'
            '<div class="col-md-8">'
            '<label class="form-label small">Knoten sperren</label>'
            '<input type="text" name="node_id" class="form-control" '
            'placeholder="Dezimal-ID oder !a1b2c3d4" required>'
            "</div>"
            '<div class="col-md-4">'
            '<button type="submit" class="btn btn-danger w-100">Hinzufügen</button>'
            "</div></form>"
            '<div class="table-scroll"><table class="nodes-table table-dark table-bordered">'
            "<thead><tr><th>Node-ID</th><th>Hex</th><th>Anzeige</th><th></th></tr></thead>"
            f"<tbody>{table}</tbody></table></div>"
            '<form method="post" class="mt-3">'
            '<input type="hidden" name="action" value="save">'
            '<label class="form-label small">Banliste bearbeiten (eine Node-ID pro Zeile)</label>'
            f'<textarea name="ban_list_text" rows="8" class="form-control font-monospace mb-2">'
            f"{html_escape(list_text)}</textarea>"
            '<div class="d-flex flex-wrap gap-2">'
            '<button type="submit" class="btn btn-success">Speichern</button>'
            "</div></form>"
            '<form method="post" class="d-inline ms-2">'
            '<input type="hidden" name="action" value="reload">'
            '<button type="submit" class="btn btn-outline-secondary">Von Datei neu laden</button>'
            "</form>"
            '<p class="small text-muted mt-2 mb-0">'
            "Gesperrte Knoten können keine BBS-Beiträge mehr posten. "
            "Im Mesh: <code>bannode add/remove/list</code> (nur per DM, Admin).</p>"
            f"{auto_html}"
        )

        return _render_admin_template(
            """
  {{ body|safe }}
""",
            title="Banliste",
            active_tab="banlist",
            body=Markup(body),
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
            fn_h = html_escape(bbs.bbs_party_display_label(fn))
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

        return _render_admin_template("""
  {{ body|safe }}
  <div class="text-center mt-3"><a href="{{ url_for('bbs_index') }}" class="btn btn-outline-secondary btn-sm">Liste</a></div>
""",
            title="BBS",
            active_tab="bbs",
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
        fn_h = html_escape(bbs.bbs_party_display_label(fn))
        when = html_escape(str(m[4])) if len(m) > 4 else ""
        return _render_admin_template(
            f"""
  <p><strong>Betreff:</strong> {subj}</p>
  <p><strong>Von:</strong> {fn_h} &nbsp; <strong>Zeit:</strong> {when}</p>
  <pre class="admin-pre">{body_esc}</pre>
  <div class="text-center mt-3">
    <a href="{{ url_for('bbs_index') }}" class="btn btn-outline-secondary btn-sm">Zurück</a>
  </div>
""",
            title=f"BBS #{mid}",
            active_tab="bbs",
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
                try:
                    flash(bbs.bbs_post_message(subj, body_txt, 0), "success")
                except Exception as e:
                    flash(f"Speichern fehlgeschlagen: {e!s}", "error")
            return redirect(url_for("bbs_index"))

        return _render_admin_template(
            """
  <p class="small text-muted">Wird wie <code>bbspost</code> mit Absender-Node <code>0</code> (Web-Admin) eingetragen.</p>
  <form method="post">
    <label>Betreff</label>
    <input type="text" name="subject" class="form-control mb-3" required maxlength="500">
    <label>Text</label>
    <textarea name="body" rows="12" class="form-control mb-3"></textarea>
    <input type="submit" value="Veröffentlichen" class="btn btn-success w-100">
  </form>
  <div class="text-center mt-3">
    <a href="{{ url_for('bbs_index') }}" class="btn btn-outline-secondary btn-sm">Abbrechen</a>
  </div>
""",
            title="Neue BBS-Nachricht",
            active_tab="bbs",
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
            to_h = html_escape(bbs.bbs_party_display_label(to_n))
            from_h = html_escape(bbs.bbs_party_display_label(from_n))
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

        return _render_admin_template(
            """
  {{ body|safe }}
""",
            title="BBS Direktnachrichten",
            active_tab="bbs",
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
        to_h = html_escape(bbs.bbs_party_display_label(to_n))
        from_h = html_escape(bbs.bbs_party_display_label(from_n))
        body_esc = html_escape(text)
        return _render_admin_template(
            f"""
  <p><strong>An:</strong> {to_h} &nbsp; <strong>Von:</strong> {from_h}</p>
  <pre class="admin-pre">{body_esc}</pre>
  <div class="text-center mt-3">
    <a href="{{ url_for('bbs_dm_index') }}" class="btn btn-outline-secondary btn-sm">Zurück</a>
  </div>
""",
            title=f"BBS-DM #{idx}",
            active_tab="bbs",
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
                try:
                    flash(bbs.bbs_post_dm(to_node, body_txt.strip(), from_node), "success")
                except Exception as e:
                    flash(f"Speichern fehlgeschlagen: {e!s}", "error")
            return redirect(url_for("bbs_dm_index"))

        return _render_admin_template(
            """
  <p class="small text-muted">Wie <code>bbspost @Ziel #Text</code>: Ziel als Dezimal-Node-ID oder Meshtastic-<code>!hex</code>.</p>
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
    <a href="{{ url_for('bbs_dm_index') }}" class="btn btn-outline-secondary btn-sm">Abbrechen</a>
  </div>
""",
            title="Neue BBS-DM",
            active_tab="bbs",
        )

    @app.route("/bbs/dm/delete/<int:idx>", methods=["POST"])
    @login_required
    @limiter.limit("60 per minute")
    def bbs_dm_delete(idx):
        from modules import bbstools as bbs

        ok, txt = bbs.bbs_delete_dm_at_index(idx)
        flash(txt, "success" if ok else "error")
        return redirect(url_for("bbs_dm_index"))

    @app.route("/einstellungen", methods=["GET", "POST"])
    @app.route("/settings", methods=["GET", "POST"])
    @login_required
    def settings_index():
        from modules import admin_web_ops as ops
        import modules.settings as st
        from modules.admin_config import build_settings_form_html

        if request.method == "POST":
            try:
                full_reload = ops.save_config_from_admin_form(request.form)
                msg = "Einstellungen gespeichert und übernommen."
                if not full_reload:
                    msg += " Einige Werte (z. B. Radio-Interface) erst nach Bot-Neustart aktiv."
                flash(msg, "success")
            except OSError as e:
                if getattr(e, "errno", None) == 13:
                    flash(ops.runtime_file_permission_hint(st.config_file), "error")
                else:
                    flash(f"Speichern fehlgeschlagen: {e!s}", "error")
            except Exception as e:
                flash(f"Speichern fehlgeschlagen: {e!s}", "error")
            return redirect(url_for("settings_index"))

        st.config.read(st.config_file, encoding="utf-8")
        return _render_admin_template(
            build_settings_form_html(st.config),
            title="Einstellungen",
            active_tab="settings",
        )

    @app.route("/umfragen")
    @login_required
    def polls_index():
        import modules.polls as polls
        import modules.settings as st

        hint = ""
        if not st.polls_enabled:
            hint = (
                '<p class="alert alert-info">Umfragen sind unter <code>[polls] enabled = False</code> '
                "deaktiviert. Verwaltung wirkt trotzdem auf <code>data/polls.pkl</code>.</p>"
            )

        rows = []
        for poll in polls.list_polls():
            pid = poll.get("id")
            active = poll.get("active", True)
            badge = (
                '<span class="badge text-bg-success">aktiv</span>'
                if active
                else '<span class="badge text-bg-secondary">geschlossen</span>'
            )
            total = sum(polls._vote_totals(poll))
            rows.append(
                "<tr>"
                f"<td><code>{pid}</code></td>"
                f"<td>{html_escape(str(poll.get('title', '')))}</td>"
                f"<td>{html_escape(str(poll.get('question', ''))[:80])}</td>"
                f"<td>{badge}</td>"
                f"<td>{total}</td>"
                f"<td>{html_escape(str(poll.get('created', '')))}</td>"
                f'<td><a class="btn btn-sm btn-outline-info" href="{url_for("polls_view", poll_id=pid)}">'
                "Anzeigen</a></td>"
                "</tr>"
            )
        table = "".join(rows) if rows else '<tr><td colspan="7">Keine Umfragen.</td></tr>'

        body = (
            hint
            + f'<p><a class="btn btn-success mb-3" href="{url_for("polls_new")}">Neue Umfrage</a></p>'
            + '<div class="table-scroll"><table class="nodes-table table-dark table-bordered">'
            + "<thead><tr><th>#</th><th>Titel</th><th>Frage</th><th>Status</th>"
            + "<th>Stimmen</th><th>Erstellt</th><th></th></tr></thead>"
            + f"<tbody>{table}</tbody></table></div>"
            + '<p class="small text-muted">Mesh: <code>!poll</code>, <code>!poll liste</code>, '
            "<code>!poll &lt;Nr&gt;</code>, <code>!poll &lt;Nr&gt; &lt;Option&gt;</code></p>"
        )

        return _render_admin_template(
            "{{ body|safe }}",
            title="Umfragen",
            active_tab="polls",
            body=Markup(body),
        )

    @app.route("/umfragen/new", methods=["GET", "POST"])
    @login_required
    def polls_new():
        import modules.polls as polls
        import modules.settings as st

        max_opt = int(getattr(st, "polls_max_options", 8))
        if request.method == "POST":
            title = (request.form.get("title") or "").strip()
            question = (request.form.get("question") or "").strip()
            raw_opts = (request.form.get("options") or "").strip()
            options = [ln.strip() for ln in raw_opts.splitlines() if ln.strip()]
            active = request.form.get("active") == "on"
            ok, txt, _pid = polls.create_poll(title, question, options, active=active)
            flash(txt, "success" if ok else "error")
            if ok:
                return redirect(url_for("polls_view", poll_id=_pid))
            return redirect(url_for("polls_new"))

        return _render_admin_template(
            f"""
  <p class="small text-muted">Pro Zeile eine Antwortoption (mind. 2, max. {max_opt}).</p>
  <form method="post">
    <label class="form-label">Titel (optional)</label>
    <input type="text" name="title" class="form-control mb-3" maxlength="80">
    <label class="form-label">Frage</label>
    <input type="text" name="question" class="form-control mb-3" required maxlength="200">
    <label class="form-label">Optionen</label>
    <textarea name="options" rows="6" class="form-control font-monospace mb-3" required
              placeholder="Ja&#10;Nein&#10;Enthaltung"></textarea>
    <div class="form-check mb-3">
      <input class="form-check-input" type="checkbox" name="active" id="pollActive" checked>
      <label class="form-check-label" for="pollActive">Sofort aktiv (Abstimmung im Mesh)</label>
    </div>
    <button type="submit" class="btn btn-success">Anlegen</button>
    <a href="{url_for("polls_index")}" class="btn btn-outline-secondary ms-2">Abbrechen</a>
  </form>
""",
            title="Neue Umfrage",
            active_tab="polls",
        )

    @app.route("/umfragen/<int:poll_id>")
    @login_required
    def polls_view(poll_id):
        import modules.polls as polls
        from modules.bbstools import bbs_party_display_label

        poll = polls.get_poll(poll_id)
        if not poll:
            flash("Umfrage nicht gefunden.", "error")
            return redirect(url_for("polls_index"))

        options = poll.get("options") or []
        votes = poll.get("votes") or {}
        totals = polls._vote_totals(poll)
        total = sum(totals)
        rows = []
        for i, opt in enumerate(options):
            voters = votes.get(str(i), [])
            voter_labels = ", ".join(
                html_escape(bbs_party_display_label(v)[:40]) for v in voters[:12]
            )
            if len(voters) > 12:
                voter_labels += f" … +{len(voters) - 12}"
            pct = f"{round(100 * totals[i] / total)}%" if total else "0%"
            rows.append(
                "<tr>"
                f"<td>{i + 1}</td>"
                f"<td>{html_escape(opt)}</td>"
                f"<td><strong>{totals[i]}</strong></td>"
                f"<td>{pct}</td>"
                f'<td class="small">{voter_labels or "—"}</td>'
                "</tr>"
            )
        table = "".join(rows)
        state = "aktiv" if poll.get("active", True) else "geschlossen"
        mesh_preview = html_escape(polls.format_poll_detail(poll_id))

        body = f"""
  <h2 class="h5">{html_escape(str(poll.get('title', '')))} <span class="badge text-bg-secondary">#{poll_id}</span></h2>
  <p><strong>Frage:</strong> {html_escape(str(poll.get('question', '')))}</p>
  <p class="text-muted small">Status: {state} · Erstellt: {html_escape(str(poll.get('created', '')))} · Gesamt: {total} Stimmen</p>
  <div class="table-scroll mb-3">
    <table class="nodes-table table-dark table-bordered table-sm">
      <thead><tr><th>#</th><th>Option</th><th>Stimmen</th><th>%</th><th>Knoten (Auszug)</th></tr></thead>
      <tbody>{table}</tbody>
    </table>
  </div>
  <h3 class="h6">Vorschau Mesh-Antwort</h3>
  <pre class="admin-pre">{mesh_preview}</pre>
  <div class="d-flex flex-wrap gap-2 mb-3">
    <form method="post" action="{url_for('polls_toggle', poll_id=poll_id)}">
      <input type="hidden" name="active" value="{'0' if poll.get('active', True) else '1'}">
      <button type="submit" class="btn btn-sm btn-outline-warning">{'Schließen' if poll.get('active', True) else 'Aktivieren'}</button>
    </form>
    <form method="post" action="{url_for('polls_reset', poll_id=poll_id)}" onsubmit="return confirm('Alle Stimmen löschen?');">
      <button type="submit" class="btn btn-sm btn-outline-secondary">Stimmen zurücksetzen</button>
    </form>
    <form method="post" action="{url_for('polls_delete', poll_id=poll_id)}" onsubmit="return confirm('Umfrage endgültig löschen?');">
      <button type="submit" class="btn btn-sm btn-danger">Löschen</button>
    </form>
    <a href="{url_for('polls_index')}" class="btn btn-sm btn-outline-secondary">Zurück</a>
  </div>
"""
        return _render_admin_template(
            body,
            title=f"Umfrage #{poll_id}",
            active_tab="polls",
        )

    @app.route("/umfragen/<int:poll_id>/toggle", methods=["POST"])
    @login_required
    def polls_toggle(poll_id):
        import modules.polls as polls

        active = request.form.get("active") == "1"
        ok, txt = polls.set_poll_active(poll_id, active)
        flash(txt, "success" if ok else "error")
        return redirect(url_for("polls_view", poll_id=poll_id))

    @app.route("/umfragen/<int:poll_id>/reset", methods=["POST"])
    @login_required
    def polls_reset(poll_id):
        import modules.polls as polls

        ok, txt = polls.reset_poll_votes(poll_id)
        flash(txt, "success" if ok else "error")
        return redirect(url_for("polls_view", poll_id=poll_id))

    @app.route("/umfragen/<int:poll_id>/delete", methods=["POST"])
    @login_required
    def polls_delete(poll_id):
        import modules.polls as polls

        ok, txt = polls.delete_poll(poll_id)
        flash(txt, "success" if ok else "error")
        return redirect(url_for("polls_index"))

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
