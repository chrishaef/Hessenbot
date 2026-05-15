#!/usr/bin/env python3
# Public bot statistics page (Flask), inspired by etc/report_generator5.py log parsing.

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from html import escape as html_escape
from typing import Any, Dict, List

from modules.paths import path_in_repo, repo_root


def _empty_log_stats() -> Dict[str, Any]:
    return {
        "command_counts": Counter(),
        "message_types": Counter(),
        "unique_users": [],
        "warnings": [],
        "errors": [],
        "hourly_activity": {},
        "bbs_messages": 0,
        "messages_waiting": 0,
        "total_messages": 0,
        "command_timestamps": [],
        "message_timestamps": [],
        "firmware1_version": "—",
        "firmware2_version": "—",
        "node1_name": "—",
        "node2_name": "—",
        "node1_ID": "—",
        "node2_ID": "—",
        "nodeCount1": "—",
        "nodeCountOnline1": "—",
        "log_lines": 0,
        "log_error": None,
    }


def parse_meshbot_log(log_path: str, max_lines: int = 25000) -> Dict[str, Any]:
    """Parse meshbot.log (same patterns as report_generator5)."""
    stats = _empty_log_stats()
    if not os.path.isfile(log_path):
        stats["log_error"] = f"Logdatei nicht gefunden: {log_path}"
        return stats

    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        stats["log_error"] = str(e)
        return stats

    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    stats["log_lines"] = len(lines)

    hourly: Dict[str, int] = defaultdict(int)
    unique_users: set = set()
    command_counts: Counter = Counter()
    message_types: Counter = Counter()
    command_timestamps: List[tuple] = []
    message_timestamps: List[tuple] = []
    warnings: List[str] = []
    errors: List[str] = []
    timestamp = None

    for line in lines:
        timestamp_match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+", line)
        if timestamp_match:
            timestamp = datetime.strptime(timestamp_match.group(1), "%Y-%m-%d %H:%M:%S")
            hourly[timestamp.strftime("%Y-%m-%d %H:00:00")] += 1

        if "Bot detected Commands" in line or "LLM Query:" in line or "PlayingGame" in line:
            command = re.search(r"'cmd': '(\w+)'", line)
            user = re.search(r"From: (.+)$", line)
            if "LLM Query:" in line and timestamp:
                command_counts["LLM Query"] += 1
                command_timestamps.append((timestamp.isoformat(), "LLM Query"))
            if "PlayingGame" in line:
                game = re.search(r"PlayingGame (\w+)", line)
                if game and timestamp:
                    command_counts[game.group(1)] += 1
                    command_timestamps.append((timestamp.isoformat(), game.group(1)))
            if command and timestamp:
                cmd = command.group(1)
                command_counts[cmd] += 1
                who = user.group(1) if user else "?"
                command_timestamps.append((timestamp.isoformat(), f"{cmd} ({who})"))

        if any(
            x in line
            for x in (
                "Sending DM:",
                "Sending Multi-Chunk DM:",
                "SendingChannel:",
                "Sending Multi-Chunk Message:",
            )
        ):
            message_types["Ausgehend"] += 1
            stats["total_messages"] += 1
            if timestamp:
                message_timestamps.append((timestamp.isoformat(), "Ausgehend"))

        if any(
            x in line
            for x in ("Received DM:", "Ignoring DM:", "Ignoring Message:", "ReceivedChannel:")
        ):
            message_types["Eingehend"] += 1
            stats["total_messages"] += 1
            if timestamp:
                message_timestamps.append((timestamp.isoformat(), "Eingehend"))

        user_match = re.search(r"From: '([^']+)'(?: To:|$)", line) or re.search(
            r"From: (.+)$", line
        )
        if user_match:
            unique_users.add(user_match.group(1).strip()[:80])

        if "WARNING |" in line:
            warnings.insert(0, line.strip()[:200])
        if "ERROR |" in line or "CRITICAL |" in line:
            errors.insert(0, line.strip()[:200])

        bbs_match = re.search(
            r"ðŸ“¡BBSdb has (\d+) messages.*?Messages waiting: (\d+)", line
        )
        if bbs_match:
            stats["bbs_messages"] = int(bbs_match.group(1))
            stats["messages_waiting"] = int(bbs_match.group(2))

        if "| Telemetry:" in line:
            telemetry_match = re.search(
                r"Telemetry:(\d+) numPacketsRx:(\d+).*?totalNodes:(\d+) Online:(\d+).*?"
                r"Uptime:(\d+d) Volt:([\d.]+) Firmware:([\d.]+)",
                line,
            )
            if telemetry_match:
                iface, _rx, total, online, uptime, volt, fw = telemetry_match.groups()
                summary = f"Nodes {online}/{total}, {uptime}, {volt}V"
                if iface == "1":
                    stats["firmware1_version"] = fw
                    stats["nodeCount1"] = total
                    stats["nodeCountOnline1"] = online
                    stats["node1_uptime"] = summary
                elif iface == "2":
                    stats["firmware2_version"] = fw
                    stats["node2_uptime"] = summary

        if "Autoresponder Started for Device" in line:
            device_match = re.search(
                r"Autoresponder Started for Device(\d+)\s+([^\s,]+).*?NodeID: (\d+)",
                line,
            )
            if device_match:
                dev_id, name, node_id = device_match.groups()
                if dev_id == "1":
                    stats["node1_name"] = name
                    stats["node1_ID"] = node_id
                elif dev_id == "2":
                    stats["node2_name"] = name
                    stats["node2_ID"] = node_id

    stats["command_counts"] = command_counts
    stats["message_types"] = message_types
    stats["hourly_activity"] = dict(hourly)
    stats["unique_users"] = list(unique_users)[-30:]
    stats["warnings"] = warnings[:15]
    stats["errors"] = errors[:15]
    stats["command_timestamps"] = command_timestamps[-40:]
    stats["message_timestamps"] = message_timestamps[-40:]
    return stats


