"""Image slicing.

Builds the full wall canvas from a source image (applying the chosen fit
mode), then crops one tile per panel using the geometry's active-area
rectangles. Bezel compensation falls out automatically because we only ever
crop the active rectangles and skip the bezel gaps between them.
"""

from PIL import Image, ImageOps


def build_canvas(src, canvas_px_w, canvas_px_h, fit):
    """Render the source image onto a wall-sized canvas using `fit`."""
    src = src.convert("RGB")
    if fit == "stretch":
        return src.resize((canvas_px_w, canvas_px_h), Image.LANCZOS)
    if fit == "cover":
        return ImageOps.fit(src, (canvas_px_w, canvas_px_h),
                            method=Image.LANCZOS, centering=(0.5, 0.5))
    if fit == "contain":
        canvas = Image.new("RGB", (canvas_px_w, canvas_px_h), (0, 0, 0))
        fitted = ImageOps.contain(src, (canvas_px_w, canvas_px_h), Image.LANCZOS)
        x = (canvas_px_w - fitted.width) // 2
        y = (canvas_px_h - fitted.height) // 2
        canvas.paste(fitted, (x, y))
        return canvas
    raise ValueError(f"unknown fit mode: {fit!r}")


def slice_image(src, tiles, canvas_w_units, canvas_h_units, fit, ppu):
    """Slice `src` into per-panel tiles.

    `ppu` is pixels-per-physical-unit for the working canvas. Returns a dict of
    {(row, col): PIL.Image} where each tile is already at its panel resolution
    and in wall-space orientation (the node applies mounting rotation).
    """
    canvas_px_w = max(1, round(canvas_w_units * ppu))
    canvas_px_h = max(1, round(canvas_h_units * ppu))
    canvas = build_canvas(src, canvas_px_w, canvas_px_h, fit)

    out = {}
    for t in tiles:
        box = (
            round(t.u0 * canvas_px_w), round(t.v0 * canvas_px_h),
            round(t.u1 * canvas_px_w), round(t.v1 * canvas_px_h),
        )
        tile_img = canvas.crop(box).resize((t.res_w, t.res_h), Image.LANCZOS)
        out[(t.row, t.col)] = tile_img
    return out


def wall_mockup(tiles_imgs, rows, cols, panel, max_px=1400):
    """Compose a preview that shows the wall *including* bezel gaps.

    Each active tile is placed inside its panel's chassis cell on a black
    background, so seams appear exactly as they will on the physical wall.
    """
    cell_w, cell_h = panel.outer_w, panel.outer_h
    bezel_x = (panel.outer_w - panel.active_w) / 2.0
    bezel_y = (panel.outer_h - panel.active_h) / 2.0

    full_w = cols * cell_w
    full_h = rows * cell_h
    scale = min(max_px / full_w, max_px / full_h)

    out_w = max(1, round(full_w * scale))
    out_h = max(1, round(full_h * scale))
    mockup = Image.new("RGB", (out_w, out_h), (10, 10, 10))

    for (r, c), img in tiles_imgs.items():
        aw = max(1, round(panel.active_w * scale))
        ah = max(1, round(panel.active_h * scale))
        x = round((c * cell_w + bezel_x) * scale)
        y = round((r * cell_h + bezel_y) * scale)
        mockup.paste(img.resize((aw, ah), Image.LANCZOS), (x, y))
    return mockup
