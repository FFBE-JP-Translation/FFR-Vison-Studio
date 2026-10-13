#!/usr/bin/env python
"""build_mod.py - package a folder of LEGACY-format assets into an IoStore mod and (optionally) install it.

usage:
  python tools/build_mod.py <mod_dir> <ModName> [--install] [--game "<game root>"]

<mod_dir> must mirror the mount layout, e.g.
  <mod_dir>/FFRS/Content/Datatable/Unit/DT_UnitParameter.uasset  (+ .uexp)
Output: build/out/zzz_<ModName>_P.{utoc,ucas,pak}
--install copies them to <game>/FFRS/Content/Paks/~mods/  (the "~mods" folder + "_P" suffix make UE mount them on top of the base game)
"""
import argparse, os, shutil, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools")); import ffrenv
RETOC = ffrenv.RETOC
DEFAULT_GAME = ffrenv.detect_game() or ""
ap = argparse.ArgumentParser()
ap.add_argument("mod_dir"); ap.add_argument("name")
ap.add_argument("--install", action="store_true"); ap.add_argument("--game", default=DEFAULT_GAME)
a = ap.parse_args()
out_dir = os.path.join(ROOT, "build", "out"); os.makedirs(out_dir, exist_ok=True)
stem = os.environ.get("FFR_MOD_STEM") or f"zzz_{a.name}_P"
if not stem.replace('_', '').isalnum() or not stem.endswith('_P'):
    raise ValueError('Mod filename must be an alphanumeric _P stem')
utoc = os.path.join(out_dir, stem + ".utoc")
r = subprocess.run([RETOC, "to-zen", "--version", "UE5_6", a.mod_dir, utoc], capture_output=True, text=True)
print(r.stdout, r.stderr)
if r.returncode != 0: sys.exit("retoc to-zen failed")
for ext in (".utoc", ".ucas", ".pak"):
    p = os.path.join(out_dir, stem + ext); print(f"  {os.path.getsize(p):>10} {p}")
if a.install:
    if not ffrenv.is_game_root(a.game): sys.exit(f"not the game folder: {a.game!r} (pass --game or set gameRoot in config.json)")
    dst = os.path.join(a.game, "FFRS", "Content", "Paks", "~mods"); os.makedirs(dst, exist_ok=True)
    for ext in (".utoc", ".ucas", ".pak"):
        shutil.copy(os.path.join(out_dir, stem + ext), dst)
    print("installed to", dst)
