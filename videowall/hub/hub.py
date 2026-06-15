#!/usr/bin/env python3
"""Video Wall Hub.

The control unit. It holds the wall layout, slices images / pre-tiles videos,
and orchestrates the display nodes (one Raspberry Pi per TV).

Run from this directory:

    pip install -r ../requirements.txt
    python hub.py --config ../config/wall.example.json

Then open http://localhost:5000

Synchronized display (stage-then-commit)
----------------------------------------
To keep every panel flipping in unison, the hub never tells a node to "show
now". Instead it:

  1. STAGES every tile on its node (the slow, variable-latency file transfer),
     and waits until all nodes report ready.
  2. Broadcasts a single SHOW-AT timestamp a short lead time in the future.

Each node schedules the actual flip against its own (NTP-synced) clock, so the
visible change lands on the same wall-clock instant on every panel regardless
of network jitter. The same mechanism drives synchronized video playback.
"""

import argparse
import io
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS

import geometry
import slicer
import tiler

app = Flask(__name__, static_folder="static")
CORS(app)

STATE = {
    "config_path": None,
    "config": None,
    "video_jobs": {},   # job_id -> status dict
}

# How far in the future to schedule a synchronized flip, in seconds. Must
# comfortably exceed worst-case node command latency on your LAN.
DEFAULT_SHOW_LEAD = 0.30


# --------------------------------------------------------------------------- #
# Config & geometry
# --------------------------------------------------------------------------- #
def load_config(path):
    with open(path) as f:
        cfg = json.load(f)
    STATE["config"] = cfg
    STATE["config_path"] = path
    return cfg


def save_config():
    with open(STATE["config_path"], "w") as f:
        json.dump(STATE["config"], f, indent=2)


def current_panel():
    cfg = STATE["config"]
    layout = geometry.LAYOUTS[cfg["layout"]]
    panel_dict = cfg["panels"][layout["orientation"]]
    return geometry.PanelSpec.from_dict(panel_dict), layout


def current_tiles():
    panel, layout = current_panel()
    tiles, cw, ch = geometry.build_tiles(layout["rows"], layout["cols"], panel)
    return tiles, cw, ch, panel, layout


def ppu_for(panel):
    """Pixels-per-physical-unit so each panel renders at >= its resolution."""
    return panel.res_w / panel.active_w


def node_for(row, col):
    return STATE["config"]["nodes"].get(f"{row},{col}")


# --------------------------------------------------------------------------- #
# Node communication
# --------------------------------------------------------------------------- #
def node_url(node, path):
    return f"http://{node['host']}:{node['port']}{path}"


def post_all(targets, path, **kwargs):
    """POST `path` to every (key, node) in `targets` concurrently.

    Returns {key: (ok, detail)}.
    """
    results = {}

    def _one(key, node):
        try:
            r = requests.post(node_url(node, path), timeout=10, **kwargs)
            return key, (r.ok, r.text[:200])
        except Exception as e:
            return key, (False, str(e))

    with ThreadPoolExecutor(max_workers=max(1, len(targets))) as ex:
        for key, res in ex.map(lambda kn: _one(*kn), targets):
            results[key] = res
    return results


def stage_and_show(staged_files, kind, loop=False, lead=DEFAULT_SHOW_LEAD):
    """Stage already-local files on each node, then broadcast a synced show.

    `staged_files` is {(row, col): (filename, bytes)}.
    """
    targets = []
    for (r, c), (fname, _) in staged_files.items():
        node = node_for(r, c)
        if node:
            targets.append(((r, c), node))

    # Phase 1: transfer + stage (absorbs network jitter here, not at flip time)
    def _stage(key, node):
        fname, payload = staged_files[key]
        try:
            r = requests.post(
                node_url(node, "/stage"),
                files={"file": (fname, io.BytesIO(payload))},
                data={"kind": kind, "loop": "1" if loop else "0"},
                timeout=30,
            )
            return key, (r.ok, r.text[:200])
        except Exception as e:
            return key, (False, str(e))

    with ThreadPoolExecutor(max_workers=max(1, len(targets))) as ex:
        stage_res = dict(ex.map(lambda kn: _stage(*kn), targets))

    ready = [k for k, (ok, _) in stage_res.items() if ok]

    # Phase 2: one common wall-clock instant for everyone to flip.
    show_at = time.time() + lead
    show_res = post_all(
        [(k, node_for(*k)) for k in ready],
        "/show_at",
        json={"at": show_at},
    )
    return {
        "show_at": show_at,
        "stage": {f"{r},{c}": v for (r, c), v in stage_res.items()},
        "show": {f"{r},{c}": v for (r, c), v in show_res.items()},
    }


