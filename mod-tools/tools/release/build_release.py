r"""build_release.py - package the studio as a Windows program: one folder with `FFR Vision Studio.exe`, no Python, .NET or Node
needed on the user's machine.

    python tools/release/build_release.py [--skip-web] [--skip-dotnet] [--skip-pyinstaller] [--ffbe-pack <folder>] [--zip]

Steps: 1. `npm run build` (the web UI)   2. `dotnet publish` ffr-dt as a self-contained single exe   3. PyInstaller one-folder
build of tools/devui/launcher.py   4. assemble build/release/FFR Vision Studio/ :
    FFR Vision Studio.exe + _internal/       Python runtime and libraries (PyInstaller)
    tools/                                   the studio and generator scripts, retoc, the web bundle
    bin/ffr-dt.exe                           table / asset tool (UAssetAPI), self-contained
    data/                                    shipped data (table mappings, enum names, catalog, icons, container listing,
                                             English text, Brave Exvius index) + optionally the Brave Exvius data pack (data/ffbe)
    mods/EstherTsukiko/units.json            an empty mod to start from (the release does not ship the developer's units)
    assets/                                  icon frames and rarity chips
    README.txt
On first start the exe finds the game through Steam and prepares its data (tools/devui/setup.py); nothing else is required.
"""
import glob, os, shutil, subprocess, sys, zipfile, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REL = os.path.join(ROOT, "build", "release")
OUT = os.path.join(REL, "FFR Vision Studio")
NAME = "FFR Vision Studio"
# These four modules adapt already prepared recordings to the installed game's
# native ACB schema. No master-data lookup, particle decoder or transcoder ships.
EFFECT_RUNTIME_FILES = ('acb_cues.py', 'acb_routing.py', 'acb_native.py', 'hca_host.py')
OFFLINE_TOOL_FILES = {'convert_ffbe_effects.py', 'convert_all_ffbe_animations.py', 'recover_ffbe_animations.py'}
OFFLINE_EFFECT_MODULES = ('catalog', 'export_ability', 'flipbook', 'hca_transcode', 'ibmb', 'layer_spec',
                          'make_gif', 'prepare_vision', 'preview_anim', 'preview_ss6', 'render', 'scene',
                          'screen_adapter', 'source_placement', 'host_coordinates', 'catalog_coverage', 'catalog_batch',
                          'to_ss6', 'uv_sampling', 'prepared_reuse', 'atomic_files', 'shared_delivery', 'regional_assets')


def effect_pyinstaller_exclusions():
    # Exclude both source package imports and the historical direct imports used
    # after adding tools/ffbe_effects to sys.path. Copies are filtered below too.
    names = [*(name[:-3] for name in sorted(OFFLINE_TOOL_FILES)), *OFFLINE_EFFECT_MODULES,
             *('ffbe_effects.' + name for name in OFFLINE_EFFECT_MODULES)]
    return [argument for name in names for argument in ('--exclude-module', name)]


def ship_effect_runtime(tools_root):
    destination = os.path.join(tools_root, 'ffbe_effects')
    os.makedirs(destination, exist_ok=True)
    for name in EFFECT_RUNTIME_FILES:
        shutil.copy2(os.path.join(ROOT, 'tools', 'ffbe_effects', name), os.path.join(destination, name))


def assert_effect_boundary(tools_root):
    actual = {os.path.basename(p) for p in glob.glob(os.path.join(tools_root, 'ffbe_effects', '*.py'))}
    if actual != set(EFFECT_RUNTIME_FILES):
        raise ValueError('Studio release includes source conversion tools or is missing native audio adapters')
    if any(os.path.exists(os.path.join(tools_root, name)) for name in OFFLINE_TOOL_FILES):
        raise ValueError('The offline effects compiler must not be shipped with Studio')

def run(cmd, cwd=None):
    print("$", " ".join(str(c) for c in cmd)); r = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str))
    if r.returncode != 0: sys.exit(f"failed: {cmd[0] if isinstance(cmd, list) else cmd}")

