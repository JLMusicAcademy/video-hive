# Video Hive (hub + nodes)

A networked video wall. A **control hub** does all the image/video editing —
slicing and bezel math — and a thin **display node** (one Raspberry Pi per TV)
shows its assigned piece. You author one master image/video at the full wall
format; the hub splices it and pushes the right piece to the right TV.

It follows the original QLab philosophy: **distribute heavy media once during
pre-production, then fire lightweight cues at show time.**

```
   BUILD (pre-production)                 FIRE (show time)
   author 1 master at wall format         hub -> every TV: "show cue 7"
        │ hub slices + bezel math              (tiny command, no media)
        ▼ push slices to each TV               ▼ all panels flip in unison
   ┌───────────────────────────────────────────────────────────┐
   │  HUB (Raspberry Pi 5 is sufficient for images + pre-tiled  │
   │  video) — layouts · slicer · bezel comp · video tiler ·    │
   │  cue library · sync scheduler · web UI                     │
   └───────────────┬───────────────────────────────────────────┘
                   │ wired Gigabit LAN
        ┌──────────┼──────────┬──────────┐
        ▼          ▼          ▼          ▼
     Pi (0,0)   Pi (0,1)   Pi (1,0)  … Pi (r,c)   each: persistent MPV +
     cue library on local disk (survives reboot)  fire-by-ID
```

## The two phases

**Build (pre-production).** Author one master at the format the hub tells you
(see *Authoring target* below). Give it a cue name, pick a mode, and **Build +
Distribute**. The hub slices the master (with bezel compensation), and pushes
each panel's slice to its node, filed under the cue ID. This is the only time
media crosses the LAN. The node stores cues on disk and reloads them on boot, so
a built show is ready immediately after a restart.

**Fire (show time).** Firing a cue sends every TV only a tiny "show cue N"
command — no media moves, so the flip is near-instant. The command carries a
single wall-clock `show_at` timestamp so all panels change in unison (see
*Synchronized flips*).

## Shows, library & default image

- **Shows.** A *show* is a named, ordered set of cues. Create unlimited shows in
  the **Shows** tab, open one to work on it (cues you build go into the open
  show), and switch freely — each show keeps its own cues. **Distribute whole
  show** pushes every cue's pre-built pieces to the TVs at once (run it before
  the show, or again after a reboot / TV swap). Shows persist on the hub disk.
- **Image library.** Reusable images stored on the hub (**Library** tab). A
  built-in **Black** rectangle is always present. Upload your own; library
  images can be used as compose sources and as the default fill.
- **Default image.** Each show has a default image (Black unless you change it)
  used for any panel a cue doesn't assign — so a cue always defines the whole
  wall.

## Supported layouts

| Orientation | Layouts | Panel (wall-space) |
|-------------|---------|--------------------|
| Landscape (16:9) | `2x2`, `4x4` | 1920×1080, rotation 0 |
| Portrait (9:16)  | `1x1`, `1x2`, `1x3`, `1x4`, `1x5` | 1080×1920, rotation 90 |

`1xN` is a horizontal **row** of N portrait panels (wide panorama). Add layouts
in `hub/geometry.py` (`LAYOUTS`).

## Authoring target (so you never do the math)

Pick a grid and the hub shows the exact size to author your master at, e.g. for
`1x5` portrait the wall is ≈ **45:16** (five 9:16 panels in a row) — *wide*, not
9:16. The UI reports two targets:

- **physical_canvas** — author here for full bezel compensation; the hub treats
  the master as the continuous surface (bezels included) and crops each panel's
  active window out.
- **active_mosaic** — the simpler 1:1 target; seams show the usual
  uncompensated offset.

## Image modes

- **span** — one master sliced across the whole grid (the video-wall look).
- **mirror** — the same whole image on every panel.
- **solo** — one image to a single selected panel (individually addressable).
- **compose** — per-panel assignment: each panel independently gets a **slice**
  of an image, a **full** fitted image (from an upload or the library), or the
  show's **default** image. A sliced image uses the full-grid geometry, so it
  stays registered across whatever (possibly non-contiguous) panels reference it
  — e.g. on a 1×5 wall, image A sliced across TV1/3/5 while TV2/4 show their own
  full images, with TV1/3/5 still perfectly aligned as if the whole row were
  image A. Compose generalizes the other three modes; unassigned panels fall
  back to the default image, so a compose cue defines the entire wall.

## Synchronized flips (the latency answer)

A fired cue carries one `show_at` wall-clock timestamp a short lead in the
future. Each node schedules the flip against **its own** clock, so every panel
changes on the same instant regardless of network jitter. Because the media is
already local, the only realtime work is a local `loadfile` — sub-millisecond.
**Requirement:** keep node clocks tight with NTP on the LAN (PTP for the
tightest sync), and use wired Gigabit.

## Bezel compensation & rotation

- **Bezel comp** is automatic: the hub builds the wall canvas including the dead
  space behind the bezels, then crops only each panel's *active* area. Set each
  panel's `active_*` (lit glass) and `outer_*` (chassis incl. bezel) in the
  config.
- **Rotation** for portrait-mounted TVs is applied at the node (MPV
  `video-rotate`), so the hub always works in wall-space orientation.

## Run it

Hub needs `ffmpeg`/`ffprobe` (for video tiling); nodes need `mpv`.

```bash
pip install -r requirements.txt        # Pillow, Flask, flask-cors, requests
```

**Hub:**

```bash
cd hub
python hub.py --config ../config/wall.example.json     # http://localhost:5000
```

**Each display node (on its Pi):**

```bash
cd node
python node.py --id tv00 --port 8001 --rotation 0      # landscape
python node.py --id tv04 --port 8005 --rotation 90     # portrait mount
```

Map each grid cell to a TV's host/port in the **Grid Config** tab (or the config
`nodes` block, `"row,col": {host, port}`). The **Identify** button flashes a
cell's label on that TV so you can confirm placement.

## Test on a single machine (no Pis, no display)

Nodes have `--headless`: they accept everything and keep files on disk, so you
can verify slicing, distribution, persistence and orchestration anywhere.

```bash
cd node
for p in 8001 8002 8003 8004; do
  python node.py --id n$p --port $p --headless --media-dir /tmp/n$p & done
cd ../hub && python hub.py --config ../config/wall.example.json &
# open http://localhost:5000 -> pick 2x2 -> Build tab: drop an image, Build
# -> Show tab: Fire the cue
```

The **Preview** button (Build tab) renders a mockup of the whole wall
*including* bezel gaps, so you can confirm continuity before distributing.

## Pre-processed video

In the Build tab, choose a video master and **Build + Distribute**. The hub
tiles it with ffmpeg (`crop`) into one silent file per panel and distributes
them under a cue ID (runs offline; progress shown). Fire it like any cue — every
node starts its tile on the same frame. Audio is stripped from tiles; route
sound separately (one node or a dedicated output) to avoid duplicate playback.

## Status / scope

Working prototype: **images + pre-processed video**, organized into **shows**
(named cue sets) with an image **library** and per-show **default image**,
build-once / fire-by-cue, on a Pi-class hub. Verified end-to-end (slicing, bezel
comp, compose, distribution, disk persistence, show isolation, custom default
image, synchronized fire) with headless nodes.

Not yet built (candidate next steps):

- **QLab bridge** — OSC listener so a QLab Network cue fires a wall cue.
- Frame-tight sync hardening (PTP, per-node offset calibration, auto-tuned lead).
- Pre-decode on stage; audio routing; cue reordering UI.
- Separate runtime config from the shipped example so running the hub doesn't
  mutate `wall.example.json`.
