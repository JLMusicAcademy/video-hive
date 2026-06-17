# QLab Media Player for Raspberry Pi 5
## Complete Installation and Usage Guide

---

## Overview

This system allows you to control a Raspberry Pi's HDMI display from QLab using OSC (Open Sound Control) commands. Display images and play videos with full control over duration and looping - all managed from QLab's interface.

### Features

✅ **Display images fullscreen** (JPG, PNG, GIF, BMP, TIFF, WebP)  
✅ **Play videos with audio** (MP4, MOV, AVI, MKV, WebM)  
✅ **Automatic duration control** from QLab settings  
✅ **Loop support** for videos  
✅ **Black screen** between content (no desktop showing)  
✅ **VLC-based** for robust, reliable playback  
✅ **OSC Query support** - QLab automatically sends duration/loop settings  

### System Requirements

**Hardware:**
- Raspberry Pi 5 (or Pi 4)
- HDMI display
- Network connection (WiFi or Ethernet)
- Official Raspberry Pi power supply (27W for Pi 5)
- microSD card (32GB+ recommended)

**Software:**
- Raspberry Pi OS (Bookworm or later)
- QLab 4 or 5 (on your Mac)

---

## Installation

### Quick Installation (Recommended)

1. **Download files to Raspberry Pi:**
   ```bash
   cd ~
   mkdir QLab-install
   cd QLab-install
   # Copy install.sh and qlab_vlc_auto.py to this directory
   ```

2. **Make installation script executable:**
   ```bash
   chmod +x install.sh
   ```

3. **Run installation script:**
   ```bash
   ./install.sh
   ```

4. **Reboot when prompted:**
   ```bash
   sudo reboot
   ```

**The installer does everything automatically!**

---

### Manual Installation

If you prefer to install manually or the automatic installer doesn't work:

#### 1. Update System

```bash
sudo apt-get update
sudo apt-get upgrade -y
```

#### 2. Install Required Packages

```bash
# Python and pip
sudo apt-get install -y python3 python3-pip

# VLC media player
sudo apt-get install -y vlc

# Image processing tools
sudo apt-get install -y imagemagick ffmpeg

# X11 utilities
sudo apt-get install -y x11-xserver-utils unclutter
```

#### 3. Install Python Packages

```bash
pip3 install python-osc --break-system-packages
```

#### 4. Create Directories

```bash
mkdir -p ~/QLab
mkdir -p ~/media
```

#### 5. Copy Script

```bash
# Copy qlab_vlc_auto.py to ~/QLab/
cp qlab_vlc_auto.py ~/QLab/
chmod +x ~/QLab/qlab_vlc_auto.py
```

#### 6. Configure Audio Output

```bash
# Set HDMI as default audio
sudo raspi-config nonint do_audio 2
```

#### 7. Configure GPU Memory

```bash
# Add to /boot/firmware/config.txt
echo "gpu_mem=256" | sudo tee -a /boot/firmware/config.txt
```

#### 8. Reboot

```bash
sudo reboot
```

---

## Network Setup

### Find Your Raspberry Pi's IP Address

After installation and reboot:

```bash
hostname -I
```

Example output: `192.168.1.100`

**Write this down - you'll need it for QLab!**

### Configure Static IP (Optional but Recommended)

To prevent the IP address from changing:

1. **Edit dhcpcd.conf:**
   ```bash
   sudo nano /etc/dhcpcd.conf
   ```

2. **Add at the end:**
   ```
   interface eth0
   static ip_address=192.168.1.100/24
   static routers=192.168.1.1
   static domain_name_servers=192.168.1.1 8.8.8.8
   ```
   (Adjust IP addresses to match your network)

3. **Save and reboot:**
   ```bash
   sudo reboot
   ```

---

## QLab Setup

### 1. Create Network Patch

