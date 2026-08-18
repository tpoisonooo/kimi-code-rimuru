#!/usr/bin/env python3
"""Build a triangle mesh over the Rimuru sprite for 2.5D puppet deformation.

Meshing (inspired by ImageToMeshAnim's "no long irregular triangles" rule):
- Quadtree grid: 28px coarse cells, subdivided to 14/7px where coverage is
  partial or a control disk is near; every leaf cell = 2 triangles, so all
  triangles stay small and uniform — no long cross-body edges by construction.
- Boundary vertices snap to the sub-pixel silhouette contour (reverted if any
  incident triangle would flip), so edges stay smooth, not staircase.
- Coverage QA: rasterized mesh must cover >=99% of the opaque sprite pixels.

Controls come from controls.json (manual annotation via annotate.html);
amplitudes are normalized per label (raw arrows kept in amp_raw).
"""
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy.ndimage import binary_erosion, map_coordinates
from skimage.measure import find_contours

OUT = os.path.dirname(os.path.abspath(__file__))
SPRITE = os.path.join(OUT, "sprite.png")

CELL = 28           # coarse grid px
MAX_DEPTH = 2       # 28 -> 14 -> 7
SUB = 3.5           # coverage subsample step px
CTRL_MARGIN = 8     # extra px around control disks forcing refinement
SNAP_DIST = 8       # max px a boundary vertex may jump to the contour

MOTION_DEFAULTS = {
    "tassel":   (1.10, 1.2),
    "hair_tip": (1.00, 4.0),
    "hem":      (1.00, 0.6),
    "boot_fur": (1.15, 0.9),
    "cuff":     (0.95, 1.7),
    "other":    (1.00, 0.0),
}
PHASE_STEP = 0.7

TARGET_AMP = {"tassel": 4.5, "hair_tip": 3.0, "hem": 2.5, "boot_fur": 2.2,
              "cuff": 1.8, "other": 2.0}

# the tassel string needs its two controls' falloff to overlap along the whole
# string, or the bead visually detaches (string is ~2px wide, fades when sheared)
RADIUS_OVERRIDE = {"tassel_0": 12, "tassel_1": 16}

# right-strand hair tips swung too wide — damp just that cluster
# (indices follow controls.json order: 0/1/2/6 = right strand, x≈0.77)
AMP_SCALE_OVERRIDE = {"hair_tip_0": 0.65, "hair_tip_1": 0.65, "hair_tip_2": 0.65, "hair_tip_6": 0.65}

# the bead must translate RIGIDLY (no squash): every vertex inside its disk
# moves with exactly the control displacement
RIGID = {"tassel_0"}
# tassel swings purely left-right
ZERO_AMP_Y = {"tassel"}


# the tassel (bead+string) is NOT meshed — it uses the strip-warp patch from
# the rimuru-skin scheme (tassel_patch.png), drawn on top after the mesh.
# We erase it from the mesh texture so the two never double-draw.
# Polygon hugs the string loop + bead; top edge stays below the pommel cap
# (grip right end must survive the erase).
TASSEL_ERASE_POLY = [
    (0.840, 0.432), (0.855, 0.432), (0.858, 0.458), (0.866, 0.478),
    (0.863, 0.503), (0.848, 0.516), (0.829, 0.516), (0.815, 0.500),
    (0.817, 0.475), (0.828, 0.455), (0.836, 0.440),
]


def make_meshed_sprite(img, w, h):
    """sprite.png with the tassel region cut out (alpha=0)."""
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).polygon([(x * w, y * h) for x, y in TASSEL_ERASE_POLY], fill=255)
    m = m.filter(ImageFilter.MaxFilter(5))  # dilate ~2px to catch aa edges
    arr = np.array(img)
    arr[..., 3][np.array(m) > 0] = 0
    out = Image.fromarray(arr, "RGBA")
    out.save(os.path.join(OUT, "sprite_meshed.png"))
    return out


