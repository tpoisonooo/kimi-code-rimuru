#!/usr/bin/env python3
"""Generate viewer.html for a character directory (thin wrapper over puppet_lib).

Usage: python3 make_viewer.py [char_dir]   — defaults to this directory (Rimuru).
See puppet_lib.py's docstring for the character-directory convention.
"""
import os
import sys

from puppet_lib import make_viewer

if __name__ == "__main__":
    make_viewer(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
