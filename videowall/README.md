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

### One wall grid

There is a **single wall grid**, set on the **Wall** tab: layout, fit, bezel
handling, and TV placement. It's a one-time setup for the physical space, and
**every workspace uses it** — there is no per-workspace grid. On the Wall tab,
**click a panel** to assign which TV sits in that cell (pick a discovered TV by
name, or enter host/port), Identify it, or reboot it. (Cues are sliced for the
current grid, so if you change the layout after building cues, rebuild them.)

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

## Run the show from QLab (OSC bridge)

Build the wall in Video Hive, then run the show from QLab. The hub listens for
OSC and each cue has **its own address** (one address per named cue), so QLab
owns the order and the address says exactly what to show — there's no shared
playhead to drift if you reorder, insert, disable, or jump cues in QLab.

On the **QLab** tab the hub shows where to send OSC (its LAN IP + UDP port) and
the address for every cue in the active workspace, e.g.:

```
/videohive/cue/<workspace>/<cue_id>     # fire that exact cue
/videohive/cue/<cue_id>                 # short form: cue in the active workspace
/videohive/black   /videohive/clear   /videohive/stop
```

In QLab, add a **Network (OSC)** cue per Video Hive cue: set its destination to
the hub's IP and port (shown on the tab) and its message to that cue's address.
GO in QLab → the hub fires the cue with the same wall-clock-synchronized
`show_at` flip as the built-in GO, so the hub hop adds only a tiny constant lead,
not desync. Copy buttons (and *Copy all addresses*) make wiring QLab quick.

**Auto-create the cues in QLab.** Rather than hand-wiring, the QLab tab can build
the Network cues straight into your open QLab workspace — one per cue, named to
match, each already sending its address. One-time QLab setup: enable OSC (Settings
→ OSC) and add one **OSC patch** pointed at the hub (the tab shows the IP:port);
note its patch number. Enter QLab's IP, port (53000), and that patch number, then
*Create cues in QLab*. The hub drives QLab's OSC API (`/new "network"`,
`/cue/selected/name`, `/cue/selected/patch`, `/cue/selected/customString`); in
QLab 5 the message protocol comes from the patch, so the cue just carries the
address. It **creates new cues each run** (doesn't update existing ones), so
delete a previous batch before re-creating; then arrange/order them in QLab as you
like.

The bridge is **on by default** (UDP `53000`, prefix `/videohive`); toggle it,
change the port, or change the prefix on the QLab tab, or from the CLI with
`--osc-port N` / `--no-osc`. It needs `python-osc` (in `requirements.txt`); if
that isn't installed the hub still runs and the bridge reports as unavailable.

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

## Hub setup (Raspberry Pi)

`hub/install-hub.sh` installs the hub on a Pi as a production service:
**push it, run it.** It installs Python + ffmpeg, clones the repo, builds a
venv, and runs the hub as a **systemd service** — so it starts on boot (comes
back after a power outage), restarts if it crashes, and the hardware watchdog
reboots the Pi if the whole system hangs.

```bash
scp hub/install-hub.sh admin@<hub-pi>:~
ssh admin@<hub-pi> 'sudo HUB_HOSTNAME=videohive-hub bash install-hub.sh'
```

The hub is a headless web/OSC server, so it needs **no desktop or autologin** —
the systemd service is more robust (it starts with no login at all). It works
on either a Lite or Desktop image and won't change your boot target. Options:
`PORT` (5000), `RUN_USER`, `HUB_HOSTNAME` (for `<name>.local`), `BRANCH`, `REPO`,
`SRC` (use an existing clone). Manage with `systemctl status|restart
videowall-hub` and `journalctl -u videowall-hub -f`; update with `git pull` in
the clone + `systemctl restart` (your `store/` of workspaces survives). It
prints the address to give nodes as `HUB=<host>.local:<port>`.

## Display node setup (Raspberry Pi)

For real TVs, `node/install-node.sh` turns a fresh Pi into a permanent display
node in one step: **push it, run it, done.** It installs everything (mpv,
imagemagick, Flask), installs the node, and configures it to:

- **boot into the node** when power is applied — the Pi boots to the desktop,
  auto-logs in, and autostarts the node *inside that session*, so mpv draws on
  the session's display (the model that works reliably on a Pi — it doesn't fight
  the compositor for the screen). Requires **Raspberry Pi OS with desktop**;
- **restart on crash** (the launcher respawns the node);
- **reboot the Pi if the whole system hangs** (hardware watchdog);
- **come up ready** — pushed cues persist on disk, so after a reboot the node
  reloads its library and is immediately fireable.

```bash
scp node/install-node.sh admin@<pi-address>:~
ssh admin@<pi-address> 'sudo NODE_ID=tv00 NODE_ROTATION=0 bash install-node.sh'
```

Per-Pi settings are environment variables (all optional): `NODE_ID` (default the
hostname), `NODE_PORT` (8001), `NODE_ROTATION` (`0|90|180|270`), `RUN_USER` (the
sudo user), `SET_HOSTNAME` (1 → also name the Pi `NODE_ID` for `<id>.local`
mDNS), and **`HUB`** (e.g. `HUB=hub.local:5000`) so the node **announces itself
to the hub** — its IP is learned automatically and you assign it to a grid cell
by name (Wall → *Discovered TVs* / *TV placement*), never typing an address.
The hub learns the node's IP from the connection, so it keeps working even when
DHCP hands the TV a new address. The script **fetches `node.py` itself**: it uses a `node.py` sitting next
to it if present (copy both files for an offline install), otherwise downloads it
from GitHub (`NODE_BRANCH`, `REPO_RAW`, or `NODE_SRC=/path` to override). On
finish it prints the IP / `<id>.local` and port to enter in the hub's *TV
placement*.

Manage a node: `journalctl -t videowall-node -f` for logs, `pkill -f node.py` to
restart it (the launcher respawns it), and `/etc/videowall-node.conf` for
id/port/rotation (edit, then reboot). A reboot is needed after install for the
desktop autologin to take effect.

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
**library** and **default image**, plus a **QLab OSC bridge** (one address per
cue) that can **auto-create the Network cues in QLab**, on a Pi-class hub.
Verified end-to-end (slicing, bezel comp & toggle, compose, build/push state,
workspace isolation, default-image fill, synchronized fire, OSC-fired cues +
control, and QLab cue auto-creation) with headless nodes and a mock QLab OSC
receiver. *The QLab auto-create path is built against QLab 5's documented OSC API
but not yet run against a live QLab — see the QLab cue-type/patch constants in
`hub.py` if your QLab build needs a tweak.*

Not yet built (candidate next steps):

- Frame-tight sync hardening (PTP, per-node offset calibration, auto-tuned lead).
- Re-edit a compose cue from its saved assignment; audio routing.

The hub treats `config/wall.example.json` as a read-only **template**: on first
run it copies it to `hub/store/wall.json` (gitignored) and reads/writes the
runtime config there, so running the hub never modifies tracked files.
