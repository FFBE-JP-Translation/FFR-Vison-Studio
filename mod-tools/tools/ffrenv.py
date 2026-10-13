r"""ffrenv.py - where everything lives, for both the source tree and the packaged app.

Source tree:   ROOT = the repository (this file's parent's parent). Helper scripts run with the current Python, ffr-dt through
               `dotnet src/ffr-dt/bin/Release/net8.0/ffr-dt.dll`, retoc from tools/retoc.
Packaged app:  `FFR Vision Studio.exe` (PyInstaller, one folder). That folder IS the root: tools/ (these scripts + retoc),
               bin/ffr-dt.exe (self-contained), data/ (shipped: Mappings.usmap, enums, catalog, icons, the Brave Exvius data
               pack), and the app writes extracted/, build/ and mods/ next to them exactly like the repository does, so every
               `ROOT = dirname(dirname(__file__))` in the tools keeps working. Helper scripts run through the exe's `--run`.
The game folder comes from <ROOT>/config.json ("gameRoot"), the FFR_GAME environment variable, or Steam's library list.
"""
import json, os, subprocess, sys

FROZEN = bool(getattr(sys, "frozen", False))
APP = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = APP
TOOLS = os.path.join(ROOT, "tools")
DATA = os.path.join(ROOT, "data")
CONFIG = os.path.join(ROOT, "config.json")
GAME_EXE = "FFRS-Win64-Shipping.exe"
GAME_APPID = "4474710"
GAME_DIRNAME = "FINAL FANTASY RESONANCE DEMO"
USMAP = os.path.join(ROOT, "extracted", "Mappings.usmap")
RETOC = os.path.join(TOOLS, "retoc", "retoc.exe")
_FFRDT_EXE = os.path.join(ROOT, "bin", "ffr-dt.exe")
_FFRDT_DLL = os.path.join(ROOT, "src", "ffr-dt", "bin", "Release", "net8.0", "ffr-dt.dll")
# command prefix for the table / asset tool: the self-contained exe when shipped, else the .NET dll
FFRDT = [_FFRDT_EXE] if os.path.exists(_FFRDT_EXE) else ["dotnet", _FFRDT_DLL]
MOD_NAME = "EstherTsukiko"          # the mod's pak stem (zzz_<MOD_NAME>_P) and mods/<MOD_NAME>/units.json


def load_config():
    try: return json.load(open(CONFIG, encoding="utf-8"))
    except Exception: return {}

def save_config(c):
    json.dump(c, open(CONFIG, "w", encoding="utf-8"), indent=1)

def steam_libraries():
    """every Steam library folder on this machine (registry SteamPath + libraryfolders.vdf), or []"""
    libs = []
    try:
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"), (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    p = winreg.QueryValueEx(k, "SteamPath" if hive == winreg.HKEY_CURRENT_USER else "InstallPath")[0]
                    if p and os.path.isdir(p): libs.append(os.path.normpath(p))
            except OSError:
                pass
    except ImportError:
        pass
    out = list(libs)
    for base in libs:
        vdf = os.path.join(base, "steamapps", "libraryfolders.vdf")
        if not os.path.exists(vdf): continue
        for line in open(vdf, encoding="utf-8", errors="ignore"):
            line = line.strip()
            if line.startswith('"path"'):
                p = line.split('"')[3].replace("\\\\", "\\")
                if os.path.isdir(p) and os.path.normpath(p) not in out: out.append(os.path.normpath(p))
    return out

def is_game_root(p):
    return bool(p) and os.path.exists(os.path.join(p, "FFRS", "Content", "Paks", "FFRS-Windows.utoc"))

def detect_game():
    """the game folder: config.json, FFR_GAME, then Steam's libraries; None when nothing is found"""
    c = load_config().get("gameRoot")
    if is_game_root(c): return c
    e = os.environ.get("FFR_GAME")
    if is_game_root(e): return e
    for lib in steam_libraries():
        p = os.path.join(lib, "steamapps", "common", GAME_DIRNAME)
        if is_game_root(p): return p
    return None

def game_root():
    r = detect_game()
    if not r: raise FileNotFoundError("the game folder is not set (config.json gameRoot) and Steam does not list FINAL FANTASY RESONANCE DEMO")
    return r

def game_paks():
    return os.path.join(game_root(), "FFRS", "Content", "Paks")

def game_running():
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {GAME_EXE}"], capture_output=True, text=True).stdout
        return GAME_EXE.lower() in out.lower()
    except Exception:
        return False

def py(script, *args):
    """argv that runs one of the tool scripts: the current interpreter from the source tree, the exe's --run when packaged"""
    if FROZEN: return [sys.executable, "--run", script, *map(str, args)]
    return [sys.executable, script, *map(str, args)]