# --------------------------------------------------------------------------- #
# Routes: static / info
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/state")
def api_state():
    cfg = STATE["config"]
    tiles, cw, ch, panel, layout = current_tiles()
    return jsonify({
        "layout": cfg["layout"],
        "fit": cfg.get("fit", "cover"),
        "layouts": list(geometry.LAYOUTS.keys()),
        "rows": layout["rows"],
        "cols": layout["cols"],
        "orientation": layout["orientation"],
        "nodes": cfg["nodes"],
        "panel": panel.__dict__,
        "tiles": [t.__dict__ for t in tiles],
    })


@app.route("/api/layout", methods=["POST"])
def api_layout():
    data = request.json or {}
    name = data.get("layout")
    if name not in geometry.LAYOUTS:
        return jsonify({"error": f"unknown layout {name!r}"}), 400
    STATE["config"]["layout"] = name
    if "fit" in data:
        STATE["config"]["fit"] = data["fit"]
    save_config()
    return jsonify({"ok": True, "layout": name})


@app.route("/api/nodes/status")
def api_nodes_status():
    nodes = STATE["config"]["nodes"]
    targets = [(k, n) for k, n in nodes.items()]

    def _ping(key, node):
        try:
            r = requests.get(node_url(node, "/status"), timeout=2)
            return key, (r.ok, r.json() if r.ok else r.text)
        except Exception as e:
            return key, (False, str(e))

    with ThreadPoolExecutor(max_workers=max(1, len(targets))) as ex:
        res = dict(ex.map(lambda kn: _ping(*kn), targets))
    return jsonify({k: {"online": ok, "detail": d} for k, (ok, d) in res.items()})


# --------------------------------------------------------------------------- #
# Routes: images
# --------------------------------------------------------------------------- #
def _slice_uploaded_image(mode, target):
    """Return {(row,col): (filename, png_bytes)} for the current upload."""
    from PIL import Image
    src = Image.open(request.files["file"].stream)
    tiles, cw, ch, panel, layout = current_tiles()
    fit = STATE["config"].get("fit", "cover")

    staged = {}
    if mode == "span":
        imgs = slicer.slice_image(src, tiles, cw, ch, fit, ppu_for(panel))
        for (r, c), img in imgs.items():
            staged[(r, c)] = (f"tile_r{r}c{c}.png", _png_bytes(img))
    elif mode == "mirror":
        # Whole image, fitted to a single panel, sent to every panel.
        whole = _fit_single(src, panel, fit)
        payload = (_png_bytes(whole))
        for t in tiles:
            staged[(t.row, t.col)] = (f"mirror_r{t.row}c{t.col}.png", payload)
    elif mode == "solo":
        r, c = target
        whole = _fit_single(src, panel, fit)
        staged[(r, c)] = (f"solo_r{r}c{c}.png", _png_bytes(whole))
    else:
        raise ValueError(f"unknown mode {mode!r}")
    return staged, (tiles, cw, ch, panel, layout)