1. **Open QLab**
2. **Go to:** Settings → Network
3. **Click:** + (to add new patch)
4. **Configure:**
   - **Name:** Raspberry Pi
   - **Type:** OSC
   - **Network:** (select your network)
   - **Destination:** [Raspberry Pi IP address]
   - **Port:** 53000
   - **Protocol:** UDP
   - **Passcode:** (leave blank)

5. **Click:** OK

### 2. Create Network Cue (Basic)

1. **Create new cue:** Network Cue
2. **Settings tab:**
   - **Destination:** Raspberry Pi (the patch you just created)
   - **Type:** OSC message
   - **Message:** `/image test.jpg`

3. **Test it!**

### 3. Create Network Cue (With Auto-Duration)

**This is the recommended method!**

1. **Create new cue:** Network Cue
2. **Basics tab:**
   - **Duration:** 5.00s (or your desired time)
3. **Settings tab:**
   - **Destination:** Raspberry Pi
   - **Type:** OSC message
   - **Message:** `/image #/cue/selected/duration# yourfile.jpg`

**QLab will automatically send the duration when the cue fires!**

---

## Usage

### Starting the Media Player

1. **On Raspberry Pi, open terminal:**
   ```bash
   cd ~/QLab
   ./start_qlab_player.sh
   ```

2. **You should see:**
   ```
   QLab Media Player - VLC with OSC Query Support
   DISPLAY: :0
   Media directory: /home/admin/media
   ======================================================================
   Black screen
   OSC Server listening on port 53000
   
   Ready!
   ```

### Adding Media Files

**Copy your media to the media directory:**

```bash
# From another computer via network:
scp yourfile.jpg pi@192.168.1.100:~/media/

# Or use a USB drive on the Pi:
cp /media/usb/yourfile.jpg ~/media/

# Or via SFTP/file browser
```

### OSC Commands

#### Images

**Basic (indefinite):**
```
/image filename.jpg
```

**With duration (manual):**
```
/image 5.0 filename.jpg
```

**With auto-duration (recommended):**
```
/image #/cue/selected/duration# filename.jpg
```
Set duration in QLab's Duration field!

#### Videos

**Basic (play to completion):**
```
/video filename.mp4
```

**With duration limit:**
```
/video 30.0 0 filename.mp4
```
(Plays for 30 seconds, no loop)

**With auto-duration and loop:**
```
/video #/cue/selected/duration# #/cue/selected/infiniteLoop# filename.mp4
```
Set duration and check Loop in QLab!

#### Control Commands

**Stop playback:**
```
/stop
```

**Clear to black screen:**
```
/clear
```

---

## QLab Cue Templates

### Image Slideshow Template

**Cue 1:**
```
Type: Network Cue
Message: /image #/cue/selected/duration# slide1.jpg
Duration: 5.00s
Continue: Auto-continue
Post-wait: 5.00s
```

**Duplicate and modify** for each slide!

### Video Playback Template

**For full video:**
```
Type: Network Cue
Message: /video #/cue/selected/duration# #/cue/selected/infiniteLoop# intro.mp4
Continue: Auto-follow
```

**For video excerpt:**
```
Type: Network Cue
Message: /video #/cue/selected/duration# #/cue/selected/infiniteLoop# clip.mp4
Duration: 30.00s
Continue: Auto-follow
```

### Looping Video Template

```
Type: Network Cue
Message: /video #/cue/selected/duration# #/cue/selected/infiniteLoop# background.mp4
Time & Loops: ☑ Loop checked
Continue: Do not continue
```

---

## File Organization

### Recommended Directory Structure

```
~/media/
├── images/
│   ├── slides/
│   │   ├── slide1.jpg
│   │   ├── slide2.jpg
│   │   └── slide3.jpg
│   └── logos/
│       └── logo.png
└── videos/
    ├── intros/
    │   └── intro.mp4
    └── backgrounds/
        └── loop.mp4
```

### Using Subdirectories

**In QLab OSC messages, include the path:**

```
/image images/slides/slide1.jpg
/video videos/intros/intro.mp4
```

