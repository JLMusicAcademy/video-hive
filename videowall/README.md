# Video Wall (hub + nodes)

A networked video wall: a **control hub** slices/orchestrates, and a thin
**display node** (one Raspberry Pi per TV) shows its assigned region. Send a
single image to one display, mirror it across the grid, or break it into pieces
so the whole wall shows one continuous picture — plus pre-processed,
synchronized video.

This is the new direction for the project. It reuses the original QLab player's
proven "persistent fullscreen MPV window" technique as the node, and grows the
old Flask backend into the hub.

```
            ┌──────────────────────────────┐
            │            HUB               │  Raspberry Pi 5 is sufficient
            │  layouts · image slicer ·    │  for images + pre-tiled video
            │  bezel comp · video tiler ·  │
            │  sync scheduler · web UI     │
            └───────────────┬──────────────┘
                            │  wired Gigabit LAN
        ┌──────────┬────────┼────────┬──────────┐
        ▼          ▼        ▼        ▼          ▼
     Pi (0,0)   Pi (0,1)  Pi(1,0)  Pi(1,1) …  Pi (r,c)
     one TV     one TV    one TV   one TV     one TV
```

## Supported layouts

| Orientation | Layouts | Panel (wall-space) |
|-------------|---------|--------------------|
| Landscape (16:9) | `2x2`, `4x4` | 1920×1080, rotation 0 |
| Portrait (9:16)  | `1x1`, `1x2`, `1x3`, `1x4`, `1x5` | 1080×1920, rotation 90 |

Add your own in `hub/geometry.py` (`LAYOUTS`). Panel physical dimensions and
node IP/port mapping live in `config/wall.example.json`.

## How simultaneous display is guaranteed (the latency answer)

Panels must flip *together* or the picture looks disjointed. The hub never says
"show now". It uses **stage-then-commit**:

1. **Stage** — push every tile to its node and wait until all report ready.
   This absorbs the variable, per-node network transfer time up front.
2. **Commit** — broadcast one `show_at` wall-clock timestamp a short lead time
   in the future (default 0.30 s for images). Each node schedules the actual
   flip against *its own* clock, so the visible change lands on the same instant
   on every panel regardless of network jitter.

The only realtime operation at flip time is a local `loadfile` of an
already-transferred file (sub-millisecond, consistent). **Requirement:** keep
node clocks tight with NTP on the LAN (PTP for the tightest sync). The same
mechanism drives synchronized video playback.

## Bezel compensation & rotation

- **Bezel comp** is automatic: the hub builds the wall canvas including the dead
  space behind the bezels, then crops only each panel's *active* area, dropping
  the strips hidden by the seams so the image stays continuous. Configure each
  panel's `active_*` (lit glass) and `outer_*` (chassis incl. bezel) in the
  config.
- **Rotation** for vertically-mounted TVs is applied at the node via MPV
  `video-rotate`, so the hub always works in wall-space orientation.

## Image modes

- **span** — one image sliced across the whole grid (the video-wall look).
- **mirror** — the same whole image on every panel.
- **solo** — one image to a single selected panel (individually addressable).

## Run it

Install deps (hub needs `ffmpeg`/`ffprobe` for video; nodes need `mpv`):

```bash
pip install -r requirements.txt
```

**Hub:**

```bash
cd hub
python hub.py --config ../config/wall.example.json
# open http://localhost:5000
```

**Each display node (on its Pi):**

```bash
cd node
python node.py --id tv00 --port 8001 --rotation 0     # landscape
python node.py --id tv00 --port 8001 --rotation 90    # portrait mount
```

Map each node's host/port to its grid coordinate in the config `nodes` block
(`"row,col": {host, port}`).

## Test on a single machine (no Pis, no display)

Nodes have a `--headless` mode: they accept all commands and write staged tiles
to `node/received/` so you can verify slicing and orchestration anywhere.

```bash
# 4 headless nodes for a 2x2 wall
cd node
for p in 8001 8002 8003 8004; do python node.py --id n$p --port $p --headless & done

cd ../hub && python hub.py --config ../config/wall.example.json &
# open http://localhost:5000, pick 2x2, drop an image, Preview, Send
```

The **Preview** button renders a mockup of the whole wall *including* bezel gaps
so you can confirm the picture is continuous before sending.

## Pre-processed video

1. **Prepare** — upload a video; the hub tiles it with ffmpeg (`crop`) into one
   silent file per panel and distributes them to the nodes. Runs offline; poll
   progress in the UI.
2. **Play** — the hub broadcasts a synchronized `show_at` and every node starts
   its tile on the same frame.

Audio is intentionally stripped from tiles — route sound separately (one node,
or a dedicated audio output) to avoid 16 copies.

## Status / scope

Working prototype for **images + pre-processed video** on a **Pi-class hub**.
Not yet built (candidate next steps):

- Frame-tight sync hardening (PTP, drift correction, per-node offset calibration).
- Live/on-the-fly video tiling (would want an N100/NUC-class hub).
- Audio routing, content scheduling/playlists, OSC bridge for QLab control,
  persisted wall presets, per-node health/auto-recovery.
