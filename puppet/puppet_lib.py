#!/usr/bin/env python3
"""Shared 2.5D mesh-puppet engine: sprite.png -> mesh.json -> preview.gif + viewer.html.

Character directory convention
------------------------------
A character lives in its own directory under puppets/ (e.g. puppets/rimuru/
for Rimuru, puppets/shuna/ for Shuna). The directory holds:

    sprite.png       (input, required)  RGBA character sprite, transparent bg
    controls.json    (input, required)  annotated control points:
                       {"points": [{"label": str, "x": 0..1, "y": 0..1,
                                    "r": px, "dx": px, "dy": px}, ...]}
                       x/y are normalized sprite coordinates; r/dx/dy in px.
                       Annotate interactively with annotate.html.
    char.json        (input, optional)  per-character tuning — see below.
                       Characters needing no special tuning omit it entirely.

Generated outputs (written by the functions below):

    sprite_meshed.png   sprite with any erase_polys regions cut out (alpha=0);
                        a plain RGBA copy when the character has none
    mesh.json           quadtree mesh + controls glued to nearest vertex
    mesh_debug.png      QA overlay (triangles + control disks/arrows)
    still_*.png         flattened preview stills at STILL_TIMES
    preview.gif         flattened looping preview (FPS x SECONDS frames)
    viewer.html         self-contained interactive viewer (from viewer.tpl.html
                        next to this file, shared by all characters)

char.json schema — every key optional, defaults shown:

    {
      "name": "Rimuru",                 // used for the viewer <title>
      "exclude_labels": ["tassel"],     // labels NOT meshed (drawn by other
                                        // means, e.g. a strip_patch); default []
      "motion_defaults": {              // per-label [period, base_phase];
        "hair_tip": [1.0, 4.0],         // default for unlisted labels: [1.0, 0.0]
        "other": [1.0, 0.0]
      },
      "target_amp": {"hair_tip": 3.0},  // per-label peak amplitude cap (px);
                                        // default 2.0
      "radius_override": {"hair_tip_0": 12},   // by control name (label_index)
      "amp_scale_override": {"hair_tip_0": 0.65},
      "rigid": ["tassel_0"],            // control names whose disk moves rigidly
      "zero_amp_y": ["tassel"],         // labels swinging purely left-right
      "erase_polys": [[[0.84, 0.43], ...]],    // normalized polygons cut from
                                        // the mesh texture (e.g. a tassel drawn
                                        // by strip_patch instead); default []
      "strip_patch": {                  // feathered patch warped by row strips
        "file": "tassel_patch.png",     // (bottom-weighted ramp), composited on
        "x": 313, "y": 247,             // top of the mesh each frame; omit the
        "amp_x": 4.0, "amp_y": 0.5,     // whole key for characters without one
        "period": 1.1, "phase": 1.2, "exp": 1.5
      }
    }

Pipeline (see the thin wrappers build_mesh.py / render_mesh_preview.py /
make_viewer.py, each taking an optional character-directory argument):

    build_mesh(char_dir)      sprite + controls -> sprite_meshed.png, mesh.json,
                              mesh_debug.png (coverage QA warns under 99%)
    render_preview(char_dir)  mesh.json + sprite_meshed.png -> stills + preview.gif
    make_viewer(char_dir)     mesh.json + sprite_meshed.png -> viewer.html

Meshing (inspired by ImageToMeshAnim's "no long irregular triangles" rule):
quadtree grid of CELL px coarse cells, subdivided to MAX_DEPTH where coverage
is partial or a control disk is near; every leaf cell triangulates watertight
across level transitions via T-junction midpoints. Boundary vertices snap to
the sub-pixel silhouette contour (reverted if any incident triangle would
flip). Deformation is compact-falloff IDW (smoothstep weights, normalized;
rigid controls claim their disk outright) with per-triangle affine texture
mapping and a slight dst expansion to hide seams.
"""
import base64
import json
import os
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from skimage.measure import find_contours

LIB_DIR = Path(__file__).resolve().parent

