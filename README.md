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

## How it's made (`mesh/`)

Full pipeline + results live in `mesh/`:

- `puppet_lib.py` — the shared engine: sprite → quadtree grid mesh (28/14/7px),
  contour snapping, coverage QA (≥99%), control glue, per-label amplitude
  normalization, IDW deform + GIF/stills render, viewer generation
  (`python3 mesh/puppet_lib.py` runs a self-test)
- `char.json` — per-character config (Rimuru's tuning: amplitude tables, tassel
  erase polys + strip patch); new characters can omit it entirely
- `build_mesh.py` / `render_mesh_preview.py` / `make_viewer.py` — thin wrappers,
  `python3 <script> [char_dir]` (default: `mesh/` itself, i.e. Rimuru)
- `controls.json` — hand-annotated control points (via `annotate.html`)
- `viewer.tpl.html` / `viewer.html` — standalone animation page
- `annotate.tpl.html` / `annotate.html` — control-point annotation tool
- `mesh.json`, `mesh_debug.png` — generated mesh + overlay
- `sprite.png` / `sprite_meshed.png` / `tassel_patch.png` — keyed sprite assets

Rebuild after edits:

```
python3 build_mesh.py && python3 render_mesh_preview.py && python3 make_viewer.py
```

More puppets built with the same pipeline, each self-contained in its own
character directory (`sprite.png` + `controls.json` + `char.json` + generated
`mesh.json` / `preview.gif` / stills / `viewer.html`):

- `mesh/shuna/` — Shuna (ponytail, miko sleeves, hakama hem)
- `mesh/treyni/` — Treyni (traveling-wave vines, hair tips, dress hem, cuffs)
- `mesh/trya/` — Trya (vines, dress scallops, peplum frills, sleeves, ribbon)

Note: the character artwork is official material — fine for internal use,
swap in your own licensed art before public redistribution (the pipeline is
artwork-agnostic).

## Acknowledgments

The triangulation approach (regular grid cells split into triangles, no long
cross-part edges) is inspired by
[ImageToMeshAnim](https://github.com/windsmoon/ImageToMeshAnim) —
thanks for the great write-up on image-to-mesh vertex animation.
