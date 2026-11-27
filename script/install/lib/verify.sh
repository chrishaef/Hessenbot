#!/usr/bin/env bash
# Hessenbot installer: self-test and install_notes.txt (no secrets).
# shellcheck shell=bash disable=SC2034,SC2015,SC2153

VERIFY_FAILS=0
NODE_ID=""

_ok() { log "  [OK]   $*"; }
_bad() { warn "  [FAIL] $*"; VERIFY_FAILS=$((VERIFY_FAILS + 1)); }
_note() { log "  [WARN] $*"; }

# check_node_info INFO: validate `node_config.py info` output against the answers (region, TX gate)
check_node_info() {
    local info="$1" region tx
    region="$(sed -n 's/^region=//p' <<<"$info")"
    tx="$(sed -n 's/^tx_enabled=//p' <<<"$info")"
    if [[ "$region" == "$RADIO_REGION" ]]; then
        _ok "Region $region"
    else
        _bad "Region ist '$region', erwartet '$RADIO_REGION'"
    fi
    if [[ "${ANTENNA_OK:-0}" != "1" && "$tx" == "true" ]]; then
        _bad "TX-GATE: tx_enabled=true, obwohl keine Antenne bestaetigt wurde! Sofort: sudo systemctl stop meshtasticd"
    elif [[ "${ANTENNA_OK:-0}" != "1" ]]; then
        _ok "TX-Gate: tx_enabled=false (Antenne nicht bestaetigt)"
    fi
}

check_meshtasticd_groups() {
    id meshtasticd >/dev/null 2>&1 || return 0
    local g groups
    groups=" $(id -nG meshtasticd 2>/dev/null) "
    for g in spi gpio; do
        getent group "$g" >/dev/null 2>&1 || continue
        [[ "$groups" == *" $g "* ]] || _note "Benutzer meshtasticd ist nicht in Gruppe '$g' (SPI/GPIO-Zugriff pruefen, falls meshtasticd nicht startet)."
    done
}

selftest() {
    CURRENT_PHASE="verify"
    step "Selbsttest"
    if [[ "$DRY_RUN" == "1" ]]; then
        log "[dry-run] Selbsttest: spidev, meshtasticd, Port 4403, Node-ID, mesh_bot.service, Web-Admin, Unterspannung"
        return 0
    fi

    [[ -e /dev/spidev0.0 ]] && _ok "/dev/spidev0.0 vorhanden" || _bad "/dev/spidev0.0 fehlt (SPI aktiv? Neustart?)"

    if systemctl is-active --quiet meshtasticd.service; then
        _ok "meshtasticd.service aktiv"
    else
        _bad "meshtasticd.service nicht aktiv (journalctl -u meshtasticd -n 50)"
    fi

    if wait_for_port localhost 4403 20; then
        _ok "Port 4403 erreichbar"
        local info
        if info="$(node_cfg info 2>/dev/null)"; then
            NODE_ID="$(sed -n 's/^node_id=//p' <<<"$info")"
            [[ -n "$NODE_ID" ]] && _ok "Node-ID: $NODE_ID" || _bad "Node-ID leer"
            log "      $(sed -n 's/^region=/Region: /p;s/^modem_preset=/Preset: /p;s/^tx_power=/TX-Leistung: /p;s/^tx_enabled=/TX aktiv: /p' <<<"$info" | paste -sd' ' -)"
            check_node_info "$info"
        else
            _bad "Node-Info nicht lesbar"
        fi
    else
        _bad "Port 4403 nicht erreichbar"
    fi

    check_meshtasticd_groups

    sleep 8
    if systemctl is-active --quiet mesh_bot.service; then
        _ok "mesh_bot.service aktiv"
    else
        _bad "mesh_bot.service nicht aktiv (journalctl -u mesh_bot -n 50)"
    fi

    if [[ "${WEB_ADMIN:-0}" == "1" ]]; then
        local port
        port="$(ini --get webAdmin.port 2>/dev/null || echo 5000)"
        if curl -fsS --max-time 5 -o /dev/null "http://127.0.0.1:${port}/"; then
            _ok "Web-Admin antwortet auf Port $port"
        else
            _note "Web-Admin antwortet (noch) nicht auf Port $port"
        fi
    fi

    local flags
    flags="$(read_throttled)"
    if ((flags & 0x1)); then
        _note "Unterspannung aktiv: Netzteil pruefen."
    fi

    if [[ $VERIFY_FAILS -eq 0 ]]; then
        log "Selbsttest bestanden."
    else
        warn "$VERIFY_FAILS Pruefung(en) fehlgeschlagen. Log: $HB_LOG_FILE"
    fi
}

