# interface1.py

from flask import Flask, request, redirect, render_template_string, url_for
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os

app = Flask(__name__)
app.secret_key = "supergeheimschlüssel"

DATEIEN = {
    "direktnachricht": "/opt/meshing-around/alert.txt",
    "news": "/opt/meshing-around/news.txt"
}
LOG_ORDNER = "/opt/meshing-around/logs"
LIVE_DATEI = os.path.join(LOG_ORDNER, "messages.log")

login_manager = LoginManager()
login_manager.init_app(app)

class User(UserMixin):
    def __init__(self, id):
        self.id = id

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
</style>
"""

@limiter.limit("5 per minute")
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if (request.form["username"] == "admin" and #<--- Change after installation
            request.form["password"] == "passwort123"): #<--- Change after installation
            user = User("admin")
            login_user(user)
            return redirect(url_for("choose"))
        return "Falsche Anmeldedaten."
    return render_template_string(dark_css + """
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
    """)

@app.route("/choose")
@login_required
def choose():
    return render_template_string(dark_css + """
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
      <div class="mt-4">
        <a href="{{url_for('logout')}}" class="btn btn-secondary">🔒 Logout</a>
      </div>
    </div>
    """)

@app.route("/edit/<dateiname>", methods=["GET", "POST"])
@login_required
def edit(dateiname):
    pfad = DATEIEN.get(dateiname)
    if not pfad:
        return "Ungültiger Dateiname.", 404

    if request.method == "POST":
        with open(pfad, "w") as f:
            f.write(request.form["text"])

    with open(pfad) as f:
        inhalt = f.read()

    return render_template_string(dark_css + f"""
    <div class="container">
      <h2 class="mb-4 text-center">📝 Datei: {dateiname.capitalize()}</h2>
      <form method="post">
        <textarea name="text" rows="20" class="form-control mb-3">{inhalt}</textarea>
        <input type="submit" value="Speichern" class="btn btn-success w-100">
      </form>
      <div class="text-center mt-3">
        <a href="{{{{url_for('choose')}}}}" class="btn btn-outline-light">
          ⬅️ Zurück
        </a>
      </div>
    </div>
    """)

@app.route("/logs")
@login_required
def logs():
    try:
        dateien = [
            f for f in os.listdir(LOG_ORDNER)
            if os.path.isfile(os.path.join(LOG_ORDNER, f))
        ]
    except:
        return "Fehler beim Lesen des Log-Ordners.", 500

    items = "".join(
        f'<a href="{url_for("view_log", filename=f)}" '
        f'class="btn btn-dark mb-2 w-100">📄 {f}</a>'
        for f in sorted(dateien)
    )

    return render_template_string(dark_css + f"""
    <div class="container text-center">
      <h2 class="mb-4">📁 Alle Dateien im Log-Ordner</h2>
      {items if items else "<p>Keine Dateien gefunden.</p>"}
      <div class="mt-4">
        <a href="{{{{url_for('choose')}}}}" class="btn btn-outline-light">
          ⬅️ Zurück
        </a>
      </div>
    </div>
    """)

@app.route("/view/<filename>")
@login_required
def view_log(filename):
    pfad = os.path.join(LOG_ORDNER, filename)
    if not os.path.isfile(pfad):
        return "Datei nicht gefunden.", 404

    try:
        with open(pfad) as f:
            inhalt = f.read()
    except:
        inhalt = "[Fehler beim Öffnen der Datei]"

    return render_template_string(dark_css + f"""
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
    """)

@app.route("/live/messages")
@login_required
def live_messages():
    try:
        with open(LIVE_DATEI) as f:
            zeilen = reversed(f.readlines())
            gefiltert = []
            for z in zeilen:
                try:
                    teile = z.strip().split(" | ")
                    # Uhrzeit extrahieren (HH:MM:SS)
                    if len(teile) > 0 and " " in teile[0]:
                        zeitstempel = teile[0].split(" ")[1].split(",")[0]
                    else:
                        zeitstempel = "??:??:??"
                    sender = teile[2] if len(teile) > 2 else "Unbekannt"
                    nachricht = teile[3] if len(teile) > 3 else ""
                    gefiltert.append(f"{zeitstempel} | {sender} | {nachricht}")
                except:
                    gefiltert.append(f"[Fehler beim Parsen] → {z.strip()}")
            inhalt = "\n\n".join(gefiltert)
    except:
        inhalt = "[Fehler beim Öffnen der Datei]"

    return render_template_string(dark_css + f"""
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
""")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)