def _fit_single(src, panel, fit):
    """Fit a whole image onto a single panel's resolution."""
    from PIL import Image, ImageOps
    src = src.convert("RGB")
    size = (panel.res_w, panel.res_h)
    if fit == "stretch":
        return src.resize(size, Image.LANCZOS)
    if fit == "contain":
        canvas = Image.new("RGB", size, (0, 0, 0))
        fitted = ImageOps.contain(src, size, Image.LANCZOS)
        canvas.paste(fitted, ((size[0] - fitted.width) // 2,
                              (size[1] - fitted.height) // 2))
        return canvas
    return ImageOps.fit(src, size, method=Image.LANCZOS)


def _png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@app.route("/api/image/send", methods=["POST"])
def api_image_send():
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    mode = request.form.get("mode", "span")
    target = _parse_target(request.form.get("target"))
    lead = float(request.form.get("lead", DEFAULT_SHOW_LEAD))

    staged, _ = _slice_uploaded_image(mode, target)
    result = stage_and_show(staged, kind="image", loop=False, lead=lead)
    return jsonify({"ok": True, "mode": mode, **result})


@app.route("/api/image/preview", methods=["POST"])
def api_image_preview():
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    mode = request.form.get("mode", "span")
    target = _parse_target(request.form.get("target"))
    staged, (tiles, cw, ch, panel, layout) = _slice_uploaded_image(mode, target)

    from PIL import Image
    imgs = {}
    for (r, c), (_, payload) in staged.items():
        imgs[(r, c)] = Image.open(io.BytesIO(payload))
    mockup = slicer.wall_mockup(imgs, layout["rows"], layout["cols"], panel)
    buf = io.BytesIO()
    mockup.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


# --------------------------------------------------------------------------- #
# Routes: video (pre-processed, then synchronized playback)
# --------------------------------------------------------------------------- #
@app.route("/api/video/prepare", methods=["POST"])
def api_video_prepare():
    """Tile a source video and distribute the tiles to the nodes.

    Runs in a background thread; poll /api/video/status/<job_id>.
    """
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400

    work = Path("_work")
    work.mkdir(exist_ok=True)
    src_path = work / "source.mp4"
    request.files["file"].save(src_path)

    job_id = str(int(time.time() * 1000))
    STATE["video_jobs"][job_id] = {"state": "tiling", "done": 0, "total": 0}

    threading.Thread(target=_prepare_worker, args=(job_id, src_path),
                     daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id})


def _prepare_worker(job_id, src_path):
    job = STATE["video_jobs"][job_id]
    try:
        tiles, cw, ch, panel, layout = current_tiles()
        fit = STATE["config"].get("fit", "cover")
        out_dir = Path("_work") / f"tiles_{job_id}"
        job["total"] = len(tiles)

        def progress(done, total, key):
            job["done"] = done

        files = tiler.tile_video(src_path, out_dir, tiles, cw, ch, fit,
                                 progress=progress)

        job["state"] = "distributing"
        for (r, c), path in files.items():
            node = node_for(r, c)
            if not node:
                continue
            with open(path, "rb") as fh:
                requests.post(
                    node_url(node, "/stage"),
                    files={"file": (path.name, fh)},
                    data={"kind": "video", "loop": "0"},
                    timeout=120,
                )
        job["state"] = "ready"
    except Exception as e:
        job["state"] = "error"
        job["error"] = str(e)


@app.route("/api/video/status/<job_id>")
def api_video_status(job_id):
    return jsonify(STATE["video_jobs"].get(job_id, {"state": "unknown"}))


@app.route("/api/video/play", methods=["POST"])
def api_video_play():
    """Start the staged video on every node at one synchronized instant."""
    data = request.json or {}
    lead = float(data.get("lead", 1.0))   # video wants a little more lead
    loop = bool(data.get("loop", False))
    show_at = time.time() + lead
    targets = [(k, n) for k, n in STATE["config"]["nodes"].items()]
    res = post_all(targets, "/show_at", json={"at": show_at, "loop": loop})
    return jsonify({"ok": True, "show_at": show_at,
                    "nodes": {k: v for k, v in res.items()}})


# --------------------------------------------------------------------------- #
# Routes: control
# --------------------------------------------------------------------------- #
@app.route("/api/control/<action>", methods=["POST"])
def api_control(action):
    if action not in ("stop", "clear", "black"):
        return jsonify({"error": "invalid action"}), 400
    targets = [(k, n) for k, n in STATE["config"]["nodes"].items()]
    res = post_all(targets, f"/{action}")
    return jsonify({"ok": True, "nodes": res})


def _parse_target(s):
    if not s:
        return (0, 0)
    r, c = s.split(",")
    return (int(r), int(c))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="../config/wall.example.json")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5000)
    args = ap.parse_args()

    load_config(args.config)
    print("=" * 60)
    print("Video Wall Hub")
    print("=" * 60)
    print(f"Config : {args.config}")
    print(f"Layout : {STATE['config']['layout']}")
    print(f"Nodes  : {len(STATE['config']['nodes'])}")
    print(f"Open   : http://localhost:{args.port}")
    print("=" * 60)
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
