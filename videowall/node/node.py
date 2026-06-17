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
import sys
import threading
import time
import urllib.request
from pathlib import Path

from flask import Flask, request, jsonify

app = Flask(__name__)

CFG = {
    "id": "node",
    "port": 8001,
    "rotation": 0,
    "media_dir": Path("media"),
    "socket": "/tmp/mpv-wall-socket",
    "headless": False,
    "gpu_context": "x11egl",   # mpv GPU backend; "drm" renders with no X server
    "hub": None,               # if set, announce ourselves to the hub here
}

STATE = {
    "library": {},       # cue_id -> {"file": str, "kind": str, "loop": bool}
    "showing": None,     # cue_id currently displayed
    "timer": None,
    "update": {"state": "idle", "log": ""},   # OS package update job
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
# Self-registration: announce this node to the hub so the operator never types
# an IP. The hub records the source address of our request, so we don't even
# need to know our own IP -- we only need to know the hub.
# --------------------------------------------------------------------------- #
def register_with_hub():
    if not CFG["hub"]:
        return
    url = CFG["hub"].rstrip("/") + "/api/register"
    body = json.dumps({"id": CFG["id"], "port": CFG["port"],
                       "rotation": CFG["rotation"]}).encode()

    def _loop():
        while True:
            try:
                req = urllib.request.Request(
                    url, data=body, headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5).read()
            except Exception:
                pass            # hub may be down/booting; just keep trying
            time.sleep(20)

    threading.Thread(target=_loop, daemon=True).start()
    print(f"[node {CFG['id']}] announcing to hub at {CFG['hub']}")


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

    # X11 backends need a DISPLAY; the DRM backend renders with no X server.
    needs_x = CFG["gpu_context"].startswith("x11")
    if needs_x and "DISPLAY" not in os.environ:
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

    print(f"[node {CFG['id']}] starting mpv (gpu-context={CFG['gpu_context']})")
    try:
        # stderr is left attached (-> the journal under systemd) so display/GPU
        # failures are visible instead of silently swallowed.
        STATE["mpv"] = subprocess.Popen([
            "mpv",
            "--fullscreen", "--keep-open=yes",
            "--image-display-duration=inf", "--idle=yes", "--force-window=yes",
            "--no-osc", "--no-osd-bar", "--osd-level=0",
            "--cursor-autohide=always", "--msg-level=all=error",
            "--hwdec=auto", "--vo=gpu", f"--gpu-context={CFG['gpu_context']}",
            f"--video-rotate={CFG['rotation']}",
            f"--input-ipc-server={CFG['socket']}",
            str(black) if black.exists() else "--idle=yes",
        ], stdout=subprocess.DEVNULL)
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
    data = request.json or {}
    cue_id = data.get("cue_id")
    cue = STATE["library"].get(cue_id)
    if cue and "loop" in data:
        cue["loop"] = bool(data["loop"])
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
    """Briefly display this node's grid label, then revert to what it was
    showing. Auto-reverts after `seconds` (default 5) so it never sticks."""
    data = request.json or {}
    label = data.get("label", CFG["id"])
    secs = float(data.get("seconds", 5))
    prev = STATE["showing"]            # identify doesn't change this; restore to it
    if CFG["headless"]:
        print(f"[node {CFG['id']}] IDENTIFY -> {label} ({secs}s)")
        return jsonify({"ok": True, "headless": True})
    img = Path(f"/tmp/ident-{CFG['id']}.png")
    os.system(f"convert -size 1280x720 xc:#202020 -gravity center "
              f"-pointsize 160 -fill white -annotate 0 '{label}' {img} 2>/dev/null")
    if img.exists():
        display(img, "image", True)

        def _revert():
            if prev and prev in STATE["library"]:
                show_cue(prev)
            else:
                show_black()

        if STATE.get("identify_timer"):
            STATE["identify_timer"].cancel()
        t = threading.Timer(secs, _revert)
        t.start()
        STATE["identify_timer"] = t
    return jsonify({"ok": True, "label": label, "seconds": secs})


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


@app.route("/reboot", methods=["POST"])
def reboot():
    """Reboot this Pi (remote management from the hub). Needs passwordless
    reboot for the node user -- the installer adds a sudoers rule for it."""
    print(f"[node {CFG['id']}] REBOOT requested")
    if CFG["headless"]:
        return jsonify({"ok": True, "headless": True})
    # Reply first, then reboot a moment later so the hub gets a response.
    threading.Timer(1.0, lambda: os.system("sudo /sbin/reboot")).start()
    return jsonify({"ok": True})


def _run_update(password):
    """apt-get update + upgrade, password fed to sudo. Output kept for polling."""
    env = dict(os.environ,
               DEBIAN_FRONTEND="noninteractive", NEEDRESTART_MODE="a")
    log = ""
    try:
        for cmd in (["sudo", "-S", "apt-get", "update"],
                    ["sudo", "-S", "apt-get", "-y",
                     "-o", "Dpkg::Options::=--force-confold", "upgrade"]):
            p = subprocess.run(cmd, input=password + "\n", capture_output=True,
                               text=True, env=env, timeout=1800)
            log += "$ " + " ".join(cmd) + "\n" + p.stdout[-4000:] + p.stderr[-1500:] + "\n"
            STATE["update"]["log"] = log[-8000:]
            if p.returncode != 0:
                STATE["update"]["state"] = "error"
                return
        STATE["update"]["state"] = "done"
    except Exception as e:
        STATE["update"] = {"state": "error", "log": log + f"\n{e}"}


@app.route("/update", methods=["POST"])
def update_packages():
    """Run an OS package update -- gated by the node's sudo password so it
    can't be triggered accidentally. Runs in the background; poll /update/status.
    NOTE: the password travels over the LAN in the clear; this is a guard
    against accidents, not a hardened secret channel."""
    pw = (request.json or {}).get("password", "")
    # Verify the sudo password (forces re-auth; 'true' isn't in any NOPASSWD rule).
    chk = subprocess.run(["sudo", "-S", "-k", "true"],
                         input=pw + "\n", capture_output=True, text=True)
    if chk.returncode != 0:
        return jsonify({"error": "sudo authentication failed"}), 403
    if STATE["update"]["state"] == "running":
        return jsonify({"error": "an update is already running"}), 409
    STATE["update"] = {"state": "running", "log": ""}
    threading.Thread(target=_run_update, args=(pw,), daemon=True).start()
    return jsonify({"ok": True, "state": "running"})


@app.route("/update/status")
def update_status():
    u = STATE["update"]
    return jsonify({"state": u["state"], "log": u["log"][-6000:]})


@app.route("/update_code", methods=["POST"])
def update_code():
    """Replace this node's program with one pushed by the hub, then restart.
    Password-gated (so it's not an open remote-code door); the hub sends its
    own vetted node.py, so nodes need no Git/repo access of their own."""
    pw = request.form.get("password", "")
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file"}), 400
    chk = subprocess.run(["sudo", "-S", "-k", "true"],
                         input=pw + "\n", capture_output=True, text=True)
    if chk.returncode != 0:
        return jsonify({"error": "sudo authentication failed"}), 403
    tmp = "/tmp/videowall-node-new.py"
    f.save(tmp)
    run_path = os.path.abspath(sys.argv[0])     # the node.py we're running
    r = subprocess.run(["sudo", "-S", "install", "-m", "755", tmp, run_path],
                       input=pw + "\n", capture_output=True, text=True)
    if r.returncode != 0:
        return jsonify({"error": "install failed: " + r.stderr[:300]}), 500
    print(f"[node {CFG['id']}] code updated -> restarting")
    threading.Timer(1.0, lambda: os._exit(0)).start()   # respawn loop relaunches new code
    return jsonify({"ok": True, "restarting": True})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="node")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--rotation", type=int, default=0, choices=[0, 90, 180, 270])
    ap.add_argument("--media-dir", default=None)
    ap.add_argument("--socket", default=None)
    ap.add_argument("--gpu-context", default="x11egl",
                    help="mpv GPU backend: 'drm' renders with no X server "
                         "(kiosk on a Pi); 'x11egl' needs an X display (default)")
    ap.add_argument("--hub", default=None,
                    help="hub base URL (e.g. http://hub.local:5000) to "
                         "auto-register with, so its IP need not be typed")
    ap.add_argument("--headless", action="store_true",
                    help="run without MPV (dev/testing)")
    args = ap.parse_args()

    CFG["id"] = args.id
    CFG["port"] = args.port
    CFG["rotation"] = args.rotation
    CFG["headless"] = args.headless
    CFG["gpu_context"] = args.gpu_context
    CFG["hub"] = args.hub
    CFG["media_dir"] = Path(args.media_dir or f"media_{args.id}")
    CFG["socket"] = args.socket or f"/tmp/mpv-wall-{args.id}.sock"

    load_library()
    print(f"[node {CFG['id']}] starting on :{args.port} "
          f"rotation={CFG['rotation']} headless={CFG['headless']}")
    start_mpv()
    register_with_hub()
    app.run(host="0.0.0.0", port=args.port, threaded=True)


if __name__ == "__main__":
    main()