---

## Troubleshooting

### Media Player Won't Start

**Check Python installation:**
```bash
python3 --version
```
Should show Python 3.9 or later.

**Check python-osc installed:**
```bash
pip3 list | grep osc
```
Should show `python-osc`.

**Check DISPLAY variable:**
```bash
echo $DISPLAY
```
Should show `:0` or `:0.0`.

**If not set:**
```bash
export DISPLAY=:0
```

### No Audio

**Check audio output:**
```bash
sudo raspi-config
```
Select: System Options → Audio → HDMI

**Test audio:**
```bash
speaker-test -t wav -c 2
```

### Video Plays But No Picture

**Check DISPLAY:**
```bash
echo $DISPLAY
```

**Run from desktop terminal** (not SSH) or set DISPLAY:
```bash
export DISPLAY=:0
./start_qlab_player.sh
```

### Desktop Shows After Video

The script should automatically show black screen. If desktop appears:

**Check script is running:**
```bash
ps aux | grep qlab
```

**Restart the script:**
```bash
pkill -9 python3
cd ~/QLab
./start_qlab_player.sh
```

### QLab Can't Connect

**Check IP address:**
```bash
hostname -I
```

**Check firewall (usually not needed on Pi):**
```bash
sudo ufw status
```

**Ping Raspberry Pi from Mac:**
```bash
ping 192.168.1.100
```

**Test OSC manually:**
```bash
# On Mac (install oscsend if needed: brew install liblo)
oscsend 192.168.1.100 53000 /clear
```

### Image/Video Not Found

**Check file exists:**
```bash
ls -la ~/media/yourfile.jpg
```

**Check filename** - case sensitive! `File.jpg` ≠ `file.jpg`

**Check permissions:**
```bash
chmod 644 ~/media/*.jpg
chmod 644 ~/media/*.mp4
```

---

## Auto-Start on Boot (Optional)

To start the media player automatically when Pi boots:

### Method 1: Desktop Autostart

1. **Create autostart file:**
   ```bash
   mkdir -p ~/.config/autostart
   nano ~/.config/autostart/qlab.desktop
   ```

2. **Add content:**
   ```ini
   [Desktop Entry]
   Type=Application
   Name=QLab Media Player
   Exec=/home/admin/QLab/start_qlab_player.sh
   X-GNOME-Autostart-enabled=true
   ```

3. **Save and reboot**

### Method 2: systemd Service

1. **Create service file:**
   ```bash
   sudo nano /etc/systemd/system/qlab-player.service
   ```

2. **Add content:**
   ```ini
   [Unit]
   Description=QLab Media Player
   After=graphical.target
   
   [Service]
   Type=simple
   User=admin
   Environment="DISPLAY=:0"
   WorkingDirectory=/home/admin/QLab
   ExecStart=/usr/bin/python3 /home/admin/QLab/qlab_vlc_auto.py
   Restart=always
   
   [Install]
   WantedBy=graphical.target
   ```