def _host_info() -> Dict[str, str]:
    if platform.system() != "Linux":
        return {"uptime": "—", "memory": "—", "disk": "—"}
    try:

        def run(cmd: str) -> str:
            return (
                subprocess.check_output(cmd, shell=True, timeout=3)
                .decode("utf-8", errors="replace")
                .strip()
            )

        return {
            "uptime": run("uptime -p"),
            "memory": f"{run('free -m | awk \'/Mem:/ {print $7}\'')} / {run('free -m | awk \'/Mem:/ {print $2}\'')} MB frei",
            "disk": f"{run('df -h / | awk \'NR==2 {print $4}\'')} frei von {run('df -h / | awk \'NR==2 {print $2}\'')}",
        }
    except Exception:
        return {"uptime": "—", "memory": "—", "disk": "—"}


def collect_runtime_stats() -> Dict[str, Any]:
    import modules.settings as st

    out: Dict[str, Any] = {
        "motd": getattr(st, "MOTD", "—"),
        "bbs_enabled": getattr(st, "bbs_enabled", False),
        "bbs_public_count": 0,
        "bbs_dm_count": 0,
        "node_summary": [],
        "mesh_nodes_total": 0,
        "interfaces_active": 0,
    }
    try:
        import modules.bbstools as bbs

        out["bbs_public_count"] = len(getattr(bbs, "bbs_messages", []) or [])
        out["bbs_dm_count"] = max(0, len(getattr(bbs, "bbs_dm", []) or []) - 1)
    except Exception:
        pass

    try:
        from modules import admin_web_ops as ops

        ifaces = ops.iter_radio_interfaces()
        out["interfaces_active"] = len(ifaces)
        total = 0
        for i in ifaces[:2]:
            err, rows = ops.list_node_rows(i)
            if err:
                out["node_summary"].append(f"IF{i}: {err}")
                continue
            total += len(rows)
            local = next((r for r in rows if r.get("is_self")), None)
            if local:
                out["node_summary"].append(
                    f"IF{i}: {local['shortName']} ({local['node_id']}) — {len(rows)} Knoten"
                )
            else:
                out["node_summary"].append(f"IF{i}: {len(rows)} Knoten in NodeDB")
        out["mesh_nodes_total"] = total
    except Exception as e:
        out["node_summary"].append(f"NodeDB: {e!s}")

    return out


