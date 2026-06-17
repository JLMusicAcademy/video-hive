#!/usr/bin/env bash
#
# Video Hive -- display-node installer for Raspberry Pi.
#
# Turns a fresh Raspberry Pi into a video-wall display node that:
#   * boots into the desktop, auto-logs in, and autostarts the node there
#     (mpv draws on the desktop session's display -- the model that works on a Pi),
#   * restarts the node automatically if it crashes (respawning launcher),
#   * reboots the whole Pi if the kernel hangs (hardware watchdog),
#   * comes up ready -- pre-staged cues persist on disk across reboots.
#   Requires Raspberry Pi OS *with desktop*.
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
#   HUB             hub address so the node self-registers and you never type
#                   its IP -- e.g. hub.local:5000 (default: empty = no register)
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
HUB="${HUB:-}"
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
USER_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"

NODE_ID="${NODE_ID:-$(hostname)}"
case "$NODE_ROTATION" in 0|90|180|270) ;; *) die "NODE_ROTATION must be 0, 90, 180 or 270";; esac

say "Installing Video Hive node '$NODE_ID' (port $NODE_PORT, rotation $NODE_ROTATION, user $RUN_USER)"

# --------------------------------------------------------------------------- #
# 1. Packages
#    The node runs inside the Pi's desktop session; mpv draws on its X display.
#    mpv, imagemagick (black/identify images), python3-flask (HTTP server),
#    x11-xserver-utils (xset, to stop blanking), mesa DRI (GL), avahi (mDNS).
#    Requires Raspberry Pi OS *with desktop* (the desktop provides X/GL).
# --------------------------------------------------------------------------- #
say "Installing packages (this is the slow part)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    mpv imagemagick \
    python3 python3-flask \
    x11-xserver-utils libgl1-mesa-dri \
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

# Fail loudly now if we installed an out-of-date node.py, instead of leaving the
# service in a silent restart loop (old node.py rejects --gpu-context -> exit 2).
# Match the argparse *option*, not the old hard-coded mpv "--gpu-context=x11egl".
grep -q 'add_argument("--gpu-context"' "$INSTALL_DIR/node.py" || die \
"the installed node.py is out of date (no --gpu-context / DRM support). The copy
 on '$NODE_BRANCH' is behind. Fix by copying the current node.py next to this
 script and re-running, or set NODE_BRANCH=<feature-branch> / NODE_SRC=/path."

# --------------------------------------------------------------------------- #
# 3. Per-Pi config (the service reads this; edit + 'systemctl restart' to change)
# --------------------------------------------------------------------------- #
say "Writing $CONF"
cat > "$CONF" <<EOF
# Video Hive display node -- per-Pi settings. Edit, then reboot (or: pkill -f node.py)
NODE_ID=$NODE_ID
NODE_PORT=$NODE_PORT
NODE_ROTATION=$NODE_ROTATION
MEDIA_DIR=$MEDIA_DIR
HUB=$HUB
EOF

# --------------------------------------------------------------------------- #
# 4. Launcher -- runs the node inside the desktop session, mpv drawing on the
#    session's X display (x11egl), auto-restarting. Output -> journal (tag
#    'videowall-node'), so: journalctl -t videowall-node
# --------------------------------------------------------------------------- #
cat > "$INSTALL_DIR/start-node.sh" <<'EOF'
#!/usr/bin/env bash
set -uo pipefail
set -a; . /etc/videowall-node.conf; set +a
export DISPLAY="${DISPLAY:-:0}"
# Keep the desktop from blanking / powering down the screen.
xset s off -dpms s noblank 2>/dev/null || true
# Self-register with the hub if one was configured (so its IP is auto-learned).
HUB_ARG=()
if [ -n "${HUB:-}" ]; then
    case "$HUB" in http*) ;; *) HUB="http://$HUB" ;; esac
    HUB_ARG=(--hub "$HUB")
fi
while true; do
    python3 /opt/videowall/node.py \
        --id "$NODE_ID" --port "$NODE_PORT" \
        --rotation "$NODE_ROTATION" --media-dir "$MEDIA_DIR" \
        --gpu-context x11egl "${HUB_ARG[@]}" 2>&1 | systemd-cat -t videowall-node
    sleep 2
done
EOF
chmod 755 "$INSTALL_DIR/start-node.sh"
usermod -aG video,render,input "$RUN_USER" || true

# --------------------------------------------------------------------------- #
# 5. Run on boot: desktop autologin + autostart the node in that session.
#    mpv draws into the logged-in desktop's display -- the model that works on
#    a Pi (it doesn't fight the compositor for the screen).
# --------------------------------------------------------------------------- #
say "Configuring desktop autologin + autostart"

# Undo any earlier (broken) console/DRM kiosk this installer may have left.
systemctl disable --now videowall-node.service >/dev/null 2>&1 || true
rm -f "$SERVICE"
sed -i '/videowall/d' "$USER_HOME/.profile" 2>/dev/null || true
systemctl daemon-reload

# Boot straight to the desktop, auto-logged-in as the kiosk user.
systemctl set-default graphical.target >/dev/null 2>&1 || true
raspi-config nonint do_boot_behaviour B4 >/dev/null 2>&1 \
    || say "could not set desktop autologin via raspi-config -- set it manually (raspi-config > System > Boot > Desktop Autologin)"

# XDG autostart entry: launch the node when the desktop session starts.
AUTOSTART_DIR="$USER_HOME/.config/autostart"
install -d -o "$RUN_USER" -g "$RUN_USER" -m 755 "$AUTOSTART_DIR"
cat > "$AUTOSTART_DIR/videowall-node.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Video Hive Node
Exec=$INSTALL_DIR/start-node.sh
X-GNOME-Autostart-enabled=true
EOF
chown "$RUN_USER:$RUN_USER" "$AUTOSTART_DIR/videowall-node.desktop"

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

# Let the hub reboot this Pi remotely: passwordless reboot for the node user.
cat > /etc/sudoers.d/videowall-reboot <<EOF
$RUN_USER ALL=(root) NOPASSWD: /sbin/reboot, /usr/sbin/reboot, /sbin/shutdown, /usr/sbin/shutdown
EOF
chmod 440 /etc/sudoers.d/videowall-reboot

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
# 8. Done -- the node starts when the desktop session comes up (after reboot)
# --------------------------------------------------------------------------- #
IP="$(hostname -I | awk '{print $1}')"
cat <<EOF

============================================================
 Video Hive node '$NODE_ID' installed.
============================================================
 Reboot to start it:   sudo reboot
 After reboot the desktop auto-logs in, the node launches, and the
 TV shows black (idle) -- ready to receive cues.

 Reach it  : http://$IP:$NODE_PORT/status
             http://$NODE_ID.local:$NODE_PORT/status   (mDNS)
 Hub TV placement -> host $IP (or $NODE_ID.local), port $NODE_PORT

 Logs    : journalctl -t videowall-node -f
 Restart : pkill -f node.py            # the launcher respawns it
 Config  : sudo nano $CONF             # id/port/rotation, then reboot
============================================================
EOF
