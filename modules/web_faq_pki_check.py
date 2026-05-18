#!/usr/bin/env python3
"""PKI-Fehlersuche in meshbot.log für die öffentliche FAQ-Seite."""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass
from html import escape as html_escape
from typing import Any, Dict, List, Optional, Tuple

from markupsafe import Markup

from modules.paths import path_in_repo

PKI_MARKERS = (
    "PKI Routing Error",
    "PKI_SEND_FAIL",
    "PKI_UNKNOWN_PUBKEY",
    "PKI_FAILED",
    "Reason:PKI_",
)

GUIDANCE = {
    "PKI_SEND_FAIL_PUBLIC_KEY": (
        "Der Bot kennt den öffentlichen Schlüssel der Ziel-Node nicht. "
        "Node-ID in <code>favoriteNodeList</code> eintragen, <code>script/addFav.py</code> ausführen, "
        "oder die Node in der Admin-NodeDB entfernen und erneut Kontakt anstoßen."
    ),
    "PKI_UNKNOWN_PUBKEY": (
        "Die Gegenstelle konnte nicht entschlüsseln (fehlender Schlüssel des Bots). "
        "Auf dem <strong>Client</strong>: Bot-Kontakt löschen und neu hinzufügen oder als Favorit setzen."
    ),
    "PKI_FAILED": (
        "PKI-Versandvoraussetzungen nicht erfüllt. Firmware und Kanal-Keys prüfen."
    ),
}


@dataclass(frozen=True)
class PkiLogHit:
    line: str
    reason: str
    role: str  # requester | target | mentioned


def parse_node_id_input(raw: str) -> Tuple[Optional[int], Optional[str]]:
    """Dezimal-ID oder !xxxxxxxx → (node_num, error_de)."""
    token = (raw or "").strip()
    if not token:
        return None, "Bitte eine Node-ID eingeben (dezimal oder !xxxxxxxx)."
    if token.startswith("!"):
        hexpart = token[1:].strip()
        if len(hexpart) != 8:
            return None, "Ungültige !hex-ID — erwartet z. B. !12ab34cd (8 Hex-Zeichen)."
        try:
            return int(hexpart, 16), None
        except ValueError:
            return None, "Ungültige !hex-ID."
    if not token.isdigit():
        return None, "Nur Dezimal-ID oder !xxxxxxxx erlaubt (kein Kurzname)."
    try:
        num = int(token)
    except ValueError:
        return None, "Ungültige Dezimal-ID."
    if num <= 0 or num > 0xFFFFFFFF:
        return None, "Node-ID außerhalb des gültigen Bereichs."
    return num, None


def decimal_to_hex(node_id: int) -> str:
    return f"!{node_id:08x}"


def resolve_meshbot_log_paths(log_dir: str) -> List[str]:
    """Aktuelles meshbot.log plus wenige rotierte Dateien (neueste zuerst)."""
    if log_dir and os.path.isabs(log_dir):
        base = log_dir
    else:
        base = path_in_repo(log_dir or "logs")
    primary = os.path.join(base, "meshbot.log")
    paths: List[str] = []
    if os.path.isfile(primary):
        paths.append(primary)
    pattern = os.path.join(base, "meshbot.log.*")
    rotated = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    for p in rotated[:2]:
        if p not in paths and os.path.isfile(p):
            paths.append(p)
    if not paths:
        fallback = path_in_repo("logs/meshbot.log")
        if os.path.isfile(fallback):
            paths.append(fallback)
    return paths


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _tail_lines(path: str, max_bytes: int = 4_000_000) -> List[str]:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            chunk = f.read()
    except OSError:
        return []
    text = chunk.decode("utf-8", errors="replace")
    if size > max_bytes and "\n" in text:
        text = text.split("\n", 1)[-1]
    return text.splitlines()


