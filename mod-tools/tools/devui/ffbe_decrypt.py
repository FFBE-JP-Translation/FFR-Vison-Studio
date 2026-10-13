r"""ffbe_decrypt.py - decrypt + extract the JP live client's unit archives with the user's DataExtractor tool
(T:\Projects\FFBE Patch\cpk_2\DataExtractor.exe: CriPakTools fork that knows FFBE's per-file asset encryption).

python tools/devui/ffbe_decrypt.py [unit30.cpk ...]      default: every unit*.cpk of the AndApp live client
-> build/ffbe_cpk/jp_live_dec/<files>   (flat: unit_anime_<form>.png, unit_cgg_<form>.csv, unit_<anim>_cgs_<form>.csv, icons)

The tool writes its output next to the input archive and only accepts archives inside a folder named "cpk", so each
archive is copied to build/ffbe_cpk/_decrypt_work/cpk/ first. Archives whose files
are already present in the output folder are skipped (pass --force to redo them).
"""
import glob, os, re, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOL_DIR = r"T:\Projects\FFBE Patch\cpk_2"
LIVE = r"C:\Users\Raegen\AppData\Roaming\AndApp\GameData\5701868182306816\5574872228495360\public"
OUT = os.path.join(ROOT, "build", "ffbe_cpk", "jp_live_dec")
WORK = os.path.join(ROOT, "build", "ffbe_cpk", "_decrypt_work")

def tool_copy():
    """private copy of the tool (exe + dlls) inside the work folder"""
    os.makedirs(WORK, exist_ok=True)
    for f in os.listdir(TOOL_DIR):
        if f.lower().endswith((".exe", ".dll")):
            dst = os.path.join(WORK, f)
            if not os.path.exists(dst): shutil.copy(os.path.join(TOOL_DIR, f), dst)
    return os.path.join(WORK, "DataExtractor.exe")

def decrypt(cpk, force=False):
    exe = tool_copy()
    name = os.path.basename(cpk)[:-4]
    job = os.path.join(WORK, "cpk"); shutil.rmtree(job, ignore_errors=True); os.makedirs(job)   # the tool only accepts archives inside a folder named "cpk"
    src = os.path.join(job, os.path.basename(cpk)); shutil.copy(cpk, src)
    t0 = time.time()
    r = subprocess.run([exe, src], cwd=WORK, capture_output=True, text=True, timeout=1800)
    os.remove(src)
    files = [f for f in os.listdir(job) if f != os.path.basename(cpk)]
    os.makedirs(OUT, exist_ok=True)
    moved = 0
    for f in files:
        dst = os.path.join(OUT, f)
        if os.path.exists(dst) and not force: os.remove(os.path.join(job, f)); continue
        shutil.move(os.path.join(job, f), dst); moved += 1
    shutil.rmtree(job, ignore_errors=True)
    bad = [f for f in files if f.endswith(".png") and not is_png(os.path.join(OUT, f))]
    print(f"{name}: {len(files)} files ({moved} new) in {time.time() - t0:.0f} s{' | NOT PNG: ' + str(len(bad)) if bad else ''}{' | rc ' + str(r.returncode) if r.returncode else ''}")
    return files

def is_png(p):
    try:
        with open(p, "rb") as fh: return fh.read(8) == b"\x89PNG\r\n\x1a\n"
    except OSError: return False

def main():
    """ffbe_decrypt.py [--out DIR] [--force] [archive ...]   (default: the live unit*.cpk into jp_live_dec)"""
    global OUT
    argv = sys.argv[1:]
    if "--out" in argv:
        i = argv.index("--out"); OUT = os.path.abspath(argv[i + 1]); del argv[i:i + 2]
    args = [a for a in argv if not a.startswith("--")]; force = "--force" in argv
    cpks = args or sorted(glob.glob(os.path.join(LIVE, "unit*.cpk")), key=lambda p: int(re.search(r"unit(\d+)", os.path.basename(p)).group(1)))
    total = 0
    for c in cpks:
        total += len(decrypt(c, force))
    sheets = len(glob.glob(os.path.join(OUT, "unit_anime_*.png")))
    print(f"done: {total} files this run; {len(os.listdir(OUT))} files ({sheets} sprite sheets) in {OUT}")

if __name__ == "__main__":
    main()
