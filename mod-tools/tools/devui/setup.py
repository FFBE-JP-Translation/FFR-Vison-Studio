r"""setup.py - first-run preparation of the studio's data, for the packaged app and the source tree alike.

    python tools/devui/setup.py [--game "<game folder>"]

What it does (each step is skipped when its output already exists):
  1. remembers the game folder (given, Steam-detected, or config.json) in <ROOT>/config.json
  2. copies the shipped data (data/) into place: extracted/Mappings.usmap, extracted/CXXHeaderDump/mucha_enums.hpp,
     extracted/locres_en.json, extracted/utoc_filelist.tsv, build/devui/ffr_catalog.json + icons, build/icons/donors,
     build/devui/ffbe_index.json + ffbe_en.json
  3. converts the game assets the generator reads to legacy .uasset with retoc: every DataTable, the three template visions'
     battle + menu sprites (13108 Terra, 13110 Cloud, 13125 Lightning) and the UI icon textures
  4. dumps every DataTable to extracted/rows/<table>.json with ffr-dt (parallel), which the catalog and the verifier read
  5. rebuilds the container listing / catalog / Brave Exvius index when they were not shipped
The game folder is never written to here; only "Install into the game" copies the finished mod into Paks/~mods.
"""
import glob, json, os, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import ffrenv
ROOT, DATA = ffrenv.ROOT, ffrenv.DATA
LEGACY = os.path.join(ROOT, "extracted", "legacy")
ROWS = os.path.join(ROOT, "extracted", "rows")
DEVUI = os.path.join(ROOT, "build", "devui")
TEMPLATE_VISIONS = (13108, 13110, 13125)       # donors the generator clones sprites / tables / textures from
# retoc `--filter` is an asset path substring; one call per entry
EXTRACT_FILTERS = ["Datatable", "UI/Textures/Icon", "UI/Unit/UIUnitSs/Data"] + [f"Chara/{kind}/summon{v}" for v in TEMPLATE_VISIONS for kind in ("summon", "menu")]
SHIPPED = [   # (data/ file or folder, destination under ROOT)
    ("Mappings.usmap", "extracted/Mappings.usmap"), ("mucha_enums.hpp", "extracted/CXXHeaderDump/mucha_enums.hpp"),
    ("locres_en.json", "extracted/locres_en.json"), ("utoc_filelist.tsv", "extracted/utoc_filelist.tsv"),
    ("ffr_catalog.json", "build/devui/ffr_catalog.json"), ("icons", "build/devui/icons"), ("icon_donors", "build/icons/donors"),
    ("ffbe/ffbe_en.json", "build/devui/ffbe_en.json"),      # the unit index is built here from the pack's sprites, never shipped
    ("DA_UIUnitSsLayout.json", "build/visions_mod/check/da/DA_UIUnitSsLayout.json"),   # menu sprite layout map the generator extends
]

# every table the catalog, the generator and the verifier read (tools/make_vision_mod.py, tools/devui/ffr_catalog.py ...): the
# preparation is not done until each of these has its dump, whatever else was skipped (string tables never dump, by design)
REQUIRED_TABLES = ["Asset/Battle/Unit/DT_BtlUnitAsset", "Asset/Skill/DT_SkillAsset", "Battle/Sequencer/DT_BtlHitEffectData", "Battle/Unit/DT_BtlUnitDesignParameter",
                   "Item/Vision/DT_VisionAwakeningMasteryData", "Item/Vision/DT_VisionItemData", "Item/Vision/DT_VisionSynchroMasteryData", "PostProcess/DT_ColorGradingParameter",
                   "Shop/DT_ShopList", "Skill/DT_CommandSkillData", "Skill/DT_MasterSkillData", "Skill/DT_PassiveSkillData", "Skill/DT_SkillData", "Skill/DT_SkillEffectData",
                   "Skill/Other/DT_SkillSealPointData", "UI/Skill/CDT_SkillIcon", "UI/Skill/DT_CommandSkillIcon", "UI/Vision/DT_VisionUpgrade_VisionUpgradeData",
                   "Unit/DT_UnitParameter", "Unit/LevelParameter/DT_UnitLevelParameterList"]

def missing_tables():
    return [t for t in REQUIRED_TABLES if not os.path.exists(os.path.join(ROWS, t + ".json"))]

def missing():
    """what still has to be prepared before the studio can build a mod (empty = ready)"""
    out = []
    if not ffrenv.detect_game(): out.append("the game folder")
    if not os.path.exists(ffrenv.USMAP): out.append("the table mappings")
    if not os.path.exists(os.path.join(LEGACY, "FFRS", "Content", "Datatable", "Skill", "DT_SkillData.uasset")): out.append("the game's data tables")
    mt = missing_tables()
    if mt: out.append(f"the table dumps ({len(mt)} of {len(REQUIRED_TABLES)} needed tables: {', '.join(t.rsplit('/', 1)[-1] for t in mt[:4])}{' ...' if len(mt) > 4 else ''})")
    if not os.path.exists(os.path.join(LEGACY, "FFRS", "Content", "Chara", "summon", "summon13110", "summon13110.uasset")): out.append("the template sprites")
    if not os.path.exists(os.path.join(DEVUI, "ffr_catalog.json")): out.append("the skill catalog")
    return out

