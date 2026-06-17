# Video in Playlist Workaround

## The Issue

Videos work fine as the LAST cue in a Playlist, but get interrupted when followed by another cue.

**Why:** When QLab's Network cue duration expires, it IMMEDIATELY sends the next OSC command, which loads the next image and interrupts the video.

---

## ✅ **Solution: Use "Start First and Enter Group" Instead**

Instead of Playlist mode, use **Start First and Enter Group** mode with manual continue settings.

### Setup:

1. **Create Group Cue**
2. **Mode tab:** Select "Start first child and enter Group"
3. **Add your cues inside:**

```
Cue 1: /image 5.0 slide1.jpg
  Continue: Auto-continue
  Post-wait: 5.00s

Cue 2: /video 30.0 0 intro.mp4  
  Continue: Auto-continue
  Post-wait: 30.00s

Cue 3: /image 10.0 logo.jpg
  Continue: Auto-continue
  Post-wait: 10.00s
```

**This works perfectly!** Each cue completes before the next starts.

---

## 📋 **Comparison:**

| Mode | Video Works? | Notes |
|------|--------------|-------|
| Playlist | ❌ Interrupted (except last cue) | Advances too quickly |
| Start First & Enter | ✅ Works perfectly | Full control of timing |
| Manual (no group) | ✅ Works perfectly | Most control |

---

## 🎯 **Recommended Setup (Not Playlist):**

### Option 1: Start First and Enter Group

**Group Cue (Start First and Enter):**
- Cue 1: Image (auto-continue, 5s post-wait)
- Cue 2: Video (auto-continue, 30s post-wait)
- Cue 3: Image (auto-continue, 10s post-wait)

**Press GO once** → Group plays through all cues automatically

### Option 2: Manual Sequence (No Group)

**Cue List:**
- Cue 1: Image (auto-continue, 5s post-wait)
- Cue 2: Video (auto-continue, 30s post-wait)
- Cue 3: Image (auto-continue, 10s post-wait)

**Press GO once** → Sequence plays through automatically

### Option 3: Timeline Group

**Group Cue (Timeline mode):**
- Cue 1: Image (pre-wait: 0s)
- Cue 2: Image (pre-wait: 5s)
- Cue 3: Video (pre-wait: 10s)
- Cue 4: Image (pre-wait: 40s)

**Press GO once** → All cues triggered, pre-waits control timing

---

## 🔧 **Why Playlist Mode Doesn't Work Well:**

**Playlist mode** is designed for:
- QLab native cues (Audio, Video cues)
- Content that QLab directly controls
- Crossfading between items

**Network cues** are different:
- They just send messages
- QLab doesn't know when content actually finishes
- Timing is based on cue duration, not actual playback

**Result:** Playlist advances based on timer, interrupting external playback.

---

## ✨ **Working Solution Example:**

```
Group Cue (Start First and Enter)
├─ Cue 1.1: /image 5.0 intro.jpg
│    Continue: Auto-continue
│    Post-wait: 5.00s
│
├─ Cue 1.2: /video 0 0 welcome.mp4
│    Continue: Auto-continue
│    Post-wait: 25.00s  ← Video length!
│
├─ Cue 1.3: /image 10.0 slide1.jpg
│    Continue: Auto-continue
│    Post-wait: 10.00s
│
├─ Cue 1.4: /video 0 0 demo.mp4
│    Continue: Auto-continue
│    Post-wait: 45.00s  ← Video length!
│
└─ Cue 1.5: /image 0 thankyou.jpg
     Continue: Do not continue
```

**Fire the Group cue once → entire sequence plays automatically!**

---

## 💡 **Pro Tips:**

### 1. Use Auto-Continue, Not Playlist

For automated sequences with Network cues, use:
- Start First and Enter Group mode, OR
- Manual cues with auto-continue

**Don't use Playlist mode** for Network cues with mixed content.

### 2. Set Post-Wait Carefully

Post-wait should equal or slightly exceed content duration:
- Image 5s → Post-wait 5.0s
- Video 30s → Post-wait 30.0s (or 30.5s for safety)

### 3. Use Pre-Wait for Precise Timing

For frame-accurate timing, use Timeline Group with pre-waits:
```
Timeline Group:
  Cue A: Pre-wait 0s
  Cue B: Pre-wait 5.0s   ← Starts exactly 5s after Group
  Cue C: Pre-wait 35.0s  ← Starts exactly 35s after Group
```

### 4. Test Your Timing

Run through the sequence and verify:
- Videos play completely
- Images display for correct duration
- No interruptions

---

## 📝 **Summary:**

**Playlist Mode:** ❌ Don't use for Network cues with videos  
**Start First & Enter:** ✅ Works perfectly  
**Auto-Continue:** ✅ Works perfectly  
**Timeline Group:** ✅ Works for precise timing  

**Use auto-continue with post-wait for reliable, automated sequences!**

---

## 🎬 **Quick Setup:**

1. Create Group cue (Start First and Enter)
2. Add your Network cues inside
3. Set each to auto-continue
4. Set post-wait to match duration
5. Fire the Group → Plays through automatically

**This is the reliable way to do automated sequences with Network cues!**