3. **Enable and start:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable qlab-player
   sudo systemctl start qlab-player
   ```

4. **Check status:**
   ```bash
   sudo systemctl status qlab-player
   ```

---

## Performance Optimization

### For Best Video Performance

1. **Use H.264 MP4 files** (most compatible)
2. **Recommended settings:**
   - Video codec: H.264
   - Audio codec: AAC
   - Frame rate: 24-30 fps
   - Resolution: 1920x1080 or lower

3. **Convert video if needed:**
   ```bash
   ffmpeg -i input.mov -c:v libx264 -preset slow -crf 22 -c:a aac -b:a 128k output.mp4
   ```

### For Best Image Performance

1. **Pre-scale images** to display resolution (1920x1080)
2. **Use JPG for photos**, PNG for graphics/logos
3. **Optimize file size:**
   ```bash
   # For JPG
   convert large.jpg -resize 1920x1080 -quality 85 optimized.jpg
   
   # For PNG
   convert large.png -resize 1920x1080 optimized.png
   ```

### Network Performance

1. **Use wired Ethernet** (more reliable than WiFi)
2. **Store media locally** on Pi (not network drives)
3. **Use static IP** to prevent connection issues

---

## Supported Formats

### Images
- JPG / JPEG
- PNG
- GIF
- BMP
- TIFF
- WebP

### Videos
- MP4 (H.264 recommended)
- MOV
- AVI
- MKV
- WebM
- M4V

---

## Advanced Usage

### Multiple Raspberry Pis

To control multiple Pi's from one QLab system:

1. **Give each Pi a unique IP address**
2. **Create separate Network Patches** in QLab:
   - "Raspberry Pi 1" → 192.168.1.100:53000
   - "Raspberry Pi 2" → 192.168.1.101:53000
3. **Select appropriate destination** for each cue

### Custom Media Directory

To use a different media directory:

1. **Edit the script:**
   ```bash
   nano ~/QLab/qlab_vlc_auto.py
   ```

2. **Change line:**
   ```python
   MEDIA_DIR = Path.home() / "media"
   ```
   to:
   ```python
   MEDIA_DIR = Path("/your/custom/path")
   ```

### Network Storage

To use network-attached storage:

1. **Mount the network drive:**
   ```bash
   sudo mount -t cifs //server/share /mnt/media -o username=user,password=pass
   ```

2. **Change MEDIA_DIR** in script to `/mnt/media`

---

## Quick Reference Card

### Start Player
```bash
cd ~/QLab
./start_qlab_player.sh
```

### Stop Player
```
Press Ctrl+C in terminal
```

### OSC Commands
```
/image #/cue/selected/duration# file.jpg
/video #/cue/selected/duration# #/cue/selected/infiniteLoop# file.mp4
/stop
/clear
```

### QLab Network Patch
```
Destination: [Pi IP address]
Port: 53000
Protocol: UDP
```

### File Location
```
~/media/yourfiles.jpg
```

---

## Getting Help

### Check Logs

**Script output** shows what's happening in real-time.

**Look for:**
- "OSC: VIDEO filename.mp4 duration=10.0s" - command received
- "Playing video: /path/to/file.mp4" - file found and playing
- "Video not found: /path" - file missing
- "ERROR: No arguments provided" - OSC message format issue

### Common Error Messages

**"Video not found"** → Check filename and path  
**"DISPLAY: NOT SET"** → Run from desktop or export DISPLAY=:0  
**"ERROR: No arguments"** → Check OSC message format  
**"Permission denied"** → chmod +x script or check file permissions  

### Still Need Help?

1. Check the script is running: `ps aux | grep qlab`
2. Check your IP address: `hostname -I`
3. Test with simple command: `/clear`
4. Verify file exists: `ls ~/media/yourfile.jpg`

---

## Appendix: OSC Query Reference

### Available Queries

| Query | Returns | Use |
|-------|---------|-----|
| `#/cue/selected/duration#` | Duration in seconds | Content display time |
| `#/cue/selected/infiniteLoop#` | 1 or 0 | Loop enabled/disabled |
| `#/cue/selected/preWait#` | Pre-wait time | Advanced timing |
| `#/cue/selected/postWait#` | Post-wait time | Advanced timing |

### Query Syntax

```
#/cue/selected/PROPERTY#
```

**Example in QLab:**
```
Message: /image #/cue/selected/duration# logo.jpg
```

**QLab sends:**
```
/image 5.0 logo.jpg
```
(If duration is 5.00s)

---

## License and Credits

This software is provided as-is for use with QLab and Raspberry Pi.

**Technologies used:**
- VLC media player
- Python 3
- python-osc library
- Raspberry Pi OS

**Created for:** QLab theatrical control integration  
**Compatible with:** QLab 4 and QLab 5

---

**End of Installation and Usage Guide**

For the latest updates and examples, see the included documentation files.
