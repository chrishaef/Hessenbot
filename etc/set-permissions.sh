#!/bin/bash
# Set ownership and permissions for MeshBot / Hessenbot runtime files (data/, logs/, config.ini).
# Usage:
#   sudo ./etc/set-permissions.sh [user] [repo_path]
# Examples:
#   sudo ./etc/set-permissions.sh meshbot /opt/meshing-around
#   sudo ./etc/set-permissions.sh meshbot "$(pwd)"

set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (e.g. sudo $0)"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_USER="${1:-meshbot}"
REPO_ROOT="${2:-$(cd "$SCRIPT_DIR/.." && pwd)}"

if ! id "$TARGET_USER" >/dev/null 2>&1; then
  echo "User '$TARGET_USER' does not exist."
  CUR_USER="$(logname 2>/dev/null || whoami)"
  printf "Use current login user (%s) instead? [y/N]: " "$CUR_USER"
  read -r yn
  if [ "$yn" = "y" ] || [ "$yn" = "Y" ]; then
    TARGET_USER="$CUR_USER"
    if ! id "$TARGET_USER" >/dev/null 2>&1; then
      echo "User '$TARGET_USER' does not exist."
      exit 1
    fi
  else
    exit 1
  fi
fi

echo "Repository: $REPO_ROOT"
echo "Owner:      $TARGET_USER:$TARGET_USER"

for dir in "$REPO_ROOT/logs" "$REPO_ROOT/data"; do
  mkdir -p "$dir"
  chown -R "$TARGET_USER:$TARGET_USER" "$dir"
  chmod 775 "$dir"
  find "$dir" -type f -exec chmod 664 {} \;
  find "$dir" -type d -exec chmod 775 {} \;
done

if [ -f "$REPO_ROOT/config.ini" ]; then
  chown "$TARGET_USER:$TARGET_USER" "$REPO_ROOT/config.ini"
  chmod 664 "$REPO_ROOT/config.ini"
fi

echo "Permissions set for $TARGET_USER on data/, logs/, and config.ini (if present)."
