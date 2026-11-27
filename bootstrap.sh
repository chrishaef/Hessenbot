#!/usr/bin/env bash
# Hessenbot bootstrap.
#
# One-command install on Raspberry Pi OS Lite (Debian 13 Trixie, arm64) with RAK6421 + RAK13302 (Slot 1):
#
#   curl -fsSL https://raw.githubusercontent.com/chrishaef/Hessenbot/main/bootstrap.sh -o /tmp/hb-bootstrap.sh && sudo bash /tmp/hb-bootstrap.sh
#
# `curl ... | sudo bash` works as well: all prompts read from /dev/tty, never from stdin.
# What it does: install git/curl, clone (or fast-forward) Hessenbot to /opt/Hessenbot, start the install wizard.
#
# Environment / options:
#   HESSENBOT_REF=<branch|tag>   or  --ref <branch|tag>   (default: main)
#   HESSENBOT_REPO=<git url>                              (default: https://github.com/chrishaef/Hessenbot.git)
#   --dry-run                    show what would happen, change nothing (uses the local checkout if run from one)
#   --legacy                     old behaviour: venv + config.ini in the directory of this script (embedded systems)
# All other options are passed on to script/install/wizard.sh (see: wizard.sh --help).
#
# The whole script is wrapped in main() so a truncated download never executes half a script.

set -Eeuo pipefail

HB_REPO_URL="${HESSENBOT_REPO:-https://github.com/chrishaef/Hessenbot.git}"
HB_REF="${HESSENBOT_REF:-main}"
HB_TARGET="/opt/Hessenbot"

bs_log() { printf '[bootstrap] %s\n' "$*" >&2; }
bs_die() {
    printf '[bootstrap] FEHLER: %s\n' "$*" >&2
    exit 1
}

legacy_install() {
    local base_dir
    base_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    cd "$base_dir"

    if [[ ! -d "$base_dir/venv" ]]; then
        python3 -m venv "$base_dir/venv"
    fi
    "$base_dir/venv/bin/pip" install -r "$base_dir/requirements.txt"

    mkdir -p "$base_dir/data"
    cp -Rn "$base_dir/etc/data/." "$base_dir/data/"

    if [[ ! -f "$base_dir/config.ini" ]]; then
        cp "$base_dir/config.template" "$base_dir/config.ini"
        sed -i.bak "s|type = serial|type = tcp|g" "$base_dir/config.ini"
        sed -i.bak "s|# hostname = meshtastic.local|hostname = localhost|g" "$base_dir/config.ini"
        rm -f "$base_dir/config.ini.bak"
    else
        echo "config.ini already exists, leaving it unchanged."
    fi
}

ensure_tools() {
    local missing=() t
    for t in git curl; do
        command -v "$t" >/dev/null 2>&1 || missing+=("$t")
    done
    [[ -f /etc/ssl/certs/ca-certificates.crt ]] || missing+=(ca-certificates)
    if [[ ${#missing[@]} -gt 0 ]]; then
        bs_log "Installiere: ${missing[*]}"
        local apt_opts=(-y -o DPkg::Lock::Timeout=300 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)
        DEBIAN_FRONTEND=noninteractive apt-get "${apt_opts[@]}" update </dev/null
        DEBIAN_FRONTEND=noninteractive apt-get "${apt_opts[@]}" install --no-install-recommends "${missing[@]}" ca-certificates </dev/null
    fi
}

sync_checkout() {
    if [[ -d "$HB_TARGET/.git" ]]; then
        bs_log "Aktualisiere bestehenden Checkout in $HB_TARGET (Ref: $HB_REF)"
        git config --system --get-all safe.directory 2>/dev/null | grep -qx "$HB_TARGET" || git config --system --add safe.directory "$HB_TARGET"
        if ! git -C "$HB_TARGET" diff --quiet || ! git -C "$HB_TARGET" diff --cached --quiet; then
            bs_die "Lokale Aenderungen in $HB_TARGET (git status pruefen). Bitte sichern/zuruecksetzen und erneut starten."
        fi
        git -C "$HB_TARGET" fetch --tags origin
        git -C "$HB_TARGET" checkout "$HB_REF"
        if git -C "$HB_TARGET" symbolic-ref -q HEAD >/dev/null; then
            git -C "$HB_TARGET" pull --ff-only origin "$HB_REF"
        fi
    elif [[ -e "$HB_TARGET" ]] && [[ -n "$(ls -A "$HB_TARGET" 2>/dev/null)" ]]; then
        bs_die "$HB_TARGET existiert, ist aber kein Git-Checkout. Bitte sichern oder entfernen."
    else
        bs_log "Klone $HB_REPO_URL nach $HB_TARGET (Ref: $HB_REF)"
        git clone --branch "$HB_REF" "$HB_REPO_URL" "$HB_TARGET"
    fi
}

main() {
    local args=() dry_run=0 legacy=0
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --ref)
                [[ $# -ge 2 ]] || bs_die "--ref braucht einen Wert"
                HB_REF="$2"
                shift
                ;;
            --legacy) legacy=1 ;;
            --dry-run)
                dry_run=1
                args+=("$1")
                ;;
            -h | --help)
                sed -n '2,20p' "${BASH_SOURCE[0]}" 2>/dev/null | sed 's/^# \{0,1\}//'
                exit 0
                ;;
            *) args+=("$1") ;;
        esac
        shift
    done

    if [[ $legacy -eq 1 ]]; then
        legacy_install
        return 0
    fi

    local here=""
    if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
        here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    fi

    if [[ $dry_run -eq 1 ]]; then
        if [[ -n "$here" && -f "$here/script/install/wizard.sh" ]]; then
            bs_log "Dry-run: nutze lokalen Checkout $here"
            exec bash "$here/script/install/wizard.sh" "${args[@]}"
        fi
        command -v git >/dev/null 2>&1 || bs_die "git fehlt (fuer den Dry-run ausserhalb eines Checkouts noetig)."
        local tmp
        tmp="$(mktemp -d)"
        git clone --depth 1 --branch "$HB_REF" "$HB_REPO_URL" "$tmp/Hessenbot"
        exec bash "$tmp/Hessenbot/script/install/wizard.sh" "${args[@]}"
    fi

    [[ "${EUID:-$(id -u)}" -eq 0 ]] || bs_die "Root-Rechte erforderlich: mit 'sudo bash' starten (z. B. curl ... -o /tmp/hb-bootstrap.sh && sudo bash /tmp/hb-bootstrap.sh)."
    command -v apt-get >/dev/null 2>&1 || bs_die "apt-get nicht gefunden: nur Debian/Raspberry Pi OS wird unterstuetzt."

    ensure_tools
    sync_checkout
    exec bash "$HB_TARGET/script/install/wizard.sh" "${args[@]}"
}

main "$@"
