#!/usr/bin/env python3
"""DM-Zustellung: Log-Auswertung (24h) und wiederholte Fehler im Betrieb."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from modules.log import logger
from modules.web_faq_pki_check import _strip_ansi, resolve_meshbot_log_paths

_RE_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+")
_RE_DM_CONFIRMED = re.compile(r"DM delivery confirmed .*?\bNode:(\d+)\b")
_RE_DM_FAIL_PKI = re.compile(r"DM delivery failed \(PKI\).*?\bNode:(\d+)\b")
_RE_DM_FAIL_OTHER = re.compile(r"DM delivery failed Device:.*?\bNode:(\d+)\b")

# (device_id, dest_node) -> consecutive failure count
_fail_streak: Dict[Tuple[int, int], int] = {}
_warned_pairs: set[Tuple[int, int]] = set()


def _alert_threshold() -> int:
    try:
        from modules.settings import dm_delivery_fail_alert_threshold

        return max(1, int(dm_delivery_fail_alert_threshold))
    except Exception:
        return 3


def _decimal_to_hex(node_id: int) -> str:
    return f"!{node_id:08x}"


def record_dm_delivery_outcome(
    device_id: int,
    dest_node: int,
    *,
    success: bool,
    is_pki: bool = False,
) -> None:
    """Track consecutive DM failures; log admin hint after threshold."""
    key = (int(device_id), int(dest_node))
    if success:
        _fail_streak.pop(key, None)
        _warned_pairs.discard(key)
        return

    streak = _fail_streak.get(key, 0) + 1
    _fail_streak[key] = streak
    threshold = _alert_threshold()
    if streak < threshold or key in _warned_pairs:
        return

    _warned_pairs.add(key)
    hex_id = _decimal_to_hex(dest_node)
    pki_note = " (PKI)" if is_pki else ""
    logger.warning(
        f"System: Admin-Hinweis: {streak}× DM-Zustellfehler{pki_note} an dieselbe Node "
        f"Node:{dest_node} {hex_id} Device:{device_id} — "
        f"NodeDB prüfen (/nodes, iface {device_id}), FAQ PKI-Check (/faq) mit Node-ID {dest_node}"
    )


def _parse_line_timestamp(line: str) -> Optional[datetime]:
    m = _RE_TS.match(line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def parse_dm_delivery_stats_24h(
    log_dir: str,
    *,
    hours: float = 24.0,
    max_bytes_per_file: int = 4_000_000,
) -> Dict[str, Any]:
    """
    Zählt DM delivery confirmed / failed (PKI) / failed (other) in den letzten `hours` Stunden.
    """
    cutoff = datetime.now() - timedelta(hours=hours)
    confirmed = 0
    failed_pki = 0
    failed_other = 0
    by_node: Dict[int, Dict[str, int]] = defaultdict(
        lambda: {"confirmed": 0, "failed_pki": 0, "failed_other": 0}
    )
    lines_scanned = 0

    paths = resolve_meshbot_log_paths(log_dir)
    for path in paths:
        try:
            with open(path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - max_bytes_per_file))
                chunk = f.read()
        except OSError:
            continue
        text = chunk.decode("utf-8", errors="replace")
        if size > max_bytes_per_file and "\n" in text:
            text = text.split("\n", 1)[-1]
        for raw in text.splitlines():
            lines_scanned += 1
            plain = _strip_ansi(raw)
            ts = _parse_line_timestamp(raw)
            if ts is None or ts < cutoff:
                continue
            if "DM delivery confirmed" in plain:
                m = _RE_DM_CONFIRMED.search(plain)
                if m:
                    confirmed += 1
                    nid = int(m.group(1))
                    by_node[nid]["confirmed"] += 1
                continue
            if "DM delivery failed (PKI)" in plain:
                m = _RE_DM_FAIL_PKI.search(plain)
                if m:
                    failed_pki += 1
                    nid = int(m.group(1))
                    by_node[nid]["failed_pki"] += 1
                continue
            if "DM delivery failed Device:" in plain:
                m = _RE_DM_FAIL_OTHER.search(plain)
                if m:
                    failed_other += 1
                    nid = int(m.group(1))
                    by_node[nid]["failed_other"] += 1

    top_problem_nodes: List[Dict[str, Any]] = []
    for nid, counts in by_node.items():
        fails = counts["failed_pki"] + counts["failed_other"]
        if fails <= 0:
            continue
        top_problem_nodes.append(
            {
                "node_id": nid,
                "node_hex": _decimal_to_hex(nid),
                **counts,
                "fails": fails,
            }
        )
    top_problem_nodes.sort(key=lambda x: x["fails"], reverse=True)

    return {
        "confirmed": confirmed,
        "failed_pki": failed_pki,
        "failed_other": failed_other,
        "failed_total": failed_pki + failed_other,
        "lines_scanned": lines_scanned,
        "hours": hours,
        "top_problem_nodes": top_problem_nodes[:8],
    }


def render_dm_delivery_stats_html(stats: Dict[str, Any], *, compact: bool = False) -> str:
    """Admin / Dashboard block for 24h DM delivery counters."""
    if not stats:
        return '<p class="text-muted small mb-0">Keine DM-Zustell-Daten.</p>'
    c = stats.get("confirmed", 0)
    fp = stats.get("failed_pki", 0)
    fo = stats.get("failed_other", 0)
    hours = int(stats.get("hours", 24))
    if compact:
        total = c + fp + fo
        if total > 0:
            chart_block = (
                '<div class="chart-canvas-wrap dm-delivery-chart-wrap">'
                '<canvas id="dmDeliveryChart" aria-label="DM-Zustellung Diagramm"></canvas>'
                "</div>"
            )
        else:
            chart_block = (
                '<p class="text-muted small mb-0 mt-3 text-center">'
                "Noch keine DM-Zustell-Meldungen im Auswertungszeitraum."
                "</p>"
            )
        return f"""
