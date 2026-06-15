#!/usr/bin/env python3
"""Video Wall Display Node.

Runs on each TV's Raspberry Pi. Intentionally "dumb and fast": it keeps one
persistent, hardware-accelerated MPV window fullscreen (the technique from the
original QLab player) and holds a **persistent library of pre-staged cues**.

Two phases, mirroring the original QLab workflow:

    PREP (pre-production):
      POST /stage   (multipart file, cue_id, kind=image|video, loop)
        -> store this panel's slice for that cue on local disk

    SHOW (live):
      POST /show_at {cue_id, at, [loop]}   -> flip to that cue at wall-clock T
      POST /show    {cue_id}               -> flip now

No media crosses the LAN at show time -- a cue is just a tiny command, so the
flip is near-instant. /show_at schedules the flip against this node's own clock
so every panel changes in unison (keep node clocks tight with NTP).

The library is persisted to a manifest on disk, so a built show is ready
immediately after a reboot.

Other routes:  GET /library   POST /forget {cue_id}   POST /identify
               POST /stop /clear /black   GET /status

Mounting rotation (portrait walls) is applied here via MPV video-rotate.
Headless fallback: with no MPV/display the node still accepts everything and
keeps files on disk so orchestration can be verified on a dev machine.
"""

import argparse
import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

from flask import Flask, request, jsonify

app = Flask(__name__)

CFG = {
    "id": "node",
    "rotation": 0,
    "media_dir": Path("media"),
    "socket": "/tmp/mpv-wall-socket",
    "headless": False,
}

STATE = {
    "library": {},       # cue_id -> {"file": str, "kind": str, "loop": bool}
    "showing": None,     # cue_id currently displayed
    "timer": None,
}


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def manifest_path():
    return CFG["media_dir"] / "manifest.json"


def load_library():
    p = manifest_path()
    if p.exists():
        try:
            STATE["library"] = json.loads(p.read_text())
        except Exception:
            STATE["library"] = {}
    print(f"[node {CFG['id']}] loaded {len(STATE['library'])} cue(s) from disk")


def save_library():
    CFG["media_dir"].mkdir(parents=True, exist_ok=True)
    manifest_path().write_text(json.dumps(STATE["library"], indent=2))


# --------------------------------------------------------------------------- #
# MPV control (persistent window)
# --------------------------------------------------------------------------- #
def mpv_command(command):
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(CFG["socket"])
        sock.send((json.dumps({"command": command}) + "\n").encode())
        sock.close()
        return True
    except Exception:
        return False


