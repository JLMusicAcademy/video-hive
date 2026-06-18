"""Offline video tiling.

Splits one source video into per-panel tile files ahead of showtime using
ffmpeg's crop filter. This is the heavy step in the "images + pre-processed
video" model, and it is intended to run before the show, not live. At showtime
the hub only distributes these files and issues a synchronized play command.

Rotation for portrait mounting is applied at the node (MPV video-rotate), so
the tiles produced here stay in wall-space orientation.
"""

import json
import subprocess
from pathlib import Path

from geometry import visible_source_rect


def probe_dimensions(src_path):
    """Return (width, height) of the source video via ffprobe."""
    out = subprocess.check_output([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json", str(src_path),
    ])
    info = json.loads(out)["streams"][0]
    return int(info["width"]), int(info["height"])


def crop_filter(tile, src_w, src_h, canvas_w, canvas_h, fit):
    """Build the ffmpeg filter string for one tile."""
    off_x, off_y, vis_w, vis_h = visible_source_rect(
        src_w, src_h, canvas_w, canvas_h, fit)
    cw = vis_w * (tile.u1 - tile.u0)
    ch = vis_h * (tile.v1 - tile.v0)
    cx = off_x + vis_w * tile.u0
    cy = off_y + vis_h * tile.v0
    # libx264 + yuv420p require even crop width/height. A non-standard source
    # size (e.g. 1928x1072) otherwise yields an odd crop and ffmpeg aborts the
    # tile -- the cue then silently never gets built. Round dimensions down to
    # even (and offsets down) so the crop always stays within the source.
    cw_i = int(cw) & ~1
    ch_i = int(ch) & ~1
    cx_i = int(cx)
    cy_i = int(cy)
    return (f"crop={cw_i}:{ch_i}:{cx_i}:{cy_i},"
            f"scale={tile.res_w}:{tile.res_h}:flags=lanczos")


def tile_video(src_path, out_dir, tiles, canvas_w, canvas_h, fit="cover",
               crf=20, preset="veryfast", progress=None):
    """Produce one tile file per panel in `out_dir`.

    Returns {(row, col): Path}. `progress(done, total, key)` is called after
    each tile if provided. 'contain' is treated as 'cover' for video.
    """
    if fit == "contain":
        fit = "cover"

    src_path = Path(src_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    src_w, src_h = probe_dimensions(src_path)
    results = {}
    total = len(tiles)
    for i, t in enumerate(tiles, 1):
        out_file = out_dir / f"r{t.row}c{t.col}.mp4"
        vf = crop_filter(t, src_w, src_h, canvas_w, canvas_h, fit)
        proc = subprocess.run([
            "ffmpeg", "-y", "-i", str(src_path),
            "-vf", vf,
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p",
            "-an",                       # tiles are silent; route audio separately
            str(out_file),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            # Surface ffmpeg's own error instead of swallowing it -- a swallowed
            # failure looks like the cue silently "never showing up".
            tail = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
            detail = " | ".join(tail[-3:]) if tail else f"exit {proc.returncode}"
            raise RuntimeError(f"ffmpeg failed tiling r{t.row}c{t.col}: {detail}")
        results[(t.row, t.col)] = out_file
        if progress:
            progress(i, total, t.key)
    return results
