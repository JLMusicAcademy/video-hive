#!/usr/bin/env bash
#
# Video Hive -- hub installer for Raspberry Pi (or any Debian/Ubuntu box).
#
# Installs everything the hub needs and runs it as a production systemd
# service: starts on boot (so it comes back after a power outage), restarts if
# it crashes, and reboots the Pi if the whole system hangs (watchdog).
#
# The hub is a headless web/OSC server -- it has no screen to drive -- so it
# does NOT use a desktop or autologin (a systemd service is more robust: it
# starts with no login at all).
#
#   scp install-hub.sh admin@<hub-pi>:~
#   ssh admin@<hub-pi> 'sudo bash install-hub.sh'
#
# Env (all optional):
#   PORT          web UI / API port                 (default 5000)
#   RUN_USER      user to run the hub as            (default: the sudo user / admin)
#   HUB_HOSTNAME  set the Pi's hostname (e.g. video-hive-hub) for <name>.local
#   BRANCH        branch to run                     (default: claude/instant-fire)
#   REPO          git URL                           (default: this project on GitHub)
#   SRC           path to an existing clone to use  (skips cloning)
#
set -euo pipefail

PORT="${PORT:-5000}"
BRANCH="${BRANCH:-claude/instant-fire}"
REPO="${REPO:-https://github.com/JLMusicAcademy/video-hive.git}"
CLONE="${SRC:-/opt/video-hive}"
SERVICE=/etc/systemd/system/videowall-hub.service

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root, e.g.  sudo bash $0"
RUN_USER="${RUN_USER:-${SUDO_USER:-admin}}"
id "$RUN_USER" >/dev/null 2>&1 || die "user '$RUN_USER' does not exist (set RUN_USER=...)"

say "Installing the Video Hive hub (port $PORT, user $RUN_USER)"

# --------------------------------------------------------------------------- #
# 1. Packages: Python + ffmpeg (video tiling) + git + avahi (<host>.local)
# --------------------------------------------------------------------------- #
say "Installing packages (this is the slow part)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-dev \
    ffmpeg git curl ca-certificates avahi-daemon \
    libjpeg-dev zlib1g-dev

# --------------------------------------------------------------------------- #
# 2. Code: clone (or update) the repo, owned by the run user
# --------------------------------------------------------------------------- #
if [ -n "${SRC:-}" ]; then
    say "Using existing repo at $SRC"
elif [ -d "$CLONE/.git" ]; then
    say "Updating existing clone at $CLONE"
    git -C "$CLONE" fetch origin
    git -C "$CLONE" checkout -f "$BRANCH"
    git -C "$CLONE" reset --hard "origin/$BRANCH"   # leaves untracked store/ intact
else
    say "Cloning $REPO ($BRANCH) -> $CLONE"
    git clone -b "$BRANCH" "$REPO" "$CLONE"
fi
chown -R "$RUN_USER":"$RUN_USER" "$CLONE"

HUB_DIR="$CLONE/videowall/hub"
[ -f "$HUB_DIR/hub.py" ] || die "hub.py not found under $HUB_DIR (wrong BRANCH/REPO?)"

# --------------------------------------------------------------------------- #
# 3. Python venv + dependencies (Flask, Pillow, requests, python-osc, ...)
# --------------------------------------------------------------------------- #
say "Creating Python venv and installing requirements"
sudo -u "$RUN_USER" python3 -m venv "$CLONE/venv"
sudo -u "$RUN_USER" "$CLONE/venv/bin/pip" install --upgrade pip
sudo -u "$RUN_USER" "$CLONE/venv/bin/pip" install -r "$CLONE/videowall/requirements.txt"

# --------------------------------------------------------------------------- #
# 4. systemd service: boot on power, restart on crash
# --------------------------------------------------------------------------- #
say "Installing systemd service"
cat > "$SERVICE" <<EOF
[Unit]
Description=Video Hive hub
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
User=$RUN_USER
WorkingDirectory=$HUB_DIR
ExecStart=$CLONE/venv/bin/python $HUB_DIR/hub.py --config ../config/wall.example.json --port $PORT
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

# Enable the service (works whether the Pi boots to console or desktop --
# graphical boot includes multi-user.target, so the hub starts either way).
systemctl daemon-reload
systemctl enable videowall-hub.service >/dev/null 2>&1 || true

# --------------------------------------------------------------------------- #
# 5. Hardware watchdog -- reboot the Pi if the whole system hangs
# --------------------------------------------------------------------------- #
say "Enabling hardware watchdog"
install -d -m 755 /etc/systemd/system.conf.d
cat > /etc/systemd/system.conf.d/videowall-watchdog.conf <<EOF
[Manager]
RuntimeWatchdogSec=15
RebootWatchdogSec=2min
EOF

# Security-only automatic updates (low risk; full upgrades stay manual).
apt-get install -y unattended-upgrades >/dev/null 2>&1 || true
cat > /etc/apt/apt.conf.d/20auto-upgrades <<EOF
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

# --------------------------------------------------------------------------- #
# 6. Optional: name the hub so TVs (and you) can use <name>.local
# --------------------------------------------------------------------------- #
if [ -n "${HUB_HOSTNAME:-}" ]; then
    if [[ "$HUB_HOSTNAME" =~ ^[a-zA-Z0-9-]+$ ]]; then
        say "Setting hostname to '$HUB_HOSTNAME'"
        hostnamectl set-hostname "$HUB_HOSTNAME" || true
        sed -i "s/127.0.1.1.*/127.0.1.1\t$HUB_HOSTNAME/" /etc/hosts 2>/dev/null || \
            printf '127.0.1.1\t%s\n' "$HUB_HOSTNAME" >> /etc/hosts
    else
        say "HUB_HOSTNAME '$HUB_HOSTNAME' isn't a valid hostname; leaving it unchanged"
    fi
fi

# --------------------------------------------------------------------------- #
# 7. Start it
# --------------------------------------------------------------------------- #
say "Starting the hub"
systemctl restart videowall-hub.service || true
sleep 3
IP="$(hostname -I | awk '{print $1}')"
HOST="$(hostname)"
systemctl is-active --quiet videowall-hub.service && ST="running" || ST="NOT running (check: journalctl -u videowall-hub -b)"

cat <<EOF

============================================================
 Video Hive hub installed.
============================================================
 Status : $ST
 Open   : http://$IP:$PORT
          http://$HOST.local:$PORT     (mDNS)

 Point your nodes at this hub when you install them:
   sudo NODE_ID=tv01 HUB=$HOST.local:$PORT bash install-node.sh
   (or HUB=$IP:$PORT)

 Manage : sudo systemctl status  videowall-hub
          sudo systemctl restart videowall-hub
          journalctl -u videowall-hub -f
 Update : cd $CLONE && git pull && sudo systemctl restart videowall-hub
          (your workspaces/library in $HUB_DIR/store survive updates)

 A reboot is recommended to confirm clean auto-start:  sudo reboot
============================================================
EOF
