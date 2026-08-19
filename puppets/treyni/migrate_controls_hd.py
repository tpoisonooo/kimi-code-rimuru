#!/usr/bin/env python3
"""One-off migration: controls.json from the old 408x597 sprite to the HD 546x802 sprite.

Reads the PRE-HD controls (default: `git show HEAD:puppets/treyni/controls.json`)
and rewrites puppets/treyni/controls.json for the full-resolution sprite:

1. Remap normalized x/y in CONTENT space: old sprite 408x597 with 4px pad
   (content 400x589) -> new sprite 546x802 with content x[4..542] y[4..797]
   (539x794). Per-axis factors sx=539/400, sy=794/589 (~1.348x).
2. Re-snap every vine* point onto the actual vines of the HD sprite: nearest
   pixel of the green-channel vine mask, then hill-climb on its distance
   transform to sit on the vine centerline. Vines are only 3-6px wide at this
   scale, so a naive affine copy lands off-vine; every point is alpha-probed
   (alpha > 60) afterwards.
3. hair_tip/cuff/hem points sit on solid regions: affine remap only, with an
   alpha>200 probe (snap to nearest solid non-skin pixel within 8px if the
   remapped spot is transparent).
4. Scale px units (r, dx, dy) by s=(sx+sy)/2; periods/phases are time-based
   and stay in char.json untouched.
5. Safety: re-check every control disk against hand/arm/face skin masks
   (regions affine-scaled, dilated 3px); shrink radius where tight, drop if
   unusable — mirrors the original gen_controls.py policy.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

CD = Path(__file__).resolve().parent
OLD_W, OLD_H, OLD_PAD = 408, 597, 4          # old sprite + pad
NEW_PAD_BOX = (4, 4, 542, 797)               # content bbox in new sprite (x0,y0,x1,y1), alpha>10
NEW_CW = NEW_PAD_BOX[2] - NEW_PAD_BOX[0] + 1  # 539
NEW_CH = NEW_PAD_BOX[3] - NEW_PAD_BOX[1] + 1  # 794
SX = NEW_CW / (OLD_W - 2 * OLD_PAD)           # 1.3475
SY = NEW_CH / (OLD_H - 2 * OLD_PAD)           # 1.34805
S = (SX + SY) / 2                             # px-unit scale ~1.3478

img = np.array(Image.open(CD / "sprite.png").convert("RGBA")).astype(int)
H, W = img.shape[:2]
R, G, B, A = img[..., 0], img[..., 1], img[..., 2], img[..., 3]

# ---- vine mask (same green classifier as the original tracer) ----
VINE = (A > 60) & (G > R + 8) & (G > B + 12) & (G < 215) & (R < 200)
# distance transform of the mask + nearest-mask-pixel indices
DIST = ndimage.distance_transform_edt(VINE)
NEAR = ndimage.distance_transform_edt(~VINE, return_distances=False, return_indices=True)

# ---- skin / protected regions, affine-scaled from the old-sprite boxes ----
skin = (A > 200) & (R > 175) & (G > 135) & (B > 105) & (R > G + 5) & (G > B + 3)


def scale_box(y0, y1, x0, x1):
    ny0 = int(round((y0 - OLD_PAD) * SY + NEW_PAD_BOX[1]))
    ny1 = int(round((y1 - OLD_PAD) * SY + NEW_PAD_BOX[1]))
    nx0 = int(round((x0 - OLD_PAD) * SX + NEW_PAD_BOX[0]))
    nx1 = int(round((x1 - OLD_PAD) * SX + NEW_PAD_BOX[0]))
    return ny0, ny1, nx0, nx1


def region(y0, y1, x0, x1):
    m = np.zeros((H, W), bool)
    ny0, ny1, nx0, nx1 = scale_box(y0, y1, x0, x1)
    m[ny0:ny1, nx0:nx1] = skin[ny0:ny1, nx0:nx1]
    return ndimage.binary_dilation(m, iterations=3)


PROT = {
    "hand_raised": region(110, 208, 156, 208),
    "hand_hip": region(218, 330, 262, 290),
    "face": region(18, 105, 198, 256),
}
PROT_ANY = np.zeros((H, W), bool)
for m in PROT.values():
    PROT_ANY |= m
PROT_DIST = ndimage.distance_transform_edt(~PROT_ANY)  # clearance to any protected px


def remap(nx, ny):
    """old normalized -> new sprite pixel coords (content-space affine)."""
    cx = nx * OLD_W - OLD_PAD
    cy = ny * OLD_H - OLD_PAD
    return cx * SX + NEW_PAD_BOX[0], cy * SY + NEW_PAD_BOX[1]


def snap_vine(x, y):
    """Nearest vine-mask pixel, then hill-climb the distance transform to the
    local centerline. Returns (nx, ny, snap_dist)."""
    xi, yi = int(round(x)), int(round(y))
    xi = min(max(xi, 0), W - 1)
    yi = min(max(yi, 0), H - 1)
    py, px = int(NEAR[0, yi, xi]), int(NEAR[1, yi, xi])  # indices are (row, col)
    d0 = float(np.hypot(px - x, py - y))
    for _ in range(6):  # ridge refine
        best = (DIST[py, px], px, py)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                qx, qy = px + dx, py + dy
                if 0 <= qx < W and 0 <= qy < H and DIST[qy, qx] > best[0]:
                    best = (DIST[qy, qx], qx, qy)
        if (best[1], best[2]) == (px, py):
            break
        px, py = best[1], best[2]
    return px, py, d0


def probe_solid(x, y, max_r=8):
    """Nearest solid (alpha>200) non-skin pixel within max_r, else None."""
    best = None
    for yy in range(max(int(y) - max_r, 0), min(int(y) + max_r + 1, H)):
        for xx in range(max(int(x) - max_r, 0), min(int(x) + max_r + 1, W)):
            if A[yy, xx] > 200 and not skin[yy, xx]:
                dd = np.hypot(xx - x, yy - y)
                if best is None or dd < best[0]:
                    best = (dd, xx, yy)
    return (best[1], best[2]) if best else None


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else None
    if src:
        old = json.load(open(src))
    else:
        old = json.loads(subprocess.check_output(
            ["git", "show", "HEAD:puppets/treyni/controls.json"], cwd=CD))
    points = []
    report = []
    snap_ds = []
    for p in old["points"]:
        x, y = remap(p["x"], p["y"])
        label = p["label"]
        if label.startswith("vine"):
            x, y, d0 = snap_vine(x, y)
            snap_ds.append(d0)
            if d0 > 10:
                report.append(f"{label} ({x},{y}): LARGE snap {d0:.1f}px")
            if A[int(y), int(x)] <= 60:
                report.append(f"{label} ({x},{y}): ALPHA FAIL {A[int(y), int(x)]}")
        else:
            if A[int(round(y)), int(round(x))] <= 100:
                fixed = probe_solid(x, y)
                if fixed:
                    report.append(f"{label} probed ({x:.1f},{y:.1f}) -> {fixed}")
                    x, y = fixed
                else:
                    report.append(f"{label} ({x:.1f},{y:.1f}): no solid pixel nearby!")
        r = p["r"] * S
        # safety: disk must stay clear of protected skin
        c = float(PROT_DIST[int(round(y)), int(round(x))])
        if c < r + 2.0:
            r_new = max(c - 2.7, 0)
            report.append(f"{label} ({x:.0f},{y:.0f}): clearance {c:.1f} -> r {r:.1f} -> {r_new:.1f}")
            r = r_new
        if r < 4.0:
            report.append(f"{label} ({x:.0f},{y:.0f}) DROPPED (unusable r {r:.1f})")
            continue
        points.append(dict(
            label=label, x=round(x / W, 4), y=round(y / H, 4),
            r=round(r, 1), dx=round(p["dx"] * S, 2), dy=round(p["dy"] * S, 2)))

    with open(CD / "controls.json", "w") as f:
        json.dump({"points": points}, f, indent=1)

    snap_ds = np.array(snap_ds)
    print(f"scale sx={SX:.4f} sy={SY:.4f} s={S:.4f}; sprite {W}x{H}")
    print(f"{len(old['points'])} -> {len(points)} controls; "
          f"vine snap dist mean {snap_ds.mean():.2f}px max {snap_ds.max():.2f}px")
    print("\n".join(report) if report else "all probes + clearances OK")


if __name__ == "__main__":
    main()
