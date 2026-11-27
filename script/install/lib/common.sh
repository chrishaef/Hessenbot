#!/usr/bin/env bash
# Hessenbot installer: shared helpers (logging, prompts via /dev/tty, dry-run aware run/write, backups, manifest).
# Sourced by wizard.sh; not executable on its own.
# shellcheck shell=bash disable=SC2034,SC2015,SC2153

HB_STATE_DIR="${HB_STATE_DIR:-/var/lib/hessenbot-install}"
HB_BACKUP_DIR="${HB_BACKUP_DIR:-/var/backups/hessenbot}"
HB_LOG_FILE="${HB_LOG_FILE:-/var/log/hessenbot-install.log}"
HB_MANIFEST="${HB_MANIFEST:-$HB_STATE_DIR/manifest}"
HB_STATE_FILE="${HB_STATE_FILE:-$HB_STATE_DIR/state.env}"

DRY_RUN="${DRY_RUN:-0}"
ASSUME_YES="${ASSUME_YES:-0}"
NONINTERACTIVE="${NONINTERACTIVE:-0}"
TS="${TS:-$(date +%Y%m%d-%H%M%S)}"
CURRENT_PHASE="init"
SECRETS=()

# --- masking ---------------------------------------------------------------

register_secret() {
    local s="${1:-}"
    [[ -n "$s" ]] && SECRETS+=("$s")
    return 0
}

mask_text() {
    local text="$1" s
    local re='[A-Za-z0-9+/]{43}='
    for s in "${SECRETS[@]+"${SECRETS[@]}"}"; do
        text="${text//"$s"/***}"
    done
    # Anything shaped like a 256-bit base64 PSK is masked even when not registered.
    while [[ "$text" =~ $re ]]; do
        text="${text/"${BASH_REMATCH[0]}"/***PSK***}"
    done
    printf '%s' "$text"
}

mask_stream() {
    local line
    while IFS= read -r line || [[ -n "$line" ]]; do
        mask_text "$line"
        printf '\n'
    done
}

# --- logging ---------------------------------------------------------------

log_init() {
    if [[ "$DRY_RUN" == "1" ]]; then
        HB_LOG_FILE="$(mktemp "${TMPDIR:-/tmp}/hessenbot-install-dry-run.XXXXXX.log")"
    fi
    local dir
    dir="$(dirname "$HB_LOG_FILE")"
    mkdir -p "$dir" 2>/dev/null || true
    (umask 077 && : >>"$HB_LOG_FILE") 2>/dev/null || HB_LOG_FILE=/dev/null
    chmod 600 "$HB_LOG_FILE" 2>/dev/null || true
}

_emit() {
    local level="$1"
    shift
    local msg
    msg="$(mask_text "$*")"
    printf '%s\n' "$msg" >&2
    printf '%s [%s] [%s] %s\n' "$(date '+%F %T')" "$level" "$CURRENT_PHASE" "$msg" >>"$HB_LOG_FILE" 2>/dev/null || true
}

log() { _emit INFO "$*"; }
warn() { _emit WARN "WARNUNG: $*"; }
step() { _emit INFO ""; _emit INFO "== $* =="; }
die() {
    _emit ERROR "FEHLER: $*"
    if declare -F on_error_hook >/dev/null 2>&1; then
        on_error_hook 1 "-" "$*" || true
    fi
    exit 1
}

on_error() {
    local rc=$? line="${1:-?}"
    _emit ERROR "Abbruch in Phase '$CURRENT_PHASE' (Zeile $line, Exit-Code $rc). Log: $HB_LOG_FILE"
    _emit ERROR "Der Assistent ist idempotent: nach Behebung denselben Befehl erneut ausfuehren."
    if declare -F on_error_hook >/dev/null 2>&1; then
        on_error_hook "$rc" "$line" || true
    fi
    exit "$rc"
}

# --- prompts (always /dev/tty, never stdin: curl | bash safe) -------------

TTY_OK=""
tty_available() {
    if [[ -z "$TTY_OK" ]]; then
        if [[ "$NONINTERACTIVE" == "1" ]]; then
            TTY_OK=0
        elif { : </dev/tty; } 2>/dev/null; then
            TTY_OK=1
        else
            TTY_OK=0
        fi
    fi
    [[ "$TTY_OK" == "1" ]]
}

