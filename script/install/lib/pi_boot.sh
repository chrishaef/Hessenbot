#!/usr/bin/env bash
# Hessenbot installer: Raspberry Pi boot configuration (SPI / I2C / optional UART), idempotent with backup.
# shellcheck shell=bash disable=SC2034,SC2015,SC2153

HB_MARK_BEGIN="# >>> hessenbot (managed block, do not edit) >>>"
HB_MARK_END="# <<< hessenbot <<<"
REBOOT_REQUIRED=0

boot_config_path() {
    if [[ -f /boot/firmware/config.txt ]]; then
        echo /boot/firmware/config.txt
    elif [[ -f /boot/config.txt ]]; then
        echo /boot/config.txt
    else
        echo /boot/firmware/config.txt
    fi
}

boot_cmdline_path() {
    if [[ -f /boot/firmware/cmdline.txt ]]; then
        echo /boot/firmware/cmdline.txt
    else
        echo /boot/cmdline.txt
    fi
}

# desired_boot_block -> managed block content (without markers)
desired_boot_block() {
    printf '%s\n' "dtparam=spi=on" "dtoverlay=spi0-0cs" "dtparam=i2c_arm=on"
    if [[ "${HAS_GPS:-0}" == "1" ]]; then
        printf '%s\n' "enable_uart=1"
    fi
}

# render_boot_config CURRENT_FILE -> new file content on stdout (existing managed block replaced, else appended)
render_boot_config() {
    local current="$1"
    {
        if [[ -f "$current" ]]; then
            awk -v b="$HB_MARK_BEGIN" -v e="$HB_MARK_END" '
                $0 == b { skip = 1; next }
                $0 == e { skip = 0; next }
                !skip { print }
            ' "$current" | sed -e :a -e '/^\n*$/{$d;N;ba' -e '}'
        fi
        printf '\n%s\n[all]\n' "$HB_MARK_BEGIN"
        desired_boot_block
        printf '%s\n' "$HB_MARK_END"
    }
}

configure_pi_boot() {
    CURRENT_PHASE="phase-a"
    step "Phase A: SPI/I2C in config.txt"
    local cfg new
    cfg="$(boot_config_path)"
    if [[ "$DRY_RUN" == "1" && ! -f "$cfg" ]]; then
        log "[dry-run] $cfg nicht vorhanden; geplanter Block:"
        desired_boot_block | sed 's/^/    /' >&2
        REBOOT_REQUIRED=1
        return 0
    fi
    [[ -f "$cfg" ]] || die "$cfg nicht gefunden (kein Raspberry Pi OS?)"

    new="$(mktemp)"
    render_boot_config "$cfg" >"$new"
    if cmp -s "$new" "$cfg"; then
        log "config.txt enthaelt bereits den Hessenbot-Block."
    else
        log "Geplante Aenderung an $cfg:"
        diff -u "$cfg" "$new" | sed 's/^/    /' >&2 || true
        if [[ "$DRY_RUN" != "1" ]]; then
            backup_file "$cfg"
            cat "$new" >"$cfg"
        fi
        REBOOT_REQUIRED=1
    fi
    rm -f "$new"

    if [[ "${HAS_GPS:-0}" == "1" ]]; then
        disable_serial_console
    fi

    if [[ "$REBOOT_REQUIRED" == "0" && ! -e /dev/spidev0.0 && "$DRY_RUN" != "1" ]]; then
        warn "/dev/spidev0.0 fehlt trotz Konfiguration; ein Neustart ist noetig."
        REBOOT_REQUIRED=1
    fi
}

disable_serial_console() {
    local cl new
    cl="$(boot_cmdline_path)"
    [[ -f "$cl" ]] || return 0
    if ! grep -qE 'console=(serial0|ttyS0|ttyAMA0),[0-9]+' "$cl"; then
        return 0
    fi
    new="$(mktemp)"
    sed -E 's/ ?console=(serial0|ttyS0|ttyAMA0),[0-9]+//g' "$cl" >"$new"
    log "Serielle Konsole wird fuer GPS deaktiviert ($cl)."
    if [[ "$DRY_RUN" != "1" ]]; then
        backup_file "$cl"
        cat "$new" >"$cl"
    fi
    rm -f "$new"
    REBOOT_REQUIRED=1
}

install_resume_unit() {
    local script="$1"
    write_file /etc/systemd/system/hessenbot-install-resume.service 644 root:root <<EOF
[Unit]
Description=Hessenbot installer (resume after reboot)
After=network-online.target
Wants=network-online.target
ConditionPathExists=$HB_STATE_FILE

[Service]
Type=oneshot
ExecStart=/usr/bin/bash $script --resume --yes --non-interactive --no-reboot
TimeoutStartSec=3600
RemainAfterExit=no

[Install]
WantedBy=multi-user.target
EOF
    run systemctl daemon-reload
    run systemctl enable hessenbot-install-resume.service
    manifest_add "UNIT	hessenbot-install-resume.service"
}

remove_resume_unit() {
    if [[ -f /etc/systemd/system/hessenbot-install-resume.service ]] || [[ "$DRY_RUN" == "1" ]]; then
        run systemctl disable hessenbot-install-resume.service || true
        if [[ "$DRY_RUN" != "1" ]]; then
            rm -f /etc/systemd/system/hessenbot-install-resume.service
            systemctl daemon-reload || true
        fi
    fi
}
