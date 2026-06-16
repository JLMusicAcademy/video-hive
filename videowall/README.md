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

## Workflow: Build → Push → Run (QLab-style)

Everything lives on one **Workspace** page — a workspace is a named, ordered set
of cues (QLab's "workspace"). Toggle **Edit / Show** mode at the top.

**Build (Edit mode).** Add a cue, give it a name, pick a mode, choose your
image/video, and **Build** — or just **drag image/video files onto the cue
list** to add them as cues automatically (span mode, named after the file). The
hub slices the master (with the chosen bezel handling) and stores each panel's
piece on the hub. The cue is now a **Draft**. Drag cue rows up/down to reorder.

**Push (pre-production).** **Push** a cue (or **Push all**) to send its pre-built
pieces to the display clients. A pushed cue is **Ready**. This is the only time
media crosses the LAN. Editing/re-building a cue makes it a Draft again. Nodes
keep pushed cues on disk and reload them on boot.

**Run.** A **standby** pointer marks the next cue. **GO** (button or Spacebar)
fires the standby cue — a tiny wall-clock-synchronized command, no media moves,
so the flip is near-instant — then advances to the next cue. **GO only fires
Ready cues**; a Draft on standby is blocked until you push it. In **Show** mode
the editor is hidden and the cue list is locked for walking the show live.

## Workspaces, library & default image

- **Workspaces.** Create unlimited workspaces; open one to work on it (cues go
  into the open workspace), switch freely — each keeps its own cues. Persisted on
  the hub disk.
- **Image library.** Reusable images stored on the hub (**Library** tab),
  **organized per workspace** — pick a workspace to see only its images (the
  built-in **Black** rectangle is global, shown for every workspace). Upload by
  drag & drop or browse. Usable as compose sources and as the default fill.
- **Default image.** Each workspace has a default image (Black unless changed)
  used for any panel a cue doesn't assign — so a cue always defines the whole
  wall.

## Supported layouts

| Orientation | Layouts | Panel (wall-space) |
|-------------|---------|--------------------|
| Landscape (16:9) | `1x1 landscape`, `2x2`, `4x4` | 1920×1080, rotation 0 |
| Portrait (9:16)  | `1x1 portrait`, `1x2`, `1x3`, `1x4`, `1x5` | 1080×1920, rotation 90 |

`1xN` is a horizontal **row** of N portrait panels (wide panorama); the two
`1x1` options are a single landscape or single portrait display. Add layouts in
`hub/geometry.py` (`LAYOUTS`).

### Per-workspace walls

The wall is **per workspace**, not global — so one workspace can drive a single
`1x1` display while another drives the full `4x4` wall. New workspaces inherit
the **system default** wall (layout, fit, bezel handling, TV placement); edit it
on the **Wall** tab to override for the open workspace, then **Reset to system
default** or **Save as system default** as needed. (Panel physical dimensions
live in the config and are shared.)

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

## Bezel handling & rotation

Set on the **Wall** tab (persisted in the config as `bezel_comp`). Set each
panel's `active_*` (lit glass) and `outer_*` (chassis incl. bezel) in the config
so the hub knows the real geometry.

- **Compensate** (`bezel_comp: true`, default) — the hub treats the master as
  continuous *across* the bezel gaps and crops only each panel's active area, so
  straight lines stay straight across seams. The slivers behind the bezels are
  hidden (≈ a few % of content). Best for **photo / video**.
- **Show everything** (`bezel_comp: false`) — panels are butted active-edge to
  active-edge with no gap, so **nothing is lost** (all text shows); the trade-off
  is that straight lines step by the bezel width at each seam. Best for
  **text / graphics**.

The authoring-target readout updates to the right master size for the chosen
mode (physical canvas with comp on; active mosaic with comp off).

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

Map each grid cell to a TV's host/port in the **Wall** tab's *TV placement* (or
the config `nodes` block, `"row,col": {host, port}`). The **Identify** button
flashes a cell's label on that TV so you can confirm placement.

## Test on a single machine (no Pis, no display)

Nodes have `--headless`: they accept everything and keep files on disk, so you
can verify slicing, distribution, persistence and orchestration anywhere.

```bash
cd node
for p in 8001 8002 8003 8004 8005; do
  python node.py --id n$p --port $p --headless --media-dir /tmp/n$p & done
cd ../hub && python hub.py --config ../config/wall.example.json &
# open http://localhost:5000 -> Workspace: Add cue, choose an image, Build,
# then Push, then GO
```

The cue editor shows a live **TV-grid preview** of how each panel will display
the cue before you build/push.

## Pre-processed video

In the cue editor, choose a video master and **Build**. The hub tiles it with
ffmpeg (`crop`) into one silent file per panel (runs offline; progress shown),
then **Push** distributes them. Fire it like any cue — every node starts its tile
on the same frame. Audio is stripped from tiles; route sound separately (one
node or a dedicated output) to avoid duplicate playback.

## Status / scope

Working prototype: **images + pre-processed video**, organized into
**workspaces** (named cue sets) on a single QLab-style page (Edit/Show modes,
GO + standby, build → push readiness gate), with a per-workspace image
**library** and **default image**, on a Pi-class hub. Verified end-to-end
(slicing, bezel comp & toggle, compose, build/push state, workspace isolation,
default-image fill, synchronized fire) with headless nodes.

Not yet built (candidate next steps):

- **QLab bridge** — OSC listener so a QLab Network cue fires a wall cue.
- Frame-tight sync hardening (PTP, per-node offset calibration, auto-tuned lead).
- Cue drag-reorder; re-edit a compose cue from its saved assignment; audio routing.
- Separate runtime config from the shipped example so running the hub doesn't
  mutate `wall.example.json`.
