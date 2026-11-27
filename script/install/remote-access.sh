#!/usr/bin/env bash
# Optional: allow remote Meshtastic clients (Companion app, MeshHessen client, MeshMonitor, python CLI) to reach the
# local meshtasticd TCP API (port 4403) through UFW, restricted to the LAN and/or Tailscale.
#
# meshtasticd listens on 0.0.0.0:4403 (IPv4, no bind-address option, no TLS, no authentication). Anyone who can reach the
# port can read and change the node (channel keys, config, factory reset). This helper therefore only adds narrow UFW
# rules; it never opens the port to the world.
#
# Usage: sudo bash script/install/remote-access.sh <command> [options]
#   status                     Show listener, UFW state and 4403 rules
#   lan [CIDR]                 Allow 4403/tcp from CIDR (default: the Pi's own IPv4 subnet, e.g. 192.168.1.0/24)
#   tailscale                  Allow 4403/tcp on the tailscale0 interface only
#   close                      Remove the rules added by this script
# Options:
#   --enable                   Also enable UFW if inactive (adds SSH 22/tcp first so you are not locked out; with a
#                              firewall on, everything else incoming is denied - check other services first)
#   --port N                   meshtasticd API port (default 4403)
#   --dry-run                  Print what would run
#   -h, --help
set -Eeuo pipefail

PORT=4403
DRY_RUN=0
ENABLE=0
CMD=""
CIDR=""
TAG="hessenbot-meshtasticd-api"

die() { echo "FEHLER: $*" >&2; exit 1; }
log() { echo "[remote-access] $*"; }

usage() { sed -n '2,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

run() {
    if [[ "$DRY_RUN" == "1" ]]; then
        echo "[dry-run] $*"
    else
        "$@"
    fi
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            status | lan | tailscale | close) CMD="$1" ;;
            --enable) ENABLE=1 ;;
            --dry-run) DRY_RUN=1 ;;
            --port)
                [[ $# -ge 2 ]] || die "--port braucht einen Wert."
                PORT="$2"
                shift
                ;;
            -h | --help) usage; exit 0 ;;
            *)
                if [[ "$CMD" == "lan" && -z "$CIDR" && "$1" == */* ]]; then
                    CIDR="$1"
                else
                    die "Unbekanntes Argument: $1 (siehe --help)"
                fi
                ;;
        esac
        shift
    done
    [[ -n "$CMD" ]] || { usage; exit 1; }
    [[ "$PORT" =~ ^[0-9]+$ && "$PORT" -ge 1 && "$PORT" -le 65535 ]] || die "Ungueltiger Port: $PORT"
}

require_root() {
    [[ "$DRY_RUN" == "1" || "${EUID:-$(id -u)}" -eq 0 ]] || die "Root-Rechte erforderlich (sudo)."
}

detect_lan_cidr() {
    local cidr
    cidr="$(ip -4 -o route show scope link 2>/dev/null | awk '$1 ~ /\// && $1 !~ /^169\.254\./ {print $1; exit}')"
    [[ -n "$cidr" ]] || die "LAN-Subnetz nicht erkannt; bitte CIDR angeben: remote-access.sh lan 192.168.1.0/24"
    echo "$cidr"
}

ensure_ufw() {
    if ! command -v ufw >/dev/null 2>&1; then
        log "ufw fehlt; installiere (apt-get install ufw)."
        run apt-get install -y ufw
    fi
    if [[ "$DRY_RUN" != "1" ]] && ufw status | grep -q '^Status: inactive'; then
        if [[ "$ENABLE" != "1" ]]; then
            log "UFW ist inaktiv: Regeln werden angelegt, greifen aber erst nach 'sudo ufw enable'."
            log "Ohne Firewall ist Port $PORT fuer jeden im Netz offen. Mit --enable aktivieren (SSH wird vorher erlaubt)."
            return 0
        fi
        log "Aktiviere UFW; SSH 22/tcp wird vorher erlaubt (Lockout-Schutz). Andere eingehende Dienste (z. B. Web-Admin :5000) danach selbst freigeben."
        run ufw allow 22/tcp comment "ssh"
        run ufw --force enable
    elif [[ "$DRY_RUN" == "1" && "$ENABLE" == "1" ]]; then
        run ufw allow 22/tcp comment "ssh"
        run ufw --force enable
    fi
}

cmd_status() {
    log "Listener auf Port $PORT:"
    ss -ltnp 2>/dev/null | awk -v p=":$PORT" 'NR==1 || $4 ~ p"$"' || true
    if command -v ufw >/dev/null 2>&1; then
        log "UFW:"
        ufw status verbose 2>/dev/null || true
    else
        log "UFW nicht installiert: Port $PORT ist fuer alle erreichbaren Netze offen (LAN, ggf. Tailscale)."
    fi
    if command -v tailscale >/dev/null 2>&1; then
        log "Tailscale-IPv4: $(tailscale ip -4 2>/dev/null | head -1 || echo unbekannt)"
    fi
}

cmd_lan() {
    local cidr="$CIDR"
    [[ -n "$cidr" ]] || cidr="$(detect_lan_cidr)"
    ensure_ufw
    log "Erlaube ${PORT}/tcp nur aus $cidr"
    run ufw allow from "$cidr" to any port "$PORT" proto tcp comment "$TAG-lan"
}

cmd_tailscale() {
    ip link show tailscale0 >/dev/null 2>&1 || log "Hinweis: Interface tailscale0 existiert (noch) nicht; Regel wird trotzdem angelegt."
    ensure_ufw
    log "Erlaube ${PORT}/tcp nur auf tailscale0"
    run ufw allow in on tailscale0 to any port "$PORT" proto tcp comment "$TAG-tailscale"
}

cmd_close() {
    local n removed=0
    command -v ufw >/dev/null 2>&1 || { log "ufw nicht installiert; nichts zu tun."; return 0; }
    while n="$(ufw status numbered | awk -v t="$TAG" '$0 ~ t {gsub(/[\[\]]/, "", $1); print $1}' | sort -rn | head -1)" && [[ -n "$n" ]]; do
        run ufw --force delete "$n"
        removed=$((removed + 1))
        [[ "$DRY_RUN" == "1" ]] && break
    done
    log "$removed Regel(n) entfernt."
}

main() {
    parse_args "$@"
    [[ "$CMD" == "status" ]] || require_root
    case "$CMD" in
        status) cmd_status ;;
        lan) cmd_lan ;;
        tailscale) cmd_tailscale ;;
        close) cmd_close ;;
    esac
}

main "$@"
