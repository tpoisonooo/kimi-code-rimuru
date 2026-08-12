# kimi-code-rimuru

<img width="800" alt="Image" src="https://github.com/user-attachments/assets/bc8c2c21-1fcb-4fd9-a8ce-a278b6e8160c" />

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
