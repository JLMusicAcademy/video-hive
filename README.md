# QLab Media Player for Raspberry Pi

> Control your Raspberry Pi's HDMI display from QLab using OSC commands. Professional media playback with hardware acceleration and smooth transitions.

![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%205-red)
![Python](https://img.shields.io/badge/python-3.9+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## 🎬 Features

- **One Persistent Window** - Smooth content switching, no desktop flashing
- **Hardware Acceleration** - Smooth video playback using GPU
- **OSC Control** - Full integration with QLab
- **Auto-Duration** - QLab automatically sends duration settings
- **Loop Support** - Background videos and continuous playback
- **Web Control** - Optional web-based control panel
- **Professional Quality** - Production-ready for live shows

---

## 🚀 Quick Start

### 1. Install on Raspberry Pi

```bash
chmod +x install.sh
./install.sh
sudo reboot
```

### 2. Start Media Player

```bash
cd ~/QLab
python3 qlab_mpv_player.py
```

### 3. Configure QLab

**Network Patch:**
- Destination: [Your Pi's IP address]
- Port: 53000
- Protocol: UDP

**Network Cue:**
```
Message: /image #/cue/selected/duration# yourfile.jpg
Duration: 5.00s
```

**That's it!** QLab automatically sends the duration.

---

## 📋 OSC Commands

### Images
```
/image <duration> <filename>
/image 5.0 slide.jpg              # Show for 5 seconds
/image #/cue/selected/duration# slide.jpg   # Auto from QLab
```

### Videos
```
/video <duration> <loop> <filename>
/video 30.0 0 intro.mp4           # 30 seconds, no loop
/video 0 1 background.mp4         # Loop forever
/video #/cue/selected/duration# #/cue/selected/infiniteLoop# video.mp4
```

### Control
```
/stop    # Stop playback
/clear   # Black screen
```

---

## 💻 System Requirements

**Hardware:**
- Raspberry Pi 5 (or Pi 4)
- HDMI display/projector
- Network connection
- microSD card (32GB+)

**Software:**
- Raspberry Pi OS (Bookworm or later)
- QLab 4 or 5 (on Mac)

---

## 📚 Documentation

- **[INSTALLATION.md](docs/INSTALLATION.md)** - Complete setup guide
- **[QUICK_REFERENCE.md](docs/QUICK_REFERENCE.md)** - Daily use commands
- **[OSC_QUERY_GUIDE.md](docs/OSC_QUERY_GUIDE.md)** - QLab OSC queries
- **[WEB_CONTROL_GUIDE.md](docs/WEB_CONTROL_GUIDE.md)** - Web interface setup
- **[PLAYLIST_WORKAROUND.md](docs/PLAYLIST_WORKAROUND.md)** - QLab playlist tips

---

## 🌐 Web Control Interface

Optional web-based control panel with playlist builder:

### Start Backend
```bash
pip3 install flask flask-cors python-osc --break-system-packages
python3 web_control_backend.py
```

### Open Browser
```
http://localhost:5000
```

**Features:**
- Quick play controls
- Playlist builder with duration
- Save/load playlists
- Remote control from any device

---

## 🎯 Use Cases

✅ **Theater Productions** - Cue videos and images from QLab  
✅ **Corporate Events** - Automated presentations  
✅ **Worship Services** - Lyrics, announcements, videos  
✅ **Museums** - Interactive displays  
✅ **Trade Shows** - Looping promotional content  
✅ **Education** - Classroom presentations  

---

## 🔧 Installation Details

The installer automatically:
- Installs Python, MPV, and dependencies
- Configures audio output (HDMI)
- Sets GPU memory for video performance
- Creates media directories
- Sets up startup scripts

**One command installs everything!**

---

## 📂 File Organization

### Recommended Structure
```
~/media/
├── videos/
│   ├── intro.mp4
│   └── demo.mp4
└── images/
    ├── slides/
    │   ├── slide1.jpg
    │   └── slide2.jpg
    └── logos/
        └── logo.png
```

### In QLab
```
/image images/slides/slide1.jpg
/video videos/intro.mp4
```

---

## ⚡ Performance

**Hardware Acceleration Enabled:**
- `--hwdec=auto` - Auto-detect hardware decoder
- `--vo=gpu` - GPU video output
- `--gpu-context=x11egl` - Hardware-accelerated rendering

**Result:** Smooth 1080p video playback on Raspberry Pi 5!

---

## 🎭 Example QLab Sequence

```
Group Cue (Start First and Enter)
├─ Cue 1: /image 3.0 title.jpg
│   Continue: Auto-continue, Post-wait: 3.0s
│
├─ Cue 2: /video 25.0 0 welcome.mp4
│   Continue: Auto-continue, Post-wait: 25.0s
│
├─ Cue 3: /image 10.0 slide1.jpg
│   Continue: Auto-continue, Post-wait: 10.0s
│
└─ Cue 4: /video 0 1 background.mp4
    Continue: Do not continue
```

**Press GO once** → Entire sequence plays automatically!

---

## 🐛 Troubleshooting

### No Video
```bash
# Check DISPLAY variable
echo $DISPLAY    # Should show :0

# Set if needed
export DISPLAY=:0
```

### No Audio
```bash
# Configure audio output
sudo raspi-config
# System Options → Audio → HDMI
```

### Can't Connect from QLab
```bash
# Get Pi IP address
hostname -I

# Test from Mac
ping [PI-IP]
```

See [INSTALLATION.md](docs/INSTALLATION.md) for complete troubleshooting.

---

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Test on Raspberry Pi
4. Submit a pull request

---

## 📝 License

MIT License - see LICENSE file for details

---

## 🙏 Acknowledgments

- Built for the theatrical and live event community
- Uses MPV media player with hardware acceleration
- OSC protocol via python-osc library
- Designed for QLab integration

---

## 📧 Support

- **Issues:** Use GitHub Issues for bug reports
- **Discussions:** Use GitHub Discussions for questions
- **Documentation:** See `/docs` folder

---

## 🎯 Supported Formats

**Videos:** MP4, MOV, AVI, MKV, WebM, M4V  
**Images:** JPG, PNG, GIF, BMP, TIFF, WebP

---

## 🔄 Updates

**Current Version:** 1.0  
**Status:** Stable  
**Last Updated:** January 2025

---

**Made with ❤️ for the live production community**

[Report Bug](../../issues) · [Request Feature](../../issues) · [Documentation](docs/)
