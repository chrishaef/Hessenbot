#!/usr/bin/env bash
# Hessenbot installer: systemd units (single source for mesh_bot.service) and reporting timer.
# Also sourced by etc/install_service.sh.
# shellcheck shell=bash disable=SC2034,SC2015,SC2153

# render_mesh_bot_unit USER GROUP PROJECT_PATH EXEC_START WAIT_FOR_MESHTASTICD(1|0) [HARDENING(1|0)]
render_mesh_bot_unit() {
    local user="$1" group="$2" path="$3" exec_start="$4" wait_meshtasticd="${5:-1}" hardening="${6:-1}"
    local after="network-online.target" wants="network-online.target" pre="" harden=""
    if [[ "$wait_meshtasticd" == "1" ]]; then
        after="network-online.target meshtasticd.service"
        wants="network-online.target meshtasticd.service"
        pre="ExecStartPre=/usr/bin/bash $path/script/install/wait-for-port.sh localhost 4403 60
TimeoutStartSec=120"
    fi
    if [[ "$hardening" == "1" ]]; then
        harden="NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=true"
    fi
    cat <<EOF
[Unit]
Description=MESH-BOT (Hessenbot)
After=$after
Wants=$wants

[Service]
Type=simple
User=$user
Group=$group
WorkingDirectory=$path
EnvironmentFile=-/etc/hessenbot/env
Environment=REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
Environment=SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
Environment=PYTHONUNBUFFERED=1
${pre}
ExecStart=$exec_start
KillSignal=SIGINT
Restart=on-failure
RestartSec=5
${harden}

[Install]
WantedBy=multi-user.target
EOF
}

render_reporting_units() {
    local user="$1" group="$2" path="$3" py="$4" out_dir="$5"
    cat >"$out_dir/mesh_bot_reporting.service" <<EOF
[Unit]
Description=Hessenbot reporting
After=network.target

[Service]
Type=oneshot
User=$user
Group=$group
WorkingDirectory=$path
ExecStart=$py etc/report_generator5.py
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=timers.target
EOF
    cat >"$out_dir/mesh_bot_reporting.timer" <<EOF
[Unit]
Description=Hessenbot reporting task

[Timer]
OnCalendar=*-*-* 04:20:00
Persistent=true
Unit=mesh_bot_reporting.service

[Install]
WantedBy=timers.target
EOF
}

install_hessenbot_services() {
    CURRENT_PHASE="services"
    step "systemd: mesh_bot.service + Reporting-Timer"
    render_mesh_bot_unit "$HB_USER" "$HB_USER" "$HB_DIR" "/usr/bin/bash $HB_DIR/launch.sh mesh" 1 1 |
        write_file /etc/systemd/system/mesh_bot.service 644 root:root

    local tmp
    tmp="$(mktemp -d)"
    render_reporting_units "$HB_USER" "$HB_USER" "$HB_DIR" "$HB_VENV/bin/python" "$tmp"
    write_file /etc/systemd/system/mesh_bot_reporting.service 644 root:root <"$tmp/mesh_bot_reporting.service"
    write_file /etc/systemd/system/mesh_bot_reporting.timer 644 root:root <"$tmp/mesh_bot_reporting.timer"
    rm -rf "$tmp"

    run systemctl daemon-reload
    run systemctl enable mesh_bot.service
    run systemctl enable --now mesh_bot_reporting.timer
    manifest_add "UNIT	mesh_bot.service"
    manifest_add "UNIT	mesh_bot_reporting.timer"
}

start_hessenbot() {
    run systemctl restart mesh_bot.service
}
