#!/usr/bin/env python3
"""Generate viewer.html from viewer.tpl.html + sprite.png + mesh.json."""
import base64
import json
from pathlib import Path

D = Path(__file__).resolve().parent


def main() -> None:
    tpl = (D / "viewer.tpl.html").read_text(encoding="utf-8")
    b64 = base64.b64encode((D / "sprite_meshed.png").read_bytes()).decode("ascii")
    tb64 = base64.b64encode((D / "tassel_patch.png").read_bytes()).decode("ascii")
    mesh = (D / "mesh.json").read_text(encoding="utf-8")
    html = tpl.replace("__SPRITE_B64__", "data:image/png;base64," + b64)
    html = html.replace("__TASSEL_B64__", "data:image/png;base64," + tb64)
    html = html.replace("__MESH_JSON__", mesh)
    (D / "viewer.html").write_text(html, encoding="utf-8")
    print(f"viewer.html regenerated ({len(html) // 1024} KiB)")


if __name__ == "__main__":
    main()
