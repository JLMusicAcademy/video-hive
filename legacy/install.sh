#!/bin/bash
#
# QLab Media Player Installation Script
# For Raspberry Pi 5 (Raspberry Pi OS Bookworm or later)
#
# This script installs everything needed to run the QLab OSC media player
#

set -e  # Exit on any error

echo "=========================================="
echo "QLab Media Player - Installation Script"
echo "For Raspberry Pi 5"
echo "=========================================="
echo ""

# Check if running on Raspberry Pi
if [ ! -f /proc/device-tree/model ]; then
    echo "WARNING: This doesn't appear to be a Raspberry Pi"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "Step 1: Updating system packages..."
echo "--------------------"
sudo apt-get update
sudo apt-get upgrade -y

echo ""
echo "Step 2: Installing Python and dependencies..."
echo "--------------------"
sudo apt-get install -y python3 python3-pip python3-venv

echo ""
echo "Step 3: Installing VLC media player..."
echo "--------------------"
sudo apt-get install -y vlc

echo ""
echo "Step 4: Installing image processing tools..."
echo "--------------------"
sudo apt-get install -y imagemagick ffmpeg

echo ""
echo "Step 5: Installing X11 utilities..."
echo "--------------------"
sudo apt-get install -y x11-xserver-utils unclutter

echo ""
echo "Step 6: Installing Python packages..."
echo "--------------------"
# Install Python OSC library and requests
pip3 install python-osc requests --break-system-packages

echo ""
echo "Step 7: Setting up directories..."
echo "--------------------"
# Create QLab directory
QLAB_DIR="$HOME/QLab"
mkdir -p "$QLAB_DIR"

# Create media directory
MEDIA_DIR="$HOME/media"
mkdir -p "$MEDIA_DIR"

echo "  Created: $QLAB_DIR"
echo "  Created: $MEDIA_DIR"

echo ""
echo "Step 8: Installing QLab Media Player script..."
echo "--------------------"

# Check if script file exists in current directory
if [ -f "qlab_vlc_auto.py" ]; then
    cp qlab_vlc_auto.py "$QLAB_DIR/"
    chmod +x "$QLAB_DIR/qlab_vlc_auto.py"
    echo "  Installed: $QLAB_DIR/qlab_vlc_auto.py"
else
    echo "  WARNING: qlab_vlc_auto.py not found in current directory"
    echo "  You'll need to copy it manually to $QLAB_DIR/"
fi

echo ""
echo "Step 9: Configuring audio output..."
echo "--------------------"
echo "Setting HDMI as default audio output..."

# Set HDMI audio as default
sudo raspi-config nonint do_audio 2

echo ""
echo "Step 10: Configuring GPU memory..."
echo "--------------------"
echo "Setting GPU memory to 256MB for better video performance..."

# Set GPU memory (requires reboot)
if ! grep -q "gpu_mem=256" /boot/firmware/config.txt 2>/dev/null; then
    echo "gpu_mem=256" | sudo tee -a /boot/firmware/config.txt
fi

echo ""
echo "Step 11: Getting network information..."
echo "--------------------"
IP_ADDRESS=$(hostname -I | awk '{print $1}')
echo "  Your Raspberry Pi IP address: $IP_ADDRESS"
echo "  Use this IP address in QLab's Network Patch settings"

echo ""
echo "Step 12: Creating startup script..."
echo "--------------------"

cat > "$QLAB_DIR/start_qlab_player.sh" << 'EOF'
#!/bin/bash
# QLab Media Player Startup Script

# Set DISPLAY if not set
export DISPLAY=${DISPLAY:-:0}

# Disable screen blanking
xset s off 2>/dev/null
xset -dpms 2>/dev/null

# Hide cursor
unclutter -idle 0 &

# Start the QLab player
cd ~/QLab
python3 qlab_vlc_auto.py
EOF

chmod +x "$QLAB_DIR/start_qlab_player.sh"
echo "  Created: $QLAB_DIR/start_qlab_player.sh"

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "Next Steps:"
echo "1. Reboot your Raspberry Pi: sudo reboot"
echo "2. After reboot, place your media files in: $MEDIA_DIR"
echo "3. Start the player: $QLAB_DIR/start_qlab_player.sh"
echo "4. Configure QLab with IP address: $IP_ADDRESS"
echo ""
echo "Quick Test:"
echo "  cd $QLAB_DIR"
echo "  python3 qlab_vlc_auto.py"
echo ""
echo "For complete setup instructions, see INSTALLATION.md"
echo ""

read -p "Would you like to reboot now? (recommended) (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Rebooting..."
    sudo reboot
fi
