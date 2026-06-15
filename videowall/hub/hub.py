#!/usr/bin/env python3
"""Video Wall Hub.

The control unit. Two phases, matching the original QLab workflow:

  BUILD (pre-production)
    Author one master image/video at the full wall format. The hub does all the
    splicing + bezel math and pushes each panel's slice to its node, filed under
    a cue ID. Heavy media crosses the LAN once, ahead of the show.

  FIRE (show time)
    A cue is fired by ID -- the hub sends every node a tiny "show cue N"
    command, synchronized so all panels flip in unison. No media moves, so the
    flip is near-instant.

Run from this directory:

    pip install -r ../requirements.txt
    python hub.py --config ../config/wall.example.json
    # open http://localhost:5000
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
from PIL import Image, ImageOps

import geometry
import slicer
import tiler

app = Flask(__name__, static_folder="static")
CORS(app)

CUE_STORE = Path(os.path.dirname(os.path.abspath(__file__))) / "cue_store"
CUES_JSON = CUE_STORE / "cues.json"

STATE = {
    "config_path": None,
    "config": None,
    "cues": {},          # cue_id -> metadata
    "build_jobs": {},    # job_id -> status
}

# Lead time before a synchronized flip (seconds). Must exceed worst-case node
# command latency. Show-time commands are tiny, so this can be small.
DEFAULT_FIRE_LEAD = 0.20
DEFAULT_VIDEO_LEAD = 0.8


# --------------------------------------------------------------------------- #
# Config & cue persistence
# --------------------------------------------------------------------------- #
def load_config(path):
    with open(path) as f:
        STATE["config"] = json.load(f)
    STATE["config_path"] = path


def save_config():
    with open(STATE["config_path"], "w") as f:
        json.dump(STATE["config"], f, indent=2)


def load_cues():
    if CUES_JSON.exists():
        STATE["cues"] = json.loads(CUES_JSON.read_text())


def save_cues():
    CUE_STORE.mkdir(parents=True, exist_ok=True)
    CUES_JSON.write_text(json.dumps(STATE["cues"], indent=2))


def current_panel():
    cfg = STATE["config"]
    layout = geometry.LAYOUTS[cfg["layout"]]
    return geometry.PanelSpec.from_dict(cfg["panels"][layout["orientation"]]), layout


def current_tiles():
    panel, layout = current_panel()
    tiles, cw, ch = geometry.build_tiles(layout["rows"], layout["cols"], panel)
    return tiles, cw, ch, panel, layout


def ppu_for(panel):
    return panel.res_w / panel.active_w


def node_for(row, col):
    return STATE["config"]["nodes"].get(f"{row},{col}")


def slugify(s):
    keep = "".join(c if c.isalnum() or c in "-_" else "-" for c in s.strip().lower())
    return "-".join(filter(None, keep.split("-"))) or f"cue-{int(time.time())}"


# --------------------------------------------------------------------------- #
# Node communication
# --------------------------------------------------------------------------- #
def node_url(node, path):
    return f"http://{node['host']}:{node['port']}{path}"


def post_targets(targets, path, **kwargs):
    """POST to many (key, node) concurrently. Returns {key: (ok, detail)}."""
    def _one(key, node):
        try:
            r = requests.post(node_url(node, path), timeout=10, **kwargs)
            return key, (r.ok, r.text[:200])
        except Exception as e:
            return key, (False, str(e))
    with ThreadPoolExecutor(max_workers=max(1, len(targets))) as ex:
        return dict(ex.map(lambda kn: _one(*kn), targets))


def all_node_items():
    return [(k, n) for k, n in STATE["config"]["nodes"].items()]


# --------------------------------------------------------------------------- #
# Image helpers
# --------------------------------------------------------------------------- #
def fit_single(src, panel, fit):
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


def png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def slice_for_mode(src, mode, target):
    """Return {(row,col): (filename, png_bytes)} for the given mode."""
    tiles, cw, ch, panel, layout = current_tiles()
    fit = STATE["config"].get("fit", "cover")
    staged = {}
    if mode == "span":
        for (r, c), img in slicer.slice_image(src, tiles, cw, ch, fit,
                                               ppu_for(panel)).items():
            staged[(r, c)] = (f"r{r}c{c}.png", png_bytes(img))
    elif mode == "mirror":
        payload = png_bytes(fit_single(src, panel, fit))
        for t in tiles:
            staged[(t.row, t.col)] = (f"r{t.row}c{t.col}.png", payload)
    elif mode == "solo":
        r, c = target
        staged[(r, c)] = (f"r{r}c{c}.png", png_bytes(fit_single(src, panel, fit)))
    else:
        raise ValueError(f"unknown mode {mode!r}")
    return staged, (tiles, cw, ch, panel, layout)


# --------------------------------------------------------------------------- #
# Routes: state / config
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
        "rows": layout["rows"], "cols": layout["cols"],
        "orientation": layout["orientation"],
        "nodes": cfg["nodes"],
        "panel": panel.__dict__,
        "authoring": geometry.authoring_target(layout["rows"], layout["cols"], panel),
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
    return jsonify({"ok": True})


@app.route("/api/nodes", methods=["POST"])
def api_nodes():
    """Grid configuration tool: replace the node<->coordinate mapping."""
    data = request.json or {}
    nodes = data.get("nodes")
    if not isinstance(nodes, dict):
        return jsonify({"error": "nodes must be an object"}), 400
    STATE["config"]["nodes"] = nodes
    save_config()
    return jsonify({"ok": True, "nodes": nodes})


@app.route("/api/nodes/status")
def api_nodes_status():
    def _ping(key, node):
        try:
            r = requests.get(node_url(node, "/status"), timeout=2)
            return key, (r.ok, r.json() if r.ok else r.text)
        except Exception as e:
            return key, (False, str(e))
    items = all_node_items()
    with ThreadPoolExecutor(max_workers=max(1, len(items))) as ex:
        res = dict(ex.map(lambda kn: _ping(*kn), items))
    return jsonify({k: {"online": ok, "detail": d} for k, (ok, d) in res.items()})


@app.route("/api/node/identify", methods=["POST"])
def api_node_identify():
    data = request.json or {}
    key = data.get("key")
    node = STATE["config"]["nodes"].get(key)
    if not node:
        return jsonify({"error": "unknown node"}), 404
    res = post_targets([(key, node)], "/identify", json={"label": key})
    return jsonify({"ok": True, "result": res})


# --------------------------------------------------------------------------- #
# Routes: BUILD (prep phase)
# --------------------------------------------------------------------------- #
@app.route("/api/preview", methods=["POST"])
def api_preview():
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    mode = request.form.get("mode", "span")
    target = parse_target(request.form.get("target"))
    src = Image.open(request.files["file"].stream)
    staged, (tiles, cw, ch, panel, layout) = slice_for_mode(src, mode, target)
    imgs = {k: Image.open(io.BytesIO(p)) for k, (_, p) in staged.items()}
    mockup = slicer.wall_mockup(imgs, layout["rows"], layout["cols"], panel)
    buf = io.BytesIO()
    mockup.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/api/cue/build", methods=["POST"])
def api_cue_build():
    """Slice a master image and distribute slices to nodes under a cue ID."""
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    name = request.form.get("name") or request.files["file"].filename
    cue_id = slugify(request.form.get("cue_id") or name)
    mode = request.form.get("mode", "span")
    target = parse_target(request.form.get("target"))

    src = Image.open(request.files["file"].stream)
    staged, _ = slice_for_mode(src, mode, target)

    dist = distribute(cue_id, staged, kind="image", loop=False)
    STATE["cues"][cue_id] = {
        "id": cue_id, "name": name, "type": "image", "mode": mode,
        "layout": STATE["config"]["layout"], "panels": list(dist["targets"]),
        "created": time.time(),
    }
    save_cues()
    return jsonify({"ok": True, "cue_id": cue_id, "distribute": dist["result"]})


@app.route("/api/cue/build_video", methods=["POST"])
def api_cue_build_video():
    """Tile a master video and distribute tile files to nodes under a cue ID."""
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    name = request.form.get("name") or request.files["file"].filename
    cue_id = slugify(request.form.get("cue_id") or name)

    CUE_STORE.mkdir(parents=True, exist_ok=True)
    src_path = CUE_STORE / f"_src_{cue_id}.mp4"
    request.files["file"].save(src_path)

    job_id = str(int(time.time() * 1000))
    STATE["build_jobs"][job_id] = {"state": "tiling", "done": 0, "total": 0}
    threading.Thread(target=_build_video_worker,
                     args=(job_id, cue_id, name, src_path), daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id, "cue_id": cue_id})


def _build_video_worker(job_id, cue_id, name, src_path):
    job = STATE["build_jobs"][job_id]
    try:
        tiles, cw, ch, panel, layout = current_tiles()
        fit = STATE["config"].get("fit", "cover")
        out_dir = CUE_STORE / f"tiles_{cue_id}"
        job["total"] = len(tiles)
        files = tiler.tile_video(src_path, out_dir, tiles, cw, ch, fit,
                                 progress=lambda d, t, k: job.update(done=d))
        job["state"] = "distributing"
        targets = []
        for (r, c), path in files.items():
            node = node_for(r, c)
            if not node:
                continue
            with open(path, "rb") as fh:
                requests.post(node_url(node, "/stage"),
                              files={"file": (path.name, fh)},
                              data={"cue_id": cue_id, "kind": "video", "loop": "0"},
                              timeout=120)
            targets.append(f"{r},{c}")
        STATE["cues"][cue_id] = {
            "id": cue_id, "name": name, "type": "video", "mode": "span",
            "layout": STATE["config"]["layout"], "panels": targets,
            "created": time.time(),
        }
        save_cues()
        job["state"] = "ready"
        job["cue_id"] = cue_id
    except Exception as e:
        job["state"] = "error"
        job["error"] = str(e)


@app.route("/api/cue/build_video/status/<job_id>")
def api_build_status(job_id):
    return jsonify(STATE["build_jobs"].get(job_id, {"state": "unknown"}))


def distribute(cue_id, staged, kind, loop):
    """Push each slice to its node, filed under cue_id (prep phase)."""
    targets = []

    def _stage(key, payload):
        r, c = key
        node = node_for(r, c)
        if not node:
            return key, (False, "no node")
        fname, data = payload
        try:
            resp = requests.post(
                node_url(node, "/stage"),
                files={"file": (fname, io.BytesIO(data))},
                data={"cue_id": cue_id, "kind": kind, "loop": "1" if loop else "0"},
                timeout=30)
            return key, (resp.ok, resp.text[:120])
        except Exception as e:
            return key, (False, str(e))

    with ThreadPoolExecutor(max_workers=max(1, len(staged))) as ex:
        res = dict(ex.map(lambda kp: _stage(*kp), staged.items()))
    for k, (ok, _) in res.items():
        if ok:
            targets.append(f"{k[0]},{k[1]}")
    return {"result": {f"{r},{c}": v for (r, c), v in res.items()},
            "targets": targets}


# --------------------------------------------------------------------------- #
# Routes: cue library + FIRE (show time)
# --------------------------------------------------------------------------- #
@app.route("/api/cues")
def api_cues():
    return jsonify(STATE["cues"])


@app.route("/api/cue/fire", methods=["POST"])
def api_cue_fire():
    """Show a pre-built cue on every panel that has it, synchronized."""
    data = request.json or {}
    cue_id = data.get("cue_id")
    cue = STATE["cues"].get(cue_id)
    if not cue:
        return jsonify({"error": f"unknown cue {cue_id!r}"}), 404
    loop = bool(data.get("loop", False))
    lead = float(data.get("lead",
                          DEFAULT_VIDEO_LEAD if cue["type"] == "video"
                          else DEFAULT_FIRE_LEAD))

    show_at = time.time() + lead
    targets = [(k, STATE["config"]["nodes"][k])
               for k in cue["panels"] if k in STATE["config"]["nodes"]]
    res = post_targets(targets, "/show_at",
                       json={"cue_id": cue_id, "at": show_at, "loop": loop})
    return jsonify({"ok": True, "cue_id": cue_id, "show_at": show_at, "nodes": res})


@app.route("/api/cue/delete", methods=["POST"])
def api_cue_delete():
    cue_id = (request.json or {}).get("cue_id")
    cue = STATE["cues"].pop(cue_id, None)
    if not cue:
        return jsonify({"error": "unknown cue"}), 404
    targets = [(k, STATE["config"]["nodes"][k])
               for k in cue["panels"] if k in STATE["config"]["nodes"]]
    post_targets(targets, "/forget", json={"cue_id": cue_id})
    save_cues()
    return jsonify({"ok": True, "cue_id": cue_id})


@app.route("/api/control/<action>", methods=["POST"])
def api_control(action):
    if action not in ("stop", "clear", "black"):
        return jsonify({"error": "invalid action"}), 400
    return jsonify({"ok": True, "nodes": post_targets(all_node_items(), f"/{action}")})


def parse_target(s):
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
    load_cues()
    print("=" * 60)
    print("Video Hive Hub")
    print("=" * 60)
    print(f"Config : {args.config}")
    print(f"Layout : {STATE['config']['layout']}")
    print(f"Nodes  : {len(STATE['config']['nodes'])}")
    print(f"Cues   : {len(STATE['cues'])}")
    print(f"Open   : http://localhost:{args.port}")
    print("=" * 60)
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
