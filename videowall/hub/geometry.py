"""Wall geometry.

Turns a panel grid plus physical panel dimensions into per-panel crop
rectangles, with bezel compensation baked in.

All physical dimensions are in the same arbitrary unit (millimetres
recommended). The math only depends on ratios, so the unit cancels out.

Bezel compensation principle
----------------------------
The wall behaves as if the source image were printed on one continuous
surface that *includes* the dead space behind the bezels, and the bezels
then physically hide part of it. Each panel therefore shows the slice of the
source that lines up with its lit (active) area's position on that continuous
surface. The strips that fall on the bezel gaps are simply never shown, so the
picture stays continuous across the seams.
"""

from dataclasses import dataclass
from math import gcd


@dataclass
class PanelSpec:
    active_w: float        # lit area width  (physical units)
    active_h: float        # lit area height (physical units)
    outer_w: float         # chassis width incl. bezel (physical units)
    outer_h: float         # chassis height incl. bezel (physical units)
    res_w: int             # output pixels in wall-space orientation
    res_h: int             # output pixels in wall-space orientation
    rotation: int = 0      # mounting rotation applied at the node (0/90/180/270)

    @classmethod
    def from_dict(cls, d):
        return cls(
            active_w=float(d["active_w"]), active_h=float(d["active_h"]),
            outer_w=float(d["outer_w"]), outer_h=float(d["outer_h"]),
            res_w=int(d["res_w"]), res_h=int(d["res_h"]),
            rotation=int(d.get("rotation", 0)),
        )


@dataclass
class Tile:
    row: int
    col: int
    # Active-area crop rectangle as fractions (0..1) of the full wall canvas.
    u0: float
    v0: float
    u1: float
    v1: float
    res_w: int
    res_h: int
    rotation: int

    @property
    def key(self):
        return f"{self.row},{self.col}"


# Layout presets requested for the wall. Panel physical dimensions come from
# the wall config; orientation only selects which panel block to use.
LAYOUTS = {
    "2x2": {"rows": 2, "cols": 2, "orientation": "landscape"},
    "4x4": {"rows": 4, "cols": 4, "orientation": "landscape"},
    "1x1": {"rows": 1, "cols": 1, "orientation": "portrait"},
    "1x2": {"rows": 1, "cols": 2, "orientation": "portrait"},
    "1x3": {"rows": 1, "cols": 3, "orientation": "portrait"},
    "1x4": {"rows": 1, "cols": 4, "orientation": "portrait"},
    "1x5": {"rows": 1, "cols": 5, "orientation": "portrait"},
}


def build_tiles(rows, cols, panel: PanelSpec):
    """Return (tiles, canvas_w, canvas_h) for a rows x cols grid of `panel`.

    canvas_w/canvas_h are the full physical extent of the wall (chassis butted
    edge to edge), in the same units as the panel spec.
    """
    canvas_w = cols * panel.outer_w
    canvas_h = rows * panel.outer_h
    bezel_x = (panel.outer_w - panel.active_w) / 2.0
    bezel_y = (panel.outer_h - panel.active_h) / 2.0

    tiles = []
    for r in range(rows):
        for c in range(cols):
            ax0 = c * panel.outer_w + bezel_x
            ay0 = r * panel.outer_h + bezel_y
            ax1 = ax0 + panel.active_w
            ay1 = ay0 + panel.active_h
            tiles.append(Tile(
                row=r, col=c,
                u0=ax0 / canvas_w, v0=ay0 / canvas_h,
                u1=ax1 / canvas_w, v1=ay1 / canvas_h,
                res_w=panel.res_w, res_h=panel.res_h,
                rotation=panel.rotation,
            ))
    return tiles, canvas_w, canvas_h


def _aspect(w, h):
    g = gcd(int(w), int(h)) or 1
    return f"{int(w)//g}:{int(h)//g}"


def authoring_target(rows, cols, panel: PanelSpec):
    """Recommend the dimensions to author the master image/video at.

    - physical_canvas: author at this size for full bezel compensation. The hub
      treats the master as the continuous physical surface (bezels included) and
      crops each panel's active window out of it.
    - active_mosaic: the simpler "no-comp" target -- each panel block maps 1:1,
      seams will show the usual uncompensated offset.
    """
    ppu = panel.res_w / panel.active_w
    active_w = cols * panel.res_w
    active_h = rows * panel.res_h
    phys_w = round(cols * panel.outer_w * ppu)
    phys_h = round(rows * panel.outer_h * ppu)
    return {
        "physical_canvas": {"w": phys_w, "h": phys_h, "aspect": _aspect(phys_w, phys_h)},
        "active_mosaic": {"w": active_w, "h": active_h, "aspect": _aspect(active_w, active_h)},
    }


def visible_source_rect(src_w, src_h, canvas_w, canvas_h, fit):
    """Rectangle of the SOURCE image (in source pixels) that maps onto the full
    wall canvas, as (off_x, off_y, vis_w, vis_h).

    'stretch' uses the whole source (aspect ignored).
    'cover'   center-crops the source to the canvas aspect ratio.

    'contain' cannot be expressed as a single source rectangle (it needs
    letterbox padding) and is handled directly in the image slicer instead.
    Video tiling therefore supports 'cover' and 'stretch'.
    """
    if fit == "stretch":
        return 0.0, 0.0, float(src_w), float(src_h)

    canvas_aspect = canvas_w / canvas_h
    src_aspect = src_w / src_h
    if src_aspect >= canvas_aspect:
        vis_h = float(src_h)
        vis_w = src_h * canvas_aspect
        off_x = (src_w - vis_w) / 2.0
        off_y = 0.0
    else:
        vis_w = float(src_w)
        vis_h = src_w / canvas_aspect
        off_x = 0.0
        off_y = (src_h - vis_h) / 2.0
    return off_x, off_y, vis_w, vis_h
