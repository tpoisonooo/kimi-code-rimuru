#!/usr/bin/env python3
"""Build the puppet mesh for a character directory (thin wrapper over puppet_lib).

Usage: python3 puppet/build_mesh.py [char_dir]   — defaults to puppets/rimuru.
See puppet_lib.py's docstring for the character-directory convention.
"""
import sys
from pathlib import Path

from puppet_lib import build_mesh

DEFAULT_CHAR_DIR = Path(__file__).resolve().parents[1] / "puppets" / "rimuru"

if __name__ == "__main__":
    build_mesh(sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_CHAR_DIR))
