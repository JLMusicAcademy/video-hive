# Web Control Interface for Media Player

A simple web-based control panel for your Raspberry Pi media player.

## Features

✨ **Quick Controls** - Send individual commands instantly  
📋 **Playlist Builder** - Create and manage playlists  
⏱️ **Duration Control** - Set display time for images  
🔁 **Loop Support** - Enable looping for videos  
💾 **Auto-Save Settings** - Remembers your Pi's IP address  

---

## Installation

### 1. Install Backend Dependencies

```bash
pip3 install flask flask-cors python-osc --break-system-packages
```

### 2. Download Files

You need both files in the same directory:
- `media_control.html` - Web interface
- `web_control_backend.py` - Python backend server

---

## Usage

### 1. Start the Backend Server

```bash
python3 web_control_backend.py
```

You'll see:
```
Media Player Web Control - Backend Server
============================================================

Starting server on http://localhost:5000

Open your browser to: http://localhost:5000
```

### 2. Open Web Interface

Open your browser to: **http://localhost:5000**

### 3. Configure Connection

- Enter your **Raspberry Pi IP address** (e.g., 192.168.1.100)
- Enter **Port** (default: 53000)
- Settings are saved automatically

### 4. Control Your Media Player!

---

## Interface Overview

### 🎮 Quick Controls

**Play individual items instantly:**

1. Enter filename (e.g., `video.mp4` or `image.jpg`)
2. Set duration (0 = default behavior)
3. Enable loop (for videos)
4. Click **Play**

**Also includes:**
- **Stop** button - Stops current playback
- **Clear** button - Shows black screen

### 📝 Playlist Builder

**Create automated sequences:**

1. **Select Type:** Image or Video
2. **Enter Filename:** From your ~/media/ directory
3. **Set Duration:** How long to display/play
4. **Loop:** (Videos only) Enable looping
5. Click **Add to Playlist**

**Playlist Controls:**
- **▶️ Play** - Play individual item
- **✕ Remove** - Remove from playlist
- **▶️ Play All** - Play entire playlist automatically
- **🗑️ Clear All** - Remove all items

---

## Examples

### Example 1: Quick Image Display

```
File: slide1.jpg
Duration: 5
→ Click Play
```

Result: Image shows for 5 seconds

### Example 2: Play Video

```
File: intro.mp4
Duration: 0 (play to completion)
Loop: No
→ Click Play
```

Result: Video plays completely

### Example 3: Build Slideshow Playlist

```
Add to Playlist:
1. Image: slide1.jpg, Duration: 5s
2. Image: slide2.jpg, Duration: 5s
3. Image: slide3.jpg, Duration: 5s

→ Click "Play All"
```

Result: Automated 15-second slideshow

### Example 4: Mixed Playlist

```
Add to Playlist:
1. Image: title.jpg, Duration: 3s
2. Video: intro.mp4, Duration: 30s
3. Image: slide1.jpg, Duration: 5s
4. Video: demo.mp4, Duration: 45s
5. Image: thankyou.jpg, Duration: 5s

→ Click "Play All"
```

Result: Complete presentation sequence

---

## How It Works

```
┌──────────────┐         HTTP          ┌──────────────┐
│              │       (localhost)      │    Python    │
│  Web Browser │ ───────────────────> │   Backend    │
│  (Frontend)  │                        │   (Flask)    │
└──────────────┘                        └──────────────┘
                                              │
                                              │ OSC/UDP
                                              ▼
                                        ┌──────────────┐
                                        │ Raspberry Pi │
                                        │ Media Player │
                                        └──────────────┘
```

1. **Web interface** sends commands via HTTP to backend
2. **Python backend** converts HTTP to OSC messages
3. **OSC messages** sent to Raspberry Pi media player
4. **Media player** displays content

---

## API Endpoints

The backend provides these endpoints:

### POST /api/send
Send raw OSC command
```json
{
  "ip": "192.168.1.100",
  "port": 53000,
  "command": "/video",
  "args": [30.0, 0, "intro.mp4"]
}
```

### POST /api/play/image
```json
{
  "ip": "192.168.1.100",
  "port": 53000,
  "filename": "slide.jpg",
  "duration": 5.0
}
```

### POST /api/play/video
```json
{
  "ip": "192.168.1.100",
  "port": 53000,
  "filename": "video.mp4",
  "duration": 30.0,
  "loop": 0
}
```

### POST /api/control/stop
Stop playback

### POST /api/control/clear
Clear to black screen

---

## Troubleshooting

### "Could not connect to backend server"

**Problem:** Backend not running  
**Solution:** Start `python3 web_control_backend.py`

### "Failed to send command"

**Problem:** Wrong Pi IP address or port  
**Solution:** 
- Check Pi IP: `hostname -I` on Pi
- Verify port (default: 53000)
- Ensure media player running on Pi

### Backend won't start - "Module not found"

**Problem:** Missing dependencies  
**Solution:**
```bash
pip3 install flask flask-cors python-osc --break-system-packages
```

### Playlist doesn't play

**Problem:** Files not found on Pi  
**Solution:** 
- Files must exist in `~/media/` on Raspberry Pi
- Check spelling and file extensions
- Use relative paths (e.g., `video.mp4` not `/home/admin/media/video.mp4`)

---

## Running on Different Computer

You can run the web interface on any computer on your network:

### 1. Start Backend on Your Computer

```bash
python3 web_control_backend.py
```

### 2. Find Your Computer's IP

```bash
# On Mac/Linux
ifconfig | grep inet

# On Windows
ipconfig
```

### 3. Access from Any Device

Open browser to: `http://YOUR_COMPUTER_IP:5000`

Example: `http://192.168.1.50:5000`

### 4. Enter Raspberry Pi's IP

In the web interface, enter your **Raspberry Pi's** IP address (not your computer's).

---

## Security Note

⚠️ **This is for local network use only!**

The backend has no authentication. Only run it on trusted networks.

For production use, add:
- Authentication
- HTTPS
- Input validation
- Rate limiting

---

## Advanced: Run Backend on Raspberry Pi

You can run the backend directly on the Raspberry Pi:

### 1. Copy Files to Pi

```bash
scp media_control.html web_control_backend.py admin@[PI-IP]:~/
```

### 2. Start Backend on Pi

```bash
cd ~
python3 web_control_backend.py
```

### 3. Access from Any Device

Open browser to: `http://[PI-IP]:5000`

**Advantage:** No need for separate backend server  
**Disadvantage:** One more thing running on Pi

---

## Summary

**Simple Setup:**
1. Install: `pip3 install flask flask-cors python-osc`
2. Run: `python3 web_control_backend.py`
3. Open: `http://localhost:5000`
4. Control your media player from the web!

**Perfect for:**
- Testing media playback
- Quick control panel
- Building playlists
- Presentations without QLab
- Remote control from phone/tablet

---

**Enjoy your web-based media control!** 🎬