def _line_mentions_node(line: str, node_id: int, hex_id: str) -> bool:
    plain = _strip_ansi(line)
    dec = str(node_id)
    if dec in plain:
        return True
    if hex_id.lower() in plain.lower():
        return True
    return False


def _extract_pki_reason(line: str) -> str:
    m = re.search(r"Reason:(PKI_[A-Z0-9_]+)", line)
    if m:
        return m.group(1)
    for marker in ("PKI_SEND_FAIL_PUBLIC_KEY", "PKI_UNKNOWN_PUBKEY", "PKI_FAILED"):
        if marker in line:
            return marker
    return "PKI"


def _hit_role(line: str, node_id: int) -> str:
    plain = _strip_ansi(line)
    dec = str(node_id)
    if re.search(rf"TargetNode:\s*{dec}\b", plain):
        return "Ziel"
    if re.search(rf"RequesterNode:\s*{dec}\b", plain):
        return "Absender"
    return "erwähnt"


def _is_pki_line(line: str) -> bool:
    plain = _strip_ansi(line)
    return any(m in plain for m in PKI_MARKERS)


def scan_pki_log_for_node(
    node_input: str,
    log_dir: str,
    *,
    max_bytes_per_file: int = 4_000_000,
    max_hits: int = 25,
) -> Dict[str, Any]:
    node_id, err = parse_node_id_input(node_input)
    if err:
        return {"ok": False, "error": err}

    assert node_id is not None
    hex_id = decimal_to_hex(node_id)
    paths = resolve_meshbot_log_paths(log_dir)
    if not paths:
        return {
            "ok": False,
            "error": "Keine meshbot.log-Datei gefunden. SyslogToFile in config.ini aktivieren?",
            "node_id": node_id,
            "node_hex": hex_id,
        }

    hits: List[PkiLogHit] = []
    lines_scanned = 0
    for path in paths:
        for line in _tail_lines(path, max_bytes=max_bytes_per_file):
            lines_scanned += 1
            if not _is_pki_line(line):
                continue
            if not _line_mentions_node(line, node_id, hex_id):
                continue
            hits.append(
                PkiLogHit(
                    line=_strip_ansi(line).strip(),
                    reason=_extract_pki_reason(line),
                    role=_hit_role(line, node_id),
                )
            )
            if len(hits) >= max_hits:
                break
        if len(hits) >= max_hits:
            break

    reasons = sorted({h.reason for h in hits})
    guidance: List[str] = []
    for r in reasons:
        for key, text in GUIDANCE.items():
            if key in r and text not in guidance:
                guidance.append(text)

    if hits:
        summary = "problems_found"
        message = (
            f"{len(hits)} PKI-relevante Einträge für Node {node_id} ({hex_id}) "
            f"im geprüften Log-Ausschnitt."
        )
    else:
        summary = "no_hits"
        message = (
            f"Keine PKI-Einträge für {node_id} ({hex_id}) im geprüften Log-Ausschnitt "
            f"({lines_scanned:,} Zeilen in {len(paths)} Datei(en)). "
            "Das schließt ein PKI-Problem nicht aus — besonders wenn der Fehler nur auf dem "
            "Client auftritt. Dann Bot-Kontakt dort löschen und neu hinzufügen."
        )

    return {
        "ok": True,
        "summary": summary,
        "message": message,
        "node_id": node_id,
        "node_hex": hex_id,
        "log_paths": paths,
        "lines_scanned": lines_scanned,
        "hits": [{"line": h.line, "reason": h.reason, "role": h.role} for h in hits],
        "guidance": guidance,
    }


