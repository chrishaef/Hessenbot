#!/usr/bin/env bash
# Hessenbot installer: wizard questions (all prompts via /dev/tty), validation, summary.
# shellcheck shell=bash disable=SC2034,SC2015,SC2153

MODEM_PRESET="${MODEM_PRESET:-}"
LONG_NAME="${LONG_NAME:-}"
SHORT_NAME="${SHORT_NAME:-}"
HESSENTEST="${HESSENTEST:-}"
BOT_CHANNELS="${BOT_CHANNELS:-}"
LAT="${LAT:-}"
LON="${LON:-}"
HAS_GPS="${HAS_GPS:-}"
WEB_ADMIN="${WEB_ADMIN:-}"
WEB_BIND="${WEB_BIND:-}"
WEB_PASSWORD="${WEB_PASSWORD:-${HESSENBOT_WEB_PASSWORD:-}}"
ANTENNA_OK="${ANTENNA_OK:-}"
ANTENNA_GAIN="${ANTENNA_GAIN:-}"
TX_POWER=""
EXISTING_NODE_ACK="${EXISTING_NODE_ACK:-}"
HW_ACK="${HW_ACK:-0}"

STATE_VARS=(MODEM_PRESET LONG_NAME SHORT_NAME HESSENTEST BOT_CHANNELS LAT LON HAS_GPS WEB_ADMIN WEB_BIND ANTENNA_OK ANTENNA_GAIN TX_POWER EXISTING_NODE_ACK MESHTASTICD_CHANNEL PHASE_A_DONE)

PRESET_KEYS=(SHORT_SLOW SHORT_FAST MEDIUM_SLOW MEDIUM_FAST LONG_MODERATE LONG_FAST LONG_SLOW)
PRESET_LABELS=("Europe Short Slow (Standard, Meshhessen)" "Short Fast" "Medium Slow" "Medium Fast" "Long Moderate" "Long Fast" "Long Slow")

is_number() { [[ "$1" =~ ^-?[0-9]+([.][0-9]+)?$ ]]; }

valid_preset() {
    local p
    for p in "${PRESET_KEYS[@]}"; do [[ "$p" == "$1" ]] && return 0; done
    return 1
}

ask_preset() {
    if [[ -n "$MODEM_PRESET" ]]; then
        valid_preset "$MODEM_PRESET" || die "Unbekanntes Modem-Preset: $MODEM_PRESET"
        return 0
    fi
    local i choice
    tty_print ""
    tty_print "Modem-Preset (Region ${RADIO_REGION}):"
    for i in "${!PRESET_KEYS[@]}"; do
        tty_print "  $((i + 1))) ${PRESET_LABELS[$i]}"
    done
    ask "Auswahl" "1"
    choice="$REPLY_VALUE"
    if [[ "$choice" =~ ^[1-7]$ ]]; then
        MODEM_PRESET="${PRESET_KEYS[$((choice - 1))]}"
    elif valid_preset "${choice^^}"; then
        MODEM_PRESET="${choice^^}"
    else
        die "Ungueltige Preset-Auswahl: $choice"
    fi
}