def start_mpv():
    if CFG["headless"]:
        print(f"[node {CFG['id']}] headless mode: MPV disabled")
        return

    if "DISPLAY" not in os.environ:
        os.environ["DISPLAY"] = ":0"

    try:
        os.remove(CFG["socket"])
    except OSError:
        pass

    black = Path("/tmp/wall-black.png")
    if not black.exists():
        if os.system(f"convert -size 64x64 xc:black {black} 2>/dev/null") != 0:
            os.system(f"ffmpeg -f lavfi -i color=black:s=64x64:r=1 "
                      f"-frames:v 1 {black} 2>/dev/null")

    try:
        STATE["mpv"] = subprocess.Popen([
            "mpv",
            "--fullscreen", "--keep-open=yes",
            "--image-display-duration=inf", "--idle=yes", "--force-window=yes",
            "--no-osc", "--no-osd-bar", "--osd-level=0",
            "--cursor-autohide=always",
            "--hwdec=auto", "--vo=gpu", "--gpu-context=x11egl",
            f"--video-rotate={CFG['rotation']}",
            f"--input-ipc-server={CFG['socket']}",
            str(black) if black.exists() else "--idle=yes",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        print(f"[node {CFG['id']}] mpv not found -> headless mode")
        CFG["headless"] = True
        return

    for _ in range(20):
        if os.path.exists(CFG["socket"]):
            time.sleep(0.3)
            print(f"[node {CFG['id']}] MPV ready")
            return
        time.sleep(0.3)
    print(f"[node {CFG['id']}] MPV socket not ready; commands may drop")


def display(path, kind, loop):
    if CFG["headless"]:
        print(f"[node {CFG['id']}] (headless) SHOW {kind} {path} loop={loop}")
        return
    mpv_command(["loadfile", str(path), "replace"])
    mpv_command(["set_property", "video-rotate", CFG["rotation"]])
    mpv_command(["set_property", "loop-file", "inf" if loop else "no"])
    mpv_command(["set_property", "pause", False])


def show_black():
    if CFG["headless"]:
        return
    black = Path("/tmp/wall-black.png")
    if black.exists():
        mpv_command(["loadfile", str(black), "replace"])
        mpv_command(["set_property", "loop-file", "inf"])


def show_cue(cue_id):
    cue = STATE["library"].get(cue_id)
    if not cue:
        return False
    display(cue["file"], cue["kind"], cue.get("loop", False))
    STATE["showing"] = cue_id
    return True


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.route("/status")
def status():
    return jsonify({
        "id": CFG["id"],
        "rotation": CFG["rotation"],
        "headless": CFG["headless"],
        "cues": sorted(STATE["library"].keys()),
        "showing": STATE["showing"],
        "clock": time.time(),
    })


@app.route("/library")
def library():
    return jsonify(STATE["library"])


@app.route("/stage", methods=["POST"])
def stage():
    """Store this panel's slice for a cue (prep phase, pre-show)."""
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    cue_id = request.form.get("cue_id")
    if not cue_id:
        return jsonify({"error": "no cue_id"}), 400
    kind = request.form.get("kind", "image")
    loop = request.form.get("loop", "0") == "1"

    cues_dir = CFG["media_dir"] / "cues"
    cues_dir.mkdir(parents=True, exist_ok=True)
    f = request.files["file"]
    ext = Path(f.filename).suffix or (".mp4" if kind == "video" else ".png")
    dest = cues_dir / f"{cue_id}{ext}"
    f.save(dest)

    STATE["library"][cue_id] = {"file": str(dest), "kind": kind, "loop": loop}
    save_library()
    return jsonify({"ok": True, "cue_id": cue_id, "file": str(dest)})


@app.route("/show", methods=["POST"])
def show_now():
    cue_id = (request.json or {}).get("cue_id")
    if not show_cue(cue_id):
        return jsonify({"error": f"cue {cue_id!r} not staged"}), 404
    return jsonify({"ok": True, "showing": cue_id})


@app.route("/show_at", methods=["POST"])
def show_at():
    """Schedule a flip to `cue_id` at wall-clock time `at` (synchronized)."""
    data = request.json or {}
    cue_id = data.get("cue_id")
    cue = STATE["library"].get(cue_id)
    if not cue:
        return jsonify({"error": f"cue {cue_id!r} not staged"}), 404
    if "loop" in data:
        cue["loop"] = bool(data["loop"])

    at = float(data.get("at", time.time()))
    if STATE["timer"]:
        STATE["timer"].cancel()
    delay = max(0.0, at - time.time())

    def _fire():
        show_cue(cue_id)

    t = threading.Timer(delay, _fire)
    t.start()
    STATE["timer"] = t
    return jsonify({"ok": True, "cue_id": cue_id, "fires_in": delay})


@app.route("/forget", methods=["POST"])
def forget():
    cue_id = (request.json or {}).get("cue_id")
    cue = STATE["library"].pop(cue_id, None)
    if cue:
        try:
            os.remove(cue["file"])
        except OSError:
            pass
        save_library()
    return jsonify({"ok": True, "cue_id": cue_id})


@app.route("/identify", methods=["POST"])
def identify():
    """Briefly display this node's grid label, to confirm physical placement."""
    label = (request.json or {}).get("label", CFG["id"])
    if CFG["headless"]:
        print(f"[node {CFG['id']}] IDENTIFY -> {label}")
        return jsonify({"ok": True, "headless": True})
    img = Path(f"/tmp/ident-{CFG['id']}.png")
    os.system(f"convert -size 1280x720 xc:#202020 -gravity center "
              f"-pointsize 160 -fill white -annotate 0 '{label}' {img} 2>/dev/null")
    if img.exists():
        display(img, "image", True)
    return jsonify({"ok": True, "label": label})


@app.route("/stop", methods=["POST"])
def stop():
    if STATE["timer"]:
        STATE["timer"].cancel()
    if not CFG["headless"]:
        mpv_command(["set_property", "pause", True])
    return jsonify({"ok": True})


@app.route("/clear", methods=["POST"])
@app.route("/black", methods=["POST"])
def clear():
    if STATE["timer"]:
        STATE["timer"].cancel()
    show_black()
    STATE["showing"] = None
    return jsonify({"ok": True})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="node")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--rotation", type=int, default=0, choices=[0, 90, 180, 270])
    ap.add_argument("--media-dir", default=None)
    ap.add_argument("--socket", default=None)
    ap.add_argument("--headless", action="store_true",
                    help="run without MPV (dev/testing)")
    args = ap.parse_args()

    CFG["id"] = args.id
    CFG["rotation"] = args.rotation
    CFG["headless"] = args.headless
    CFG["media_dir"] = Path(args.media_dir or f"media_{args.id}")
    CFG["socket"] = args.socket or f"/tmp/mpv-wall-{args.id}.sock"

    load_library()
    print(f"[node {CFG['id']}] starting on :{args.port} "
          f"rotation={CFG['rotation']} headless={CFG['headless']}")
    start_mpv()
    app.run(host="0.0.0.0", port=args.port, threaded=True)


if __name__ == "__main__":
    main()