# ask VAR "Frage" "default" -> value in $REPLY_VALUE
ask() {
    local prompt="$1" default="${2:-}" answer=""
    if [[ "$ASSUME_YES" == "1" ]] || ! tty_available; then
        if [[ "$ASSUME_YES" != "1" && "$NONINTERACTIVE" != "1" ]]; then
            die "Kein Terminal (/dev/tty) verfuegbar. Mit --yes --non-interactive und Flags starten."
        fi
        REPLY_VALUE="$default"
        return 0
    fi
    if [[ -n "$default" ]]; then
        printf '%s [%s]: ' "$prompt" "$default" >/dev/tty
    else
        printf '%s: ' "$prompt" >/dev/tty
    fi
    IFS= read -r answer </dev/tty || answer=""
    REPLY_VALUE="${answer:-$default}"
}

ask_secret() {
    local prompt="$1" answer=""
    if ! tty_available; then
        die "Geheimer Wert ('$prompt') benoetigt ein Terminal; im nicht-interaktiven Modus nicht moeglich."
    fi
    printf '%s: ' "$prompt" >/dev/tty
    IFS= read -rs answer </dev/tty || answer=""
    printf '\n' >/dev/tty
    REPLY_VALUE="$answer"
    register_secret "$answer"
}

# confirm "Frage" default(y|n); returns 0 for yes
confirm() {
    local prompt="$1" default="${2:-y}" hint answer
    if [[ "$ASSUME_YES" == "1" ]]; then
        [[ "$default" == "y" ]]
        return
    fi
    if ! tty_available; then
        [[ "$NONINTERACTIVE" == "1" ]] && { [[ "$default" == "y" ]]; return; }
        die "Kein Terminal (/dev/tty) verfuegbar. Mit --yes --non-interactive und Flags starten."
    fi
    [[ "$default" == "y" ]] && hint="J/n" || hint="j/N"
    while true; do
        printf '%s [%s]: ' "$prompt" "$hint" >/dev/tty
        IFS= read -r answer </dev/tty || answer=""
        answer="${answer:-$default}"
        case "${answer,,}" in
            y | yes | j | ja) return 0 ;;
            n | no | nein) return 1 ;;
            *) printf 'Bitte j oder n eingeben.\n' >/dev/tty ;;
        esac
    done
}

tty_print() {
    if tty_available; then
        printf '%s\n' "$*" >/dev/tty
    else
        printf '%s\n' "$*" >&2
    fi
}

# --- execution -------------------------------------------------------------

# run CMD ARGS...: dry-run aware; output is masked and logged.
run() {
    local shown
    shown="$(mask_text "$*")"
    if [[ "$DRY_RUN" == "1" ]]; then
        _emit INFO "[dry-run] $shown"
        return 0
    fi
    _emit INFO "+ $shown"
    local rc=0
    set -o pipefail
    "$@" 2>&1 | mask_stream | tee -a "$HB_LOG_FILE" >&2 || rc=${PIPESTATUS[0]}
    return "$rc"
}

# run_quiet: like run but output only goes to the log (noisy apt)
run_quiet() {
    local shown
    shown="$(mask_text "$*")"
    if [[ "$DRY_RUN" == "1" ]]; then
        _emit INFO "[dry-run] $shown"
        return 0
    fi
    _emit INFO "+ $shown"
    local rc=0
    "$@" </dev/null 2>&1 | mask_stream >>"$HB_LOG_FILE" || rc=${PIPESTATUS[0]}
    if [[ $rc -ne 0 ]]; then
        warn "Befehl fehlgeschlagen (Exit $rc): $shown (Details: $HB_LOG_FILE)"
        tail -n 15 "$HB_LOG_FILE" >&2 || true
    fi
    return "$rc"
}

# apt_run ARGS...: apt-get that never prompts (conffiles keep local edits) and waits for the dpkg lock.
APT_OPTS=(-y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold -o DPkg::Lock::Timeout=300)
apt_run() {
    DEBIAN_FRONTEND=noninteractive run_quiet apt-get "${APT_OPTS[@]}" "$@"
}

# --- manifest / backup -----------------------------------------------------

