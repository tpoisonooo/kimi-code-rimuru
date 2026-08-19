#!/usr/bin/env python3
"""Generate annotate.html from annotate.tpl.html + a character's sprite.png + mesh.json.

Usage: python3 puppet/make_annotate.py [char_dir]   — defaults to puppets/rimuru.

Re-run after every build_mesh.py run so the overlay and snap targets stay
in sync with the mesh.
"""
import base64
import json
import sys
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent
DEFAULT_CHAR_DIR = LIB_DIR.parent / "puppets" / "rimuru"


def main() -> None:
    char_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CHAR_DIR
    tpl = (LIB_DIR / "annotate.tpl.html").read_text(encoding="utf-8")
    b64 = base64.b64encode((char_dir / "sprite.png").read_bytes()).decode("ascii")
    mesh = json.loads((char_dir / "mesh.json").read_text(encoding="utf-8"))
    mesh_slim = {"points": mesh["points"], "tris": mesh["tris"]}
    html = tpl.replace("__SPRITE_B64__", "data:image/png;base64," + b64)
    html = html.replace("__MESH_JSON__", json.dumps(mesh_slim, separators=(",", ":")))
    (char_dir / "annotate.html").write_text(html, encoding="utf-8")
    print(f"annotate.html regenerated ({len(html) // 1024} KiB)")


if __name__ == "__main__":
    main()
