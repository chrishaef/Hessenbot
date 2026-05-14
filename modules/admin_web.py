#!/usr/bin/env python3
# Small Flask admin UI: edit alert/news files, browse logs, live messages.log view.
# Started in a background thread when [webAdmin] enabled in config.ini.

import os
import secrets
import threading
from html import escape as html_escape
from typing import Optional

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
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user


def _abs_path(rel_or_abs: str) -> str:
    return os.path.abspath(os.path.join(os.getcwd(), rel_or_abs))


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
    live_datei = os.path.join(log_dir, "messages.log")

    login_manager = LoginManager()
    login_manager.init_app(app)

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
  background-color: #121212;
  color: #f8f9fa;
  font-family: 'Segoe UI', sans-serif;
  padding-top: 60px;
}
.container {
  max-width: 800px;
  margin: auto;
  background-color: #1e1e1e;
  padding: 30px;
  border-radius: 10px;
  box-shadow: 0 0 20px rgba(25, 125, 25, 0.5);
}
textarea, input[type="text"], input[type="password"] {
  background-color: #2a2a2a;
  color: #f8f9fa;
  border: 1px solid #444;
}
.btn-primary {
  background-color: #0d6efd;
  border-color: #0d6efd;
}
.btn-primary:hover {
  background-color: #0b5ed7;
}
a {
  color: #90cdf4;
}
.alert { border-radius: 6px; padding: 12px; margin-bottom: 16px; }
.alert-success { background: #1e4620; border: 1px solid #2a6; color: #d4edda; }
.alert-danger { background: #4a1e1e; border: 1px solid #a44; color: #f8d7da; }
.alert-info { background: #1e3a4a; border: 1px solid #48a; color: #d1ecf1; }
table.nodes-table { width: 100%; font-size: 0.9rem; }
table.nodes-table th, table.nodes-table td { border-bottom: 1px solid #444; padding: 8px; text-align: left; }
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

    @limiter.limit("5 per minute")
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            if (
                request.form.get("username") == admin_username
                and request.form.get("password") == admin_password
            ):
                login_user(User("admin"))
                return redirect(url_for("choose"))
            return "Falsche Anmeldedaten."
        return render_template_string(
            dark_css
            + """
    <div class="container">
      <h2 class="mb-4 text-center">🔐 Login</h2>
      <form method="post">
        <input type="text" name="username" placeholder="Benutzername"
               class="form-control mb-3">
        <input type="password" name="password" placeholder="Passwort"
               class="form-control mb-3">
        <input type="submit" value="Login" class="btn btn-primary w-100">
      </form>
    </div>
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
      <pre style="white-space: pre-wrap;
                  background-color:#2a2a2a;
                  padding:15px;
                  border-radius:6px;">{inhalt}</pre>
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
        try:
            with open(live_datei, encoding="utf-8") as f:
                zeilen = reversed(f.readlines())
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
            inhalt = "\n".join(gefiltert)
        except OSError:
            inhalt = "[Fehler beim Öffnen der Datei]"

        return render_template_string(
            dark_css
            + f"""
<meta http-equiv="refresh" content="5">
<div class="container">
  <h2 class="mb-4 text-center">📡 Bereinigte Live-Ansicht: messages.log</h2>
  <pre style="white-space: pre-wrap;
              background-color:#2a2a2a;
              padding:15px;
              border-radius:6px;">{inhalt}</pre>
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
<table class="nodes-table table-dark">
<thead><tr><th>Num</th><th>Kurz</th><th>Lang</th><th>Zuletzt</th><th>SNR</th><th></th></tr></thead>
<tbody>{"".join(rows_html)}</tbody></table>"""

        from markupsafe import Markup

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
            value = request.form.get("value", "")
            interval = request.form.get("interval", "")
            sched_time = request.form.get("time", "")
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
      <div class="col"><label>Interface</label>
        <input type="number" name="interface" class="form-control" min="1" max="9" value="{{ iface }}"></div>
      <div class="col"><label>Kanal</label>
        <input type="number" name="channel" class="form-control" value="{{ chan }}"></div>
    </div>
    <div class="form-check mb-2">
      <input class="form-check-input" type="checkbox" name="schedulerMotd" id="sm"{{ chk_sm|safe }}>
      <label class="form-check-label" for="sm">MOTD als geplante Nachricht verwenden</label>
    </div>
    <label>Nachricht (wenn nicht MOTD)</label>
    <textarea name="message" rows="3" class="form-control mb-3">{{ msg }}</textarea>
    <label>value (day, hour, min, joke, news, …)</label>
    <input type="text" name="value" class="form-control mb-2" value="{{ val }}">
    <label>interval</label>
    <input type="text" name="interval" class="form-control mb-2" value="{{ ivl }}">
    <label>time (HH:MM)</label>
    <input type="text" name="time" class="form-control mb-3" value="{{ tim }}">
    <input type="submit" value="Speichern" class="btn btn-success w-100">
  </form>
  <p class="small text-muted mt-3">Siehe <code>config.template</code> Abschnitt <code>[scheduler]</code> und <code>modules/scheduler.py</code>.</p>
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
            val=st.schedulerValue,
            ivl=st.schedulerInterval,
            tim=st.schedulerTime,
        )

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

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
    logger.info(f"Web admin UI listening on http://{host}:{port}/login")