def copy_tree(src, dst, ignore=None):
    if os.path.isdir(dst): shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore)


def ship_converter_data(data):
    """Small, versioned mechanics evidence for imports before game extraction."""
    destination = os.path.join(data, "ability_converter")
    os.makedirs(destination, exist_ok=True)
    for name in ('reviewed-rules.json', 'vision-kits.sqlite', 'vision-kits-audit.json'):
        source = os.path.join(ROOT, 'data', 'ability_converter', name)
        if not os.path.isfile(source): raise FileNotFoundError('Build all reviewed vision kits before packaging: ' + source)
        if os.path.abspath(source) != os.path.abspath(os.path.join(destination, name)):
            shutil.copy2(source, os.path.join(destination, name))
    for name in ("ffr-effects.json", "ffbe-effects.json", "proposed-map.json", "proposed-policies.json"):
        shutil.copy2(os.path.join(ROOT, "docs", "build16", name), os.path.join(destination, name))
    for name in ("Skill/DT_SkillData.json", "Skill/DT_PassiveSkillData.json", "Skill/Other/DT_SkillGeneralData.json", "Skill/Other/DT_SkillTargetData.json"):
        target = os.path.join(destination, "rows", name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, "extracted", "rows", name), target)

def main():
    a = sys.argv[1:]
    os.makedirs(REL, exist_ok=True)
    if "--skip-web" not in a: run("npm run build", cwd=os.path.join(ROOT, "tools", "devui", "web"))
    if "--skip-dotnet" not in a:
        run(["dotnet", "publish", os.path.join(ROOT, "src", "ffr-dt"), "-c", "Release", "-r", "win-x64", "--self-contained", "true",
             "-p:PublishSingleFile=true", "-p:IncludeNativeLibrariesForSelfExtract=true", "-p:DebugType=None", "-o", os.path.join(REL, "ffr-dt")])
    if "--skip-pyinstaller" not in a:
        run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--name", NAME, "--distpath", os.path.join(REL, "dist"), "--workpath", os.path.join(REL, "work"),
             "--specpath", REL, "--collect-all", "uvicorn", "--collect-all", "fastapi", "--collect-all", "starlette", "--collect-all", "anyio",
             "--hidden-import", "multipart", "--hidden-import", "PIL.WebPImagePlugin", "--hidden-import", "sqlite3",
             *effect_pyinstaller_exclusions(),
             os.path.join(ROOT, "tools", "devui", "launcher.py")])
    # ---- assemble
    if os.path.isdir(OUT): shutil.rmtree(OUT)
    copy_tree(os.path.join(REL, "dist", NAME), OUT)
    py_ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "node_modules", "src", "*.log", ".vite")
    os.makedirs(os.path.join(OUT, "tools"), exist_ok=True)
    for f in glob.glob(os.path.join(ROOT, "tools", "*.py")):
        if os.path.basename(f) not in OFFLINE_TOOL_FILES: shutil.copy(f, os.path.join(OUT, "tools"))
    shutil.copy(os.path.join(ROOT, "tools", "vision_card_names.json"), os.path.join(OUT, "tools"))
    for sub in ("devui", "ability_converter", "effect_review", "ffbe2ss6", "retoc", "repak"):
        copy_tree(os.path.join(ROOT, "tools", sub), os.path.join(OUT, "tools", sub), ignore=py_ignore)
    ship_effect_runtime(os.path.join(OUT, 'tools'))
    assert_effect_boundary(os.path.join(OUT, 'tools'))
    os.makedirs(os.path.join(OUT, "tools", "scripts"), exist_ok=True); shutil.copy(os.path.join(ROOT, "tools", "scripts", "utoc_index.py"), os.path.join(OUT, "tools", "scripts"))
    copy_tree(os.path.join(ROOT, "tools", "devui", "web", "dist"), os.path.join(OUT, "tools", "devui", "web", "dist"))
    os.makedirs(os.path.join(OUT, "bin"), exist_ok=True)
    for f in glob.glob(os.path.join(REL, "ffr-dt", "*")): shutil.copy(f, os.path.join(OUT, "bin"))
    data = os.path.join(OUT, "data"); os.makedirs(os.path.join(data, "ffbe"), exist_ok=True)
    ship_converter_data(data)
    ship = [("extracted/Mappings.usmap", "Mappings.usmap"), ("extracted/CXXHeaderDump/mucha_enums.hpp", "mucha_enums.hpp"), ("extracted/locres_en.json", "locres_en.json"),
            ("extracted/utoc_filelist.tsv", "utoc_filelist.tsv"), ("build/devui/ffr_catalog.json", "ffr_catalog.json"), ("build/devui/icons", "icons"), ("build/icons/donors", "icon_donors"),
            ("build/devui/ffbe_en.json", "ffbe/ffbe_en.json"),   # the unit index is NOT shipped: setup builds it from the pack's sprites
            ("data/ffbe/ability_icons", "ffbe/ability_icons"),
            ("build/visions_mod/check/da/DA_UIUnitSsLayout.json", "DA_UIUnitSsLayout.json")]
    for src, dst in ship:
        s, d = os.path.join(ROOT, src), os.path.join(data, dst)
        if not os.path.exists(s): print("  ! not shipped (missing):", src); continue
        (copy_tree if os.path.isdir(s) else shutil.copy)(s, d)
    if "--ffbe-pack" in a:
        pack = a[a.index("--ffbe-pack") + 1]
        for item in os.listdir(pack):
            s, d = os.path.join(pack, item), os.path.join(data, "ffbe", item)
            (copy_tree if os.path.isdir(s) else shutil.copy)(s, d)
    copy_tree(os.path.join(ROOT, "assets"), os.path.join(OUT, "assets"))
    os.makedirs(os.path.join(OUT, "mods", "EstherTsukiko"), exist_ok=True)
    open(os.path.join(OUT, "mods", "EstherTsukiko", "units.json"), "w", encoding="utf-8").write("[]\n")
    lay = os.path.join(ROOT, "mods", "EstherTsukiko", "icon_layout.json")
    if os.path.exists(lay): shutil.copy(lay, os.path.join(OUT, "mods", "EstherTsukiko"))
    open(os.path.join(OUT, "README.txt"), "w", encoding="utf-8").write(README)
    print("assembled", OUT)
    if "--zip" in a:
        z = os.path.join(REL, f"FFR-Vision-Studio-{datetime.date.today():%Y%m%d}.zip")
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            for dp, _, fs in os.walk(OUT):
                for f in fs:
                    p = os.path.join(dp, f); zf.write(p, os.path.relpath(p, REL))
        print("zipped", z, os.path.getsize(z) // 1048576, "MB")

README = """FFR Vision Studio
=================
Adds Brave Exvius units as Visions to FINAL FANTASY RESONANCE (Steam demo).

1. Unzip this folder anywhere you like (not inside the game folder).
2. Run "FFR Vision Studio.exe". A console window stays open while the studio runs; your browser opens the studio.
3. First run: the studio finds the game through Steam and prepares its data (a few minutes, once). If the game is installed
   somewhere Steam does not list, paste the game folder.
4. Easy mode: add a unit, pick its abilities, bonuses, stats and Resonance from what the game already has, then press
   "Install into the game" (the game must be closed). The new Vision is sold in the Mitra item shop.
   Advanced mode: everything, including Brave Exvius kit imports and animation edits.

The studio writes to its own folder (extracted/, build/, mods/, config.json) and to <game>/FFRS/Content/Paks/~mods/.
To uninstall the mod, delete the zzz_EstherTsukiko_P.* files from that ~mods folder.
"""

if __name__ == "__main__":
    main()
