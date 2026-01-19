# Using QLab OSC Queries - Automatic Duration & Loop!

## 🎉 **YOU'RE RIGHT! QLab CAN Send Duration Automatically!**

Using **OSC Queries**, QLab can automatically include the duration and loop settings from your cue!

---

## 📥 **Use This Script:**

**[qlab_vlc_auto.py](computer:///mnt/user-data/outputs/qlab_vlc_auto.py)** - Reads duration/loop from QLab automatically!

---

## 🎯 **How OSC Queries Work:**

When you put `#/cue/selected/duration#` in your OSC message, QLab **automatically replaces it** with the actual duration value from your cue!

**You type:**
```
/image #/cue/selected/duration# logo.jpg
```

**QLab sends:**
```
/image 5.0 logo.jpg
```
(If your cue's duration is set to 5.00s)

---

## ✨ **Setup in QLab - Step by Step**

### For Images with Auto-Duration:

1. **Create Network Cue**
2. **Basics tab:**
   - Set **Duration** to your desired time (e.g., 5.00s)
3. **Settings tab:**
   - **Destination:** Raspberry Pi
   - **Type:** OSC message
   - **Message:** `/image #/cue/selected/duration# yourfile.jpg`

**That's it!** QLab will automatically send the duration.

### For Videos with Auto-Duration:

**Message:**
```
/video #/cue/selected/duration# yourfile.mp4
```

Set duration in QLab's Duration field, and it's automatically used!

### For Videos with Loop:

**Message:**
```
/video #/cue/selected/duration# #/cue/selected/infiniteLoop# yourfile.mp4
```

**Basics tab:**
- Set **Duration** (e.g., 10.00s)  
- Check **Loop** checkbox in Time & Loops tab

QLab sends both values automatically!

---

## 📋 **Complete Examples**

### Example 1: Image Slideshow (Auto-Duration)

**Cue 1 - Network Cue:**
```
Message: /image #/cue/selected/duration# slide1.jpg
Duration: 5.00s
Continue: Auto-continue
Post-wait: 5.00s
```

**Cue 2 - Network Cue:**
```
Message: /image #/cue/selected/duration# slide2.jpg
Duration: 5.00s
Continue: Auto-continue  
Post-wait: 5.00s
```

Each image shows for the duration you set in QLab - no manual numbers needed!

### Example 2: Looping Video

**Network Cue:**
```
Message: /video #/cue/selected/duration# #/cue/selected/infiniteLoop# background.mp4
Duration: (doesn't matter when looping)
Time & Loops tab: ☑ Loop checked
```

Video loops indefinitely!

### Example 3: Video Excerpt (Auto-Duration)

**Network Cue:**
```
Message: /video #/cue/selected/duration# longvideo.mp4
Duration: 30.00s
```

Plays only first 30 seconds (even if video is 5 minutes long).

### Example 4: Image Until Manual Advance

**Network Cue:**
```
Message: /image intermission.jpg
Duration: (leave at default or 0)
Continue: Do not continue
```

Image stays until you press GO on next cue.

---

## 🔍 **Available OSC Queries for Media Control**

| OSC Query | Returns | Use For |
|-----------|---------|---------|
| `#/cue/selected/duration#` | Duration in seconds | How long to show content |
| `#/cue/selected/infiniteLoop#` | 1 or 0 | Whether to loop |
| `#/cue/selected/continueMode#` | 0, 1, or 2 | Continue mode |
| `#/cue/selected/preWait#` | Pre-wait time | Advanced timing |
| `#/cue/selected/postWait#` | Post-wait time | Advanced timing |

For your use case, you mainly need **duration** and **infiniteLoop**.

---

## 🎬 **Practical Workflows**

### Workflow 1: Set Duration in QLab, Use Query

**All your cues:**
```
Message: /image #/cue/selected/duration# FILENAME
```

**Just change the Duration field in QLab** - no need to edit OSC message!

- Cue 1: Duration 3.00s → shows 3 seconds
- Cue 2: Duration 10.00s → shows 10 seconds  
- Cue 3: Duration 5.00s → shows 5 seconds

### Workflow 2: Template Cue

Create one "template" Network cue:
```
Message: /image #/cue/selected/duration# PLACEHOLDER.jpg
Duration: 5.00s
```

**Duplicate it** for each image:
- Just change the filename
- Adjust duration as needed
- OSC query automatically uses the new duration!

### Workflow 3: Mixed Durations

```
Cue 1: /image #/cue/selected/duration# title.jpg
  Duration: 3.00s
  
Cue 2: /video #/cue/selected/duration# intro.mp4
  Duration: 15.00s
  
Cue 3: /image #/cue/selected/duration# logo.png
  Duration: 10.00s
```

All use the same OSC message format, different durations!

---

## ⚙️ **OSC Query Syntax**

The `#` symbols tell QLab "this is a query, replace it with the actual value":

```
#/cue/selected/PROPERTY#
```

**At runtime**, QLab replaces this with the actual value.

**Common pattern:**
```
/media/TYPE #/cue/selected/duration# FILENAME
         └─ QLab replaces with actual number
```

---

## 🔄 **Loop Settings**

### Enable Looping in QLab:

1. Select your cue
2. Go to **Time & Loops** tab
3. Check **☑ Loop**
4. In OSC message: `/video #/cue/selected/duration# #/cue/selected/infiniteLoop# file.mp4`

QLab sends `1` for loop enabled, `0` for disabled.

### Infinite Loop Example:

**Message:**
```
/video #/cue/selected/infiniteLoop# background.mp4
```

If loop is checked, sends: `/video 1 background.mp4`  
If not checked, sends: `/video 0 background.mp4`

Script interprets `1` as "loop forever", `0` as "play once".

---

## 💡 **Pro Tips**

### Tip 1: Use Queries for Flexibility

**With query:**
```
/image #/cue/selected/duration# slide.jpg
```
Change duration in QLab → automatically updates!

**Without query:**
```
/image 5.0 slide.jpg
```
Change duration in QLab → must also edit OSC message

### Tip 2: Mix Query and Fixed Values

You can use queries for some values, fixed for others:
```
/video #/cue/selected/duration# 0 clip.mp4
                                      └─ Never loop (fixed)
```

### Tip 3: Default to Queries

Make it your standard template:
```
/image #/cue/selected/duration# FILENAME
/video #/cue/selected/duration# #/cue/selected/infiniteLoop# FILENAME
```

Then just:
1. Duplicate cue
2. Change filename
3. Adjust duration/loop in QLab
4. Done!

---

## 🧪 **Testing OSC Queries**

### Test if Query Works:

1. Create Network cue with: `/image #/cue/selected/duration# test.jpg`
2. Set Duration to 3.00s
3. Look at QLab's log (⌘L) when you fire the cue
4. Should show it sent: `/image 3.0 test.jpg`

### Verify on Raspberry Pi:

The script prints what it receives:
```
OSC: IMAGE test.jpg duration=3.0s
```

If you see the duration value, the query worked!

---

## 📝 **Complete QLab Cue Template**

### Image Cue Template:

**Basics:**
- **Duration:** [Set your time]
- **Continue:** Auto-continue
- **Post-wait:** [Same as duration]

**Settings:**
- **Destination:** Raspberry Pi
- **Type:** OSC message  
- **Message:** `/image #/cue/selected/duration# FILENAME.jpg`

### Video Cue Template:

**Basics:**
- **Duration:** [Set if limiting playback]
- **Continue:** Auto-follow (for sequences)

**Time & Loops:**
- **Loop:** [Check if looping]

**Settings:**
- **Destination:** Raspberry Pi
- **Type:** OSC message
- **Message:** `/video #/cue/selected/duration# #/cue/selected/infiniteLoop# FILENAME.mp4`

---

## ⚠️ **Important Notes**

### Query Must Be In Message Field

OSC queries only work **in the OSC message itself**, not in other fields.

✅ **Correct:**
```
Message: /image #/cue/selected/duration# file.jpg
```

❌ **Wrong:**
```
Duration field: #/cue/selected/duration#
```

### Queries Evaluate at Send Time

The query is evaluated **when the cue fires**, not when you create it.

So you can:
1. Create cue with query
2. Later change the duration
3. Query uses the updated value!

### Space Handling

QLab automatically formats the OSC message correctly - you don't need to worry about spacing.

---

## 🎯 **Summary**

**Old way (manual):**
```
Message: /image 5.0 logo.jpg
```
Change duration → Edit OSC message too ❌

**New way (OSC query):**
```
Message: /image #/cue/selected/duration# logo.jpg
Duration: 5.00s
```
Change duration → OSC message auto-updates ✅

**With loop:**
```
Message: /video #/cue/selected/duration# #/cue/selected/infiniteLoop# video.mp4
Duration: 10.00s
Loop: ☑ Checked
```
QLab automatically sends duration and loop status!

---

## 🚀 **Quick Start**

1. **Use the new script:** `qlab_vlc_auto.py`
2. **In every QLab Network cue, use:**
   - Images: `/image #/cue/selected/duration# FILENAME`
   - Videos: `/video #/cue/selected/duration# #/cue/selected/infiniteLoop# FILENAME`
3. **Set duration in QLab's Duration field**
4. **Check Loop if needed**
5. **Done!** QLab sends everything automatically!

**No more typing durations in OSC messages!** ✨
