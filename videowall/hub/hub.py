#!/usr/bin/env python3
"""Video Hive Hub.

A *workspace* is a named, ordered set of cues (QLab-style). Workflow:

  EDIT      Open/create a workspace, add cues, and configure each one (mode,
            sources, compose). Building a cue slices it and stores the pieces on
            the hub. A cue is then a DRAFT until it is pushed.
  PUSH      Send a cue's (or the whole workspace's) pre-built pieces to the
            display clients. A pushed cue is READY. Editing a cue makes it a
            draft again. This is the pre-production step.
  RUN       GO fires the standby cue (only if READY) -- a tiny synchronized
            command, no media moves -- then advances to the next cue.

Run from this directory:

    pip install -r ../requirements.txt
    python hub.py --config ../config/wall.example.json
    # open http://localhost:5000
"""

import argparse
import base64
import copy
import io
import json
import os
import shutil
import socket
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

try:                                              # the QLab OSC bridge is optional
    from pythonosc.dispatcher import Dispatcher
    from pythonosc.osc_server import ThreadingOSCUDPServer
    from pythonosc.udp_client import SimpleUDPClient
    HAVE_OSC = True
except ImportError:
    HAVE_OSC = False

try:                                              # mDNS node discovery is optional
    from zeroconf import Zeroconf, ServiceBrowser
    HAVE_ZEROCONF = True
except ImportError:
    HAVE_ZEROCONF = False

MDNS_NODE_TYPE = "_videohive-node._tcp.local."

app = Flask(__name__, static_folder="static")
CORS(app)

STORE = Path(os.path.dirname(os.path.abspath(__file__))) / "store"
LIB_DIR = STORE / "library"
WS_DIR = STORE / "workspaces"
LIB_JSON = STORE / "library.json"
SETTINGS_JSON = STORE / "settings.json"

STATE = {
    "config_path": None,
    "config": None,
    "library": {},
    "settings": {},
    "workspace": None,     # active workspace dict (cached)
    "build_jobs": {},
    "registry": {},        # node_id -> {ip, port, rotation, last_seen} (self-registered)
}

NODE_ONLINE_SEC = 60       # a registered node counts as "online" if seen within this

# Live state of the QLab->hub OSC listener (the bridge).
OSC = {"server": None, "thread": None, "running": False, "port": None}

DEFAULT_FIRE_LEAD = 0.20
DEFAULT_VIDEO_LEAD = 0.8
DEFAULT_OSC_PORT = 53000
DEFAULT_OSC_PREFIX = "/videohive"
DEFAULT_QLAB_PORT = 53000        # QLab listens for OSC control here by default
QLAB_CUE_TYPE = "network"        # /new type string for an OSC/Network cue (QLab 5)


# --------------------------------------------------------------------------- #
# Wall config
# --------------------------------------------------------------------------- #
def load_config(template_path):
    """Load the wall config from the runtime store (gitignored). On first run,
    seed it from the given template (e.g. wall.example.json) -- after that the
    template is never written to, so it stays clean for `git pull`."""
    STORE.mkdir(parents=True, exist_ok=True)
    runtime = STORE / "wall.json"
    if runtime.exists():
        STATE["config"] = json.loads(runtime.read_text())
    else:
        STATE["config"] = json.loads(Path(template_path).read_text())
        runtime.write_text(json.dumps(STATE["config"], indent=2))
    STATE["config_path"] = str(runtime)


def save_config():
    with open(STATE["config_path"], "w") as f:
        json.dump(STATE["config"], f, indent=2)


def default_wall():
    """The system-default wall (the template new workspaces inherit)."""
    cfg = STATE["config"]
    return {
        "layout": cfg["layout"],
        "fit": cfg.get("fit", "cover"),
        "bezel_comp": cfg.get("bezel_comp", True),
        "panels": cfg["panels"],
        "nodes": cfg.get("nodes", {}),
    }


def effective_config():
    """The one wall grid, system-wide. Every workspace uses it -- there is no
    per-workspace grid."""
    return default_wall()


def grid_view(grid):
    """Computed, client-friendly view of a grid dict."""
    name = grid["layout"] if grid["layout"] in geometry.LAYOUTS else next(iter(geometry.LAYOUTS))
    layout = geometry.LAYOUTS[name]
    panel = geometry.PanelSpec.from_dict(grid["panels"][layout["orientation"]])
    return {
        "layout": name, "fit": grid.get("fit", "cover"),
        "bezel_comp": grid.get("bezel_comp", True),
        "rows": layout["rows"], "cols": layout["cols"],
        "orientation": layout["orientation"], "nodes": grid.get("nodes", {}),
        "panel": panel.__dict__,
        "authoring": geometry.authoring_target(layout["rows"], layout["cols"], panel),
    }


def eff_nodes():
    return effective_config().get("nodes", {})


def current_panel():
    cfg = effective_config()
    name = cfg["layout"] if cfg["layout"] in geometry.LAYOUTS else next(iter(geometry.LAYOUTS))
    layout = geometry.LAYOUTS[name]
    return geometry.PanelSpec.from_dict(cfg["panels"][layout["orientation"]]), layout


def current_tiles():
    panel, layout = current_panel()
    bezel_comp = effective_config().get("bezel_comp", True)
    tiles, cw, ch = geometry.build_tiles(layout["rows"], layout["cols"], panel,
                                         bezel_comp)
    return tiles, cw, ch, panel, layout


def ppu_for(panel):
    return panel.res_w / panel.active_w


def resolve_node(entry):
    """Turn a TV-placement entry into a concrete {host, port}, or None.

    An entry is either a self-registered node by id -- {"node": "tv01"} -- which
    we resolve to its last-known IP from the registry, or an explicit
    {"host", "port"} (manual/legacy). Resolving by id means a TV's IP can change
    (DHCP) and the mapping still works as long as it keeps registering."""
    if not entry:
        return None
    if entry.get("node"):
        reg = STATE["registry"].get(entry["node"])
        if reg:
            return {"host": reg["ip"], "port": reg.get("port", 8001)}
        return None
    if entry.get("host"):
        return {"host": entry["host"], "port": entry.get("port", 8001)}
    return None


