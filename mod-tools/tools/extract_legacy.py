#!/usr/bin/env python
"""extract_legacy.py - convert game assets (Zen/IoStore) to legacy .uasset/.uexp with retoc.
usage: python tools/extract_legacy.py [--filter Datatable] [--out extracted/legacy]
Everything under FFRS/Content matching the filter is written to --out (defaults: Datatable + Strings only).
"""
import argparse, os, subprocess
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools")); import ffrenv
RETOC = ffrenv.RETOC
PAKS = ffrenv.game_paks()
ap = argparse.ArgumentParser(); ap.add_argument("--filter", action="append"); ap.add_argument("--out", default=os.path.join(ROOT, "extracted", "legacy"))
a = ap.parse_args()
for f in (a.filter or ["Datatable"]):
    cmd = [RETOC, "to-legacy", "--no-shaders", "--filter", f, PAKS, a.out]
    print(" ".join(cmd)); subprocess.run(cmd, check=True)
