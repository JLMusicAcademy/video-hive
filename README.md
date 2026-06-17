# Video Hive

A networked **video wall**: a control **hub** does all the editing (slicing,
bezel math, video tiling) and a thin **display node** — one Raspberry Pi per TV —
shows its assigned piece. Author one master at the full wall format; the hub
splices it and pushes the right piece to the right TV, then fires lightweight,
wall-clock-synchronized cues at show time. QLab can drive the whole show over OSC.

## Where things are

- **[`videowall/`](videowall/README.md)** — the project. Hub, display node,
  layouts/slicer/tiler, the web UI, and the QLab OSC bridge.
- **[`videowall/node/install-node.sh`](videowall/node/install-node.sh)** — one
  script to turn a fresh Raspberry Pi into a display node (auto-start on boot,
  restart on crash, ready fast). See *Display node setup* in the videowall README.
- **[`legacy/`](legacy/README.md)** — the original single-display QLab media
  player this grew out of. Archived; not used by the video wall.

## Quick start

```bash
cd videowall
pip install -r requirements.txt
cd hub && python hub.py --config ../config/wall.example.json   # http://localhost:5000
```

Then set up one Pi per TV with `videowall/node/install-node.sh`. Full docs:
**[videowall/README.md](videowall/README.md)**.
