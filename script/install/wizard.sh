#!/usr/bin/env bash
# Hessenbot installer wizard: Raspberry Pi 4 + RAK6421/RAK13302 (Slot 1, SPI), native only.
#
#   sudo bash script/install/wizard.sh [options]        (normally started by bootstrap.sh)
#
# Phases: preflight -> questions -> summary/confirm -> A (packages, SPI/I2C, reboot+resume)
#         -> B (meshtasticd, node config, Hessenbot venv/config, systemd) -> self-test.
# All prompts read from /dev/tty (curl | bash safe). Idempotent; re-run after any failure.

set -Eeuo pipefail

INSTALL_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib"
export INSTALL_LIB_DIR

# shellcheck source=lib/common.sh
source "$INSTALL_LIB_DIR/common.sh"
# shellcheck source=lib/detect.sh
source "$INSTALL_LIB_DIR/detect.sh"
# shellcheck source=lib/pi_boot.sh
source "$INSTALL_LIB_DIR/pi_boot.sh"
# shellcheck source=lib/meshtasticd.sh
source "$INSTALL_LIB_DIR/meshtasticd.sh"
# shellcheck source=lib/hessenbot.sh
source "$INSTALL_LIB_DIR/hessenbot.sh"
# shellcheck source=lib/channels.sh
source "$INSTALL_LIB_DIR/channels.sh"
# shellcheck source=lib/services.sh
source "$INSTALL_LIB_DIR/services.sh"
# shellcheck source=lib/questions.sh
source "$INSTALL_LIB_DIR/questions.sh"
# shellcheck source=lib/verify.sh
source "$INSTALL_LIB_DIR/verify.sh"
# shellcheck source=lib/revert.sh
source "$INSTALL_LIB_DIR/revert.sh"

# shellcheck source=radios.d/rak6421-13302-slot1.conf
source "$INSTALL_LIB_DIR/../radios.d/rak6421-13302-slot1.conf"

trap 'on_error $LINENO' ERR
trap cleanup_exit EXIT

REVERT=0
RESUME=0
NO_REBOOT=0
SKIP_MESHTASTICD=0
SKIP_NODE_CONFIG=0
PHASE_A_DONE=0

usage() {
    cat <<'EOF'
Hessenbot Installer (Raspberry Pi 4 + RAK6421/RAK13302 Slot 1, EU_868, nativ)

Optionen:
  --dry-run               Nur anzeigen, nichts aendern (kein Root noetig)
  --yes                   Defaults/Flags ohne Rueckfragen verwenden
  --non-interactive       Kein Terminal erwartet (impliziert fehlende Antworten = Defaults)
  --revert                Aenderungen laut Manifest zurueckbauen
  --no-reboot             Nach SPI-Aenderung nicht neu starten (Befehl nach Reboot erneut ausfuehren)
  --skip-meshtasticd      meshtasticd nicht installieren/konfigurieren
  --skip-node-config      Node (Region/Preset/Kanaele) nicht konfigurieren
  --meshtasticd-channel beta|alpha|daily   (Default: beta)
  --preset NAME           z. B. SHORT_SLOW (Default), LONG_FAST, MEDIUM_SLOW ...
  --long-name TEXT --short-name TEXT
  --hessentest on|off     Testkanal #2 (Default: off)
  --bot-channels LIST     Kanalindizes, die der Bot verarbeitet (Default: 1)
  --lat DEG --lon DEG     Standort
  --web-admin on|off      Passwort interaktiv (empfohlen). Nicht-interaktiv: Env HESSENBOT_WEB_PASSWORD
                          (kurz in ps/Shell-History sichtbar - nur auf vertrauenswuerdigen Systemen)
  --accept-tx-window      Kurzes Sendefenster ohne Antenne akzeptieren (Region-Erstsetzen, vorhandene Node-Prefs; fuer --yes)
  --confirm-hardware      RAK6421 + RAK13302 (Slot 1) ohne HAT-EEPROM-Treffer bestaetigen (fuer --yes)
  --antenna yes|no        Antenne bestaetigt (Default: no -> TX aus)
  --antenna-gain DBI      Antennengewinn (Default 3)
  -h, --help
EOF
}

