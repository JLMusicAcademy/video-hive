#!/usr/bin/env bash
#
# Video Hive -- run one display node per screen on a SINGLE machine
# (a Mac Mini, or any computer with several displays).
#
# Each display gets its own node.py process, pinned to one physical screen and
# registered with the hub on its own port. The hub treats them as separate nodes
# and assigns each to a grid cell -- exactly like separate Pis -- but because
# they all share one GPU and one system clock, playback stays far better synced
# than independent machines do.
#
# Usage:
#   ./run-mac-displays.sh <hub-host:port> [display-count]
#   ./run-mac-displays.sh localhost:5000 3      # 3 displays, hub on this Mac
#   ./run-mac-displays.sh stop                  # stop all nodes started here
#
# Requirements (macOS):  brew install mpv ffmpeg python ; pip3 install flask
#
# Env (optional):
#   BASE_PORT   first HTTP port (default 8001; displays use 8001, 8002, ...)
#   ID_PREFIX   node id prefix  (default "mac"; ids are mac-1, mac-2, ...)
#   ROTATION    0|90|180|270 applied to every screen (default 0)
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_PORT="${BASE_PORT:-8001}"
ID_PREFIX="${ID_PREFIX:-mac}"
ROTATION="${ROTATION:-0}"
RUN_DIR="$HOME/.videohive"
PID_FILE="$RUN_DIR/mac-nodes.pids"

mkdir -p "$RUN_DIR"

stop_nodes() {
    if [ -f "$PID_FILE" ]; then
        while read -r pid; do
            [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
        done < "$PID_FILE"
        rm -f "$PID_FILE"
        echo "Stopped Video Hive display nodes."
    else
        # Fallback: nothing tracked -- best effort.
        pkill -f "node.py --id ${ID_PREFIX}-" 2>/dev/null || true
        echo "No tracked PIDs; sent best-effort stop to ${ID_PREFIX}-* nodes."
    fi
}

if [ "${1:-}" = "stop" ]; then
    stop_nodes
    exit 0
fi

HUB="${1:-localhost:5000}"
COUNT="${2:-3}"
case "$HUB" in http*) ;; *) HUB="http://$HUB" ;; esac

command -v mpv  >/dev/null || { echo "ERROR: mpv not found. Run: brew install mpv"; exit 1; }
command -v python3 >/dev/null || { echo "ERROR: python3 not found."; exit 1; }

# Clear any previous run so we don't double-start.
stop_nodes 2>/dev/null || true
: > "$PID_FILE"

echo "Starting $COUNT display node(s), hub=$HUB"
for i in $(seq 0 $((COUNT - 1))); do
    n=$((i + 1))
    id="${ID_PREFIX}-${n}"
    port=$((BASE_PORT + i))
    python3 "$HERE/node.py" \
        --id "$id" --port "$port" --screen "$i" --rotation "$ROTATION" \
        --media-dir "$RUN_DIR/$id" --hub "$HUB" \
        >"$RUN_DIR/$id.log" 2>&1 &
    echo $! >> "$PID_FILE"
    echo "  $id -> screen $i, http://localhost:$port  (log: $RUN_DIR/$id.log)"
done

cat <<EOF

All nodes started. They self-register with the hub at $HUB.
In the hub UI, assign ${ID_PREFIX}-1 .. ${ID_PREFIX}-${COUNT} to your grid cells.

Logs : tail -f $RUN_DIR/${ID_PREFIX}-*.log
Stop : $0 stop
EOF