manifest_add() {
    [[ "$DRY_RUN" == "1" ]] && return 0
    mkdir -p "$HB_STATE_DIR"
    chmod 700 "$HB_STATE_DIR"
    (umask 077 && printf '%s\n' "$*" >>"$HB_MANIFEST")
}

# backup_file PATH -> prints backup path (empty if no file); records MODIFIED in the manifest
backup_file() {
    local f="$1" b
    [[ -e "$f" || -L "$f" ]] || return 0
    b="${f}.hessenbot-${TS}"
    if [[ "$DRY_RUN" == "1" ]]; then
        _emit INFO "[dry-run] Backup $f -> $b"
        return 0
    fi
    [[ -e "$b" ]] || cp -a "$f" "$b"
    manifest_add "MODIFIED	$f	$b"
}

# write_file PATH MODE OWNER:GROUP < content ; creates a backup when content differs
write_file() {
    local path="$1" mode="${2:-644}" owner="${3:-root:root}" tmp
    tmp="$(mktemp)"
    cat >"$tmp"
    if [[ -f "$path" ]] && cmp -s "$tmp" "$path"; then
        rm -f "$tmp"
        log "Unveraendert: $path"
        return 0
    fi
    if [[ "$DRY_RUN" == "1" ]]; then
        _emit INFO "[dry-run] schreibe $path (mode $mode, $owner)"
        rm -f "$tmp"
        return 0
    fi
    if [[ -e "$path" ]]; then
        backup_file "$path"
    else
        manifest_add "CREATED	$path"
    fi
    mkdir -p "$(dirname "$path")"
    install -m "$mode" -o "${owner%%:*}" -g "${owner##*:}" "$tmp" "$path"
    rm -f "$tmp"
    log "Geschrieben: $path"
}

# --- state (answers; no secrets) ------------------------------------------

state_save() {
    [[ "$DRY_RUN" == "1" ]] && return 0
    mkdir -p "$HB_STATE_DIR"
    chmod 700 "$HB_STATE_DIR"
    local var
    (
        umask 077
        : >"$HB_STATE_FILE.tmp"
        for var in "$@"; do
            printf '%s=%q\n' "$var" "${!var-}" >>"$HB_STATE_FILE.tmp"
        done
        mv "$HB_STATE_FILE.tmp" "$HB_STATE_FILE"
    )
}

# state_get VAR: value of VAR from the saved state file (empty when absent); never touches the caller's variables
state_get() {
    [[ -f "$HB_STATE_FILE" ]] || return 0
    (
        # shellcheck source=/dev/null
        source "$HB_STATE_FILE" 2>/dev/null
        printf '%s' "${!1-}"
    )
}

# state_load: load saved answers. Variables already set (command-line flags) win, except
# PHASE_A_DONE which always comes from the state file.
state_load() {
    [[ -f "$HB_STATE_FILE" ]] || return 1
    local var line saved
    while IFS= read -r line; do
        var="${line%%=*}"
        [[ "$var" =~ ^[A-Z][A-Z0-9_]*$ ]] || continue
        saved="$(state_get "$var")"
        if [[ "$var" == "PHASE_A_DONE" || -z "${!var-}" ]]; then
            printf -v "$var" '%s' "$saved"
        fi
    done <"$HB_STATE_FILE"
    return 0
}

# --- cleanup of temporary secret files -------------------------------------

CLEANUP_FILES=()
cleanup_register() { CLEANUP_FILES+=("$1"); }
cleanup_exit() {
    local f
    for f in "${CLEANUP_FILES[@]+"${CLEANUP_FILES[@]}"}"; do
        [[ -e "$f" ]] && { shred -u "$f" 2>/dev/null || rm -f "$f"; }
    done
    return 0
}

# --- misc ------------------------------------------------------------------

have() { command -v "$1" >/dev/null 2>&1; }

wait_for_port() {
    local host="$1" port="$2" timeout="${3:-60}" i
    [[ "$DRY_RUN" == "1" ]] && return 0
    for ((i = 0; i < timeout; i++)); do
        if (exec 3<>"/dev/tcp/$host/$port") 2>/dev/null; then
            return 0
        fi
        sleep 1
    done
    return 1
}

version_ge() {
    [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" == "$2" ]]
}