# ---------- meshing constants (shared by all characters) ----------

CELL = 28           # coarse grid px
MAX_DEPTH = 2       # 28 -> 14 -> 7
CTRL_MARGIN = 8     # extra px around control disks forcing refinement
SNAP_DIST = 8       # max px a boundary vertex may jump to the contour
COVERAGE_MIN = 0.99  # coverage QA threshold

PHASE_STEP = 0.7             # phase offset between same-label controls
DEFAULT_MOTION = (1.0, 0.0)  # (period, base_phase) for unlisted labels
DEFAULT_TARGET_AMP = 2.0     # peak amplitude cap for unlisted labels

# ---------- render constants ----------

FPS = 12
SECONDS = 6
STILL_TIMES = (0.27, 0.55, 0.83)
EXPAND = 0.8          # px dst-triangle expansion (seam hiding)


# ---------- per-character config ----------

def load_char_config(char_dir):
    """Read optional char.json from the character directory ({} when absent)."""
    path = os.path.join(char_dir, "char.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def make_meshed_sprite(img, char_dir, cfg):
    """sprite.png with any erase_polys regions cut out (alpha=0)."""
    w, h = img.size
    polys = cfg.get("erase_polys", [])
    if polys:
        m = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(m)
        for poly in polys:
            d.polygon([(x * w, y * h) for x, y in poly], fill=255)
        m = m.filter(ImageFilter.MaxFilter(5))  # dilate ~2px to catch aa edges
        arr = np.array(img)
        arr[..., 3][np.array(m) > 0] = 0
        out = Image.fromarray(arr, "RGBA")
    else:
        out = img
    out.save(os.path.join(char_dir, "sprite_meshed.png"))
    return out


def load_controls(char_dir, w, h, cfg):
    with open(os.path.join(char_dir, "controls.json")) as f:
        data = json.load(f)
    exclude = set(cfg.get("exclude_labels", []))
    motion_defaults = cfg.get("motion_defaults", {})
    target_amp = cfg.get("target_amp", {})
    radius_override = cfg.get("radius_override", {})
    amp_scale_override = cfg.get("amp_scale_override", {})
    rigid = set(cfg.get("rigid", []))
    zero_amp_y = set(cfg.get("zero_amp_y", []))

    counts = {}
    controls = []
    for p in data["points"]:
        if p["label"] in exclude:
            continue  # excluded labels are drawn by other means, not meshed
        period, base_phase = motion_defaults.get(
            p["label"], motion_defaults.get("other", DEFAULT_MOTION))
        idx = counts.get(p["label"], 0)
        counts[p["label"]] = idx + 1
        controls.append({
            "name": f'{p["label"]}_{idx}', "label": p["label"],
            "x": p["x"] * w, "y": p["y"] * h,
            "radius": p["r"], "amp_x": p["dx"], "amp_y": p["dy"],
            "period": period, "phase": round(base_phase + idx * PHASE_STEP, 2),
        })
    # normalize amplitudes per label so the group peak hits its target
    by_label = {}
    for c in controls:
        by_label.setdefault(c["label"], []).append(c)
    for label, group in by_label.items():
        peak = max(np.hypot(c["amp_x"], c["amp_y"]) for c in group)
        scale = min(1.0, target_amp.get(label, DEFAULT_TARGET_AMP) / max(peak, 1e-9))
        for c in group:
            c["amp_raw"] = [c["amp_x"], c["amp_y"]]
            c["amp_x"] = round(c["amp_x"] * scale, 2)
            c["amp_y"] = round(c["amp_y"] * scale, 2)
    for c in controls:
        if c["name"] in radius_override:
            c["radius_raw"] = c["radius"]
            c["radius"] = radius_override[c["name"]]
        if c["name"] in amp_scale_override:
            c["amp_x"] = round(c["amp_x"] * amp_scale_override[c["name"]], 2)
            c["amp_y"] = round(c["amp_y"] * amp_scale_override[c["name"]], 2)
        if c["label"] in zero_amp_y:
            c["amp_y"] = 0.0
        c["rigid"] = c["name"] in rigid
    return controls


# ---------- quadtree mesher ----------

def classify(alpha, x0, y0, x1, y1):
    """Exact cell coverage at full resolution — subsampling misses thin wisps."""
    sub = alpha[int(y0):int(y1), int(x0):int(x1)]
    if sub.size == 0:
        return "none"
    opaque = sub > 100
    if not opaque.any():
        return "none"
    if opaque.all():
        return "full"
    return "partial"


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
        kind = classify(alpha, x0, y0, min(x0 + s, w), min(y0 + s, h))
        if kind == "none":
            return
        if kind == "full" or depth >= MAX_DEPTH or s <= 7:
            cells.append((x0, y0, s))
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
        if classify(alpha, x0, y0, min(x0 + s, w), min(y0 + s, h)) == "none":
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
    """Perimeter-fan triangulation per cell, with T-junction midpoints included:
    any vertex lying on a cell edge is inserted into that edge's polygon chain,
    so coarse/fine level transitions stay watertight by construction."""
    vid = {}
    points = []

    def vertex(x, y):
        key = (round(x, 1), round(y, 1))
        if key not in vid:
            vid[key] = len(points)
            points.append(key)
        return vid[key]

    # first pass: register every cell corner
    for x0, y0, s in cells:
        x1, y1 = min(x0 + s, w - 1), min(y0 + s, h - 1)
        if x1 <= x0 or y1 <= y0:
            continue  # clipped to zero area (x0 >= w-1 or y0 >= h-1): cannot triangulate
        for px, py in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            vertex(px, py)
    point_set = set(points)
    step = CELL / (2 ** MAX_DEPTH)

    tris = []
    for x0, y0, s in cells:
        x1, y1 = min(x0 + s, w - 1), min(y0 + s, h - 1)
        if x1 <= x0 or y1 <= y0:
            continue  # same zero-area sliver skip as the corner pass above
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        poly = []
        for e in range(4):
            ax, ay = corners[e]
            bx, by = corners[(e + 1) % 4]
            poly.append((ax, ay))
            # midpoints contributed by finer neighbors along this edge
            dx, dy = (1 if bx > ax else -1 if bx < ax else 0), (1 if by > ay else -1 if by < ay else 0)
            t = step
            while t < s:
                mx, my = ax + dx * t, ay + dy * t
                key = (round(mx, 1), round(my, 1))
                if key in point_set:
                    poly.append(key)
                t += step
        cx = sum(p[0] for p in poly) / len(poly)
        cy = sum(p[1] for p in poly) / len(poly)
        ids = [vertex(px, py) for px, py in poly]
        if len(ids) == 4:
            # no T-junction midpoints: plain quad split
            tris.append([ids[0], ids[1], ids[2]])
            tris.append([ids[0], ids[2], ids[3]])
            continue
        c = vertex(round(cx, 1), round(cy, 1))
        for i in range(len(ids)):
            tris.append([c, ids[i], ids[(i + 1) % len(ids)]])
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


# ---------- build: sprite + controls -> mesh.json ----------

def build_mesh(char_dir):
    """Build mesh.json (+ sprite_meshed.png, mesh_debug.png) for a character."""
    cfg = load_char_config(char_dir)
    img = Image.open(os.path.join(char_dir, "sprite.png")).convert("RGBA")
    w, h = img.size
    img = make_meshed_sprite(img, char_dir, cfg)  # erase regions cut out
    alpha = np.array(img)[..., 3]
    mask = alpha > 100

    controls = load_controls(char_dir, w, h, cfg)
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
    if cov < COVERAGE_MIN:
        print("WARNING: mesh does not fully cover the sprite")

    mesh = {"width": w, "height": h,
            "points": [[round(float(x), 1), round(float(y), 1)] for x, y in points],
            "tris": tris,
            "controls": [{
                "name": c["name"], "label": c["label"], "vertex": c["vertex"],
                "radius": c["radius"], "amp_x": c["amp_x"], "amp_y": c["amp_y"],
                "period": c["period"], "phase": c["phase"], "rigid": c["rigid"],
            } for c in controls]}
    with open(os.path.join(char_dir, "mesh.json"), "w") as f:
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
    vis.convert("RGB").save(os.path.join(char_dir, "mesh_debug.png"))
    print("mesh.json + mesh_debug.png written")


# ---------- deform: compact-falloff IDW ----------

def smooth01(u):
    u = np.clip(u, 0.0, 1.0)
    return u * u * (3 - 2 * u)


def build_state(mesh):
    pts = np.array(mesh["points"], dtype=float)
    ctrls = mesh["controls"]
    cpos = pts[[c["vertex"] for c in ctrls]]                    # (M,2)
    radius = np.array([c["radius"] for c in ctrls])             # (M,)
    diff = pts[:, None, :] - cpos[None, :, :]                   # (N,M,2)
    dist = np.hypot(diff[..., 0], diff[..., 1])                 # (N,M)
    w = smooth01(1.0 - dist / radius[None, :])                  # (N,M)
    w[dist >= radius[None, :]] = 0.0
    wsum = w.sum(axis=1, keepdims=True)                         # (N,1)
    W = np.divide(w, wsum, out=np.zeros_like(w), where=wsum > 0)
    # rigid controls claim their disk outright: uniform weight 1, no blending
    for j, c in enumerate(ctrls):
        if c.get("rigid"):
            claimed = dist[:, j] < c["radius"]
            W[claimed, :] = 0.0
            W[claimed, j] = 1.0
    return pts, ctrls, W


def displace(mesh, state, t):
    pts, ctrls, W = state
    disp = np.zeros((len(ctrls), 2))
    for i, c in enumerate(ctrls):
        s = np.sin(2 * np.pi * t / c["period"] + c["phase"])
        disp[i] = (c["amp_x"] * s, c["amp_y"] * s)
    return pts + W @ disp


def affine_coeffs(dst_tri, src_tri):
    """Affine map dst -> src as PIL AFFINE coeffs (a,b,c,d,e,f)."""
    d = np.array(dst_tri, dtype=float)
    s = np.array(src_tri, dtype=float)
    M = np.column_stack([d, np.ones(3)])
    ax = np.linalg.solve(M, s[:, 0])
    ay = np.linalg.solve(M, s[:, 1])
    return (ax[0], ax[1], ax[2], ay[0], ay[1], ay[2])


def expand_tri(tri, pad=EXPAND):
    p = np.array(tri, dtype=float)
    c = p.mean(axis=0)
    out = []
    for v in p:
        d = v - c
        n = np.hypot(*d)
        out.append(v + d / max(n, 1e-9) * pad)
    return np.array(out)


# ---------- strip patch (row-strip warp, e.g. Rimuru's tassel) ----------

def warp_strip_patch(patch, t, params):
    """Rows shifted with a bottom-weighted ramp — a solid-texture region (e.g.
    a bead) stays rigid because its rows all carry the same fill."""
    ph, pw = patch.shape[:2]
    out = np.zeros_like(patch)
    ang = 2 * np.pi * t / params["period"] + params["phase"]
    sx, sy = np.sin(ang), np.cos(ang)
    for j in range(ph):
        w = (j / (ph - 1)) ** params["exp"]
        dx = int(round(params["amp_x"] * w * sx))
        dy = int(round(params["amp_y"] * w * sy))
        src = j - dy
        if not (0 <= src < ph):
            continue
        row = patch[src]
        if dx > 0:
            out[j, dx:] = row[: pw - dx]
        elif dx < 0:
            out[j, : pw + dx] = row[-dx:]
        else:
            out[j] = row
    return out


# ---------- render: mesh.json + sprite_meshed.png -> stills + gif ----------

def render_frame(mesh, state, sprite, strip, t):
    """strip: (patch_array, params) or None."""
    w, h = mesh["width"], mesh["height"]
    dp = displace(mesh, state, t)
    sp = np.array(mesh["points"], dtype=float)
    frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for a, b, c in mesh["tris"]:
        src = sp[[a, b, c]]
        dst = expand_tri(dp[[a, b, c]])
        x0 = max(int(np.floor(dst[:, 0].min())) - 1, 0)
        y0 = max(int(np.floor(dst[:, 1].min())) - 1, 0)
        x1 = min(int(np.ceil(dst[:, 0].max())) + 1, w)
        y1 = min(int(np.ceil(dst[:, 1].max())) + 1, h)
        if x1 <= x0 or y1 <= y0:
            continue
        sx0 = max(int(np.floor(src[:, 0].min())) - 2, 0)
        sy0 = max(int(np.floor(src[:, 1].min())) - 2, 0)
        sx1 = min(int(np.ceil(src[:, 0].max())) + 2, w)
        sy1 = min(int(np.ceil(src[:, 1].max())) + 2, h)
        crop = sprite.crop((sx0, sy0, sx1, sy1))
        co = affine_coeffs(dst, src)
        # tile coords: global dst = (x0+tx, y0+ty); crop coords = src - (sx0,sy0)
        coeffs = (co[0], co[1], co[0] * x0 + co[1] * y0 + co[2] - sx0,
                  co[3], co[4], co[3] * x0 + co[4] * y0 + co[5] - sy0)
        tile = crop.transform((x1 - x0, y1 - y0), Image.AFFINE, coeffs, Image.BILINEAR)
        m = Image.new("L", (x1 - x0, y1 - y0), 0)
        ImageDraw.Draw(m).polygon([(px - x0, py - y0) for px, py in dst], fill=255)
        frame.paste(tile, (x0, y0), m)
    if strip is not None:
        patch, params = strip
        warped = Image.fromarray(warp_strip_patch(patch, t, params))
        frame.alpha_composite(warped, (params["x"], params["y"]))
    return frame


def load_strip_patch(char_dir, cfg):
    """(patch_array, params) when char.json configures a strip_patch, else None."""
    sp = cfg.get("strip_patch")
    if not sp:
        return None
    patch = Image.open(os.path.join(char_dir, sp["file"])).convert("RGBA")
    return np.array(patch), sp


def render_preview(char_dir):
    """Render preview stills + GIF for a character directory."""
    cfg = load_char_config(char_dir)
    mesh = json.load(open(os.path.join(char_dir, "mesh.json")))
    sprite = Image.open(os.path.join(char_dir, "sprite_meshed.png")).convert("RGBA")
    strip = load_strip_patch(char_dir, cfg)
    state = build_state(mesh)
    w, h = mesh["width"], mesh["height"]

    for t in STILL_TIMES:
        f = render_frame(mesh, state, sprite, strip, t)
        flat = Image.new("RGBA", (w, h), (255, 255, 255, 255))
        flat.alpha_composite(f)
        flat.convert("RGB").save(os.path.join(char_dir, f"still_{t:.2f}.png"))

    frames = []
    n = FPS * SECONDS
    for i in range(n):
        f = render_frame(mesh, state, sprite, strip, i / FPS)
        flat = Image.new("RGBA", (w, h), (255, 255, 255, 255))
        flat.alpha_composite(f)
        frames.append(flat.convert("RGB"))
        if (i + 1) % 24 == 0:
            print(f"{i + 1}/{n}")
    pal = frames[0].quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    frames_q = [fr.quantize(palette=pal, dither=Image.Dither.NONE) for fr in frames]
    frames_q[0].save(
        os.path.join(char_dir, "preview.gif"),
        save_all=True, append_images=frames_q[1:],
        duration=round(1000 / FPS), loop=0, optimize=True,
    )
    print("gif ok")


# ---------- viewer: mesh.json + sprite_meshed.png -> viewer.html ----------

def make_viewer(char_dir):
    """Generate viewer.html from the shared viewer.tpl.html + character assets."""
    cfg = load_char_config(char_dir)
    tpl = (LIB_DIR / "viewer.tpl.html").read_text(encoding="utf-8")
    b64 = base64.b64encode(
        (Path(char_dir) / "sprite_meshed.png").read_bytes()).decode("ascii")
    sp = cfg.get("strip_patch")
    if sp:
        patch = Image.open(os.path.join(char_dir, sp["file"]))
        tb64 = base64.b64encode((Path(char_dir) / sp["file"]).read_bytes()).decode("ascii")
        tjson = json.dumps({
            "x": sp["x"], "y": sp["y"], "w": patch.width, "h": patch.height,
            "amp_x": sp["amp_x"], "amp_y": sp["amp_y"],
            "period": sp["period"], "phase": sp["phase"], "exp": sp["exp"],
        })
    else:
        tb64, tjson = "", "null"
    name = cfg.get("name", os.path.basename(os.path.normpath(char_dir)))
    mesh = (Path(char_dir) / "mesh.json").read_text(encoding="utf-8")
    html = tpl.replace("__TITLE__", cfg.get("title", f"{name} mesh puppet"))
    html = html.replace("__SPRITE_B64__", "data:image/png;base64," + b64)
    html = html.replace("__TASSEL_B64__", "data:image/png;base64," + tb64 if sp else "")
    html = html.replace("__STRIP_JSON__", tjson)
    html = html.replace("__MESH_JSON__", mesh)
    (Path(char_dir) / "viewer.html").write_text(html, encoding="utf-8")
    print(f"viewer.html regenerated ({len(html) // 1024} KiB)")


def build_all(char_dir):
    """Full pipeline: build_mesh + render_preview + make_viewer."""
    build_mesh(char_dir)
    render_preview(char_dir)
    make_viewer(char_dir)


# ---------- regression self-test ----------

def self_test():
    """Regression check for the zero-area-triangle bug: a synthetic sprite with
    opaque pixels in the last column AND last row (quadtree cells then start at
    x0 == w-1 / y0 == h-1 and clip to zero area) must build_mesh +
    render_preview without LinAlgError, with coverage QA passing.
    Run: python3 puppet_lib.py"""
    w = h = 50  # w-1 = h-1 = 49 = 7 * smallest cell: a depth-2 cell starts on the edge
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ink = (80, 120, 200, 255)
    d.rectangle((8, 8, 40, 40), fill=ink)      # body
    # content touching the last column/row, backed by kept 7px cells one
    # column/row in (so their triangles cover it) but with holes keeping every
    # coarser edge cell partial, so the walk refines down to zero-area slivers
    d.rectangle((42, 0, 48, 20), fill=ink)
    d.rectangle((0, 42, 20, 48), fill=ink)
    for hx, hy in ((45, 3), (45, 17), (3, 45), (17, 45)):
        d.point((hx, hy), fill=(0, 0, 0, 0))
    d.line((w - 1, 0, w - 1, 19), fill=ink)    # wisp down the last column
    d.line((0, h - 1, 19, h - 1), fill=ink)    # wisp across the last row
    alpha = np.array(img)[..., 3]

    cells = collect_cells(alpha, w, h, [])
    assert any(x0 >= w - 1 or y0 >= h - 1 for x0, y0, _ in cells), \
        "test no longer exercises the last-column/row hazard"
    _, tris, _ = cells_to_mesh(cells, w, h)
    assert all(len({a, b, c}) == 3 for a, b, c in tris), "degenerate triangle emitted"

    with tempfile.TemporaryDirectory() as tmp:
        img.save(os.path.join(tmp, "sprite.png"))
        with open(os.path.join(tmp, "controls.json"), "w") as f:
            json.dump({"points": []}, f)
        build_mesh(tmp)
        render_preview(tmp)  # must not raise LinAlgError
        mesh = json.load(open(os.path.join(tmp, "mesh.json")))
        cov = coverage_qa(mesh["points"], mesh["tris"], alpha > 100)
    assert cov >= COVERAGE_MIN, f"coverage {cov * 100:.2f}% below {COVERAGE_MIN * 100:.0f}%"
    print(f"self_test ok (cells {len(cells)}, tris {len(tris)}, coverage {cov * 100:.2f}%)")


if __name__ == "__main__":
    self_test()
