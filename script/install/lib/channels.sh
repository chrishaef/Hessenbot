#!/usr/bin/env bash
# Hessenbot installer: node channels (ShortSlow / Mesh Hessen / optional HessenTest), node spec, bot channel mapping.
# shellcheck shell=bash disable=SC2034,SC2015,SC2153

CHANNELS_DIR="${CHANNELS_DIR:-$INSTALL_LIB_DIR/../channels.d}"
CHAN_INDEX=()
CHAN_ROLE=()
CHAN_NAME=()
CHAN_PSK=()
CHAN_LABEL=()
CHAN_REQUIRED=()

load_channel_defs() {
    local f
    CHAN_INDEX=() CHAN_ROLE=() CHAN_NAME=() CHAN_PSK=() CHAN_LABEL=() CHAN_REQUIRED=()
    for f in "$CHANNELS_DIR"/*.conf; do
        [[ -f "$f" ]] || continue
        local line idx role name psk label req
        line="$(
            # shellcheck source=/dev/null
            source "$f" && printf '%s|%s|%s|%s|%s|%s' "$CH_INDEX" "$CH_ROLE" "$CH_NAME" "$CH_PSK_B64" "$CH_LABEL" "$CH_REQUIRED"
        )" || die "Kanaldefinition fehlerhaft: $f"
        IFS='|' read -r idx role name psk label req <<<"$line"
        [[ "$idx" =~ ^[0-7]$ ]] || die "Ungueltiger Kanalindex in $f"
        if [[ "$psk" != "default" ]]; then
            [[ "$psk" =~ ^[A-Za-z0-9+/]{43}=$ ]] || die "Ungueltiger PSK (Base64, 32 Byte) in $f"
            register_secret "$psk"
        fi
        [[ ${#name} -le 11 ]] || die "Kanalname zu lang in $f"
        CHAN_INDEX+=("$idx")
        CHAN_ROLE+=("$role")
        CHAN_NAME+=("$name")
        CHAN_PSK+=("$psk")
        CHAN_LABEL+=("$label")
        CHAN_REQUIRED+=("$req")
    done
    [[ ${#CHAN_INDEX[@]} -gt 0 ]] || die "Keine Kanaldefinitionen in $CHANNELS_DIR"
}

# channel_enabled I -> 0 if the channel is configured by this run
channel_enabled() {
    local i="$1"
    [[ "${CHAN_REQUIRED[$i]}" == "1" ]] && return 0
    [[ "${CHAN_INDEX[$i]}" == "2" && "${HESSENTEST:-off}" == "on" ]]
}

# enabled_channel_indices -> comma list (node indices configured by this run)
enabled_channel_indices() {
    local i out=()
    for i in "${!CHAN_INDEX[@]}"; do
        channel_enabled "$i" && out+=("${CHAN_INDEX[$i]}")
    done
    local IFS=,
    echo "${out[*]}"
}

# json_str VALUE -> JSON string literal (inputs are validated, still escape quotes/backslashes)
json_str() {
    local v="$1"
    v="${v//\\/\\\\}"
    v="${v//\"/\\\"}"
    printf '"%s"' "$v"
}

# write_node_spec FILE : 0600 JSON for node_config.py (contains PSKs)
write_node_spec() {
    local file="$1" i first=1 tx_enabled="false" tx_power=1
    if [[ "${ANTENNA_OK:-0}" == "1" ]]; then
        tx_enabled="true"
        tx_power="${TX_POWER:-1}"
    fi
    (
        umask 077
        {
            printf '{\n'
            if [[ -n "${LONG_NAME:-}" ]]; then
                printf '  "owner": {"long": %s, "short": %s},\n' "$(json_str "$LONG_NAME")" "$(json_str "${SHORT_NAME:-}")"
            fi
            printf '  "lora": {"region": %s, "modem_preset": %s, "tx_power": %s, "tx_enabled": %s},\n' \
                "$(json_str "$RADIO_REGION")" "$(json_str "$MODEM_PRESET")" "$tx_power" "$tx_enabled"
            printf '  "channels": [\n'
            for i in "${!CHAN_INDEX[@]}"; do
                [[ $first -eq 1 ]] || printf ',\n'
                first=0
                if channel_enabled "$i"; then
                    printf '    {"index": %s, "role": %s, "name": %s, "psk": %s}' \
                        "${CHAN_INDEX[$i]}" "$(json_str "${CHAN_ROLE[$i]}")" "$(json_str "${CHAN_NAME[$i]}")" "$(json_str "${CHAN_PSK[$i]}")"
                else
                    printf '    {"index": %s, "role": "DISABLED", "name": "", "psk": "default", "only_if_name": %s}' \
                        "${CHAN_INDEX[$i]}" "$(json_str "${CHAN_NAME[$i]}")"
                fi
            done
            printf '\n  ]\n}\n'
        } >"$file"
    )
}

node_cfg() {
    "$HB_VENV/bin/python" "$INSTALL_LIB_DIR/../node_config.py" "$@"
}

# configure_node: apply region/preset/owner/channels, TX gate
configure_node() {
    CURRENT_PHASE="node-config"
    step "Node-Konfiguration (Region, Preset, Kanaele)"
    if [[ "${SKIP_NODE_CONFIG:-0}" == "1" ]]; then
        log "--skip-node-config: ueberspringe."
        return 0
    fi
    if [[ "$DRY_RUN" == "1" ]]; then
        log "[dry-run] Node-Spec:"
        log "  Region ${RADIO_REGION}, Preset ${MODEM_PRESET}, tx_power $([[ "${ANTENNA_OK:-0}" == "1" ]] && echo "${TX_POWER:-?}" || echo 1) dBm, tx_enabled $([[ "${ANTENNA_OK:-0}" == "1" ]] && echo true || echo false)"
        local i
        for i in "${!CHAN_INDEX[@]}"; do
            channel_enabled "$i" && log "  Kanal #${CHAN_INDEX[$i]} ${CHAN_ROLE[$i]} '${CHAN_NAME[$i]:-<Preset>}' (PSK $([[ "${CHAN_PSK[$i]}" == "default" ]] && echo default || echo '***'))"
        done
        return 0
    fi

    local spec rc=0
    spec="$(mktemp /run/hessenbot-spec.XXXXXX)"
    cleanup_register "$spec"
    write_node_spec "$spec"

    log "Aktuelle Kanaele der Node:"
    node_cfg inspect "$spec" || rc=$?
    if [[ $rc -eq 10 ]]; then
        warn "Bestehende Kanaele weichen ab und wuerden ueberschrieben (siehe KONFLIKT oben)."
        confirm "Diese Kanaele ueberschreiben?" n || die "Abgebrochen; Kanaele unveraendert."
    elif [[ $rc -ne 0 ]]; then
        die "Node nicht erreichbar (meshtasticd laeuft? journalctl -u meshtasticd)."
    fi

    apply_node_spec "$spec"
    # Firmware forces tx_enabled=true when the region is set for the first time; a second pass applies tx_enabled=false.
    local try
    for ((try = 1; try <= "${VERIFY_ATTEMPTS:-5}"; try++)); do
        rc=0
        node_cfg verify "$spec" >/dev/null 2>&1 || rc=$?
        [[ $rc -eq 0 || $rc -eq 12 ]] && break
        sleep "${VERIFY_SLEEP:-5}"
    done
    if [[ $rc -eq 12 ]]; then
        log "Node hat TX nach dem ersten Setzen der Region aktiviert; setze TX-Gate erneut (zweiter Durchlauf) ..."
        apply_node_spec "$spec"
    fi
    verify_node_spec "$spec"
    NODE_GATE_VERIFIED=1
    state_save "${STATE_VARS[@]}"
    log "Node-Konfiguration verifiziert (Kanaele, Region, Preset, TX-Leistung, TX-Gate)."
}

# apply_node_spec SPEC: write the spec to the node, then wait for the meshtasticd restart that follows the commit
apply_node_spec() {
    local spec="$1"
    node_cfg apply "$spec" --force || warn "node_config apply meldete einen Fehler (Neustart der Node waehrend des Schreibens ist moeglich); pruefe Ergebnis."
    log "Warte auf meshtasticd-Neustart nach Config-Aenderung ..."
    wait_for_port_cycle localhost 4403 12 90 || die "meshtasticd nach Konfiguration nicht erreichbar (journalctl -u meshtasticd -n 50)."
}

# wait_for_port_cycle HOST PORT DOWN_SECS UP_SECS: meshtasticd restarts shortly after a config commit, so first wait
# (briefly) for the old process to drop the port, then for the new one to listen.
wait_for_port_cycle() {
    local host="$1" port="$2" down_secs="$3" up_secs="$4" i
    [[ "$DRY_RUN" == "1" ]] && return 0
    for ((i = 0; i < down_secs; i++)); do
        (exec 3<>"/dev/tcp/$host/$port") 2>/dev/null || break
        sleep 1
    done
    wait_for_port "$host" "$port" "$up_secs"
}

# verify_node_spec SPEC: node_config.py verify with retries (node may still be rebooting); a TX-gate violation is fatal.
verify_node_spec() {
    local spec="$1" attempt rc=1 max="${VERIFY_ATTEMPTS:-5}"
    for ((attempt = 1; attempt <= max; attempt++)); do
        rc=0
        node_cfg verify "$spec" || rc=$?
        [[ $rc -eq 0 ]] && return 0
        [[ $attempt -lt $max ]] && { log "Verifikation $attempt/$max: Abweichung/Fehler (Exit $rc), neuer Versuch ..."; sleep "${VERIFY_SLEEP:-5}"; }
    done
    if [[ $rc -eq 12 ]]; then
        warn "TX ist auf der Node AKTIV, obwohl keine Antenne bestaetigt wurde: stoppe meshtasticd."
        systemctl stop meshtasticd || warn "meshtasticd konnte nicht gestoppt werden: sofort 'sudo systemctl stop meshtasticd' ausfuehren!"
        die "TX war aktiv ohne bestaetigte Antenne; meshtasticd wurde gestoppt. Konfiguration pruefen (node_config.py info), dann den Assistenten erneut starten."
    fi
    die "Node-Konfiguration nicht wie erwartet uebernommen (Exit $rc, siehe ABWEICHUNG oben)."
}

# defined_channel_indices: every channel index this installer knows (enabled or not), comma list
defined_channel_indices() {
    local i out=()
    for i in "${!CHAN_INDEX[@]}"; do out+=("${CHAN_INDEX[$i]}"); done
    local IFS=,
    echo "${out[*]}"
}

# apply_bot_channels: map BOT_CHANNELS onto ignoreChannels/ignoreDefaultChannel/messagesChannel
apply_bot_channels() {
    CURRENT_PHASE="bot-channels"
    local cfg="$HB_DIR/config.ini" existing
    existing="$(defined_channel_indices)"
    log "Bot verarbeitet Kanaele: ${BOT_CHANNELS} (Installer-Kanaele: ${existing}; nicht gewaehlte werden ignoriert)"
    if [[ "$DRY_RUN" == "1" && ! -f "$cfg" ]]; then
        log "[dry-run] config.ini fehlt; Kanal-Mapping wuerde auf config.template angewendet."
        cfg="$HB_DIR/config.template"
        [[ -f "$cfg" ]] || return 0
        python3 "$INSTALL_LIB_DIR/../bot_channels.py" "$cfg" --selected "$BOT_CHANNELS" --existing "$existing" | sed 's/^/    /' >&2
        log "(keine Ausgabe = keine Aenderung an den Kanal-Keys noetig)"
        return 0
    fi
    run python3 "$INSTALL_LIB_DIR/../bot_channels.py" "$cfg" --selected "$BOT_CHANNELS" --existing "$existing" --apply
}
