#!/usr/bin/env bash
#
# Video Hive -- display-node installer for Raspberry Pi.
#
# Turns a fresh Raspberry Pi into a video-wall display node that:
#   * boots straight into the node when power is applied (no desktop, no login),
#   * restarts the node automatically if it crashes (systemd Restart=always),
#   * reboots the whole Pi if the kernel hangs (hardware watchdog),
#   * comes up fast and ready -- pre-staged cues persist on disk across reboots.
#
# Push it to a Pi and run it. That's the whole install:
#
#     scp install-node.sh admin@<pi-address>:~
#     ssh admin@<pi-address> 'sudo NODE_ID=tv00 NODE_ROTATION=0 bash install-node.sh'
#
# It fetches the node program (node.py) for you: it uses a node.py sitting next
# to this script if present, otherwise downloads it from GitHub. So you can copy
# just this one file, or copy this file + node.py together for an offline install.
#
# Per-Pi configuration (environment variables, all optional):
#   NODE_ID         unique name for this display      (default: the hostname)
#   NODE_PORT       HTTP port the hub talks to         (default: 8001)
#   NODE_ROTATION   0 | 90 | 180 | 270 for the mount   (default: 0)
#   RUN_USER        user the kiosk runs as             (default: the sudo user, or admin)
#   SET_HOSTNAME    1 = set the Pi's hostname to NODE_ID for <id>.local mDNS
#                   0 = leave hostname alone           (default: 1)
#   NODE_SRC        path to a local node.py to install (skips the download)
#   NODE_BRANCH     git branch to download node.py from (default: main)
#   REPO_RAW        raw repo base URL (default: this project's GitHub)
#
set -euo pipefail

# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
NODE_PORT="${NODE_PORT:-8001}"
NODE_ROTATION="${NODE_ROTATION:-0}"
SET_HOSTNAME="${SET_HOSTNAME:-1}"
NODE_BRANCH="${NODE_BRANCH:-main}"
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/JLMusicAcademy/video-hive}"
INSTALL_DIR=/opt/videowall
MEDIA_DIR=/var/lib/videowall
CONF=/etc/videowall-node.conf
SERVICE=/etc/systemd/system/videowall-node.service
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root, e.g.  sudo bash $0"

# Who the kiosk runs as (a normal user, not root -- X gets root rights via Xwrapper).
RUN_USER="${RUN_USER:-${SUDO_USER:-admin}}"
id "$RUN_USER" >/dev/null 2>&1 || die "user '$RUN_USER' does not exist (set RUN_USER=...)"

NODE_ID="${NODE_ID:-$(hostname)}"
case "$NODE_ROTATION" in 0|90|180|270) ;; *) die "NODE_ROTATION must be 0, 90, 180 or 270";; esac

say "Installing Video Hive node '$NODE_ID' (port $NODE_PORT, rotation $NODE_ROTATION, user $RUN_USER)"

# --------------------------------------------------------------------------- #
# 1. Packages
#    mpv + a minimal X server (mpv uses x11egl) + imagemagick (black/identify
#    images) + python3-flask (the node's HTTP server) + avahi (so the hub can
#    reach this Pi as <id>.local).
# --------------------------------------------------------------------------- #
say "Installing packages (this is the slow part)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    mpv imagemagick \
    python3 python3-flask \
    xserver-xorg xinit x11-xserver-utils \
    avahi-daemon ca-certificates curl

# --------------------------------------------------------------------------- #
# 2. Install the node program
# --------------------------------------------------------------------------- #
install -d -m 755 "$INSTALL_DIR"
install -d -o "$RUN_USER" -g "$RUN_USER" -m 755 "$MEDIA_DIR"

if [ -n "${NODE_SRC:-}" ]; then
    say "Using node.py from NODE_SRC=$NODE_SRC"
    install -m 755 "$NODE_SRC" "$INSTALL_DIR/node.py"
elif [ -f "$SCRIPT_DIR/node.py" ]; then
    say "Using node.py found next to this script"
    install -m 755 "$SCRIPT_DIR/node.py" "$INSTALL_DIR/node.py"
else
    URL="$REPO_RAW/$NODE_BRANCH/videowall/node/node.py"
    say "Downloading node.py from $URL"
    curl -fsSL "$URL" -o "$INSTALL_DIR/node.py" \
        || die "could not download node.py. Copy node.py next to this script, or set NODE_SRC=/path/to/node.py (private repo?)."
    chmod 755 "$INSTALL_DIR/node.py"
fi

