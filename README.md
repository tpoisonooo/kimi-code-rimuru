# kimi-code-rimuru

<img width="800" alt="Image" src="https://github.com/user-attachments/assets/bc8c2c21-1fcb-4fd9-a8ce-a278b6e8160c" />

## Affects
Insert `skin.js` into the kimi-code dist-web frontend with no side effects on agents.

The skin is a 2.5D mesh puppet: the sprite is triangulated once (quadtree grid,
contour-snapped), and a handful of hand-annotated control points drive the coat
hem corners, hair tips, boot fur and cuff fur via compact-falloff IDW; the sword
tassel is a separate strip-warped patch so the bead stays rigid. Everything else
is guaranteed static. Static triangles are baked to an offscreen canvas, so each
frame only re-renders the deforming ones.

## How to install

All in one python file:

```python
% python3 rimuru_skin_install.py --help
Rimuru skin for Kimi Code Web UI — single-file installer.

Usage:
  python3 rimuru_skin_install.py                 apply (auto-detect dist-web)
  python3 rimuru_skin_install.py /path/to/dist-web   apply to a specific bundle
  python3 rimuru_skin_install.py --check [path]  report skin/bundle status
                                                 (exit 0 = intact, 1 = needs re-run)
  python3 rimuru_skin_install.py --remove [path] uninstall
  python3 rimuru_skin_install.py --help          show this help

Notes:
  - Apply is idempotent; reload the web UI page afterwards (no server restart).
  - A manual path always wins. Auto-detect tries, in order: source checkout
    (~/kimi-code), npm-global package, `kimi` on PATH, packaged-binary caches
    (~/.cache/kimi-code/web/...). All hits are listed when several exist.
  - Every kimi-code upgrade / sync:web rebuilds the bundle and wipes the patch.
    The installer stamps version + bundle fingerprint into rimuru-skin/.stamp.json
    and warns on re-apply; --check reports CHANGED in that case. 
```

## How it's made (`puppet/` + `puppets/`)

The shared engine lives in `puppet/`; each character is self-contained in its
own `puppets/<char>/` directory:

- `puppet/puppet_lib.py` — the shared engine: sprite → quadtree grid mesh
  (28/14/7px), contour snapping, coverage QA (≥99%), control glue, per-label
  amplitude normalization, IDW deform + GIF/stills render, viewer generation
  (`python3 puppet/puppet_lib.py` runs a self-test)
- `puppet/build_mesh.py` / `render_mesh_preview.py` / `make_viewer.py` /
  `make_annotate.py` — thin wrappers, `python3 puppet/<script> [char_dir]`
  (default: `puppets/rimuru`)
- `puppet/viewer.tpl.html` / `annotate.tpl.html` — shared templates for the
  standalone animation page and the control-point annotation tool
- `puppets/<char>/sprite.png` — keyed sprite (input)
- `puppets/<char>/controls.json` — hand-annotated control points (via
  `annotate.html`)
- `puppets/<char>/char.json` — per-character tuning (Rimuru's: amplitude
  tables, tassel erase polys + strip patch); new characters can omit it
  entirely
- `puppets/<char>/mesh.json`, `mesh_debug.png`, `sprite_meshed.png`,
  `preview.gif`, `still_*.png`, `viewer.html` — generated outputs
- `puppets/rimuru/` additionally holds `tassel_patch.png` and the generated
  `annotate.html`

Rebuild a character after edits (from the repo root):

```
python3 puppet/build_mesh.py puppets/rimuru && python3 puppet/render_mesh_preview.py puppets/rimuru && python3 puppet/make_viewer.py puppets/rimuru
```

Characters built with the same pipeline (previews are 72-frame loops at 12fps,
rendered 1:1 at sprite resolution):

- `puppets/rimuru/` — Rimuru (coat hem corners, hair tips, boot/cuff fur,
  sword tassel) — `puppets/rimuru/preview.gif` (400×618)
- `puppets/shuna/` — Shuna (ponytail, miko sleeves, hakama hem) —
  `puppets/shuna/preview.gif` (202×524)
- `puppets/treyni/` — Treyni (traveling-wave vines, hair tips, dress hem,
  cuffs) — `puppets/treyni/preview.gif` (408×597)
- `puppets/trya/` — Trya (wind-blown dress, vines, peplum frills, sleeves,
  ribbon) — `puppets/trya/preview.gif` (739×1319)

## The skin installer (`skin/`)

`rimuru_skin_install.py` is a self-contained single file: the Rimuru skin
assets are base64-embedded in its `PAYLOAD` dict. The production sources live
in `skin/`, one file per embedded asset:

- `skin/skin.js` — the web-UI widget (fetches the other assets from
  `/rimuru-skin/` at runtime)
- `skin/mesh.json` / `sprite_meshed.png` / `tassel_patch.png` — frozen
  snapshots of the Rimuru puppet build, deliberately decoupled from the
  pipeline: rebuilding `puppets/rimuru` does not change the installer
- `skin/make_installer.py` — regenerates the installer's `PAYLOAD` block from
  these sources (`--check` only reports staleness, exit 1)

After editing anything in `skin/`, regenerate + verify the installer:

```
python3 skin/make_installer.py && python3 rimuru_skin_install.py --help
```

To ship a newer puppet build, copy `puppets/rimuru/mesh.json`,
`sprite_meshed.png` and `tassel_patch.png` over the `skin/` snapshots first,
then regenerate.

Note: the character artwork is official material — fine for internal use,
swap in your own licensed art before public redistribution (the pipeline is
artwork-agnostic).

## Acknowledgments

The triangulation approach (regular grid cells split into triangles, no long
cross-part edges) is inspired by
[ImageToMeshAnim](https://github.com/windsmoon/ImageToMeshAnim) —
thanks for the great write-up on image-to-mesh vertex animation.