def _copy_shipped(log):
    for src, dst in SHIPPED:
        s, d = os.path.join(DATA, src), os.path.join(ROOT, dst)
        if not os.path.exists(s) or os.path.exists(d): continue
        os.makedirs(os.path.dirname(d), exist_ok=True)
        (shutil.copytree if os.path.isdir(s) else shutil.copy)(s, d); log(f"placed {dst}")

def _extract(paks, log):
    for f in EXTRACT_FILTERS:
        marker = {"Datatable": "FFRS/Content/Datatable/Skill/DT_SkillData.uasset", "UI/Textures/Icon": "FFRS/Content/UI/Textures/Icon/menu",
                  "UI/Unit/UIUnitSs/Data": "FFRS/Content/UI/Unit/UIUnitSs/Data/DA_UIUnitSsLayout.uasset"}.get(f, "FFRS/Content/" + f)
        if os.path.exists(os.path.join(LEGACY, marker)): continue
        log(f"converting game assets: {f} ...")
        r = subprocess.run([ffrenv.RETOC, "to-legacy", "--no-shaders", "--filter", f, paks, LEGACY], capture_output=True, text=True)
        if r.returncode != 0: raise RuntimeError(f"retoc failed on {f}: {(r.stderr or r.stdout)[-600:]}")

def _dump_rows(log):
    tables = [p for p in glob.glob(os.path.join(LEGACY, "FFRS", "Content", "Datatable", "**", "*.uasset"), recursive=True)]
    todo = []
    for p in tables:
        rel = os.path.relpath(p, os.path.join(LEGACY, "FFRS", "Content", "Datatable"))[:-7]
        out = os.path.join(ROWS, rel + ".json")
        if not os.path.exists(out): todo.append((p, out))
    if not todo: return
    log(f"reading {len(todo)} data tables ...")
    errors = {}
    def one(job):
        p, out = job; os.makedirs(os.path.dirname(out), exist_ok=True)
        try:
            r = subprocess.run(ffrenv.FFRDT + ["rows", p, out, "--usmap", ffrenv.USMAP], capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode != 0 or not os.path.exists(out): errors[out] = (r.stderr or r.stdout or "").strip()[-300:] or f"exit {r.returncode}"
        except Exception as ex:                                # a crashed launch must not take the whole pool down
            errors[out] = str(ex)
        return out if os.path.exists(out) else None
    # the shipped ffr-dt is a single-file .NET exe that unpacks its native libraries on first use: run one table alone before
    # the parallel pass, and retry whatever the parallel pass dropped one at a time
    one(todo[0]); done = 1
    with ThreadPoolExecutor(max_workers=max(2, min(6, (os.cpu_count() or 4) - 1))) as ex:
        for res in ex.map(one, todo[1:]):
            done += 1
            if done % 100 == 0: log(f"  {done}/{len(todo)} tables")
    retry = [job for job in todo if not os.path.exists(job[1])]
    if retry:
        log(f"  retrying {len(retry)} table(s) one at a time ...")
        for job in retry: one(job)
    bad = [job[1] for job in todo if not os.path.exists(job[1])]
    needed = [b for b in bad if any(b.replace("\\", "/").endswith(t + ".json") for t in REQUIRED_TABLES)]
    if bad: log(f"  {len(bad)} table(s) could not be read ({len(bad) - len(needed)} of them string tables or others the studio does not need)")
    for b in needed:                                           # these stop a build: say why while the log is in front of the user
        log(f"  ! needed table failed: {os.path.relpath(b, ROWS)}: {errors.get(b, 'no output')}")

def _listing(paks, log):
    out = os.path.join(ROOT, "extracted", "utoc_filelist.tsv")
    if os.path.exists(out): return
    log("listing the game's asset container ...")
    r = subprocess.run(ffrenv.py(os.path.join(ffrenv.TOOLS, "scripts", "utoc_index.py"), out, os.path.dirname(os.path.dirname(os.path.dirname(paks)))), capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out): raise RuntimeError(f"container listing failed: {(r.stderr or r.stdout)[-400:]}")

def prepare(game=None, log=print):
    game = game or ffrenv.detect_game()
    if not ffrenv.is_game_root(game): raise FileNotFoundError(f"not the game folder (no FFRS/Content/Paks/FFRS-Windows.utoc): {game}")
    c = ffrenv.load_config(); c["gameRoot"] = game; ffrenv.save_config(c); log(f"game: {game}")
    _copy_shipped(log)
    if not os.path.exists(ffrenv.USMAP): raise FileNotFoundError("extracted/Mappings.usmap is missing (it ships in data/Mappings.usmap)")
    paks = os.path.join(game, "FFRS", "Content", "Paks")
    _extract(paks, log)
    _dump_rows(log)
    _listing(paks, log)
    if not os.path.exists(os.path.join(DEVUI, "ffr_catalog.json")):
        log("building the skill catalog ...")
        import ffr_catalog; ffr_catalog.build()
    if not os.path.exists(os.path.join(DEVUI, "ffbe_index.json")):
        log("indexing the Brave Exvius data ...")
        try:
            import ffbe_catalog; ffbe_catalog.build_index()
        except Exception as ex:
            log(f"  Brave Exvius index not built ({ex}); add the data pack under data/ffbe/ and prepare again")
    left = missing()
    if left: raise RuntimeError("still missing: " + ", ".join(left))
    log("ready")

if __name__ == "__main__":
    g = sys.argv[sys.argv.index("--game") + 1] if "--game" in sys.argv else None
    prepare(g)
