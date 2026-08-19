#!/usr/bin/env python3
"""Regenerate rimuru_skin_install.py's embedded PAYLOAD from the skin/ sources.

rimuru_skin_install.py is a self-contained single-file installer: its PAYLOAD
dict holds the rimuru-skin/ web assets base64-embedded. The production sources
of those assets live here in skin/, one file per PAYLOAD key (1:1 mapping):

    skin.js             the widget itself; it fetches mesh.json /
                        sprite_meshed.png / tassel_patch.png from /rimuru-skin/
                        at runtime, so no mesh or image data is embedded in it
    mesh.json           frozen snapshot of the Rimuru puppet mesh
                        (built by the puppet/ pipeline — see puppets/rimuru/)
    sprite_meshed.png   frozen snapshot of the keyed, erase-polys-cut sprite
    tassel_patch.png    frozen snapshot of the tassel strip-patch texture

The snapshots are deliberately decoupled from the puppet pipeline: rebuilding
puppets/rimuru does NOT change the installer. To ship a newer puppet, copy the
regenerated puppets/rimuru/{mesh.json,sprite_meshed.png,tassel_patch.png}
over the skin/ files, then re-run this script.

Usage:

    python3 skin/make_installer.py           rewrite rimuru_skin_install.py in place
    python3 skin/make_installer.py --check   report only; exit 1 when the
                                             installer is stale vs skin/

Only the PAYLOAD block is regenerated; the surrounding installer logic is left
untouched — edit rimuru_skin_install.py directly for logic changes, then re-run
this script to confirm the PAYLOAD is still in sync.
"""
import base64
import re
import sys
from pathlib import Path

SKIN_DIR = Path(__file__).resolve().parent
INSTALLER = SKIN_DIR.parent / "rimuru_skin_install.py"

# PAYLOAD block: a line "PAYLOAD = {", then one ' "key": "<base64>"' line per
# asset (comma-separated, last line bare), then a closing "}" line.
BLOCK_RE = re.compile(r"^PAYLOAD = \{\n(.*?)^\}$", re.S | re.M)
ENTRY_RE = re.compile(r'^ "([^"]+)": "([A-Za-z0-9+/=]+)"(,?)$', re.M)


def render_block(keys):
    lines = ["PAYLOAD = {"]
    for i, key in enumerate(keys):
        b64 = base64.b64encode((SKIN_DIR / key).read_bytes()).decode("ascii")
        lines.append(f' "{key}": "{b64}"{"," if i < len(keys) - 1 else ""}')
    lines.append("}")
    return "\n".join(lines)


def main():
    src = INSTALLER.read_text(encoding="utf-8")
    m = BLOCK_RE.search(src)
    if not m:
        sys.exit(f"error: PAYLOAD block not found in {INSTALLER}")
    keys = [e.group(1) for e in ENTRY_RE.finditer(m.group(1))]
    if not keys:
        sys.exit("error: no entries found in PAYLOAD block")
    missing = [k for k in keys if not (SKIN_DIR / k).is_file()]
    if missing:
        sys.exit(f"error: PAYLOAD keys without a skin/ source: {', '.join(missing)}")
    out = src[: m.start()] + render_block(keys) + src[m.end():]
    if out == src:
        print("rimuru_skin_install.py is up to date with skin/")
        return
    if "--check" in sys.argv[1:]:
        sys.exit("rimuru_skin_install.py is STALE vs skin/ — run skin/make_installer.py")
    INSTALLER.write_text(out, encoding="utf-8")
    print(f"rimuru_skin_install.py regenerated from skin/ ({len(out)} bytes)")


if __name__ == "__main__":
    main()