def load_controls(w, h):
    with open(os.path.join(OUT, "controls.json")) as f:
        data = json.load(f)
    counts = {}
    controls = []
    for p in data["points"]:
        if p["label"] == "tassel":
            continue  # tassel uses the strip-warp patch, not mesh deformation
        period, base_phase = MOTION_DEFAULTS.get(p["label"], MOTION_DEFAULTS["other"])
        idx = counts.get(p["label"], 0)
        counts[p["label"]] = idx + 1
        controls.append({
            "name": f'{p["label"]}_{idx}', "label": p["label"],
            "x": p["x"] * w, "y": p["y"] * h,
            "radius": p["r"], "amp_x": p["dx"], "amp_y": p["dy"],
            "period": period, "phase": round(base_phase + idx * PHASE_STEP, 2),
        })
    by_label = {}
    for c in controls:
        by_label.setdefault(c["label"], []).append(c)
    for label, group in by_label.items():
        peak = max(np.hypot(c["amp_x"], c["amp_y"]) for c in group)
        scale = min(1.0, TARGET_AMP.get(label, 2.0) / max(peak, 1e-9))
        for c in group:
            c["amp_raw"] = [c["amp_x"], c["amp_y"]]
            c["amp_x"] = round(c["amp_x"] * scale, 2)
            c["amp_y"] = round(c["amp_y"] * scale, 2)
    for c in controls:
        if c["name"] in RADIUS_OVERRIDE:
            c["radius_raw"] = c["radius"]
            c["radius"] = RADIUS_OVERRIDE[c["name"]]
        if c["name"] in AMP_SCALE_OVERRIDE:
            c["amp_x"] = round(c["amp_x"] * AMP_SCALE_OVERRIDE[c["name"]], 2)
            c["amp_y"] = round(c["amp_y"] * AMP_SCALE_OVERRIDE[c["name"]], 2)
        if c["label"] in ZERO_AMP_Y:
            c["amp_y"] = 0.0
        c["rigid"] = c["name"] in RIGID
    return controls


# ---------- quadtree mesher ----------

def coverage(alpha, x0, y0, s):
    """Fraction of subsamples inside the cell that are opaque."""
    n = max(2, int(s / SUB))
    xs = x0 + (np.arange(n) + 0.5) * s / n
    ys = y0 + (np.arange(n) + 0.5) * s / n
    gx, gy = np.meshgrid(xs, ys)
    vals = map_coordinates(alpha.astype(float), [gy.ravel(), gx.ravel()], order=1, mode="constant")
    return float((vals > 100).mean())


def near_control(x0, y0, s, controls):
    cx, cy = x0 + s / 2, y0 + s / 2
    rad = s / 2 * 1.4143
    for c in controls:
        if np.hypot(cx - c["x"], cy - c["y"]) < rad + c["radius"] + CTRL_MARGIN:
            return True
    return False


def collect_cells(alpha, w, h, controls):
    cells = []

    def walk(x0, y0, s, depth):
        if x0 >= w or y0 >= h:
            return
        cov = coverage(alpha, x0, y0, s)
        if cov == 0.0:
            return
        if cov >= 0.94:
            cells.append((x0, y0, s))
            return
        if depth >= MAX_DEPTH or s <= 7:
            cells.append((x0, y0, s))   # finest partial cell: keep, snap fixes edge
            return
        half = s / 2
        walk(x0, y0, half, depth + 1)
        walk(x0 + half, y0, half, depth + 1)
        walk(x0, y0 + half, half, depth + 1)
        walk(x0 + half, y0 + half, half, depth + 1)

    # force refinement near controls regardless of coverage
    def walk_forced(x0, y0, s, depth):
        if x0 >= w or y0 >= h:
            return
        if coverage(alpha, x0, y0, s) == 0.0:
            return
        if near_control(x0, y0, s, controls) and depth < MAX_DEPTH:
            half = s / 2
            walk_forced(x0, y0, half, depth + 1)
            walk_forced(x0 + half, y0, half, depth + 1)
            walk_forced(x0, y0 + half, half, depth + 1)
            walk_forced(x0 + half, y0 + half, half, depth + 1)
            return
        walk(x0, y0, s, depth)

    for gx in range(0, w, CELL):
        for gy in range(0, h, CELL):
            walk_forced(gx, gy, CELL, 0)
    return cells


def cells_to_mesh(cells, w, h):
    vid = {}
    points = []
    tris = []

    def vertex(x, y):
        key = (round(x, 1), round(y, 1))
        if key not in vid:
            vid[key] = len(points)
            points.append(key)
        return vid[key]

    for x0, y0, s in cells:
        x1, y1 = min(x0 + s, w - 1), min(y0 + s, h - 1)
        a = vertex(x0, y0)
        b = vertex(x1, y0)
        c = vertex(x1, y1)
        d = vertex(x0, y1)
        tris.append([a, b, c])
        tris.append([a, c, d])
    return points, tris, vid