def render_pki_checker_html(result: Optional[Dict[str, Any]] = None) -> str:
    """Formular + optional Ergebnisblock für die FAQ-Seite."""
    result_block = ""
    if result is not None:
        if not result.get("ok"):
            result_block = f"""
<div class="alert alert-danger mt-3 mb-0" role="alert">
  <i class="bi bi-exclamation-triangle me-1"></i>{html_escape(result.get("error", "Unbekannter Fehler"))}
</div>"""
        else:
            alert_cls = "alert-warning" if result.get("summary") == "problems_found" else "alert-success"
            icon = "exclamation-triangle" if result.get("summary") == "problems_found" else "check-circle"
            hits = result.get("hits") or []
            hit_rows = ""
            if hits:
                items = []
                for h in hits[:15]:
                    line_short = h["line"]
                    if len(line_short) > 220:
                        line_short = line_short[:217] + "…"
                    items.append(
                        '<li class="mb-2">'
                        f'<span class="badge text-bg-secondary me-1">{html_escape(h["role"])}</span>'
                        f'<span class="badge text-bg-warning me-1">{html_escape(h["reason"])}</span>'
                        f'<code class="small d-block mt-1 text-wrap">{html_escape(line_short)}</code>'
                        "</li>"
                    )
                hit_rows = f'<ul class="list-unstyled small mb-2 mt-2">{"".join(items)}</ul>'
                if len(hits) > 15:
                    hit_rows += f'<p class="small text-muted mb-0">… und {len(hits) - 15} weitere Treffer.</p>'

            guidance_html = ""
            for g in result.get("guidance") or []:
                guidance_html += f'<p class="small mb-2">{Markup(g)}</p>'

            log_files = ", ".join(html_escape(os.path.basename(p)) for p in result.get("log_paths") or [])
            meta = (
                f'<p class="small text-muted mb-0">'
                f'Geprüft: {html_escape(log_files)} · '
                f'{result.get("lines_scanned", 0):,} Zeilen (Tail-Ausschnitt)'
                f"</p>"
            )
            nid = result.get("node_id", "")
            nhex = html_escape(str(result.get("node_hex", "")))
            if result.get("summary") == "problems_found":
                msg_html = (
                    f'{len(hits)} PKI-relevante Einträge für Node '
                    f'<code>{html_escape(str(nid))}</code> (<code>{nhex}</code>) im Log-Ausschnitt.'
                )
            else:
                lines = result.get("lines_scanned", 0)
                nfiles = len(result.get("log_paths") or [])
                msg_html = (
                    f'Keine PKI-Einträge für <code>{html_escape(str(nid))}</code> '
                    f'(<code>{nhex}</code>) ({lines:,} Zeilen, {nfiles} Datei(en)). '
                    f'Client-seitig ggf. Bot-Kontakt neu anlegen.'
                )
            result_block = f"""
<div class="alert {alert_cls} mt-3 mb-0" role="alert">
  <i class="bi bi-{icon} me-1"></i>{msg_html}
  {hit_rows}
  {guidance_html}
  {meta}
</div>"""

    return f"""
<div class="portal-card p-4 mb-4 faq-pki-check">
  <h2 class="h5 section-title mb-2">
    <i class="bi bi-shield-lock text-success me-2"></i>PKI-Log prüfen
  </h2>
  <p class="text-muted small mb-3">
    Dezimal-Node-ID oder <code>!hex</code> eingeben. Es werden die letzten Abschnitte von
    <code>meshbot.log</code> nach PKI-Routing-Fehlern mit dieser Node durchsucht.
  </p>
  <form method="post" action="/faq/pki-check" class="row g-2 align-items-end">
    <div class="col-sm-8 col-md-6">
      <label for="faqNodeId" class="form-label small mb-1">Node-ID</label>
      <input type="text" class="form-control form-control-sm" id="faqNodeId" name="node_id"
             placeholder="z. B. 2813308004 oder !a7b8c9d0"
             value="{html_escape((result or {}).get('node_input', ''))}"
             pattern="[0-9!a-fA-F]+" autocomplete="off" required>
    </div>
    <div class="col-auto">
      <button type="submit" class="btn btn-success btn-sm">
        <i class="bi bi-search me-1"></i>Log durchsuchen
      </button>
    </div>
  </form>
  {result_block}
</div>"""
