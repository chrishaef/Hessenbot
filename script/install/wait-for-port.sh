#!/usr/bin/env bash
# Wait until HOST:PORT accepts TCP connections (used as ExecStartPre of mesh_bot.service).
# Always exits 0 after the timeout so the bot's own reconnect logic / Restart=on-failure takes over.
# Usage: wait-for-port.sh [host] [port] [timeout_seconds]
host="${1:-localhost}"
port="${2:-4403}"
timeout="${3:-60}"

for ((i = 0; i < timeout; i++)); do
    if (exec 3<>"/dev/tcp/$host/$port") 2>/dev/null; then
        exit 0
    fi
    sleep 1
done
echo "wait-for-port: $host:$port not reachable after ${timeout}s, starting anyway" >&2
exit 0
