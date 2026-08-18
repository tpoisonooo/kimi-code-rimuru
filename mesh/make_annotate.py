#!/usr/bin/env python3
"""Generate annotate.html from annotate.tpl.html + sprite.png + mesh.json.

Re-run after every build_mesh.py run so the overlay and snap targets stay
in sync with the mesh.
"""
import base64
import json
from pathlib import Path

D = Path(__file__).resolve().parent


def main() -> None:
    tpl = (D / "annotate.tpl.html").read_text(encoding="utf-8")
    b64 = base64.b64encode((D / "sprite.png").read_bytes()).decode("ascii")
    mesh = json.loads((D / "mesh.json").read_text(encoding="utf-8"))
    mesh_slim = {"points": mesh["points"], "tris": mesh["tris"]}
    html = tpl.replace("__SPRITE_B64__", "data:image/png;base64," + b64)
    html = html.replace("__MESH_JSON__", json.dumps(mesh_slim, separators=(",", ":")))
    (D / "annotate.html").write_text(html, encoding="utf-8")
    print(f"annotate.html regenerated ({len(html) // 1024} KiB)")


if __name__ == "__main__":
    main()
