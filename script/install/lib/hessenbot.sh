#!/usr/bin/env bash
# Hessenbot installer: service user, venv (mandatory), config.ini from template via ini_set.py.
# shellcheck shell=bash disable=SC2034,SC2015,SC2153

HB_DIR="${HB_DIR:-/opt/Hessenbot}"
HB_VENV="${HB_VENV:-$HB_DIR/venv}"
HB_USER="${HB_USER:-meshbot}"

ensure_service_user() {
    if id "$HB_USER" >/dev/null 2>&1; then
        log "Benutzer $HB_USER existiert bereits."
    else
        run useradd --system --no-create-home --home-dir "$HB_DIR" --shell /usr/sbin/nologin --user-group "$HB_USER"
        manifest_add "USER	$HB_USER"
    fi
    # video: vcgencmd (Temperatur/Throttle) fuer Dashboard und sysEnv.sh
    if getent group video >/dev/null 2>&1 && ! id -nG "$HB_USER" 2>/dev/null | tr ' ' '\n' | grep -qx video; then
        run usermod -aG video "$HB_USER"
    fi
}

setup_venv() {
    CURRENT_PHASE="hessenbot"
    step "Hessenbot: Python-venv"
    [[ -f "$HB_DIR/requirements.txt" ]] || die "requirements.txt nicht in $HB_DIR gefunden."
    if [[ ! -x "$HB_VENV/bin/python" ]]; then
        run python3 -m venv "$HB_VENV"
        manifest_add "CREATED	$HB_VENV"
    else
        log "venv vorhanden: $HB_VENV"
    fi
    run_quiet "$HB_VENV/bin/pip" install --upgrade pip wheel
    run_quiet "$HB_VENV/bin/pip" install -r "$HB_DIR/requirements.txt"
    [[ "$DRY_RUN" == "1" ]] || log "Python-Pakete installiert."
}

setup_runtime_files() {
    run mkdir -p "$HB_DIR/data" "$HB_DIR/logs"
    if [[ "$DRY_RUN" == "1" ]]; then
        _emit INFO "[dry-run] cp -Rn etc/data/. data/; custom_scheduler.py aus Template"
        return 0
    fi
    cp -Rn "$HB_DIR/etc/data/." "$HB_DIR/data/"
    if [[ ! -f "$HB_DIR/modules/custom_scheduler.py" && -f "$HB_DIR/etc/custom_scheduler.template" ]]; then
        cp "$HB_DIR/etc/custom_scheduler.template" "$HB_DIR/modules/custom_scheduler.py"
        log "modules/custom_scheduler.py aus Template erzeugt."
    fi
}

ini() {
    python3 "$INSTALL_LIB_DIR/../ini_set.py" "$HB_DIR/config.ini" "$@"
}

setup_config_ini() {
    CURRENT_PHASE="hessenbot"
    step "Hessenbot: config.ini"
    local cfg="$HB_DIR/config.ini"
    if [[ -f "$cfg" ]]; then
        log "Bestehende config.ini gefunden."
        if confirm "config.ini behalten (Standard) und nur die Installer-Werte setzen?" y; then
            backup_file "$cfg"
        else
            backup_file "$cfg"
            if [[ "$DRY_RUN" != "1" ]]; then
                cp "$HB_DIR/config.template" "$cfg"
                log "config.ini aus config.template neu erzeugt (Backup vorhanden)."
            fi
        fi
    elif [[ "$DRY_RUN" == "1" ]]; then
        _emit INFO "[dry-run] cp config.template config.ini"
    else
        cp "$HB_DIR/config.template" "$cfg"
        manifest_add "CREATED	$cfg"
        log "config.ini aus config.template erzeugt."
    fi

    if [[ "$DRY_RUN" == "1" && ! -f "$cfg" ]]; then
        log "[dry-run] ini_set: interface.type=tcp, hostname=localhost, interface2.enabled=False, location lat/lon=${LAT}/${LON}, webAdmin enabled=$([[ "${WEB_ADMIN:-0}" == "1" ]] && echo True || echo False)"
        return 0
    fi
    local args=() a
    while IFS= read -r a; do args+=(--set "$a"); done < <(config_ini_assignments)
    ini "${args[@]}"
}

# config_ini_assignments: section.key=value lines the installer sets (webAdmin.host only when the admin is enabled)
config_ini_assignments() {
    printf '%s\n' "interface.type=tcp" "interface.hostname=localhost" "interface2.enabled=False" \
        "location.lat=${LAT}" "location.lon=${LON}"
    if [[ "${WEB_ADMIN:-0}" == "1" ]]; then
        printf '%s\n' "webAdmin.enabled=True" "webAdmin.host=${WEB_BIND:-0.0.0.0}"
    else
        printf '%s\n' "webAdmin.enabled=False"
    fi
}

# write_env_file: web admin secrets, 0600
write_env_file() {
    CURRENT_PHASE="env"
    [[ "${WEB_ADMIN:-0}" == "1" ]] || return 0
    local envf=/etc/hessenbot/env secret
    if [[ -z "${WEB_PASSWORD:-}" ]]; then
        if [[ -f "$envf" ]]; then
            log "$envf bleibt unveraendert."
            return 0
        fi
        die "Web-Admin-Passwort fehlt."
    fi
    secret="$(openssl rand -hex 32)"
    register_secret "$secret"
    write_file "$envf" 600 root:root <<EOF
HESSENBOT_WEB_PASSWORD=${WEB_PASSWORD}
HESSENBOT_WEB_SECRET=${secret}
EOF
    chmod 600 "$envf" 2>/dev/null || true
}

fix_permissions() {
    CURRENT_PHASE="permissions"
    if [[ "$DRY_RUN" == "1" ]]; then
        _emit INFO "[dry-run] etc/set-permissions.sh $HB_USER $HB_DIR"
        return 0
    fi
    bash "$HB_DIR/etc/set-permissions.sh" "$HB_USER" "$HB_DIR"
    git config --system --get-all safe.directory 2>/dev/null | grep -qx "$HB_DIR" || git config --system --add safe.directory "$HB_DIR" || true
}

setup_hessenbot() {
    ensure_service_user
    setup_venv
    setup_runtime_files
    setup_config_ini
}
