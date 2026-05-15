#!/bin/bash
# Update Hessenbot / meshing-around: stop systemd units, git pull, refresh venv deps, optional config merge, start units.
# Run from the repository root (same directory as this file). Use sudo if services run as root.
#
# Usage:
#   ./update.sh              full update
#   ./update.sh --no-merge skip script/configMerge.py

set -uo pipefail

cd "$(dirname "$0")"
REPO_ROOT=$(pwd)

DO_MERGE=1
for arg in "$@"; do
    if [[ "$arg" == "--no-merge" ]]; then
        DO_MERGE=0
    fi
done

if [[ ${EUID:-0} -eq 0 ]]; then
    SUDO=""
else
    SUDO="sudo"
fi
SC="${SUDO} systemctl"

# Match etc/*.service names used by install.sh
UNITS=(
    mesh_bot.service
    pong_bot.service
    mesh_bot_w3_server.service
    mesh_bot_reporting.timer
)

echo "=============================================="
echo "  Hessenbot / MeshBot — Update"
echo "=============================================="
echo "Repository: $REPO_ROOT"
echo

# --- Stop (best-effort; ignore if unit not installed) ---
echo "----------------------------------------------"
echo "Stopping systemd units (if present)..."
echo "----------------------------------------------"
for svc in "${UNITS[@]}"; do
    if $SUDO systemctl cat "$svc" &>/dev/null; then
        if $SC is-active --quiet "$svc" 2>/dev/null || $SC is-failed --quiet "$svc" 2>/dev/null; then
            echo ">> Stopping $svc"
            $SC stop "$svc" || true
        else
            echo "   (inactive) $svc"
        fi
    else
        echo "   (not installed) $svc — skip"
    fi
done
# Oneshot reporting service may still be running without the timer being "active"
if $SUDO systemctl cat mesh_bot_reporting.service &>/dev/null; then
    $SC stop mesh_bot_reporting.service 2>/dev/null || true
fi

echo
echo "----------------------------------------------"
echo "Git: pull latest"
echo "----------------------------------------------"
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "ERROR: Not a git repository."
    exit 1
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)
echo "Current branch: $BRANCH"

if ! git pull --ff-only; then
    echo "WARN: git pull --ff-only failed (e.g. diverged history). Trying merge pull..."
    git pull || {
        echo "ERROR: git pull failed. Resolve manually, then re-run update.sh."
        exit 1
    }
fi

echo
echo "----------------------------------------------"
echo "Python dependencies (venv)"
echo "----------------------------------------------"
if [[ -f "$REPO_ROOT/venv/bin/pip" ]]; then
    if ! (
        set -e
        # shellcheck source=/dev/null
        source "$REPO_ROOT/venv/bin/activate"
        pip install -U -r "$REPO_ROOT/requirements.txt"
    ); then
        echo "ERROR: pip install in venv failed."
        exit 1
    fi
    echo "pip install -r requirements.txt completed in venv."
else
    echo "No venv found at ./venv — skip pip (use install.sh or: python3 -m venv venv && ./venv/bin/pip install -r requirements.txt)."
fi

echo
echo "----------------------------------------------"
echo "Optional: custom scheduler module"
echo "----------------------------------------------"
if [[ ! -f modules/custom_scheduler.py ]] && [[ -f etc/custom_scheduler.template ]]; then
    cp -n etc/custom_scheduler.template modules/custom_scheduler.py && echo "Created modules/custom_scheduler.py from template (first time)."
fi

if [[ "$DO_MERGE" -eq 1 ]] && [[ -f script/configMerge.py ]]; then
    echo
    echo "----------------------------------------------"
    echo "Merging config (config.template → config_new.ini)"
    echo "----------------------------------------------"
    ( cd "$REPO_ROOT" && python3 script/configMerge.py > ini_merge_log.txt 2>&1 ) || true
    if grep -q "Error during configuration merge" ini_merge_log.txt 2>/dev/null; then
        echo "WARN: config merge reported errors — see ini_merge_log.txt"
    else
        echo "Config merge finished — review config_new.ini and ini_merge_log.txt if needed."
    fi
else
    echo "Skipping config merge (--no-merge or script missing)."
fi

echo
echo "----------------------------------------------"
echo "Runtime permissions (data/, logs/)"
echo "----------------------------------------------"
BOT_USER="meshbot"
for svc in mesh_bot.service pong_bot.service mesh_bot_w3_server.service; do
    if $SUDO systemctl cat "$svc" &>/dev/null; then
        u=$($SUDO systemctl show "$svc" -p User --value 2>/dev/null || true)
        if [[ -n "$u" && "$u" != "0" ]]; then
            BOT_USER="$u"
            break
        fi
    fi
done
if [[ -x "$REPO_ROOT/etc/set-permissions.sh" ]]; then
    $SUDO bash "$REPO_ROOT/etc/set-permissions.sh" "$BOT_USER" "$REPO_ROOT" || \
        echo "WARN: set-permissions.sh failed (user $BOT_USER)."
else
    echo "WARN: etc/set-permissions.sh not found — fix manually:"
    echo "  sudo chown -R $BOT_USER:$BOT_USER $REPO_ROOT/data $REPO_ROOT/logs"
fi

echo
echo "----------------------------------------------"
echo "Starting enabled units"
echo "----------------------------------------------"
for svc in "${UNITS[@]}"; do
    if $SUDO systemctl cat "$svc" &>/dev/null; then
        if $SC is-enabled --quiet "$svc" 2>/dev/null; then
            echo ">> Starting $svc"
            $SC start "$svc" || echo "WARN: start failed for $svc"
        else
            echo "   (disabled) $svc — not started"
        fi
    fi
done

echo
echo "=============================================="
echo "  Update finished."
echo "=============================================="
echo "Status examples:"
echo "  $SUDO systemctl status mesh_bot.service"
echo "  $SUDO journalctl -u mesh_bot.service -f"
exit 0