def node_for(row, col):
    return resolve_node(eff_nodes().get(f"{row},{col}"))


def slugify(s):
    keep = "".join(c if c.isalnum() or c in "-_" else "-" for c in s.strip().lower())
    return "-".join(filter(None, keep.split("-"))) or f"id-{int(time.time())}"


# --------------------------------------------------------------------------- #
# Library / settings / workspaces persistence
# --------------------------------------------------------------------------- #
def load_library():
    STATE["library"] = json.loads(LIB_JSON.read_text()) if LIB_JSON.exists() else {}


def save_library():
    LIB_JSON.write_text(json.dumps(STATE["library"], indent=2))


def load_settings():
    STATE["settings"] = (json.loads(SETTINGS_JSON.read_text())
                         if SETTINGS_JSON.exists() else {})


def save_settings():
    SETTINGS_JSON.write_text(json.dumps(STATE["settings"], indent=2))


def library_image(img_id):
    meta = STATE["library"].get(img_id) or STATE["library"]["black"]
    return Image.open(STORE / meta["file"]).convert("RGB")


def add_library_image(name, fileobj, workspace=None):
    img_id = slugify(name)
    base, n = img_id, 1
    while img_id in STATE["library"]:
        img_id = f"{base}-{n}"; n += 1
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    rel = f"library/{img_id}.png"
    Image.open(fileobj).convert("RGB").save(STORE / rel)
    STATE["library"][img_id] = {"name": name, "file": rel, "builtin": False,
                                "workspace": workspace}
    save_library()
    return img_id


def default_image_id():
    ws = active_workspace()
    return (ws.get("default_image") or STATE["settings"].get("default_image")
            or "black")


def workspace_path(ws_id):
    return WS_DIR / f"{ws_id}.json"


def list_workspaces():
    out = []
    for p in sorted(WS_DIR.glob("*.json")):
        d = json.loads(p.read_text())
        out.append({"id": d["id"], "name": d["name"],
                    "cues": len(d.get("cues", {})), "created": d.get("created")})
    return out


def save_workspace(ws):
    WS_DIR.mkdir(parents=True, exist_ok=True)
    workspace_path(ws["id"]).write_text(json.dumps(ws, indent=2))


def create_workspace(name):
    ws_id = slugify(name)
    base, n = ws_id, 1
    while workspace_path(ws_id).exists():
        ws_id = f"{base}-{n}"; n += 1
    ws = {"id": ws_id, "name": name, "default_image": None,
          "created": time.time(), "order": [], "cues": {}}
    save_workspace(ws)
    return ws


def open_workspace(ws_id):
    STATE["workspace"] = json.loads(workspace_path(ws_id).read_text())
    STATE["settings"]["active_workspace"] = ws_id
    save_settings()
    return STATE["workspace"]


def active_workspace():
    if STATE["workspace"] is None:
        wid = STATE["settings"].get("active_workspace")
        if wid and workspace_path(wid).exists():
            STATE["workspace"] = json.loads(workspace_path(wid).read_text())
        else:
            wss = list_workspaces()
            STATE["workspace"] = (json.loads(workspace_path(wss[0]["id"]).read_text())
                                  if wss else create_workspace("My Workspace"))
            STATE["settings"]["active_workspace"] = STATE["workspace"]["id"]
            save_settings()
    return STATE["workspace"]


def workspace_asset_dir(ws_id, cue_id):
    return WS_DIR / ws_id / cue_id


