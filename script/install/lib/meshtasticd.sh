#!/usr/bin/env bash
# Hessenbot installer: meshtasticd from the OBS repository (native apt), RAK6421/RAK13302 slot 1 preset.
# shellcheck shell=bash disable=SC2034,SC2015,SC2153

MESHTASTICD_CHANNEL="${MESHTASTICD_CHANNEL:-beta}"
RADIO_PROFILE="rak6421-13302-slot1"
RADIO_PRESET_FILE="lora-RAK6421-13302-slot1.yaml"
MESHTASTICD_ETC="${MESHTASTICD_ETC:-/etc/meshtasticd}"

install_base_packages() {
    CURRENT_PHASE="phase-a"
    step "Basispakete"
    export DEBIAN_FRONTEND=noninteractive
    run_quiet apt-get update
    run_quiet apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg git openssl \
        python3 python3-venv python3-dev build-essential libffi-dev
}

backup_node_identity() {
    local dirs=() d archive
    for d in /var/lib/meshtasticd /var/lib/meshtasticd-*; do
        [[ -d "$d" ]] && dirs+=("$d")
    done
    if [[ ${#dirs[@]} -eq 0 ]]; then
        log "Keine bestehende Node-Identitaet (/var/lib/meshtasticd) gefunden."
        return 0
    fi
    archive="$HB_BACKUP_DIR/meshtasticd-identity-$TS.tar.gz"
    log "Sichere Node-Identitaet (Keys/Prefs) nach $archive (0600)."
    if [[ "$DRY_RUN" == "1" ]]; then
        _emit INFO "[dry-run] tar czf $archive ${dirs[*]}"
        return 0
    fi
    mkdir -p "$HB_BACKUP_DIR"
    chmod 700 "$HB_BACKUP_DIR"
    (umask 077 && tar czf "$archive" "${dirs[@]}")
    manifest_add "BACKUP	$archive"
}

setup_meshtasticd_repo() {
    local distro url keyring list tmpkey
    distro="$(obs_distro)"
    url="https://download.opensuse.org/repositories/network:/Meshtastic:/${MESHTASTICD_CHANNEL}/${distro}/"
    keyring="/etc/apt/keyrings/meshtastic-${MESHTASTICD_CHANNEL}.gpg"
    list="/etc/apt/sources.list.d/meshtastic-${MESHTASTICD_CHANNEL}.sources"

    case "$MESHTASTICD_CHANNEL" in
        beta | alpha | daily) ;;
        *) die "Unbekannter meshtasticd-Kanal '$MESHTASTICD_CHANNEL' (beta|alpha|daily)." ;;
    esac

    log "meshtasticd-Quelle: $url"
    if ls /etc/apt/sources.list.d/*Meshtastic*.list >/dev/null 2>&1; then
        warn "Alte Meshtastic-.list-Quelle gefunden; bitte nach der Installation manuell entfernen, um Duplikate zu vermeiden."
    fi

    if [[ "$DRY_RUN" == "1" ]]; then
        _emit INFO "[dry-run] curl -fsSL ${url}Release.key | gpg --dearmor > $keyring"
    else
        mkdir -p /etc/apt/keyrings
        tmpkey="$(mktemp)"
        curl -fsSL --retry 3 "${url}Release.key" -o "$tmpkey.asc" || die "Release.key von OBS nicht ladbar."
        gpg --dearmor --yes -o "$tmpkey" "$tmpkey.asc"
        [[ -s "$tmpkey" ]] || die "Leerer OBS-Schluessel."
        if [[ ! -f "$keyring" ]]; then
            manifest_add "CREATED	$keyring"
        elif ! cmp -s "$tmpkey" "$keyring"; then
            backup_file "$keyring"
        fi
        install -m 644 "$tmpkey" "$keyring"
        rm -f "$tmpkey" "$tmpkey.asc"
    fi

    write_file "$list" 644 root:root <<EOF
Types: deb
URIs: $url
Suites: /
Signed-By: $keyring
EOF
}

install_meshtasticd_package() {
    CURRENT_PHASE="phase-b"
    step "meshtasticd (apt, OBS ${MESHTASTICD_CHANNEL})"
    backup_node_identity
    setup_meshtasticd_repo
    export DEBIAN_FRONTEND=noninteractive
    run_quiet apt-get update
    run_quiet apt-get install -y meshtasticd
    manifest_add "APT	meshtasticd"
}

# ensure_general_config: MACAddressSource under General (node id no longer MAC-based, but keep eth0 stable on Pi 4)
ensure_general_config() {
    local cfg="$MESHTASTICD_ETC/config.yaml" new
    [[ -f "$cfg" ]] || { log "$cfg nicht vorhanden (dry-run?)."; return 0; }
    if grep -qE '^[[:space:]]+MACAddress(Source)?:' "$cfg"; then
        log "config.yaml: MACAddress/MACAddressSource bereits gesetzt."
        return 0
    fi
    new="$(mktemp)"
    if grep -qE '^General:' "$cfg"; then
        awk '{ print } /^General:/ && !done { print "  MACAddressSource: eth0"; done = 1 }' "$cfg" >"$new"
    else
        { cat "$cfg"; printf 'General:\n  MACAddressSource: eth0\n'; } >"$new"
    fi
    log "config.yaml: setze General.MACAddressSource: eth0"
    if [[ "$DRY_RUN" != "1" ]]; then
        backup_file "$cfg"
        cat "$new" >"$cfg"
    fi
    rm -f "$new"
}

link_radio_preset() {
    local avail="$MESHTASTICD_ETC/available.d/$RADIO_PRESET_FILE"
    local confd="$MESHTASTICD_ETC/config.d" link f dest
    link="$confd/$RADIO_PRESET_FILE"

    if [[ ! -f "$avail" ]]; then
        if [[ "$DRY_RUN" == "1" ]]; then
            warn "[dry-run] $avail existiert (noch) nicht; waere nach der Paketinstallation erforderlich."
            return 0
        fi
        die "Preset $avail fehlt. Installierte meshtasticd-Version zu alt? (apt-cache policy meshtasticd)"
    fi

    run mkdir -p "$confd"
    if [[ -d "$confd" ]]; then
        for f in "$confd"/lora-*.yaml; do
            [[ -e "$f" || -L "$f" ]] || continue
            [[ "$(basename "$f")" == "$RADIO_PRESET_FILE" ]] && continue
            warn "Anderes LoRa-Profil in config.d: $(basename "$f") (es darf nur ein lora-*.yaml aktiv sein)."
            if confirm "Nach $HB_BACKUP_DIR verschieben?" y; then
                dest="$HB_BACKUP_DIR/config.d-$TS"
                if [[ "$DRY_RUN" != "1" ]]; then
                    mkdir -p "$dest"
                    mv "$f" "$dest/"
                    manifest_add "MOVED	$f	$dest/$(basename "$f")"
                else
                    _emit INFO "[dry-run] mv $f $dest/"
                fi
            else
                die "Konflikt mit bestehendem LoRa-Profil; manuell aufloesen."
            fi
        done
    fi

    if [[ -L "$link" && "$(readlink "$link")" == "$avail" ]]; then
        log "Preset bereits verlinkt: $link"
    else
        run ln -sfn "$avail" "$link"
        manifest_add "SYMLINK	$link"
    fi
}

start_meshtasticd() {
    run systemctl enable meshtasticd.service
    run systemctl restart meshtasticd.service
    manifest_add "UNIT	meshtasticd.service"
    [[ "$DRY_RUN" == "1" ]] && return 0
    if ! wait_for_port localhost 4403 90; then
        warn "meshtasticd antwortet nicht auf Port 4403. Log: journalctl -u meshtasticd -n 50"
        return 1
    fi
    log "meshtasticd lauscht auf 4403."
}

configure_meshtasticd() {
    CURRENT_PHASE="phase-b"
    step "meshtasticd: Radio-Profil ($RADIO_PROFILE)"
    ensure_general_config
    link_radio_preset
    start_meshtasticd || die "meshtasticd startet nicht (SPI/Preset pruefen: journalctl -u meshtasticd)."
}
