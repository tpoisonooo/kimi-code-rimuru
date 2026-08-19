#!/usr/bin/env python3
"""Build the puppet mesh for a character directory (thin wrapper over puppet_lib).

Usage: python3 build_mesh.py [char_dir]   — defaults to this directory (Rimuru).
See puppet_lib.py's docstring for the character-directory convention.
"""
import os
import sys

from puppet_lib import build_mesh

if __name__ == "__main__":
    build_mesh(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