ask_names() {
    if [[ -z "$LONG_NAME" && "$ASSUME_YES" != "1" ]]; then
        tty_print ""
        ask "Long Name der Node (leer = Meshtastic-Standard unveraendert)" ""
        LONG_NAME="$REPLY_VALUE"
    fi
    if [[ -n "$LONG_NAME" ]]; then
        [[ ${#LONG_NAME} -le 39 ]] || die "Long Name max. 39 Zeichen."
        if [[ -z "$SHORT_NAME" ]]; then
            ask "Short Name (max. 4 Zeichen)" "${LONG_NAME:0:4}"
            SHORT_NAME="$REPLY_VALUE"
        fi
        [[ ${#SHORT_NAME} -ge 1 && ${#SHORT_NAME} -le 4 ]] || die "Short Name: 1-4 Zeichen."
    fi
}

ask_hessentest() {
    if [[ -z "$HESSENTEST" ]]; then
        tty_print ""
        if confirm "Optionalen Testkanal 'HessenTest' (#2) einrichten?" n; then HESSENTEST=on; else HESSENTEST=off; fi
    fi
    [[ "$HESSENTEST" == "on" || "$HESSENTEST" == "off" ]] || die "--hessentest erwartet on|off"
}

ask_bot_channels() {
    local avail i token ok
    avail="$(enabled_channel_indices)"
    if [[ -z "$BOT_CHANNELS" ]]; then
        tty_print ""
        tty_print "Auf welchen Kanaelen soll der Bot Befehle verarbeiten?"
        tty_print "Alle nicht gewaehlten Kanaele werden vom Bot ignoriert (Senden und Empfangen der Node selbst bleibt davon unberuehrt)."
        for i in "${!CHAN_INDEX[@]}"; do
            channel_enabled "$i" && tty_print "  #${CHAN_INDEX[$i]} ${CHAN_LABEL[$i]}"
        done
        ask "Kanalindizes, kommagetrennt (Vorauswahl: nur Mesh Hessen)" "1"
        BOT_CHANNELS="$REPLY_VALUE"
    fi
    BOT_CHANNELS="${BOT_CHANNELS// /}"
    [[ -n "$BOT_CHANNELS" ]] || die "Mindestens ein Bot-Kanal erforderlich."
    for token in ${BOT_CHANNELS//,/ }; do
        ok=0
        for i in ${avail//,/ }; do [[ "$i" == "$token" ]] && ok=1; done
        [[ $ok -eq 1 ]] || die "Kanal #$token ist nicht eingerichtet (verfuegbar: $avail)."
    done
}

ask_location() {
    local def_lat def_lon
    def_lat="$(python3 "$INSTALL_LIB_DIR/../ini_set.py" "$HB_DIR/config.template" --get location.lat 2>/dev/null || echo 50.4484)"
    def_lon="$(python3 "$INSTALL_LIB_DIR/../ini_set.py" "$HB_DIR/config.template" --get location.lon 2>/dev/null || echo 9.509)"
    if [[ -z "$LAT" || -z "$LON" ]]; then
        tty_print ""
        tty_print "Standort des Bots (manuell; kein IP-Geolocation-Aufruf). Wird fuer Wetter, Warnungen usw. genutzt."
        ask "Breitengrad (lat)" "$def_lat"
        LAT="$REPLY_VALUE"
        ask "Laengengrad (lon)" "$def_lon"
        LON="$REPLY_VALUE"
    fi
    is_number "$LAT" && is_number "$LON" || die "Ungueltige Koordinaten: $LAT / $LON"
    awk -v a="$LAT" -v o="$LON" 'BEGIN { exit !(a >= -90 && a <= 90 && o >= -180 && o <= 180) }' || die "Koordinaten ausserhalb des gueltigen Bereichs."
}

ask_gps() {
    HAS_GPS=0
}

valid_web_password() {
    local p="$1"
    [[ ${#p} -ge 10 ]] || return 1
    [[ "$p" != *[\"\'\\]* ]] || return 1
    [[ "$p" == "${p#"${p%%[![:space:]]*}"}" && "$p" == "${p%"${p##*[![:space:]]}"}" ]] || return 1
    [[ "$p" != *$'\n'* ]] || return 1
    return 0
}

ask_web_admin() {
    if [[ -z "$WEB_ADMIN" ]]; then
        tty_print ""
        if confirm "Web-Admin (Flask-Portal) aktivieren?" n; then WEB_ADMIN=1; else WEB_ADMIN=0; fi
    fi
    case "$WEB_ADMIN" in on | 1) WEB_ADMIN=1 ;; off | 0) WEB_ADMIN=0 ;; *) die "--web-admin erwartet on|off" ;; esac
    [[ "$WEB_ADMIN" == "1" ]] || return 0

    if [[ -z "$WEB_BIND" ]]; then
        if confirm "Web-Admin nur lokal (127.0.0.1) erreichbar machen? (Nein = im LAN offen)" n; then
            WEB_BIND=127.0.0.1
        else
            WEB_BIND=0.0.0.0
        fi
    fi
    if [[ -n "$WEB_PASSWORD" ]]; then
        register_secret "$WEB_PASSWORD"
        valid_web_password "$WEB_PASSWORD" || die "HESSENBOT_WEB_PASSWORD ungueltig (>=10 Zeichen, keine Anfuehrungszeichen/Backslash, keine fuehrenden/folgenden Leerzeichen)."
        return 0
    fi
    local p1 p2
    while true; do
        ask_secret "Admin-Passwort (mind. 10 Zeichen, keine Anfuehrungszeichen/Backslash)"
        p1="$REPLY_VALUE"
        if ! valid_web_password "$p1"; then
            warn "Passwort ungueltig (zu kurz oder unzulaessige Zeichen)."
            continue
        fi
        ask_secret "Passwort wiederholen"
        p2="$REPLY_VALUE"
        [[ "$p1" == "$p2" ]] && break
        warn "Passwoerter stimmen nicht ueberein."
    done
    WEB_PASSWORD="$p1"
}

ask_antenna() {
    tty_print ""
    tty_print "Der 1-W-Booster (SKY66122) darf NIE ohne Antenne senden. TX bleibt aus, bis die Antenne bestaetigt ist."
    if [[ -z "$ANTENNA_OK" ]]; then
        if confirm "Ist eine passende 868-MHz-Antenne an der RAK13302 angeschlossen?" n; then ANTENNA_OK=1; else ANTENNA_OK=0; fi
    fi
    case "$ANTENNA_OK" in yes | 1) ANTENNA_OK=1 ;; no | 0) ANTENNA_OK=0 ;; *) die "--antenna erwartet yes|no" ;; esac
    if [[ -z "$ANTENNA_GAIN" ]]; then
        if [[ "$ANTENNA_OK" == "1" ]]; then
            ask "Antennengewinn in dBi" "3"
            ANTENNA_GAIN="$REPLY_VALUE"
        else
            ANTENNA_GAIN=3
        fi
    fi
    is_number "$ANTENNA_GAIN" || die "Antennengewinn muss eine Zahl sein."
    TX_POWER="$(compute_tx_power "$ANTENNA_GAIN")"
    if [[ "$ANTENNA_OK" == "1" ]]; then
        log "tx_power = ${TX_POWER} dBm (${RADIO_TX_POWER_CAP} dBm Obergrenze minus ${ANTENNA_GAIN} dBi, abgerundet). EU_868: 10 % Duty Cycle beachten."
    fi
}

# compute_tx_power GAIN_DBI -> integer dBm, rounded down, clamped to 1..RADIO_TX_POWER_CAP
compute_tx_power() {
    awk -v cap="$RADIO_TX_POWER_CAP" -v g="$1" 'BEGIN { p = cap - g; p = (p == int(p)) ? p : (p > 0 ? int(p) : int(p) - 1); if (p < 1) p = 1; if (p > cap) p = cap; print p }'
}

# existing_node_prefs -> 0 when meshtasticd already has stored settings (it may transmit as soon as it starts)
existing_node_prefs() {
    local d
    for d in ${MESHTASTICD_STATE_DIRS:-/var/lib/meshtasticd /var/lib/meshtasticd-*}; do
        [[ -d "$d" ]] || continue
        [[ -n "$(find "$d" -name config.proto -size +0 -print -quit 2>/dev/null)" ]] && return 0
    done
    return 1
}

ask_existing_node() {
    [[ "$ANTENNA_OK" != "1" ]] || return 0
    [[ "${SKIP_MESHTASTICD:-0}" != "1" ]] || return 0
    existing_node_prefs || return 0
    if [[ "$EXISTING_NODE_ACK" == "1" ]]; then
        return 0
    fi
    tty_print ""
    warn "Es gibt bereits gespeicherte meshtasticd-Einstellungen (/var/lib/meshtasticd)."
    warn "Eine bereits konfigurierte Node kann sofort senden (NodeInfo), sobald meshtasticd startet - das TX-Gate greift erst danach."
    warn "Antenne zuerst an die RAK13302 anschliessen oder die Node-Prefs entfernen (Backup: /var/backups/hessenbot)."
    if confirm "meshtasticd trotzdem ohne bestaetigte Antenne starten?" n; then
        EXISTING_NODE_ACK=1
    else
        die "Abgebrochen. Antenne anschliessen und erneut starten (Antenne: ja), oder --skip-meshtasticd verwenden."
    fi
}

ask_all() {
    CURRENT_PHASE="questions"
    step "Abfragen"
    ask_preset
    ask_names
    ask_hessentest
    ask_bot_channels
    ask_location
    ask_gps
    ask_web_admin
    ask_antenna
    ask_existing_node
}

print_summary() {
    local i bot_has_default=0 token
    step "Zusammenfassung (es wurde noch nichts geaendert)"
    log "Hardware:        $RADIO_LABEL"
    log "Region/Preset:   ${RADIO_REGION} / ${MODEM_PRESET}"
    log "Node-Name:       ${LONG_NAME:-<unveraendert>}${SHORT_NAME:+ ($SHORT_NAME)}"
    for i in "${!CHAN_INDEX[@]}"; do
        channel_enabled "$i" && log "Kanal #${CHAN_INDEX[$i]}:       ${CHAN_ROLE[$i]} ${CHAN_LABEL[$i]}"
    done
    log "Bot-Kanaele:     ${BOT_CHANNELS} (Rest wird ignoriert)"
    for token in ${BOT_CHANNELS//,/ }; do [[ "$token" == "0" ]] && bot_has_default=1; done
    if [[ $bot_has_default -eq 1 ]]; then
        warn "Der Bot verarbeitet Kanal #0 (ShortSlow): ignoreDefaultChannel=False weicht vom Meshhessen-Standard ab."
    fi
    log "Standort:        ${LAT}, ${LON}"
    log "GPS/UART:        nicht Teil dieser Version (UART bleibt aus)"
    log "Web-Admin:       $([[ "$WEB_ADMIN" == "1" ]] && echo "ja, Bind ${WEB_BIND}, Passwort in /etc/hessenbot/env (0600)" || echo nein)"
    log "TX:              $([[ "$ANTENNA_OK" == "1" ]] && echo "an, ${TX_POWER} dBm" || echo "AUS bis Antenne bestaetigt")"
    log "meshtasticd:     OBS ${MESHTASTICD_CHANNEL} ($(obs_distro)), nativ per apt"
    log "config.ini:      $([[ -f "$HB_DIR/config.ini" ]] && echo "vorhanden (Backup), " || echo "neu aus config.template, ")setzt interface.type=tcp, interface.hostname=localhost, interface2.enabled=False,"
    log "                 location.lat/lon, webAdmin.enabled$([[ "$WEB_ADMIN" == "1" ]] && echo "/host"), Bot-Kanal-Keys (ignoreChannels, ignoreDefaultChannel, messagesChannel)"
    log "Aenderungen:     $(boot_config_path) (SPI/I2C), apt-Quelle+Schluessel, /etc/meshtasticd/config.d, /opt/Hessenbot (venv, config.ini),"
    log "                 Benutzer ${HB_USER}, /etc/systemd/system (mesh_bot, Reporting-Timer), /etc/hessenbot/env"
    log "Backups/Manifest: ${HB_BACKUP_DIR}, ${HB_MANIFEST} (Rueckbau: wizard.sh --revert)"
}