# --------------------------------------------------------------------------- #
# 3. Per-Pi config (the service reads this; edit + 'systemctl restart' to change)
# --------------------------------------------------------------------------- #
say "Writing $CONF"
cat > "$CONF" <<EOF
# Video Hive display node -- per-Pi settings. Edit, then:
#   sudo systemctl restart videowall-node
NODE_ID=$NODE_ID
NODE_PORT=$NODE_PORT
NODE_ROTATION=$NODE_ROTATION
MEDIA_DIR=$MEDIA_DIR
EOF

# --------------------------------------------------------------------------- #
# 4. Launcher -- runs inside its own X (started by the service via xinit)
# --------------------------------------------------------------------------- #
cat > "$INSTALL_DIR/start-node.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
set -a; . /etc/videowall-node.conf; set +a
# Keep the screen awake forever.
xset s off -dpms s noblank 2>/dev/null || true
exec python3 /opt/videowall/node.py \
    --id "$NODE_ID" --port "$NODE_PORT" \
    --rotation "$NODE_ROTATION" --media-dir "$MEDIA_DIR"
EOF
chmod 755 "$INSTALL_DIR/start-node.sh"

# Let a normal user start the X server (it needs root rights for the GPU/KMS).
install -d -m 755 /etc/X11
cat > /etc/X11/Xwrapper.config <<EOF
allowed_users=anybody
needs_root_rights=yes
EOF
usermod -aG tty,video,render,input "$RUN_USER" || true

# --------------------------------------------------------------------------- #
# 5. systemd service -- auto-start on boot, restart on crash
# --------------------------------------------------------------------------- #
say "Installing systemd service"
cat > "$SERVICE" <<EOF
[Unit]
Description=Video Hive display node ($NODE_ID)
After=systemd-user-sessions.service network-online.target getty@tty1.service
Wants=network-online.target
Conflicts=getty@tty1.service

[Service]
User=$RUN_USER
PAMName=login
WorkingDirectory=$INSTALL_DIR
TTYPath=/dev/tty1
StandardInput=tty
StandardOutput=journal
StandardError=journal
TTYReset=yes
TTYVHangup=yes
# Own X server on vt1; start-node.sh launches the node inside it.
ExecStart=/usr/bin/xinit $INSTALL_DIR/start-node.sh -- :0 vt1 -nolisten tcp -nocursor
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

# Boot to console (not the desktop) so our kiosk owns the screen and boots fast.
systemctl set-default multi-user.target >/dev/null 2>&1 || true
systemctl daemon-reload
systemctl enable videowall-node.service >/dev/null 2>&1 || true

# --------------------------------------------------------------------------- #
# 6. Hardware watchdog -- reboot the Pi if the whole system hangs
# --------------------------------------------------------------------------- #
say "Enabling hardware watchdog"
install -d -m 755 /etc/systemd/system.conf.d
cat > /etc/systemd/system.conf.d/videowall-watchdog.conf <<EOF
[Manager]
RuntimeWatchdogSec=15
RebootWatchdogSec=2min
EOF

# --------------------------------------------------------------------------- #
# 7. Optional: name the Pi after the node, so the hub can use <id>.local
# --------------------------------------------------------------------------- #
if [ "$SET_HOSTNAME" = "1" ] && [ "$NODE_ID" != "$(hostname)" ]; then
    if [[ "$NODE_ID" =~ ^[a-zA-Z0-9-]+$ ]]; then
        say "Setting hostname to '$NODE_ID'"
        hostnamectl set-hostname "$NODE_ID" || true
        sed -i "s/127.0.1.1.*/127.0.1.1\t$NODE_ID/" /etc/hosts 2>/dev/null || \
            printf '127.0.1.1\t%s\n' "$NODE_ID" >> /etc/hosts
    else
        say "NODE_ID '$NODE_ID' isn't a valid hostname; leaving hostname unchanged"
    fi
fi

# --------------------------------------------------------------------------- #
# 8. Start it now
# --------------------------------------------------------------------------- #
say "Starting the node"
systemctl restart videowall-node.service || true
sleep 2
IP="$(hostname -I | awk '{print $1}')"
systemctl is-active --quiet videowall-node.service && STATUS="running" || STATUS="NOT running (check: journalctl -u videowall-node -b)"

cat <<EOF

============================================================
 Video Hive node installed.
============================================================
 Node id   : $NODE_ID
 Status    : $STATUS
 Reach it  : http://$IP:$NODE_PORT/status
             http://$NODE_ID.local:$NODE_PORT/status   (mDNS)
 In the hub's TV placement, map this display's grid cell to:
             host = $IP   (or $NODE_ID.local)   port = $NODE_PORT

 Manage:   sudo systemctl status  videowall-node
           sudo systemctl restart videowall-node
           journalctl -u videowall-node -b -f
           sudo nano $CONF   # change id/port/rotation, then restart

 A reboot is recommended to confirm clean auto-start:  sudo reboot
============================================================
EOF