need_value() { [[ $# -ge 2 && -n "${2:-}" ]] || die "Option $1 braucht einen Wert."; }

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run) DRY_RUN=1 ;;
            --yes | -y) ASSUME_YES=1 ;;
            --non-interactive) NONINTERACTIVE=1 ;;
            --revert) REVERT=1 ;;
            --resume) RESUME=1 ;;
            --no-reboot) NO_REBOOT=1 ;;
            --skip-meshtasticd) SKIP_MESHTASTICD=1 ;;
            --skip-node-config) SKIP_NODE_CONFIG=1 ;;
            --meshtasticd-channel) need_value "$@"; MESHTASTICD_CHANNEL="$2"; shift ;;
            --preset) need_value "$@"; MODEM_PRESET="${2^^}"; shift ;;
            --long-name) need_value "$@"; LONG_NAME="$2"; shift ;;
            --short-name) need_value "$@"; SHORT_NAME="$2"; shift ;;
            --hessentest) need_value "$@"; HESSENTEST="$2"; shift ;;
            --bot-channels) need_value "$@"; BOT_CHANNELS="$2"; shift ;;
            --lat) need_value "$@"; LAT="$2"; shift ;;
            --lon) need_value "$@"; LON="$2"; shift ;;
            --gps) need_value "$@"; [[ "$2" == "off" ]] || die "GPS/UART wird in dieser Version nicht eingerichtet (--gps off)."; shift ;;
            --confirm-hardware) HW_ACK=1 ;;
            --accept-tx-window) TX_WINDOW_ACK=1; EXISTING_NODE_ACK=1 ;;
            --web-admin) need_value "$@"; WEB_ADMIN="$2"; shift ;;
            --antenna) need_value "$@"; ANTENNA_OK="$2"; shift ;;
            --antenna-gain) need_value "$@"; ANTENNA_GAIN="$2"; shift ;;
            --install-dir) need_value "$@"; HB_DIR="$2"; HB_VENV="$2/venv"; shift ;;
            -h | --help) usage; exit 0 ;;
            *) die "Unbekannte Option: $1 (siehe --help)" ;;
        esac
        shift
    done
}

# phase_a: base packages, SPI/I2C, env file; returns after state is saved
phase_a() {
    install_base_packages
    configure_pi_boot
    write_env_file
    PHASE_A_DONE=1
    state_save "${STATE_VARS[@]}"
}

# on_error_hook RC LINE [MESSAGE]: leave a visible note for the next login (resume runs unattended)
on_error_hook() {
    [[ "$DRY_RUN" == "1" ]] && return 0
    [[ "${RESUME:-0}" == "1" || -f "$HB_STATE_DIR/resume.pending" ]] || return 0
    # One automatic retry per reboot cycle only: without the marker the unit's ConditionPathExists skips the next boot.
    [[ "${RESUME:-0}" == "1" ]] && rm -f "$HB_STATE_DIR/resume.pending"
    write_install_status "Hessenbot-Installation FEHLGESCHLAGEN in Phase '${CURRENT_PHASE}'.
Log:       $HB_LOG_FILE
Journal:   journalctl -u hessenbot-install-resume -n 100
Erneut:    sudo bash $HB_DIR/script/install/wizard.sh   (Antworten werden angeboten)
Der automatische Neustart-Fortsetzungsdienst startet nicht erneut von selbst."
}

finish_reboot() {
    step "Neustart erforderlich (SPI/I2C aktiviert)"
    install_resume_unit "$HB_DIR/script/install/wizard.sh"
    if [[ "$DRY_RUN" == "1" ]]; then
        log "[dry-run] Neustart waere erforderlich; Installation wuerde danach automatisch fortgesetzt."
        return 1
    fi
    write_install_status "Hessenbot-Installation laeuft nach dem Neustart weiter (Dienst hessenbot-install-resume).
Fortschritt: journalctl -u hessenbot-install-resume -f
Log:         $HB_LOG_FILE"
    log "Nach dem Neustart setzt sich die Installation automatisch fort."
    log "Fortschritt nach dem Login: journalctl -u hessenbot-install-resume -f   (Log: $HB_LOG_FILE)"
    if [[ "$NO_REBOOT" == "1" ]]; then
        log "Bitte neu starten: sudo reboot"
        exit 0
    fi
    if confirm "Jetzt neu starten?" y; then
        sync
        systemctl reboot
        exit 0
    fi
    log "Bitte spaeter neu starten (sudo reboot)."
    exit 0
}

