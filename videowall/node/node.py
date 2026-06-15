#!/usr/bin/env python3
"""Video Wall Display Node.

Runs on each TV's Raspberry Pi. It is intentionally "dumb and fast": it keeps
one persistent, hardware-accelerated MPV window fullscreen (the same technique
as the original QLab player) and does exactly what the hub tells it:

    POST /stage     (multipart file, kind=image|video, loop)  -> receive + preload
    POST /show_at    {at, [loop]}                              -> flip at wall-clock T
    POST /show                                                 -> flip immediately
    POST /stop  /clear  /black
    GET  /status

Synchronized flips
------------------
/stage absorbs the variable-latency file transfer. /show_at schedules the
actual flip against this node's own clock, so every panel changes on the same
wall-clock instant. Keep node clocks tight with NTP/PTP on the LAN.

Mounting rotation (portrait walls) is applied here via MPV's video-rotate, so
the hub always sends tiles in wall-space orientation.

Headless fallback: if MPV or a display is unavailable, the node still accepts
commands and writes staged files to ./received/ so slicing and orchestration
can be verified on a dev machine.
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
    "mpv": None,
    "staged": None,      # dict: {path, kind, loop}
    "showing": None,
    "timer": None,
}


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
        print("[node] headless mode: MPV disabled, staging to ./received/")
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
            "--fullscreen",
            "--keep-open=yes",
            "--image-display-duration=inf",
            "--idle=yes",
            "--force-window=yes",
            "--no-osc", "--no-osd-bar", "--osd-level=0",
            "--cursor-autohide=always",
            "--hwdec=auto", "--vo=gpu", "--gpu-context=x11egl",
            f"--video-rotate={CFG['rotation']}",
            f"--input-ipc-server={CFG['socket']}",
            str(black) if black.exists() else "--idle=yes",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        print("[node] mpv not found -> headless mode")
        CFG["headless"] = True
        return

    for _ in range(20):
        if os.path.exists(CFG["socket"]):
            time.sleep(0.3)
            print("[node] MPV ready")
            return
        time.sleep(0.3)
    print("[node] MPV socket not ready; commands may be dropped")


def show_file(path, kind, loop):
    """Flip the persistent window to `path` immediately."""
    if CFG["headless"]:
        print(f"[node {CFG['id']}] (headless) SHOW {kind} {path} loop={loop}")
        STATE["showing"] = {"path": str(path), "kind": kind}
        return

    mpv_command(["loadfile", str(path), "replace"])
    mpv_command(["set_property", "video-rotate", CFG["rotation"]])
    mpv_command(["set_property", "loop-file", "inf" if loop else "no"])
    mpv_command(["set_property", "pause", False])
    STATE["showing"] = {"path": str(path), "kind": kind}


def show_black():
    if CFG["headless"]:
        STATE["showing"] = None
        return
    black = Path("/tmp/wall-black.png")
    if black.exists():
        mpv_command(["loadfile", str(black), "replace"])
        mpv_command(["set_property", "loop-file", "inf"])


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.route("/status")
def status():
    return jsonify({
        "id": CFG["id"],
        "rotation": CFG["rotation"],
        "headless": CFG["headless"],
        "staged": bool(STATE["staged"]),
        "showing": STATE["showing"],
        "clock": time.time(),
    })


@app.route("/stage", methods=["POST"])
def stage():
    """Receive and preload a tile, but do not display it yet."""
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    kind = request.form.get("kind", "image")
    loop = request.form.get("loop", "0") == "1"

    media_dir = CFG["media_dir"]
    media_dir.mkdir(parents=True, exist_ok=True)
    f = request.files["file"]
    dest = media_dir / f"staged_{f.filename}"
    f.save(dest)

    # Also keep a copy in received/ for headless inspection.
    if CFG["headless"]:
        recv = Path("received")
        recv.mkdir(exist_ok=True)
        (recv / f.filename).write_bytes(dest.read_bytes())

    STATE["staged"] = {"path": dest, "kind": kind, "loop": loop}
    return jsonify({"ok": True, "staged": str(dest)})


@app.route("/show", methods=["POST"])
def show_now():
    s = STATE["staged"]
    if not s:
        return jsonify({"error": "nothing staged"}), 400
    show_file(s["path"], s["kind"], s["loop"])
    return jsonify({"ok": True})


@app.route("/show_at", methods=["POST"])
def show_at():
    """Schedule the flip of the staged media for wall-clock time `at`."""
    s = STATE["staged"]
    if not s:
        return jsonify({"error": "nothing staged"}), 400
    data = request.json or {}
    at = float(data.get("at", time.time()))
    if "loop" in data:
        s["loop"] = bool(data["loop"])

    if STATE["timer"]:
        STATE["timer"].cancel()

    delay = max(0.0, at - time.time())

    def _fire():
        show_file(s["path"], s["kind"], s["loop"])

    t = threading.Timer(delay, _fire)
    t.start()
    STATE["timer"] = t
    return jsonify({"ok": True, "fires_in": delay})


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

    print(f"[node {CFG['id']}] starting on :{args.port} "
          f"rotation={CFG['rotation']} headless={CFG['headless']}")
    start_mpv()
    app.run(host="0.0.0.0", port=args.port, threaded=True)


if __name__ == "__main__":
    main()
