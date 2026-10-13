import mmap, re, os, collections
G = r"S:\Program Files (x86)\Steam\steamapps\common\FINAL FANTASY RESONANCE DEMO"
EXE = os.path.join(G, r"FFRS\Binaries\Win64\FFRS-Win64-Shipping.exe")
OUT = r"S:\Projects\ffr\extracted\exe_strings"
os.makedirs(OUT, exist_ok=True)
with open(EXE,"rb") as f:
    mm = mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
    # ASCII strings >= 6 chars
    asc = set(m.group().decode() for m in re.finditer(rb"[\x20-\x7e]{6,}", mm))
    # UTF-16LE strings >= 6 chars
    u16 = set()
    for m in re.finditer(rb"(?:[\x20-\x7e]\x00){6,}", mm):
        u16.add(m.group().decode("utf-16-le"))
    mm.close()
allس = None
alls = asc | u16
print("ascii strings:", len(asc), "utf16 strings:", len(u16))
def dump(name, items):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as o:
        for s in sorted(items): o.write(s+"\n")
    print(f"{name}: {len(items)}")
cpp = {s for s in alls if re.fullmatch(r"[AUFE]?CPP_[A-Za-z0-9_]+", s)}
dump("cpp_classes.txt", cpp)
dm = {s for s in alls if re.search(r"DebugMenu|DM_IA_|CPP_DM|DMI_", s)}
dump("debugmenu_strings.txt", dm)
unit = {s for s in alls if re.search(r"UnitParameter|UnitLevelParameter|PlayableUnit|VisionItem|SkillData|SkillEffect|PassiveSkill|AppDataTableList|DataTableList", s)}
dump("unit_datatable_strings.txt", unit)
cvars = {s for s in alls if re.fullmatch(r"(mucha|ffrs|dm|btl|debug|ss6|ss|ffr|game|ui|map|event)\.[A-Za-z0-9_.]+", s, re.I)}
dump("cvars.txt", cvars)
ss = {s for s in alls if re.search(r"SpriteStudio|SsProject|SsAnim|\.ssae|\.sspj|\.ssce|SsPlayer", s)}
dump("spritestudio_strings.txt", ss)
paths = {s for s in alls if s.startswith("/Game/") or s.startswith("/Script/mucha") or s.startswith("/DebugMenuWidget/")}
dump("asset_paths_in_exe.txt", paths)
shipping = {s for s in alls if re.search(r"UE_BUILD_SHIPPING|WITH_EDITOR|Shipping|bIsDebugMenuEnabled|EnableDebugMenu|IsDebugMenu|DebugMenuEnable|CheatManager", s)}
dump("shipping_flags.txt", shipping)
# print top hits
for n in ["cpp_classes.txt","debugmenu_strings.txt","unit_datatable_strings.txt","cvars.txt","spritestudio_strings.txt","shipping_flags.txt"]:
    print("\n----", n); print(open(os.path.join(OUT,n),encoding="utf-8").read()[:2500])