phase_b() {
    CURRENT_PHASE="phase-b"
    if [[ "$SKIP_MESHTASTICD" == "1" ]]; then
        log "--skip-meshtasticd: meshtasticd wird nicht installiert/konfiguriert."
    else
        install_meshtasticd_package
        configure_meshtasticd
    fi
    setup_hessenbot
    configure_node
    apply_bot_channels
    fix_permissions
    install_hessenbot_services
    start_hessenbot
    selftest
    write_install_notes
    remove_resume_unit
    clear_install_status
    print_summary_end
}

# resolve_answers: sets REUSE (1 = answers come from the saved state). Declining reuse starts from a clean slate.
resolve_answers() {
    REUSE=0
    if [[ "$RESUME" == "1" ]]; then
        [[ -f "$HB_STATE_FILE" ]] || die "Kein gespeicherter Installationsstand ($HB_STATE_FILE)."
        REUSE=1
    elif [[ "$DRY_RUN" != "1" && -n "$(state_get MODEM_PRESET)" ]]; then
        if confirm "Gespeicherte Antworten einer frueheren Installation wiederverwenden?" y; then
            REUSE=1
        fi
    fi

    if [[ $REUSE -eq 1 ]]; then
        state_load
        [[ -n "$MODEM_PRESET" ]] || die "Gespeicherter Stand unvollstaendig; ohne --resume neu starten."
        ANTENNA_OK="${ANTENNA_OK:-0}"
        WEB_ADMIN="${WEB_ADMIN:-0}"
        if [[ -n "${ANTENNA_GAIN:-}" ]]; then
            TX_POWER="$(compute_tx_power "$ANTENNA_GAIN")"
        fi
        if [[ "$RESUME" != "1" ]]; then
            ask_antenna_risks
            state_save "${STATE_VARS[@]}"
        fi
    else
        PHASE_A_DONE=0
        ask_all
        state_save "${STATE_VARS[@]}"
    fi
    : "${MESHTASTICD_CHANNEL:=beta}"
}

main() {
    parse_args "$@"
    if [[ "$ASSUME_YES" == "1" && "$NONINTERACTIVE" != "1" ]] && ! { : </dev/tty; } 2>/dev/null; then
        NONINTERACTIVE=1
    fi
    log_init

    local repo_root
    repo_root="$(cd "$INSTALL_LIB_DIR/../../.." && pwd)"
    HB_VENV="$HB_DIR/venv"
    if [[ "$repo_root" != "$HB_DIR" ]]; then
        if [[ "$DRY_RUN" == "1" || "$REVERT" == "1" ]]; then
            [[ "$REVERT" == "1" ]] || warn "Checkout liegt in $repo_root (nicht $HB_DIR); dry-run liest von dort."
            [[ "$REVERT" == "1" ]] || { HB_DIR="$repo_root"; HB_VENV="$HB_DIR/venv"; }
        else
            die "Der Assistent muss aus $HB_DIR laufen (aktuell: $repo_root). Bitte bootstrap.sh verwenden oder --install-dir angeben."
        fi
    fi

    if [[ "$REVERT" == "1" ]]; then
        [[ "$DRY_RUN" == "1" || "${EUID:-$(id -u)}" -eq 0 ]] || die "Root-Rechte erforderlich."
        revert_install
        exit 0
    fi

    log "Hessenbot Installer (${HB_DIR}) - Pi 4 + RAK6421/RAK13302, nativ. Log: $HB_LOG_FILE"
    [[ "$DRY_RUN" == "1" ]] && log "*** DRY-RUN: es werden keine Aenderungen vorgenommen ***"

    preflight
    detect_hardware
    load_channel_defs

    resolve_answers
    print_summary
    if [[ $REUSE -eq 0 ]] && ! confirm "Mit diesen Einstellungen fortfahren?" y; then
        die "Abgebrochen. Es wurde nichts geaendert."
    fi

    if [[ "${PHASE_A_DONE:-0}" != "1" || "$DRY_RUN" == "1" ]]; then
        PHASE_A_DONE=0
        phase_a
        if [[ "$REBOOT_REQUIRED" == "1" ]]; then
            if finish_reboot; then return 0; fi
        fi
    else
        log "Phase A bereits abgeschlossen."
        if [[ ! -e /dev/spidev0.0 ]]; then
            warn "/dev/spidev0.0 fehlt weiterhin (SPI aktiv? Neustart ausstehend?). meshtasticd wird ohne SPI nicht starten."
        fi
    fi

    phase_b
    if [[ "$DRY_RUN" == "1" ]]; then
        log "*** DRY-RUN beendet: nichts wurde veraendert. Log: $HB_LOG_FILE ***"
    fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
