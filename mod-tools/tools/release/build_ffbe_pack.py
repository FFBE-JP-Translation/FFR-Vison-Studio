r"""build_ffbe_pack.py - gather the Brave Exvius data the studio reads into one folder (data/ffbe) for the packaged app.

    python tools/release/build_ffbe_pack.py <out folder> [--sprites all | --sprites <form id> ... | --sprites none]

Contents (the studio's ffbe_catalog.py looks here first when data/ffbe exists):
    ffbeEquip.zip                 the ten source tables the studio reads (units, skills, magic, passives, limit bursts; GL + JP)
                                  with the same internal paths as the original ffbeEquip-master.zip
    datamine/{gl,jp}/*.json       the wiki datamine tables (units / skills / limitbursts)
    ffbe_en.json, ffbe_index.json the cached English names and the unit index (from build/devui)
    sprites/<form id>/            unit sheets + cgg/cgs (+ icon) per form, in the BFFrameAnimator layout
Sprite sheets are large (3,000+ forms); ship the units you want or none, and add more later by dropping form folders in.
"""
import json, os, shutil, sys, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools", "devui"))
import ffbe_catalog as fc

def main():
    out = sys.argv[1]; os.makedirs(out, exist_ok=True)
    sprites = sys.argv[sys.argv.index("--sprites") + 1:] if "--sprites" in sys.argv else ["none"]
    # 1. ffbeEquip tables
    if os.path.exists(fc.ZIP):
        src = zipfile.ZipFile(fc.ZIP)
        with zipfile.ZipFile(os.path.join(out, "ffbeEquip.zip"), "w", zipfile.ZIP_DEFLATED) as dst:
            for region, base in fc.SRC.items():
                for t in fc.TABLES:
                    n = base + t + ".json"
                    try: dst.writestr(n, src.read(n))
                    except KeyError: print("  missing in zip:", n)
        print("ffbeEquip tables packed")
    # 2. datamine
    for sub in ("gl", "jp"):
        d = os.path.join(fc.DATAMINE, sub)
        if not os.path.isdir(d): continue
        os.makedirs(os.path.join(out, "datamine", sub), exist_ok=True)
        for t in ("units.json", "skills.json", "limitbursts.json"):
            if os.path.exists(os.path.join(d, t)): shutil.copy(os.path.join(d, t), os.path.join(out, "datamine", sub, t))
        print("datamine", sub, "copied")
    # 3. caches
    # Preserve movement, per-component targeting, hit timing and sound references
    # needed by the shared resonance resolver on machines without local dumps.
    for name in ("F_UNIT_MST", "F_LIMITBURST_MST", "F_EFFECT_GROUP_MST"):
        source = os.path.join(ROOT, "build", "devui", "live_jp", name + ".json")
        if os.path.isfile(source):
            os.makedirs(os.path.join(out, "master"), exist_ok=True)
            shutil.copy(source, os.path.join(out, "master", name + ".json"))
    for f in ("ffbe_en.json",):
        p = os.path.join(fc.OUT, f)
        if os.path.exists(p): shutil.copy(p, os.path.join(out, f))
    # Shared and per-unit LB sounds must be available without developer drives.
    for name in ("SE.acb", "System.acb"):
        source = os.path.join(ROOT, "data", "ffbe", "audio", name)
        if not os.path.isfile(source): source = os.path.join("S:/FFBE JP Data Export/public", name)
        if not os.path.isfile(source): raise FileNotFoundError(f"Missing FFBE audio source: {name}")
        os.makedirs(os.path.join(out, "audio"), exist_ok=True)
        shutil.copy2(source, os.path.join(out, "audio", name))
    # 4. sprites
    if sprites and sprites[0] != "none":
        forms = list(fc.sprite_map().keys()) if sprites[0] == "all" else sprites
        n = 0
        for form in forms:
            files = fc.sprite_files(form)          # only this form's files: flat roots hold thousands of forms in one folder
            if not files: continue
            dst = os.path.join(out, "sprites", str(form))
            if os.path.isdir(dst): continue
            os.makedirs(dst)
            for f in files: shutil.copy(f, dst)
            n += 1
            if n % 100 == 0: print(f"  {n} forms")
        print(n, "sprite folders copied")
    print("pack at", out)

if __name__ == "__main__":
    main()
