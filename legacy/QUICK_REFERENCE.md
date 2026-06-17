# QLab Media Player - Quick Reference

## Starting the Player

```bash
cd ~/QLab
./start_qlab_player.sh
```

## Stopping the Player

Press `Ctrl+C` in the terminal

---

## QLab Network Patch Setup

```
Name: Raspberry Pi
Type: OSC
Destination: [Your Pi IP]
Port: 53000
Protocol: UDP
```

---

## OSC Command Templates

### Image (Auto-Duration)
```
/image #/cue/selected/duration# filename.jpg
```
Set duration in QLab's Duration field!

### Image (Manual Duration)
```
/image 5.0 filename.jpg
```
Shows for 5 seconds

### Image (Indefinite)
```
/image filename.jpg
```
Shows until next command

---

### Video (Auto-Duration + Loop)
```
/video #/cue/selected/duration# #/cue/selected/infiniteLoop# filename.mp4
```
Set duration and loop in QLab!

### Video (Manual - 30 seconds, no loop)
```
/video 30.0 0 filename.mp4
```

### Video (Loop Forever)
```
/video 0 1 filename.mp4
```

### Video (Play to Completion)
```
/video filename.mp4
```

---

### Control Commands
```
/stop     - Stop current playback
/clear    - Black screen
```

---

## File Locations

**Media files:** `~/media/`  
**Script:** `~/QLab/qlab_vlc_auto.py`  
**Startup:** `~/QLab/start_qlab_player.sh`

---

## QLab Cue Template (Images)

**Basics:**
- Duration: 5.00s

**Settings:**
- Destination: Raspberry Pi
- Type: OSC message
- Message: `/image #/cue/selected/duration# slide1.jpg`

**Continue:**
- Auto-continue
- Post-wait: 5.00s

---

## QLab Cue Template (Videos)

**Basics:**
- Duration: (auto from video length)

**Time & Loops:**
- Loop: ☐ (check if looping)

**Settings:**
- Destination: Raspberry Pi
- Type: OSC message
- Message: `/video #/cue/selected/duration# #/cue/selected/infiniteLoop# intro.mp4`

**Continue:**
- Auto-follow

---

## Troubleshooting Commands

**Get Pi IP address:**
```bash
hostname -I
```

**Test audio:**
```bash
speaker-test -t wav -c 2
```

**Check script running:**
```bash
ps aux | grep qlab
```

**Kill VLC if stuck:**
```bash
pkill -9 vlc
```

**Restart player:**
```bash
cd ~/QLab
./start_qlab_player.sh
```

---

## Network Test (from Mac)

**Ping Pi:**
```bash
ping 192.168.1.100
```

**Send test OSC:**
```bash
oscsend 192.168.1.100 53000 /clear
```

---

## Supported Formats

**Images:** JPG, PNG, GIF, BMP, TIFF, WebP  
**Videos:** MP4, MOV, AVI, MKV, WebM

---

## Common File Paths

**Absolute path:**
```
/image /home/admin/images/slide1.jpg
```

**Relative path:**
```
/image slide1.jpg
```

**Subdirectory:**
```
/image images/slides/slide1.jpg
```

---

## OSC Query Cheat Sheet

| Query | Returns |
|-------|---------|
| `#/cue/selected/duration#` | Cue duration |
| `#/cue/selected/infiniteLoop#` | Loop on/off (1/0) |
| `#/cue/selected/preWait#` | Pre-wait time |
| `#/cue/selected/postWait#` | Post-wait time |

---

## Quick Sequences

**Slideshow (3 images, 5s each):**
```
Cue 1: /image #/cue/selected/duration# slide1.jpg (5s, auto-continue)
Cue 2: /image #/cue/selected/duration# slide2.jpg (5s, auto-continue)
Cue 3: /image #/cue/selected/duration# slide3.jpg (5s, auto-continue)
Cue 4: /clear
```

**Video then image:**
```
Cue 1: /video intro.mp4 (auto-follow)
Cue 2: /image logo.jpg 10.0
```

**Looping background:**
```
Cue 1: /video 0 1 background.mp4 (do not continue)
```
Press GO on next cue to stop loop.

---

**For complete documentation, see INSTALLATION.md**