def collect_dashboard(log_dir: str) -> Dict[str, Any]:
    base = log_dir if os.path.isabs(log_dir) else path_in_repo(log_dir)
    log_path = os.path.join(base, "meshbot.log")
    if not os.path.isfile(log_path):
        log_path = path_in_repo("logs/meshbot.log")
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "repo": repo_root(),
        "log_path": log_path,
        "log": parse_meshbot_log(log_path),
        "runtime": collect_runtime_stats(),
        "host": _host_info(),
    }


def _metric_card(title: str, value: str, sub: str = "", accent: str = "") -> str:
    val_cls = f" metric-value {accent}" if accent else "metric-value"
    sub_html = f'<div class="metric-label">{html_escape(sub)}</div>' if sub else ""
    return f"""
    <div class="metric-card">
      <div class="metric-label">{html_escape(title)}</div>
      <div class="{val_cls.strip()}">{html_escape(value)}</div>
      {sub_html}
    </div>"""


def _list_items(items: List[str], empty: str = "Keine Einträge") -> str:
    if not items:
        return f'<li class="text-muted">{html_escape(empty)}</li>'
    return "".join(f"<li>{html_escape(str(x))}</li>" for x in items)


def render_dashboard_page(data: Dict[str, Any], admin_url: str) -> str:
    log = data["log"]
    rt = data["runtime"]
    host = data["host"]
    cmd: Counter = log["command_counts"]
    top_cmds = cmd.most_common(12)
    cmd_chart_labels = json.dumps([c[0] for c in top_cmds])
    cmd_chart_values = json.dumps([c[1] for c in top_cmds])
    msg_types = log["message_types"]
    msg_labels = json.dumps(list(msg_types.keys()) or ["—"])
    msg_values = json.dumps(list(msg_types.values()) or [0])

    cards = [
        _metric_card("Nachrichten", str(log["total_messages"]), "meshbot.log"),
        _metric_card("Befehle", str(len(cmd)), f"{sum(cmd.values())} Aufrufe", "text-success"),
        _metric_card("Nutzer", str(len(log["unique_users"])), "eindeutig", "text-info"),
        _metric_card(
            "BBS öffentlich",
            str(rt["bbs_public_count"]),
            "live" if rt["bbs_enabled"] else "deaktiviert",
        ),
        _metric_card("BBS DMs", str(rt["bbs_dm_count"]), "ohne Zeile 0"),
        _metric_card(
            "Mesh-Knoten",
            str(rt["mesh_nodes_total"]),
            f"{rt['interfaces_active']} Radio(s)",
            "text-success",
        ),
        _metric_card("Warnungen", str(len(log["warnings"])), "Log"),
        _metric_card("Fehler", str(len(log["errors"])), "Log"),
    ]

    recent_cmds = [
        f"{ts}: {label}" for ts, label in reversed(log["command_timestamps"][-12:])
    ]
    recent_msgs = [
        f"{ts}: {label}" for ts, label in reversed(log["message_timestamps"][-12:])
    ]
    node_lines = rt["node_summary"] or ["Kein Radio verbunden"]
    log_note = ""
    if log.get("log_error"):
        log_note = f'<p class="alert alert-info mb-3"><i class="bi bi-info-circle me-2"></i>{html_escape(log["log_error"])}</p>'
    else:
        log_note = f'<p class="small text-muted mb-3"><i class="bi bi-file-text me-1"></i>{html_escape(str(log["log_lines"]))} Zeilen · {html_escape(data["log_path"])}</p>'

    return f"""
<div class="hero-section mb-4">
  <div class="row align-items-center g-3">
    <div class="col-lg-8">
      <h1 class="display-6 fw-bold mb-2">
        <i class="bi bi-broadcast text-success me-2"></i>Hessenbot
      </h1>
      <p class="intro-text mb-0">
        Live-Statistik aus Log und laufendem Bot · Stand {html_escape(data["generated_at"])}
      </p>
    </div>
    <div class="col-lg-4 text-lg-end">
      <a href="{html_escape(admin_url)}" class="btn btn-success">
        <i class="bi bi-shield-lock me-2"></i>Admin-Bereich
      </a>
    </div>
  </div>
</div>
{log_note}
<div class="row g-2 mb-4">{"".join(f'<div class="col-6 col-md-4 col-xl-3">{c}</div>' for c in cards)}</div>

<div class="row g-3 mb-4">
  <div class="col-lg-6">
    <div class="section-card h-100">
      <h2 class="section-title h5"><i class="bi bi-reception-4 text-success me-2"></i>Funk / NodeDB</h2>
      <ul class="dash-list mb-0">{_list_items(node_lines)}</ul>
      <p class="small text-muted mt-3 mb-0">
        IF1: {html_escape(str(log.get("node1_name", "—")))} · FW {html_escape(str(log.get("firmware1_version", "—")))}<br>
        IF2: {html_escape(str(log.get("node2_name", "—")))} · FW {html_escape(str(log.get("firmware2_version", "—")))}
      </p>
    </div>
  </div>
  <div class="col-lg-6">
    <div class="section-card h-100">
      <h2 class="section-title h5"><i class="bi bi-pc-display text-success me-2"></i>Host</h2>
      <ul class="dash-list mb-0">
        <li>Uptime: {html_escape(host["uptime"])}</li>
        <li>RAM: {html_escape(host["memory"])}</li>
        <li>Disk: {html_escape(host["disk"])}</li>
      </ul>
    </div>
  </div>
</div>

<div class="row g-3 mb-4">
  <div class="col-lg-6">
    <div class="section-card">
      <h2 class="section-title h5"><i class="bi bi-bar-chart text-success me-2"></i>Top-Befehle</h2>
      <canvas id="cmdChart" height="140"></canvas>
    </div>
  </div>
  <div class="col-lg-6">
    <div class="section-card">
      <h2 class="section-title h5"><i class="bi bi-pie-chart text-success me-2"></i>Nachrichtentypen</h2>
      <canvas id="msgChart" height="140"></canvas>
    </div>
  </div>
</div>

<div class="row g-3 mb-4">
  <div class="col-lg-6">
    <div class="section-card">
      <h2 class="section-title h5"><i class="bi bi-clock-history me-2 text-success"></i>Letzte Befehle</h2>
      <ul class="dash-list dash-scroll mb-0">{_list_items(recent_cmds, "Noch keine Befehle")}</ul>
    </div>
  </div>
  <div class="col-lg-6">
    <div class="section-card">
      <h2 class="section-title h5"><i class="bi bi-chat-dots me-2 text-success"></i>Letzte Nachrichten</h2>
      <ul class="dash-list dash-scroll mb-0">{_list_items(recent_msgs, "Noch keine Nachrichten")}</ul>
    </div>
  </div>
</div>

<div class="section-card mb-3">
  <h2 class="section-title h5"><i class="bi bi-chat-quote me-2 text-success"></i>Message of the Day</h2>
  <p class="motd-box mb-0">{html_escape(str(rt.get("motd", "—"))[:500])}</p>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
document.addEventListener('DOMContentLoaded', function() {{
  const gridColor = 'rgba(128,128,128,0.15)';
  const tickColor = getComputedStyle(document.documentElement).getPropertyValue('--text-secondary').trim() || '#6c757d';
  const opts = {{
    responsive: true,
    plugins: {{ legend: {{ labels: {{ color: tickColor }} }} }},
    scales: {{
      x: {{ ticks: {{ color: tickColor }}, grid: {{ color: gridColor }} }} }},
      y: {{ ticks: {{ color: tickColor }}, grid: {{ color: gridColor }} }}, beginAtZero: true }}
    }}
  }};
  const cmdLabels = {cmd_chart_labels};
  if (cmdLabels.length && document.getElementById('cmdChart')) {{
    new Chart(document.getElementById('cmdChart'), {{
      type: 'bar',
      data: {{
        labels: cmdLabels,
        datasets: [{{ label: 'Befehle', data: {cmd_chart_values},
          backgroundColor: 'rgba(46, 125, 94, 0.65)' }}]
      }},
      options: opts
    }});
  }}
  const msgLabels = {msg_labels};
  if (msgLabels.length && document.getElementById('msgChart')) {{
    new Chart(document.getElementById('msgChart'), {{
      type: 'doughnut',
      data: {{
        labels: msgLabels,
        datasets: [{{ data: {msg_values},
          backgroundColor: ['#2e7d5e','#20c997','#198754','#6c757d'] }}]
      }},
      options: {{ responsive: true, plugins: {{ legend: {{ labels: {{ color: tickColor }} }} }} }} }}
    }});
  }}
}});
</script>
"""

