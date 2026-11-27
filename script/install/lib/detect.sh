#!/usr/bin/env bash
# Hessenbot installer: environment and hardware detection (read-only).
# shellcheck shell=bash disable=SC2034,SC2015,SC2153

OS_ID=""
OS_CODENAME=""
OS_ARCH=""
PI_MODEL=""
HAT_PRODUCT=""
HAT_VENDOR=""
PREFLIGHT_WARNINGS=0

_pf_fail() {
    # Hard failure on a real install, plain warning in dry-run (CI containers are not Pis).
    if [[ "$DRY_RUN" == "1" ]]; then
        warn "$* (dry-run: ignoriert)"
        PREFLIGHT_WARNINGS=$((PREFLIGHT_WARNINGS + 1))
    else
        die "$*"
    fi
}

_pf_warn() {
    warn "$*"
    PREFLIGHT_WARNINGS=$((PREFLIGHT_WARNINGS + 1))
}

read_dt_string() {
    local f="$1"
    [[ -r "$f" ]] || return 0
    tr -d '\0' <"$f" 2>/dev/null || true
}

detect_os() {
    if [[ -r /etc/os-release ]]; then
        # shellcheck source=/dev/null
        OS_ID="$(. /etc/os-release && printf '%s' "${ID:-}")"
        OS_CODENAME="$(. /etc/os-release && printf '%s' "${VERSION_CODENAME:-}")"
    fi
    OS_ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m)"
}

detect_pi() {
    PI_MODEL="$(read_dt_string /proc/device-tree/model)"
    HAT_PRODUCT="$(read_dt_string /proc/device-tree/hat/product)"
    HAT_VENDOR="$(read_dt_string /proc/device-tree/hat/vendor)"
}

# OBS distribution directory for the detected Debian release
obs_distro() {
    case "$OS_CODENAME" in
        trixie) echo "Debian_13" ;;
        bookworm) echo "Debian_12" ;;
        *) [[ "${DRY_RUN:-0}" == "1" ]] && echo "Debian_13" || echo "" ;;
    esac
}

check_internet() {
    [[ "$DRY_RUN" == "1" ]] && return 0
    curl -fsS --max-time 15 -o /dev/null -I https://download.opensuse.org/ 2>/dev/null
}

check_python() {
    local py ver
    py="$(command -v python3 || true)"
    if [[ -z "$py" ]]; then
        log "python3 nicht gefunden (wird installiert)."
        return 0
    fi
    ver="$("$py" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    log "Python: $ver"
    if ! version_ge "$ver" "3.11"; then
        _pf_fail "Python $ver ist zu alt (benoetigt >= 3.11, Trixie liefert 3.13)."
    elif [[ "$ver" != "3.13" ]]; then
        _pf_warn "Python $ver statt 3.13 (Ziel: Debian Trixie); sollte trotzdem funktionieren."
    fi
}

check_ntp() {
    have timedatectl || return 0
    local sync
    sync="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)"
    if [[ "$sync" != "yes" ]]; then
        _pf_warn "Systemzeit ist (noch) nicht per NTP synchronisiert; apt/TLS und der Bot brauchen eine korrekte Uhr."
    fi
}

# Returns throttled flags as integer (0 when vcgencmd is unavailable)
read_throttled() {
    have vcgencmd || { echo 0; return; }
    local raw
    raw="$(vcgencmd get_throttled 2>/dev/null | sed -n 's/^throttled=//p')"
    [[ -n "$raw" ]] && echo "$((raw))" || echo 0
}

check_power() {
    local flags
    flags="$(read_throttled)"
    if ((flags & 0x1)); then
        _pf_warn "Unterspannung JETZT erkannt (vcgencmd get_throttled). 1-W-TX braucht ein 5 V / 3 A Netzteil (USB-C)."
    elif ((flags & 0x10000)); then
        _pf_warn "Unterspannung seit dem Boot aufgetreten. Netzteil pruefen (5 V / 3 A empfohlen)."
    fi
}

check_disk_mem() {
    local free_mb mem_mb
    free_mb="$(df -Pm / | awk 'NR==2 {print $4}')"
    mem_mb="$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)"
    log "Freier Speicher auf /: ${free_mb} MB, RAM: ${mem_mb} MB"
    if [[ -n "$free_mb" ]] && ((free_mb < 1024)); then
        _pf_fail "Weniger als 1 GB frei auf / (${free_mb} MB)."
    fi
}

preflight() {
    CURRENT_PHASE="preflight"
    step "Preflight"
    if [[ "$DRY_RUN" != "1" && "${EUID:-$(id -u)}" -ne 0 ]]; then
        die "Root-Rechte erforderlich: mit sudo ausfuehren."
    fi

    detect_os
    detect_pi
    log "System: ${OS_ID:-?} ${OS_CODENAME:-?} (${OS_ARCH:-?})"
    log "Modell: ${PI_MODEL:-unbekannt}"

    case "$OS_CODENAME" in
        trixie) ;;
        bookworm) _pf_warn "Debian Bookworm wird unterstuetzt, Ziel ist Trixie (Debian 13)." ;;
        *) _pf_fail "Nicht unterstuetztes System '${OS_ID:-?}/${OS_CODENAME:-?}'. Benoetigt: Raspberry Pi OS (Debian Trixie, 64-bit)." ;;
    esac

    case "$OS_ARCH" in
        arm64) ;;
        armhf) _pf_fail "32-bit OS (armhf) erkannt. Bitte Raspberry Pi OS Lite 64-bit (arm64) verwenden." ;;
        *) _pf_fail "Architektur '$OS_ARCH' nicht unterstuetzt (benoetigt: arm64)." ;;
    esac

    if [[ "$PI_MODEL" != *"Raspberry Pi 4"* ]]; then
        _pf_warn "Raspberry Pi 4 nicht erkannt (Modell: '${PI_MODEL:-?}'). Getestet nur mit Pi 4B."
        if [[ "$DRY_RUN" != "1" ]] && ! confirm "Trotzdem fortfahren?" n; then
            die "Abgebrochen."
        fi
    fi

    if [[ -z "$(obs_distro)" ]]; then
        _pf_fail "Keine OBS-Paketquelle fuer '$OS_CODENAME' bekannt."
    fi
    if ! check_internet; then
        _pf_fail "Kein Zugriff auf download.opensuse.org (Internet/DNS pruefen)."
    fi

    check_disk_mem
    check_python
    check_ntp
    check_power
}

detect_hardware() {
    CURRENT_PHASE="hardware"
    step "Hardware"
    log "Festgelegt: RAK6421 HAT + RAK13302 (1 W) in Slot 1, SPI, Region EU_868."
    if [[ -n "$HAT_PRODUCT" ]]; then
        log "HAT-EEPROM: ${HAT_VENDOR:-?} / ${HAT_PRODUCT}"
    fi
    if [[ "$HAT_PRODUCT" == *"6421"* || "$HAT_PRODUCT" == *"RAK"* ]]; then
        log "RAK6421 per HAT-EEPROM erkannt."
        return 0
    fi
    log "Kein HAT-EEPROM-Treffer (das ist kein Fehler)."
    if [[ "$DRY_RUN" != "1" ]] && ! confirm "RAK6421 + RAK13302 in Slot 1 angenommen?" y; then
        die "Nur RAK6421 + RAK13302 (Slot 1) wird in dieser Version unterstuetzt."
    fi
}