# ---------- contour snapping ----------

def snap_to_contour(points, tris, mask):
    h, w = mask.shape
    contour = np.vstack([c for c in find_contours(mask.astype(float), 0.5) if len(c) > 8])
    contour_xy = contour[:, ::-1]  # (y,x) -> (x,y)
    pts = np.array(points, dtype=float)

    # incident triangles per vertex
    incident = {}
    for ti, (a, b, c) in enumerate(tris):
        for v in (a, b, c):
            incident.setdefault(v, []).append(ti)

    def areas_ok(v, xy):
        for ti in incident.get(v, []):
            a, b, c = tris[ti]
            p = [xy if x == v else pts[x] for x in (a, b, c)]
            cross = (p[1][0] - p[0][0]) * (p[2][1] - p[0][1]) - (p[1][1] - p[0][1]) * (p[2][0] - p[0][0])
            if cross <= 0.5:
                return False
        return True

    snapped = 0
    for i, (x, y) in enumerate(pts):
        d = np.hypot(contour_xy[:, 0] - x, contour_xy[:, 1] - y)
        j = int(d.argmin())
        if d[j] > SNAP_DIST:
            continue
        if 1 <= i:  # cheap boundary test: near-contour vertices only
            pass
        cand = contour_xy[j]
        # keep the vertex strictly inside the mask to avoid poking out
        ci = cand.astype(int)
        if not (0 <= ci[1] < h and 0 <= ci[0] < w):
            continue
        if areas_ok(i, cand):
            pts[i] = cand
            snapped += 1
    return pts, snapped


# ---------- coverage QA ----------

def coverage_qa(points, tris, mask):
    h, w = mask.shape
    rend = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(rend)
    for a, b, c in tris:
        d.polygon([tuple(points[a]), tuple(points[b]), tuple(points[c])], fill=255)
    covered = (np.array(rend) > 0) | ~mask
    return float(covered.mean())


def main():
    img = Image.open(SPRITE).convert("RGBA")
    w, h = img.size
    img = make_meshed_sprite(img, w, h)   # tassel cut out -> strip patch draws it
    alpha = np.array(img)[..., 3]
    mask = alpha > 100

    controls = load_controls(w, h)
    cells = collect_cells(alpha, w, h, controls)
    points, tris, _ = cells_to_mesh(cells, w, h)
    print(f"cells {len(cells)} -> points {len(points)}, triangles {len(tris)}")

    points, snapped = snap_to_contour(points, tris, mask)
    print(f"snapped {snapped}/{len(points)} boundary vertices")

    # glue controls to nearest vertex (annotation coordinates are authoritative)
    arr = np.array(points, dtype=float)
    for c in controls:
        d = np.hypot(arr[:, 0] - c["x"], arr[:, 1] - c["y"])
        c["vertex"] = int(d.argmin())

    cov = coverage_qa(points, tris, mask)
    print(f"coverage: {cov * 100:.2f}%")
    if cov < 0.99:
        print("WARNING: mesh does not fully cover the sprite")

    mesh = {"width": w, "height": h,
            "points": [[round(float(x), 1), round(float(y), 1)] for x, y in points],
            "tris": tris,
            "controls": [{
                "name": c["name"], "label": c["label"], "vertex": c["vertex"],
                "radius": c["radius"], "amp_x": c["amp_x"], "amp_y": c["amp_y"],
                "period": c["period"], "phase": c["phase"], "rigid": c["rigid"],
            } for c in controls]}
    with open(os.path.join(OUT, "mesh.json"), "w") as f:
        json.dump(mesh, f)

    vis = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    vis.alpha_composite(img)
    d = ImageDraw.Draw(vis)
    for a, b, c in tris:
        d.polygon([tuple(points[a]), tuple(points[b]), tuple(points[c])], outline=(0, 180, 0, 90))
    for c in controls:
        cx, cy = c["x"], c["y"]
        r = c["radius"]
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 0, 0, 120))
        d.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=(255, 0, 0, 255))
        d.line((cx, cy, cx + c["amp_x"], cy + c["amp_y"]), fill=(255, 0, 0, 220), width=2)
        d.text((cx + 6, cy - 6), c["name"], fill=(200, 0, 0))
    vis.convert("RGB").save(os.path.join(OUT, "mesh_debug.png"))
    print("mesh.json + mesh_debug.png written")


if __name__ == "__main__":
    main()