<div class="dm-delivery-stats-compact">
  <div class="row g-2 text-center mb-0">
    <div class="col-4">
      <div class="metric-label small">Bestätigt</div>
      <div class="metric-value text-success">{c}</div>
    </div>
    <div class="col-4">
      <div class="metric-label small">PKI-Fehler</div>
      <div class="metric-value text-warning">{fp}</div>
    </div>
    <div class="col-4">
      <div class="metric-label small">Sonst. Fehler</div>
      <div class="metric-value text-danger">{fo}</div>
    </div>
  </div>
  {chart_block}
</div>"""

    top = stats.get("top_problem_nodes") or []
    top_html = ""
    if top:
        rows = []
        for n in top[:5]:
            rows.append(
                f'<li class="small mb-1">'
                f'<code>{n["node_hex"]}</code> '
                f'<span class="text-muted">({n["node_id"]})</span> — '
                f'PKI: {n["failed_pki"]}, sonst: {n["failed_other"]}, OK: {n["confirmed"]}'
                f'</li>'
            )
        top_html = (
            '<p class="small fw-semibold mb-1 mt-3">Häufigste Problem-Nodes</p>'
            f'<ul class="list-unstyled mb-0">{"".join(rows)}</ul>'
        )

    return f"""
<div class="row g-2 mb-0">
  <div class="col-md-4">
    <div class="metric-card h-100">
      <div class="metric-label">Bestätigt</div>
      <div class="metric-value text-success">{c}</div>
      <div class="metric-label metric-sub">DM ACK (24h)</div>
    </div>
  </div>
  <div class="col-md-4">
    <div class="metric-card h-100">
      <div class="metric-label">PKI-Fehler</div>
      <div class="metric-value text-warning">{fp}</div>
      <div class="metric-label metric-sub">delivery failed (PKI)</div>
    </div>
  </div>
  <div class="col-md-4">
    <div class="metric-card h-100">
      <div class="metric-label">Sonst. Fehler</div>
      <div class="metric-value text-danger">{fo}</div>
      <div class="metric-label metric-sub">Routing / Timeout</div>
    </div>
  </div>
</div>
<p class="small text-muted mb-0 mt-2">
  Auswertung der letzten {hours} Stunden ({stats.get("lines_scanned", 0):,} Log-Zeilen im Tail).
  Voraussetzung: <code>wantAckOnDm = True</code>.
</p>
{top_html}"""
