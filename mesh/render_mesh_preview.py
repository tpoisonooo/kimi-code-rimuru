#!/usr/bin/env python3
"""Render preview stills + GIF for the mesh-puppet Rimuru animation.

Deformation: compact-falloff IDW — each control displaces vertices within its
radius (smoothstep falloff, normalized weights); vertices outside every radius
stay exactly static. Per-triangle affine texture mapping with a slight dst
expansion to hide seams.
"""
import json
import os

import numpy as np
from PIL import Image, ImageDraw

OUT = os.path.dirname(os.path.abspath(__file__))

FPS = 12
SECONDS = 6
STILL_TIMES = (0.27, 0.55, 0.83)
EXPAND = 0.8          # px dst-triangle expansion (seam hiding)


def load():
    mesh = json.load(open(os.path.join(OUT, "mesh.json")))
    sprite = Image.open(os.path.join(OUT, "sprite_meshed.png")).convert("RGBA")
    tassel = Image.open(os.path.join(OUT, "tassel_patch.png")).convert("RGBA")
    return mesh, sprite, tassel


# tassel from the rimuru-skin strip scheme: one feathered patch, rows shifted
# with a bottom-weighted ramp — bead stays rigid because its texture is solid
TASSEL = {"x": 313, "y": 247, "amp_x": 4.0, "amp_y": 0.5, "period": 1.1, "phase": 1.2, "exp": 1.5}


def warp_tassel(patch, t):
    ph, pw = patch.shape[:2]
    out = np.zeros_like(patch)
    ang = 2 * np.pi * t / TASSEL["period"] + TASSEL["phase"]
    sx, sy = np.sin(ang), np.cos(ang)
    for j in range(ph):
        w = (j / (ph - 1)) ** TASSEL["exp"]
        dx = int(round(TASSEL["amp_x"] * w * sx))
        dy = int(round(TASSEL["amp_y"] * w * sy))
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


def render_frame(mesh, state, sprite, tassel, t):
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
    # tassel patch on top (strip warp, same params as the rimuru-skin version)
    warped = Image.fromarray(warp_tassel(np.array(tassel), t))
    frame.alpha_composite(warped, (TASSEL["x"], TASSEL["y"]))
    return frame


def main():
    mesh, sprite, tassel = load()
    state = build_state(mesh)
    w, h = mesh["width"], mesh["height"]

    for t in STILL_TIMES:
        f = render_frame(mesh, state, sprite, tassel, t)
        flat = Image.new("RGBA", (w, h), (255, 255, 255, 255))
        flat.alpha_composite(f)
        flat.convert("RGB").save(os.path.join(OUT, f"still_{t:.2f}.png"))

    frames = []
    n = FPS * SECONDS
    for i in range(n):
        f = render_frame(mesh, state, sprite, tassel, i / FPS)
        flat = Image.new("RGBA", (w, h), (255, 255, 255, 255))
        flat.alpha_composite(f)
        frames.append(flat.convert("RGB"))
        if (i + 1) % 24 == 0:
            print(f"{i + 1}/{n}")
    pal = frames[0].quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    frames_q = [fr.quantize(palette=pal, dither=Image.Dither.NONE) for fr in frames]
    frames_q[0].save(
        os.path.join(OUT, "preview.gif"),
        save_all=True, append_images=frames_q[1:],
        duration=round(1000 / FPS), loop=0, optimize=True,
    )
    print("gif ok")


if __name__ == "__main__":
    main()
