#!/usr/bin/env python3
"""Render preview stills + GIF for a character directory (thin wrapper over puppet_lib).

Usage: python3 render_mesh_preview.py [char_dir]   — defaults to this directory (Rimuru).
See puppet_lib.py's docstring for the character-directory convention.
"""
import os
import sys

from puppet_lib import render_preview

if __name__ == "__main__":
    render_preview(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