write_install_notes() {
    CURRENT_PHASE="notes"
    local notes="$HB_DIR/install_notes.txt" ip
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    if [[ "$DRY_RUN" == "1" ]]; then
        _emit INFO "[dry-run] schreibe $notes"
        return 0
    fi
    cat >"$notes" <<EOF
Hessenbot Pi 4 + RAK6421/RAK13302 (Slot 1) - Installationsnotizen ($TS)
Keine Geheimnisse in dieser Datei (Passwoerter: /etc/hessenbot/env, PSKs: script/install/channels.d).

Node-ID:        ${NODE_ID:-(siehe: $HB_VENV/bin/python $HB_DIR/script/install/node_config.py info)}
Region/Preset:  ${RADIO_REGION} / ${MODEM_PRESET}
Kanaele:        #0 ShortSlow (Primary), #1 Mesh Hessen$([[ "${HESSENTEST:-off}" == "on" ]] && echo ", #2 HessenTest")
Bot verarbeitet Kanaele: ${BOT_CHANNELS}
TX:             $([[ "${ANTENNA_OK:-0}" == "1" ]] && echo "aktiv, tx_power=${TX_POWER} dBm" || echo "AUS (Antenne nicht bestaetigt)")
Web-Admin:      $([[ "${WEB_ADMIN:-0}" == "1" ]] && echo "http://${ip:-<ip>}:$(ini --get webAdmin.port 2>/dev/null || echo 5000)/admin" || echo "aus")

Dienste:
  sudo systemctl status meshtasticd mesh_bot
  sudo journalctl -u meshtasticd -f
  sudo journalctl -u mesh_bot -f
  sudo systemctl restart meshtasticd && sudo systemctl restart mesh_bot

TX nach Antennenanschluss freigeben (nie ohne Antenne senden!):
  $HB_VENV/bin/meshtastic --host localhost --set lora.tx_enabled true

MQTT:     Zugang fuer MeshHessen mit dieser Node-ID im MQTT-Webadmin beantragen.

Update:   cd $HB_DIR && sudo ./update.sh
Revert:   sudo bash $HB_DIR/script/install/wizard.sh --revert
Backups:  $HB_BACKUP_DIR (Node-Identitaet/Keys: vor Neuinstallation sichern!)
Install-Log: $HB_LOG_FILE
EOF
    chmod 644 "$notes"
    log "Notizen: $notes"
}

print_summary_end() {
    step "Fertig"
    log "Node-ID:  ${NODE_ID:-unbekannt}"
    log "MQTT:     MeshHessen-MQTT-Zugang mit dieser Node-ID im MQTT-Webadmin beantragen."
    if [[ "${WEB_ADMIN:-0}" == "1" ]]; then
        log "Web-Admin: siehe $HB_DIR/install_notes.txt"
    fi
    if [[ "${ANTENNA_OK:-0}" != "1" ]]; then
        warn "TX ist AUS. Antenne anschliessen, dann: $HB_VENV/bin/meshtastic --host localhost --set lora.tx_enabled true"
    fi
    log "Logs: journalctl -u meshtasticd -u mesh_bot -f"
    log "73!"
}