def ensure_store():
    for d in (STORE, LIB_DIR, WS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    load_library()
    load_settings()
    if "black" not in STATE["library"]:
        Image.new("RGB", (1920, 1920), (0, 0, 0)).save(LIB_DIR / "black.png")
        STATE["library"]["black"] = {"name": "Black", "file": "library/black.png",
                                     "builtin": True, "workspace": None}
        save_library()
    STATE["settings"].setdefault("default_image", "black")
    save_settings()
    active_workspace()


# --------------------------------------------------------------------------- #
# Node communication
# --------------------------------------------------------------------------- #
def node_url(node, path):
    return f"http://{node['host']}:{node['port']}{path}"


def post_targets(targets, path, **kwargs):
    def _one(key, node):
        try:
            r = requests.post(node_url(node, path), timeout=10, **kwargs)
            return key, (r.ok, r.text[:200])
        except Exception as e:
            return key, (False, str(e))
    with ThreadPoolExecutor(max_workers=max(1, len(targets))) as ex:
        return dict(ex.map(lambda kn: _one(*kn), targets))


def all_node_items():
    out = []
    for k, n in eff_nodes().items():
        rn = resolve_node(n)
        if rn:
            out.append((k, rn))
    return out


def known_nodes():
    """Every TV we can currently reach: those mapped in the grid plus any that
    have self-registered. De-duplicated by host:port."""
    targets = {}
    for _k, node in all_node_items():
        targets[(node["host"], node["port"])] = node
    for reg in STATE["registry"].values():
        targets.setdefault((reg["ip"], reg.get("port", 8001)),
                           {"host": reg["ip"], "port": reg.get("port", 8001)})
    return list(targets.values())


def expected_cue_ids():
    """Every node-side cue id that *should* exist -- across all workspaces."""
    ids = set()
    for p in WS_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        for cid in d.get("cues", {}):
            ids.add(node_cue_id(d["id"], cid))
    return ids


def forget_everywhere(cue_ids):
    """Tell every reachable TV to forget these node-side cue ids (best effort)."""
    cue_ids = list(cue_ids)
    if not cue_ids:
        return
    nodes = known_nodes()

    def _one(node):
        for cid in cue_ids:
            try:
                requests.post(node_url(node, "/forget"),
                              json={"cue_id": cid}, timeout=10)
            except Exception:
                pass
    if nodes:
        with ThreadPoolExecutor(max_workers=len(nodes)) as ex:
            list(ex.map(_one, nodes))


def local_ip():
    """Best-effort LAN IP of the hub -- the address QLab should send OSC to."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def ws_for(ws_id):
    """Resolve a workspace dict by id (active cache if it matches, else from
    disk). None when ws_id is given but unknown; the active workspace when not."""
    if not ws_id:
        return active_workspace()
    if STATE["workspace"] and STATE["workspace"]["id"] == ws_id:
        return STATE["workspace"]
    p = workspace_path(ws_id)
    return json.loads(p.read_text()) if p.exists() else None


def ws_nodes(ws):
    """The TV placement that a given workspace fires against (its own grid
    override if it has one, else the system default)."""
    return (ws.get("wall") or default_wall()).get("nodes", {})


def fire_cue(cue_id, ws_id=None, loop=None, lead=None, force=False):
    """Fire a cue: schedule a synchronized flip on every panel's TV at a shared
    wall-clock time. Shared by the HTTP route and the QLab OSC bridge. Returns a
    result dict; on failure it carries an HTTP-style `status`."""
    ws = ws_for(ws_id)
    if ws is None:
        return {"ok": False, "status": 404, "error": f"unknown workspace {ws_id!r}"}
    cue = ws["cues"].get(cue_id)
    if not cue:
        return {"ok": False, "status": 404, "error": f"unknown cue {cue_id!r}"}
    if not cue.get("pushed") and not force:
        return {"ok": False, "status": 409, "needs_push": True,
                "error": "cue not pushed to displays"}

    if loop is None:
        loop = bool(cue.get("loop", False))
    nodes = ws_nodes(ws)
    nid = node_cue_id(ws["id"], cue_id)
    targets = [(k, rn) for k in cue["panels"]
               if (rn := resolve_node(nodes.get(k)))]
    # Simplest possible: fire a "show now" to every panel's TV in parallel and
    # let each display flip on receipt. No clock, no scheduling.
    res = post_targets(targets, "/show", json={"cue_id": nid, "loop": bool(loop)})
    return {"ok": True, "cue_id": cue_id, "workspace": ws["id"], "nodes": res}


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
    tiles, cw, ch, panel, layout = current_tiles()
    fit = effective_config().get("fit", "cover")
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


def resolve_sources(assignments):
    sources = {"default": library_image(default_image_id())}
    for i, f in enumerate(request.files.getlist("files")):
        sources[f"u:{i}"] = Image.open(f.stream).convert("RGB")
    for a in assignments:
        s = a.get("source")
        if isinstance(s, str) and s.startswith("lib:"):
            sources.setdefault(s, library_image(s[4:]))
    return sources


def compose_images(sources, assignments):
    tiles, cw, ch, panel, layout = current_tiles()
    fit = effective_config().get("fit", "cover")
    ppu = ppu_for(panel)
    slice_cache = {}
    out = {}
    for a in assignments:
        r, c = parse_target(a["panel"])
        key = a.get("source", "default")
        src = sources.get(key, sources["default"])
        if a.get("render") == "slice":
            if key not in slice_cache:
                slice_cache[key] = slicer.slice_image(src, tiles, cw, ch, fit, ppu)
            out[(r, c)] = slice_cache[key][(r, c)]
        else:
            out[(r, c)] = fit_single(src, panel, fit)
    for t in tiles:
        out.setdefault((t.row, t.col), fit_single(sources["default"], panel, fit))
    return out, (tiles, cw, ch, panel, layout)


def black_tile(panel):
    return Image.new("RGB", (panel.res_w, panel.res_h), (0, 0, 0))


def tiles_to_dataurls(imgs, max_px=360):
    out = {}
    for (r, c), img in imgs.items():
        thumb = img.copy()
        thumb.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        thumb.save(buf, format="PNG")
        out[f"{r},{c}"] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    return out


# --------------------------------------------------------------------------- #
# Cue assets, distribution, push state
# --------------------------------------------------------------------------- #
def save_assets(ws_id, cue_id, staged):
    adir = workspace_asset_dir(ws_id, cue_id)
    adir.mkdir(parents=True, exist_ok=True)
    assets = {}
    for (r, c), (fname, data) in staged.items():
        (adir / fname).write_bytes(data)
        assets[f"{r},{c}"] = fname
    return assets


def node_cue_id(ws_id, cue_id):
    return f"{ws_id}__{cue_id}"


def distribute_cue(ws_id, cue):
    adir = workspace_asset_dir(ws_id, cue["id"])
    nid = node_cue_id(ws_id, cue["id"])
    loop = "1" if cue.get("loop") else "0"
    kind = "video" if cue["type"] == "video" else "image"

    def _one(key_fname):
        key, fname = key_fname
        r, c = parse_target(key)
        node = node_for(r, c)
        if not node:
            return key, (False, "no node")
        try:
            with open(adir / fname, "rb") as fh:
                resp = requests.post(node_url(node, "/stage"),
                                     files={"file": (fname, fh)},
                                     data={"cue_id": nid, "kind": kind, "loop": loop},
                                     timeout=120)
            return key, (resp.ok, resp.text[:120])
        except Exception as e:
            return key, (False, str(e))

    items = list(cue["assets"].items())
    with ThreadPoolExecutor(max_workers=max(1, len(items))) as ex:
        return dict(ex.map(_one, items))


def record_cue(cue):
    """Add/replace a cue in the active workspace (as a draft -- not pushed)."""
    ws = active_workspace()
    cue["pushed"] = False
    cue["built_at"] = time.time()
    ws["cues"][cue["id"]] = cue
    if cue["id"] not in ws["order"]:
        ws["order"].append(cue["id"])
    save_workspace(ws)


def cue_public(cue):
    return {k: cue[k] for k in ("id", "name", "type", "mode", "panels",
                                "pushed") if k in cue}


# --------------------------------------------------------------------------- #
# Routes: state / config
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/state")
def api_state():
    ws = active_workspace()
    eff = grid_view(effective_config())
    return jsonify({
        **eff,                                   # the one wall grid
        "layouts": list(geometry.LAYOUTS.keys()),
        "active_workspace": {"id": ws["id"], "name": ws["name"],
                             "default_image": default_image_id()},
    })


@app.route("/api/layout", methods=["POST"])
def api_layout():
    """Set the wall grid's layout / fit / bezel (one grid, system-wide)."""
    data = request.json or {}
    name = data.get("layout")
    if name not in geometry.LAYOUTS:
        return jsonify({"error": f"unknown layout {name!r}"}), 400
    grid = STATE["config"]
    grid["layout"] = name
    if "fit" in data:
        grid["fit"] = data["fit"]
    if "bezel_comp" in data:
        grid["bezel_comp"] = bool(data["bezel_comp"])
    save_config()
    return jsonify({"ok": True})


@app.route("/api/nodes", methods=["POST"])
def api_nodes():
    """Set the wall's TV placement (which physical TV sits in each cell)."""
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


def record_node(nid, ip, port, rotation=0, via="register"):
    STATE["registry"][nid] = {"ip": ip, "port": int(port),
                              "rotation": int(rotation), "last_seen": time.time(),
                              "via": via}


@app.route("/api/register", methods=["POST"])
def api_register():
    """A display node announces itself here (id + port). We record the source
    IP of the request, so a node never needs to know -- or report -- its own
    address, and the operator never types one."""
    d = request.json or {}
    nid = d.get("id")
    if not nid:
        return jsonify({"error": "id required"}), 400
    ip = d.get("ip") or request.remote_addr
    record_node(nid, ip, d.get("port", 8001), d.get("rotation", 0), via="register")
    return jsonify({"ok": True, "id": nid, "ip": ip})


# --------------------------------------------------------------------------- #
# mDNS discovery: nodes advertise _videohive-node._tcp via avahi; the hub
# browses for them. This finds nodes with no per-node hub address configured.
# --------------------------------------------------------------------------- #
class _NodeBrowserListener:
    def add_service(self, zc, type_, name):
        self._seen(zc, type_, name)

    def update_service(self, zc, type_, name):
        self._seen(zc, type_, name)

    def remove_service(self, zc, type_, name):
        pass

    def _seen(self, zc, type_, name):
        try:
            info = zc.get_service_info(type_, name, timeout=2000)
            if not info:
                return
            addrs = info.parsed_addresses() if hasattr(info, "parsed_addresses") else []
            if not addrs:
                return
            props = info.properties or {}
            nid = (props.get(b"id") or b"").decode() or name.split(".")[0]
            rotation = int((props.get(b"rotation") or b"0").decode() or 0)
            record_node(nid, addrs[0], info.port or 8001, rotation, via="mdns")
            print(f"[mdns] discovered node {nid} at {addrs[0]}:{info.port}")
        except Exception:
            pass


def start_mdns():
    if not HAVE_ZEROCONF:
        print("[mdns] zeroconf not installed -- node discovery via mDNS disabled")
        return
    try:
        zc = Zeroconf()
        ServiceBrowser(zc, MDNS_NODE_TYPE, _NodeBrowserListener())
        STATE["_zeroconf"] = zc
        print(f"[mdns] browsing for nodes ({MDNS_NODE_TYPE})")
    except Exception as e:
        print(f"[mdns] could not start: {e}")


@app.route("/api/nodes/discovered")
def api_nodes_discovered():
    """Nodes that announced themselves (push register or mDNS) -- the pick-list
    for TV placement."""
    now = time.time()
    nodes = [{"id": k, "ip": v["ip"], "port": v["port"], "rotation": v["rotation"],
              "via": v.get("via", "register"),
              "online": (now - v["last_seen"]) < NODE_ONLINE_SEC,
              "age": round(now - v["last_seen"], 1)}
             for k, v in sorted(STATE["registry"].items())]
    return jsonify({"nodes": nodes})


@app.route("/api/node/identify", methods=["POST"])
def api_node_identify():
    key = (request.json or {}).get("key")
    node = resolve_node(eff_nodes().get(key))
    if not node:
        return jsonify({"error": "node not mapped or offline"}), 404
    return jsonify({"ok": True,
                    "result": post_targets([(key, node)], "/identify",
                                           json={"label": key})})


@app.route("/api/node/reboot", methods=["POST"])
def api_node_reboot():
    """Reboot one mapped TV."""
    key = (request.json or {}).get("key")
    node = resolve_node(eff_nodes().get(key))
    if not node:
        return jsonify({"error": "node not mapped or offline"}), 404
    return jsonify({"ok": True, "result": post_targets([(key, node)], "/reboot")})


@app.route("/api/nodes/reboot_all", methods=["POST"])
def api_nodes_reboot_all():
    """Reboot every mapped TV."""
    return jsonify({"ok": True, "nodes": post_targets(all_node_items(), "/reboot")})


# --------------------------------------------------------------------------- #
# Routes: library + settings
# --------------------------------------------------------------------------- #
@app.route("/api/library")
def api_library():
    workspace = request.args.get("workspace")

    def keep(v):
        if v.get("builtin") or v.get("workspace") is None:
            return True
        return workspace is None or v.get("workspace") == workspace

    imgs = {k: v for k, v in STATE["library"].items() if keep(v)}
    return jsonify({"images": imgs, "default": default_image_id()})


@app.route("/api/library", methods=["POST"])
def api_library_add():
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    name = request.form.get("name") or request.files["file"].filename
    workspace = request.form.get("workspace") or active_workspace()["id"]
    img_id = add_library_image(name, request.files["file"].stream, workspace=workspace)
    return jsonify({"ok": True, "id": img_id})


@app.route("/api/library/<img_id>", methods=["DELETE"])
def api_library_delete(img_id):
    meta = STATE["library"].get(img_id)
    if not meta:
        return jsonify({"error": "unknown image"}), 404
    if meta.get("builtin"):
        return jsonify({"error": "cannot delete built-in image"}), 400
    try:
        os.remove(STORE / meta["file"])
    except OSError:
        pass
    del STATE["library"][img_id]
    save_library()
    return jsonify({"ok": True})


@app.route("/api/library/<img_id>/thumb")
def api_library_thumb(img_id):
    img = library_image(img_id)
    img.thumbnail((200, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/api/settings", methods=["POST"])
def api_settings():
    data = request.json or {}
    if "default_image" in data:
        STATE["settings"]["default_image"] = data["default_image"]
        save_settings()
    return jsonify({"ok": True, "settings": STATE["settings"]})


# --------------------------------------------------------------------------- #
# Routes: workspaces
# --------------------------------------------------------------------------- #
@app.route("/api/workspaces")
def api_workspaces():
    return jsonify({"workspaces": list_workspaces(), "active": active_workspace()["id"]})


@app.route("/api/workspaces", methods=["POST"])
def api_workspaces_create():
    name = (request.json or {}).get("name", "Untitled Workspace")
    ws = create_workspace(name)
    open_workspace(ws["id"])
    return jsonify({"ok": True, "id": ws["id"]})


@app.route("/api/workspace/save_as", methods=["POST"])
def api_workspace_save_as():
    """Duplicate the active workspace's settings (default image) into a new,
    empty workspace."""
    src = active_workspace()
    name = (request.json or {}).get("name") or f"{src['name']} copy"
    ws = create_workspace(name)
    ws["default_image"] = src.get("default_image")
    save_workspace(ws)
    open_workspace(ws["id"])
    return jsonify({"ok": True, "id": ws["id"]})


@app.route("/api/workspace/open", methods=["POST"])
def api_workspace_open():
    wid = (request.json or {}).get("id")
    if not workspace_path(wid).exists():
        return jsonify({"error": "unknown workspace"}), 404
    open_workspace(wid)
    return jsonify({"ok": True, "id": wid})


@app.route("/api/workspace")
def api_workspace():
    ws = active_workspace()
    cues = [cue_public(ws["cues"][cid]) for cid in ws["order"] if cid in ws["cues"]]
    ready = all(c["pushed"] for c in cues) if cues else True
    return jsonify({"id": ws["id"], "name": ws["name"],
                    "default_image": default_image_id(),
                    "all_ready": ready, "cues": cues})


@app.route("/api/workspace/<wid>", methods=["DELETE"])
def api_workspace_delete(wid):
    p = workspace_path(wid)
    if not p.exists():
        return jsonify({"error": "unknown workspace"}), 404
    d = json.loads(p.read_text())
    cue_ids = [node_cue_id(wid, cid) for cid in d.get("cues", {})]
    os.remove(p)
    shutil.rmtree(WS_DIR / wid, ignore_errors=True)
    if STATE["settings"].get("active_workspace") == wid:
        STATE["workspace"] = None
        active_workspace()
    forget_everywhere(cue_ids)              # wipe this workspace's slices off the TVs
    return jsonify({"ok": True, "forgot": len(cue_ids)})


@app.route("/api/nodes/purge", methods=["POST"])
def api_nodes_purge():
    """Housekeeping: tell every reachable TV to forget any staged cue that no
    longer belongs to a workspace (orphans left by deletes / grid changes)."""
    expected = expected_cue_ids()
    results = {}
    for node in known_nodes():
        label = f"{node['host']}:{node['port']}"
        try:
            lib = requests.get(node_url(node, "/library"), timeout=5).json()
            stale = [cid for cid in lib if cid not in expected]
            for cid in stale:
                requests.post(node_url(node, "/forget"),
                              json={"cue_id": cid}, timeout=10)
            results[label] = {"removed": stale}
        except Exception as e:
            results[label] = {"error": str(e)}
    return jsonify({"ok": True, "nodes": results})


@app.route("/api/workspace/default_image", methods=["POST"])
def api_workspace_default_image():
    img_id = (request.json or {}).get("default_image")
    ws = active_workspace()
    ws["default_image"] = img_id
    save_workspace(ws)
    return jsonify({"ok": True, "default_image": default_image_id()})


@app.route("/api/workspace/push", methods=["POST"])
def api_workspace_push():
    """Push every cue in the active workspace to the displays (pre-production)."""
    ws = active_workspace()
    results = {}
    for cid in ws["order"]:
        cue = ws["cues"].get(cid)
        if cue and cue.get("assets"):
            res = distribute_cue(ws["id"], cue)
            ok = all(v[0] for v in res.values()) if res else False
            cue["pushed"] = ok
            cue["pushed_at"] = time.time()
            results[cid] = ok
    save_workspace(ws)
    return jsonify({"ok": True, "pushed": results})


# --------------------------------------------------------------------------- #
# Routes: preview / live tiles
# --------------------------------------------------------------------------- #
@app.route("/api/preview", methods=["POST"])
def api_preview():
    mode = request.form.get("mode", "span")
    target = parse_target(request.form.get("target"))
    src = Image.open(request.files["file"].stream)
    staged, (tiles, cw, ch, panel, layout) = slice_for_mode(src, mode, target)
    imgs = {k: Image.open(io.BytesIO(p)) for k, (_, p) in staged.items()}
    mockup = slicer.wall_mockup(imgs, layout["rows"], layout["cols"], panel)
    buf = io.BytesIO(); mockup.save(buf, format="PNG"); buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/api/tiles", methods=["POST"])
def api_tiles():
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    mode = request.form.get("mode", "span")
    target = parse_target(request.form.get("target"))
    src = Image.open(request.files["file"].stream)
    staged, (tiles, cw, ch, panel, layout) = slice_for_mode(src, mode, target)
    imgs = {k: Image.open(io.BytesIO(p)) for k, (_, p) in staged.items()}
    default = fit_single(library_image(default_image_id()), panel,
                         effective_config().get("fit", "cover"))
    for t in tiles:
        imgs.setdefault((t.row, t.col), default)
    return jsonify({"tiles": tiles_to_dataurls(imgs), "rows": layout["rows"],
                    "cols": layout["cols"], "orientation": layout["orientation"]})


@app.route("/api/tiles_compose", methods=["POST"])
def api_tiles_compose():
    assignments = json.loads(request.form.get("assign", "[]"))
    sources = resolve_sources(assignments)
    imgs, (tiles, cw, ch, panel, layout) = compose_images(sources, assignments)
    return jsonify({"tiles": tiles_to_dataurls(imgs), "rows": layout["rows"],
                    "cols": layout["cols"], "orientation": layout["orientation"]})


@app.route("/api/cue/<cue_id>/tiles")
def api_cue_tiles(cue_id):
    """Preview of a cue's already-built per-panel pieces (for the editor)."""
    ws = active_workspace()
    cue = ws["cues"].get(cue_id)
    if not cue:
        return jsonify({"error": "unknown cue"}), 404
    clay = geometry.LAYOUTS.get(cue.get("layout"), current_panel()[1])
    base = {"rows": clay["rows"], "cols": clay["cols"],
            "orientation": clay["orientation"], "type": cue["type"]}
    if cue["type"] == "video":
        return jsonify({**base, "tiles": {}})
    adir = workspace_asset_dir(ws["id"], cue_id)
    imgs = {}
    for key, fname in cue["assets"].items():
        r, c = parse_target(key)
        try:
            imgs[(r, c)] = Image.open(adir / fname)
        except Exception:
            pass
    return jsonify({**base, "tiles": tiles_to_dataurls(imgs)})


# --------------------------------------------------------------------------- #
# Routes: build cues (into the active workspace, as drafts)
# --------------------------------------------------------------------------- #
@app.route("/api/cue/build", methods=["POST"])
def api_cue_build():
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    name = request.form.get("name") or request.files["file"].filename
    cue_id = resolve_cue_id(name)
    mode = request.form.get("mode", "span")
    target = parse_target(request.form.get("target"))
    ws = active_workspace()

    src = Image.open(request.files["file"].stream)
    staged, _ = slice_for_mode(src, mode, target)
    assets = save_assets(ws["id"], cue_id, staged)
    record_cue({"id": cue_id, "name": name, "type": "image", "mode": mode,
                "layout": effective_config()["layout"], "panels": list(assets.keys()),
                "assets": assets, "loop": False, "created": time.time()})
    return jsonify({"ok": True, "cue_id": cue_id})


@app.route("/api/cue/build_compose", methods=["POST"])
def api_cue_build_compose():
    assignments = json.loads(request.form.get("assign", "[]"))
    name = request.form.get("name") or "compose"
    cue_id = resolve_cue_id(name)
    ws = active_workspace()

    sources = resolve_sources(assignments)
    imgs, _ = compose_images(sources, assignments)
    staged = {(r, c): (f"r{r}c{c}.png", png_bytes(img)) for (r, c), img in imgs.items()}
    assets = save_assets(ws["id"], cue_id, staged)
    record_cue({"id": cue_id, "name": name, "type": "image", "mode": "compose",
                "layout": effective_config()["layout"], "panels": list(assets.keys()),
                "assets": assets, "assign": assignments, "loop": False,
                "created": time.time()})
    return jsonify({"ok": True, "cue_id": cue_id})


@app.route("/api/cue/build_video", methods=["POST"])
def api_cue_build_video():
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    name = request.form.get("name") or request.files["file"].filename
    cue_id = resolve_cue_id(name)
    ws = active_workspace()

    adir = workspace_asset_dir(ws["id"], cue_id)
    adir.mkdir(parents=True, exist_ok=True)
    src_path = adir / "_source.mp4"
    request.files["file"].save(src_path)

    job_id = str(int(time.time() * 1000))
    STATE["build_jobs"][job_id] = {"state": "tiling", "done": 0, "total": 0}
    threading.Thread(target=_build_video_worker,
                     args=(job_id, ws["id"], cue_id, name, src_path, adir),
                     daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id, "cue_id": cue_id})


def _build_video_worker(job_id, ws_id, cue_id, name, src_path, adir):
    job = STATE["build_jobs"][job_id]
    try:
        tiles, cw, ch, panel, layout = current_tiles()
        fit = effective_config().get("fit", "cover")
        job["total"] = len(tiles)
        files = tiler.tile_video(src_path, adir, tiles, cw, ch, fit,
                                 progress=lambda d, t, k: job.update(done=d))
        assets = {f"{r},{c}": path.name for (r, c), path in files.items()}
        cue = {"id": cue_id, "name": name, "type": "video", "mode": "span",
               "layout": effective_config()["layout"], "panels": list(assets.keys()),
               "assets": assets, "loop": False, "created": time.time(),
               "pushed": False, "built_at": time.time()}
        ws = json.loads(workspace_path(ws_id).read_text())
        ws["cues"][cue_id] = cue
        if cue_id not in ws["order"]:
            ws["order"].append(cue_id)
        save_workspace(ws)
        if STATE["workspace"] and STATE["workspace"]["id"] == ws_id:
            STATE["workspace"] = ws
        job["state"] = "ready"
        job["cue_id"] = cue_id
    except Exception as e:
        job["state"] = "error"
        msg = str(e)
        if isinstance(e, FileNotFoundError) or "ffprobe" in msg or "ffmpeg" in msg:
            msg = "ffmpeg/ffprobe not found on the hub -- install ffmpeg to build video cues"
        job["error"] = msg


@app.route("/api/cue/build_video/status/<job_id>")
def api_build_status(job_id):
    return jsonify(STATE["build_jobs"].get(job_id, {"state": "unknown"}))


# --------------------------------------------------------------------------- #
# Routes: push / fire / delete
# --------------------------------------------------------------------------- #
@app.route("/api/cue/push", methods=["POST"])
def api_cue_push():
    cue_id = (request.json or {}).get("cue_id")
    ws = active_workspace()
    cue = ws["cues"].get(cue_id)
    if not cue:
        return jsonify({"error": "unknown cue"}), 404
    res = distribute_cue(ws["id"], cue)
    ok = all(v[0] for v in res.values()) if res else False
    cue["pushed"] = ok
    cue["pushed_at"] = time.time()
    save_workspace(ws)
    return jsonify({"ok": ok, "cue_id": cue_id,
                    "nodes": {k: v[0] for k, v in res.items()}})


@app.route("/api/cue/fire", methods=["POST"])
def api_cue_fire():
    data = request.json or {}
    res = fire_cue(data.get("cue_id"), ws_id=data.get("workspace"),
                   loop=data.get("loop"), lead=data.get("lead"),
                   force=data.get("force"))
    if not res.get("ok"):
        return jsonify(res), res.pop("status", 400)
    return jsonify(res)


def resolve_cue_id(name):
    """Reuse an existing cue's id when rebuilding it (so its assets / pushes
    stay valid); otherwise derive a stable id from the name."""
    existing = request.form.get("existing_id")
    if existing and existing in active_workspace()["cues"]:
        return existing
    return slugify(request.form.get("cue_id") or name)


@app.route("/api/cue/rename", methods=["POST"])
def api_cue_rename():
    """Rename a cue's display label (its id and pushed pieces are unchanged)."""
    data = request.json or {}
    ws = active_workspace()
    cue = ws["cues"].get(data.get("cue_id"))
    if not cue:
        return jsonify({"error": "unknown cue"}), 404
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    cue["name"] = name
    save_workspace(ws)
    return jsonify({"ok": True, "name": name})


@app.route("/api/cue/reorder", methods=["POST"])
def api_cue_reorder():
    """Set the cue order for the active workspace (drag-to-reorder)."""
    order = (request.json or {}).get("order", [])
    ws = active_workspace()
    valid = [cid for cid in order if cid in ws["cues"]]
    # keep any cues not mentioned (safety) appended in their old order
    valid += [cid for cid in ws["order"] if cid not in valid]
    ws["order"] = valid
    save_workspace(ws)
    return jsonify({"ok": True, "order": valid})


@app.route("/api/cue/delete", methods=["POST"])
def api_cue_delete():
    cue_id = (request.json or {}).get("cue_id")
    ws = active_workspace()
    cue = ws["cues"].pop(cue_id, None)
    if not cue:
        return jsonify({"error": "unknown cue"}), 404
    if cue_id in ws["order"]:
        ws["order"].remove(cue_id)
    save_workspace(ws)
    nid = node_cue_id(ws["id"], cue_id)
    targets = [(k, rn) for k in cue["panels"]
               if (rn := resolve_node(eff_nodes().get(k)))]
    post_targets(targets, "/forget", json={"cue_id": nid})
    shutil.rmtree(workspace_asset_dir(ws["id"], cue_id), ignore_errors=True)
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


# --------------------------------------------------------------------------- #
# QLab <-> hub OSC bridge
#
# QLab runs the show. Each QLab Network (OSC) cue sends one address that names
# the exact Video Hive cue to fire (Option 2: one address per cue), e.g.
#     /videohive/cue/<workspace>/<cue_id>
# The hub maps that to fire_cue(), which schedules the synchronized flip. There
# is no shared playhead to drift: QLab owns the order, the address says what to
# show. Convenience control addresses: /videohive/black|clear|stop.
# --------------------------------------------------------------------------- #
def osc_settings():
    s = STATE["settings"].setdefault("osc", {})
    s.setdefault("enabled", True)
    s.setdefault("port", DEFAULT_OSC_PORT)
    s.setdefault("prefix", DEFAULT_OSC_PREFIX)
    return s


def osc_prefix():
    return "/" + osc_settings()["prefix"].strip("/")


def qlab_target():
    """Saved 'where is QLab' settings for auto-creating cues (host/port/patch)."""
    t = STATE["settings"].setdefault("qlab", {})
    t.setdefault("host", "")
    t.setdefault("port", DEFAULT_QLAB_PORT)
    t.setdefault("patch", 1)
    return t


def _osc_route(address, *args):
    """Default handler for every incoming OSC message under our prefix."""
    prefix = osc_prefix()
    if not (address == prefix or address.startswith(prefix + "/")):
        return
    parts = [p for p in address[len(prefix):].split("/") if p]
    if not parts:
        return
    head = parts[0]

    if head in ("black", "clear", "stop"):
        post_targets(all_node_items(), f"/{head}")
        print(f"[osc] control {head}")
        return

    if head == "cue":
        rest = parts[1:]
        if len(rest) >= 2:                        # /cue/<ws>/<cue_id>
            ws_id, cue_id = rest[0], rest[1]
        elif len(rest) == 1:                      # /cue/<cue_id>  (active workspace)
            ws_id, cue_id = None, rest[0]
        elif args:                                # /cue  with cue_id as an argument
            ws_id, cue_id = None, str(args[0])
        else:
            print("[osc] /cue with no cue id -- ignored")
            return
        nums = [a for a in args if isinstance(a, (int, float))]
        lead = float(nums[0]) if nums else None
        res = fire_cue(cue_id, ws_id=ws_id, lead=lead)
        if res.get("ok"):
            print(f"[osc] fire {res['workspace']}/{cue_id} @ {res['show_at']:.2f}")
        else:
            print(f"[osc] fire {ws_id or '(active)'}/{cue_id} FAILED: {res.get('error')}")
        return

    print(f"[osc] unhandled address {address!r}")


def stop_osc():
    if OSC.get("server"):
        try:
            OSC["server"].shutdown()
        except Exception:
            pass
    OSC.update(server=None, thread=None, running=False, port=None)


def start_osc():
    """(Re)start the OSC listener from current settings. Safe to call repeatedly;
    degrades quietly when disabled or when python-osc isn't installed."""
    stop_osc()
    s = osc_settings()
    if not s.get("enabled"):
        print("[osc] bridge disabled")
        return False
    if not HAVE_OSC:
        print("[osc] python-osc not installed -- bridge disabled "
              "(pip install python-osc)")
        return False
    disp = Dispatcher()
    disp.set_default_handler(_osc_route)
    try:
        server = ThreadingOSCUDPServer(("0.0.0.0", int(s["port"])), disp)
    except OSError as e:
        print(f"[osc] cannot bind udp/{s['port']}: {e}")
        return False
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    OSC.update(server=server, thread=t, running=True, port=int(s["port"]))
    print(f"[osc] listening on udp/{s['port']}  prefix {osc_prefix()}")
    return True


def osc_status():
    s = osc_settings()
    return {"enabled": bool(s["enabled"]), "port": int(s["port"]),
            "prefix": osc_prefix(), "running": OSC.get("running", False),
            "available": HAVE_OSC}


def cue_address(ws_id, cue_id):
    return f"{osc_prefix()}/cue/{ws_id}/{cue_id}"


def export_to_qlab(host, port=DEFAULT_QLAB_PORT, patch=None, passcode=None,
                   gap=0.05):
    """Auto-create one QLab Network cue per Video Hive cue in the active
    workspace. QLab runs the show; each created cue sends that cue's OSC address
    back to this hub (Option 2). We address the new cue as /cue/selected/* right
    after /new (which selects it), so no reply parsing is needed.

    In QLab 5 a Network cue's protocol is set by its *patch*, so the user makes
    one OSC patch in QLab pointed at this hub and we reference it by number; the
    message itself is the cue's address, set via /customString."""
    if not HAVE_OSC:
        return {"ok": False, "error": "python-osc is not installed on the hub"}
    ws = active_workspace()
    cues = [(cid, ws["cues"][cid]) for cid in ws["order"] if cid in ws["cues"]]
    if not cues:
        return {"ok": False, "error": "this workspace has no cues to export"}
    try:
        client = SimpleUDPClient(host, int(port))
    except Exception as e:
        return {"ok": False, "error": f"cannot open OSC to {host}:{port}: {e}"}

    def send(addr, *args):
        client.send_message(addr, list(args))
        if gap:
            time.sleep(gap)

    if passcode:
        send("/connect", str(passcode))
    made = []
    for cid, cue in cues:
        addr = cue_address(ws["id"], cid)
        send("/new", QLAB_CUE_TYPE)            # creates + selects a Network cue
        send("/cue/selected/name", cue["name"])
        if patch not in (None, ""):
            send("/cue/selected/patch", int(patch))
        send("/cue/selected/customString", addr)   # the OSC message QLab will send
        made.append({"name": cue["name"], "address": addr})
    return {"ok": True, "count": len(made), "cues": made,
            "qlab": {"host": host, "port": int(port), "patch": patch}}


@app.route("/api/qlab")
def api_qlab():
    """Everything QLab needs: where to send OSC, and the address for each cue in
    the active workspace (Option 2 -- one address per named cue)."""
    ws = active_workspace()
    prefix = osc_prefix()
    cues = []
    for cid in ws["order"]:
        c = ws["cues"].get(cid)
        if not c:
            continue
        cues.append({"id": cid, "name": c["name"], "type": c["type"],
                     "pushed": bool(c.get("pushed")),
                     "address": cue_address(ws["id"], cid)})
    return jsonify({
        "osc": osc_status(),
        "host": local_ip(),
        "workspace": {"id": ws["id"], "name": ws["name"]},
        "control": {k: f"{prefix}/{k}" for k in ("black", "clear", "stop")},
        "target": qlab_target(),
        "cues": cues,
    })


@app.route("/api/qlab/export", methods=["POST"])
def api_qlab_export():
    """Auto-create the Network cues in QLab over its OSC API."""
    d = request.json or {}
    host = (d.get("host") or "").strip()
    if not host:
        return jsonify({"error": "QLab host/IP is required"}), 400
    try:
        port = int(d.get("port") or DEFAULT_QLAB_PORT)
    except (TypeError, ValueError):
        return jsonify({"error": "port must be a number"}), 400
    patch = d.get("patch")
    t = qlab_target()                              # remember for next time
    t["host"], t["port"] = host, port
    t["patch"] = patch if patch not in (None, "") else t["patch"]
    save_settings()
    res = export_to_qlab(host, port, patch, d.get("passcode"),
                         float(d.get("gap", 0.05)))
    return (jsonify(res), 200) if res.get("ok") else (jsonify(res), 400)


@app.route("/api/qlab/osc", methods=["POST"])
def api_qlab_osc():
    """Enable/disable the bridge or change its port/prefix, then (re)start it."""
    data = request.json or {}
    s = osc_settings()
    if "enabled" in data:
        s["enabled"] = bool(data["enabled"])
    if "port" in data:
        try:
            s["port"] = int(data["port"])
        except (TypeError, ValueError):
            return jsonify({"error": "port must be a number"}), 400
    if "prefix" in data:
        p = str(data["prefix"]).strip() or DEFAULT_OSC_PREFIX
        s["prefix"] = "/" + p.strip("/")
    save_settings()
    start_osc()
    return jsonify({"ok": True, "osc": osc_status()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="../config/wall.example.json")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--osc-port", type=int, default=None,
                    help=f"UDP port for the QLab OSC bridge (default {DEFAULT_OSC_PORT})")
    ap.add_argument("--no-osc", action="store_true",
                    help="disable the QLab OSC bridge")
    args = ap.parse_args()

    load_config(args.config)
    ensure_store()
    ws = active_workspace()

    s = osc_settings()
    if args.osc_port is not None:
        s["port"] = args.osc_port
    if args.no_osc:
        s["enabled"] = False
    save_settings()

    print("=" * 60)
    print("Video Hive Hub")
    print("=" * 60)
    print(f"Config    : {args.config}")
    print(f"Layout    : {STATE['config']['layout']}")
    print(f"Nodes     : {len(STATE['config']['nodes'])}")
    print(f"Workspace : {ws['name']} ({len(ws['cues'])} cues)")
    st = osc_status()
    print(f"QLab OSC  : {'udp/%d %s' % (st['port'], st['prefix']) if st['enabled'] else 'disabled'}"
          f"{'' if st['available'] else '  (python-osc not installed)'}")
    have_ff = shutil.which("ffmpeg") and shutil.which("ffprobe")
    print(f"Video     : {'ffmpeg ready' if have_ff else 'ffmpeg/ffprobe NOT FOUND -- video cues will fail (images are fine)'}")
    print(f"Open      : http://localhost:{args.port}")
    print("=" * 60)
    start_osc()
    start_mdns()
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
