#!/usr/bin/env python3
"""Prepare puppets/treyni/sprite.png from resources/Treyni__transparent_full_body.png.

The source is already RGBA on a transparent background, so this only trims
the transparent margins, keeping a small padding so silhouette tips stay off
the image edge. Full HD: NO downscale (the old 400x589 sprite was a 0.74x
reduction; this keeps the native 546x820 resolution, trimmed to 547x802).
"""
from pathlib import Path

import numpy as np
from PIL import Image

SRC = Path(__file__).resolve().parents[2] / "resources" / "Treyni__transparent_full_body.png"
DST = Path(__file__).resolve().parent / "sprite.png"
PAD = 4

img = Image.open(SRC).convert("RGBA")
alpha = np.array(img)[..., 3]
ys, xs = np.where(alpha > 10)
x0 = max(xs.min() - PAD, 0)
y0 = max(ys.min() - PAD, 0)
x1 = min(xs.max() + PAD + 1, img.width)
y1 = min(ys.max() + PAD + 1, img.height)
out = img.crop((x0, y0, x1, y1))
out.save(DST)
print(f"{SRC.name} {img.size} -> {DST} {out.size}")
