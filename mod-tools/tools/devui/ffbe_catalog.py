r"""ffbe_catalog.py - FFBE side of the dev UI: unit index across every local data source, per-unit detail (forms, stats, skills,
passives, limit bursts, sprite animations), the FFBE -> FFR stat formula and animation previews rendered from cgg/cgs data.

Data regions (first hit wins in region_of): GL / JP = ffbeEquip sources (S:\ffbeEquip-master.zip, ~mid 2022),
GLW / JPW = aEnigmatic wiki datamine (T:\Projects\ffbe\ffbe-wiki-tools\datamine\data\{gl,jp}, 2024-10, same shape, includes the
newest units such as Raegen -Ultimate Summon-). English names / descriptions / ability names come from the user's FFBE English
patch tables (T:\Projects\FFBE Patch\english_patch\swapped) where they exist.
Sprite roots (first hit wins): the BFFrameAnimator Units folder, the JP live client archives extracted to build/ffbe_cpk/jp_live
(3,529 forms through 2025-10), and the GL client dump packs (T:\ffbe_patch\gl_extracted, 3,690 forms).
python tools/devui/ffbe_catalog.py rebuilds build/devui/ffbe_index.json (+ ffbe_en.json).
"""
import glob, io, json, os, re, sys, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ffbe2ss6"))
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# the packaged app ships a data pack (tools/release/build_ffbe_pack.py) under data/ffbe; the developer's machine has the full sources
PACK = os.path.join(ROOT, "data", "ffbe")
def _first(*cands): return next((c for c in cands if c and os.path.exists(c)), cands[-1])
ZIP = _first(os.path.join(PACK, "ffbeEquip.zip"), r"S:\ffbeEquip-master.zip")
DATAMINE = _first(os.path.join(PACK, "datamine"), r"T:\Projects\ffbe\ffbe-wiki-tools\datamine\data")
PATCH = _first(os.path.join(PACK, "english_patch"), r"T:\Projects\FFBE Patch\english_patch\swapped")
PATCH_ICONS = _first(os.path.join(PACK, "ability_icons"), r"T:\Projects\FFBE Patch\jp_extracted\on_demand_asset2\item1")
OUT = os.path.join(ROOT, "build", "devui")
SRC = {"GL": "ffbeEquip-master/tools/GL/sources/", "JP": "ffbeEquip-master/tools/JP/sources/"}
TABLES = ("units", "skills_ability", "skills_magic", "skills_passive", "limitbursts")
REGION_ORDER = ("GL", "JP", "GLW", "JPW", "LIVE")
REGION_LABEL = {"GL": "GL", "JP": "JP", "GLW": "GL 2024", "JPW": "JP 2024", "LIVE": "JP live"}
# the datamine stores unit roles as ids; names derived by matching the same units in the ffbeEquip tables
DATAMINE_ROLES = {1: "Attacker", 2: "Mage", 3: "Tank", 4: "Magic Tank", 5: "Healer", 6: "Support", 7: "Breaker", 8: "Versatile", 9: "EXP Boost",
                  10: "Sellable", 11: "Fusion", 12: "Stat Boost", 13: "Stat Break", 14: "Over-Level", 15: "Remove Over-Level"}
# sprite roots: (path, layout) layout "perform" = <root>/<form id>/files, "flat" = files directly, "packs" = <root>/*/files
SPRITE_ROOTS = [
    (os.path.join(PACK, "sprites"), "perform", "pack"),                              # the shipped data pack (form folders)
    (r"S:\FFBE JP Data Export\BFFrameAnimator-master\Units", "perform", "jp_export"),
    (os.path.join(ROOT, "build", "ffbe_cpk", "jp_live_dec"), "flat", "jp_live"),      # live client archives decrypted by tools/devui/ffbe_decrypt.py
    (r"T:\ffbe_patch\gl_extracted\common_lang\sd\unit", "packs", "gl_extracted"),
    (r"T:\ffbe_patch\jp_extracted\on_demand_asset3", "packs", "jp_memorial"),
]
# English patch tables: file, id key, value key (the patch obfuscates the column names; G4L0YIB2 = name)
EN_TABLES = {"units": ("SsidX62G.txt", "3HriTp6B", "G4L0YIB2"), "unit_desc": ("Da62x85q.txt", "3HriTp6B", "fYhnz5N9"),
             "abilities": ("TK61DudV.txt", "Ga5V42LZ", "G4L0YIB2"), "magic": ("wJE09yxD.txt", "6E5u1xrs", "G4L0YIB2"),
             "lb": ("c5T4PIyL.txt", "PR2HIc71", "G4L0YIB2")}
JP_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")

# FFR Terra (13108) / FFBE Magitek Warrior Terra 7* max stats -> per-stat ratio applied to every ported unit's max stats
TERRA_FFR = {"MaxHitPoint": 800, "MaxMagicPoint": 100, "Attack": 25, "Defence": 30, "Intelligence": 10, "Mind": 20, "Agility": 15}
TERRA_FFBE = {"HP": 4450, "MP": 288, "ATK": 137, "DEF": 144, "MAG": 220, "SPR": 198}
STAT_MAP = {"MaxHitPoint": "HP", "MaxMagicPoint": "MP", "Attack": "ATK", "Defence": "DEF", "Intelligence": "MAG", "Mind": "SPR"}

# ---------------------------------------------------------------- data sources
_src = None
def sources():
    global _src
    if _src is not None: return _src
    _src = {}
    if os.path.isfile(os.path.join(PACK, "catalog.json")):
        _src = {region: {t: {} for t in TABLES} for region in REGION_ORDER}
        for path in glob.glob(os.path.join(PACK, "unit_records", "*.json")):
            doc = json.load(open(path, encoding="utf-8"))
            for region, tables in doc.get("sources", {}).items():
                for name, rows in tables.items():
                    _src.setdefault(region, {}).setdefault(name, {}).update(rows)
        return _src
    z = zipfile.ZipFile(ZIP) if os.path.exists(ZIP) else None
    for region, base in SRC.items():
        _src[region] = {}
        for t in TABLES:
            try: _src[region][t] = json.loads(z.read(base + t + ".json")) if z else {}
            except KeyError: _src[region][t] = {}
    for region, sub in (("GLW", "gl"), ("JPW", "jp")):
        d = os.path.join(DATAMINE, sub)
        if not os.path.isdir(d): continue
        tabs = {t: {} for t in TABLES}
        try:
            tabs["units"] = json.load(open(os.path.join(d, "units.json"), encoding="utf-8"))
            for u in tabs["units"].values():
                u["roles"] = [DATAMINE_ROLES.get(r, str(r)) if isinstance(r, int) else r for r in (u.get("roles") or [])]
            for sid, s in json.load(open(os.path.join(d, "skills.json"), encoding="utf-8")).items():
                # Keep the complete structured source. Presentation adapters
                # must not discard hit weights, resource costs or restrictions.
                row = {**s, "cost": {resource: s[key] for key, resource in
                                     (("mp_cost", "MP"), ("lb_cost", "LB"), ("ev_cost", "EV")) if key in s}}
                kind = "skills_passive" if s.get("active") is False else "skills_magic" if s.get("type") == "MAGIC" else "skills_ability"
                tabs[kind][str(sid)] = row
            for lid, lb in json.load(open(os.path.join(d, "limitbursts.json"), encoding="utf-8")).items():
                levels = lb.get("levels") or {}
                lo = levels[min(levels, key=lambda k: int(k))] if levels else {}
                tabs["limitbursts"][str(lid)] = {**lb, "name": lb.get("name"), "min_level_effects": lo.get("effects"), "attack_count": lb.get("attack_count"),
                                                 "attack_type": lb.get("damage_type"), "element_inflict": lb.get("element_inflict"), "cost": lb.get("cost")}
        except FileNotFoundError:
            continue
        _src[region] = tabs
    live = live_units()
    if live: _src["LIVE"] = {"units": live, "skills_ability": {}, "skills_magic": {}, "skills_passive": {}, "limitbursts": {}}
    return _src

LIVE_SRC = os.path.join(ROOT, "build", "devui", "live_jp", "F_UNIT_MST.json")   # decrypted by tools/devui/ffbe_live.py (developer machine)
def live_units():
    """Units that exist only in the live JP client (newer than the datamine), as the sources() shape. Read from the data pack's
    live_units.json; on the developer machine derived from F_UNIT_MST.json and written into the pack so the release ships it."""
    packed = os.path.join(PACK, "live_units.json")
    if os.path.exists(packed):
        try: return json.load(open(packed, encoding="utf-8"))
        except Exception: pass
    if not os.path.exists(LIVE_SRC): return {}
    try: rows = json.load(open(LIVE_SRC, encoding="utf-8"))
    except Exception: return {}
    if isinstance(rows, dict): rows = rows.get("rows") or list(rows.values())   # ffbe_live.py writes {"table", "file", "rows": [...]}
    units = {}
    def stat(v):
        try: lo, hi = str(v).split(",")[:2]; return [int(lo), int(hi)]
        except Exception: return None
    for r in rows:
        if not isinstance(r, dict): continue
        uid = str(r.get("unit_id") or ""); fid = str(r.get("unit_evo_id") or "")
        if not uid.isdigit() or not fid.isdigit(): continue
        nv = str(r.get("nv_level") or "0")
        rarity = "NV+" if fid.endswith(("27", "37")) and nv not in ("0", "") else ("NV" if nv not in ("0", "") else str(r.get("rarity") or ""))
        u = units.setdefault(uid, {"name": r.get("name"), "rarity_min": rarity, "rarity_max": rarity, "roles": [], "entries": {}, "live": True})
        if fid.endswith(("27", "37")): u["rarity_max"] = rarity
        u["entries"][fid] = {"rarity": rarity, "nv_level": nv, "is_shift_form": str(r.get("is_shift_form") or "0"), "nv_unit_evo_id": str(r.get("nv_unit_evo_id") or "0"),
                             "limitburst_id": r.get("lb_id"), "stats": {k: stat(r.get(c)) for k, c in (("HP", "hp"), ("MP", "mp"), ("ATK", "atk"), ("DEF", "def"), ("MAG", "mag"), ("SPR", "spr"))}}
    try:
        if os.path.isdir(PACK): json.dump(units, open(packed, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception: pass
    return units

_en = None
def english():
    """{table: {id: english text}} from the FFBE English patch (cached in build/devui/ffbe_en.json)"""
    global _en
    if _en is not None: return _en
    cache = os.path.join(OUT, "ffbe_en.json")
    if os.path.exists(cache):
        _en = json.load(open(cache, encoding="utf-8")); return _en
    _en = {t: {} for t in EN_TABLES}
    for t, (fn, idk, valk) in EN_TABLES.items():
        p = os.path.join(PATCH, fn)
        if not os.path.exists(p): continue
        for line in open(p, encoding="utf-8", errors="ignore"):
            line = line.strip()
            if not line.startswith("{"): continue
            try: d = json.loads(line)
            except Exception: continue
            i, v = d.get(idk), d.get(valk)
            if i and isinstance(v, str) and v.strip(): _en[t][str(i)] = v.replace("<br>", " ").strip()
    os.makedirs(OUT, exist_ok=True)
    json.dump(_en, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    return _en

def is_jp(s): return bool(s and JP_RE.search(s))
_gloss = None
def glossary():
    """hand-written English for names the patch does not cover (tools/devui/jp_glossary.json)"""
    global _gloss
    if _gloss is None:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jp_glossary.json")
        _gloss = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    return _gloss
def translate(kind, text):
    """glossary lookup: returns the English name or None"""
    if not text: return None
    v = (glossary().get(kind) or {}).get(text.strip())
    return v or None
def en_name(uid):
    v = english()["units"].get(str(uid)); return v if v and not is_jp(v) else None
def en_desc(uid):
    v = english()["unit_desc"].get(str(uid)); return v if v and not is_jp(v) else None
def en_skill(sid):
    e = english(); v = e["abilities"].get(str(sid)) or e["magic"].get(str(sid))
    return v if v and not is_jp(v) else None
def en_lb(uid):
    v = english()["lb"].get(str(uid)); return v if v and not is_jp(v) else None
def ability_icon_path(name):
    if not name: return None
    import skill_icons
    bundled = skill_icons.path(name)
    if bundled: return str(bundled)
    p = os.path.join(PATCH_ICONS, os.path.basename(name))
    return p if os.path.exists(p) else None

# ---------------------------------------------------------------- sprites
_sprite_map = None; _locked = None
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
def is_png(path):
    try:
        with open(path, "rb") as fh: return fh.read(8) == PNG_MAGIC
    except OSError: return False
def sprite_map():
    """form id -> (directory holding a readable unit_anime_<form>.png, root label); first root wins.
    Sheets that are not real PNGs (the JP live client stores most of its unit archives encrypted) are skipped and listed in locked_forms()."""
    global _sprite_map, _locked
    if _sprite_map is not None: return _sprite_map
    _sprite_map = {}; _locked = {}
    def offer(fid, d, label):
        if fid in _sprite_map: return
        if is_png(os.path.join(d, f"unit_anime_{fid}.png")): _sprite_map[fid] = (d, label); _locked.pop(fid, None)
        else: _locked.setdefault(fid, (d, label))
    for root, layout, label in SPRITE_ROOTS:
        # A prepared catalog resolves forms through downloaded bundles. Scanning
        # the developer's raw client trees here can block imports for minutes.
        if os.path.isfile(os.path.join(PACK, "catalog.json")) and label not in ("pack", "jp_live"):
            continue
        if not os.path.isdir(root): continue
        if layout == "perform":
            for d in os.listdir(root):
                if d.isdigit() and os.path.exists(os.path.join(root, d, f"unit_anime_{d}.png")): offer(d, os.path.join(root, d), label)
        else:
            dirs = [root] if layout == "flat" else [os.path.join(root, d) for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
            for d in dirs:
                for f in os.listdir(d):
                    m = re.match(r"unit_anime_(\d+)\.png$", f)
                    if m: offer(m.group(1), d, label)
    return _sprite_map
def locked_forms():
    """form id -> (dir, label) for sheets that exist only in an encrypted form"""
    sprite_map(); return _locked

def _pack_dir(form):
    """the shipped / downloaded sprite root, checked live: a pack fetched after the engine started must be found at once"""
    d = os.path.join(PACK, "sprites", str(form))
    if os.path.isdir(d) and is_png(os.path.join(d, f"unit_anime_{form}.png")):
        m = sprite_map()
        if str(form) not in m or m[str(form)][1] != "pack": m[str(form)] = (d, "pack"); _locked.pop(str(form), None)
        return d
    return None

def sprite_dir(form):
    d = _pack_dir(form)
    if d: return d
    custom = glob.glob(os.path.join(ROOT, 'units', 'custom', '*', 'sprites', str(form))) if str(form).isdigit() else []
    for path in custom:
        if is_png(os.path.join(path, f'unit_anime_{form}.png')): return path
    e = sprite_map().get(str(form)); return e[0] if e else None
def sprite_source(form):
    if _pack_dir(form): return "pack"
    e = sprite_map().get(str(form)); return e[1] if e else None
def sprite_files(form):
    """every file of the form (sheet, cgg, cgs, icon, illustration, extra pages)"""
    d = sprite_dir(form)
    if not d: return []
    return [os.path.join(d, f) for f in os.listdir(d) if re.search(r"_%s(_\d+)?\.(png|csv)$" % form, f)]

def ffr_stats(ffbe_max):
    """FFBE max stats (dict HP/MP/ATK/DEF/MAG/SPR) -> FFR base stats via the Terra ratios; Agility stays at the vision default"""
    out = {}
    for ffr, ffbe in STAT_MAP.items():
        v = ffbe_max.get(ffbe)
        out[ffr] = max(1, int(round(v * TERRA_FFR[ffr] / TERRA_FFBE[ffbe]))) if v else TERRA_FFR[ffr]
    out["Agility"] = TERRA_FFR["Agility"]
    return out

# ---------------------------------------------------------------- index / detail
_rarities = _rar_forms = None
def rarities():
    """Corrected rarity per unit and per form (docs/units/rarities.md). The shipped sources contradict themselves -- the live
    table's `rarity` string is derived from the id suffix and calls Brave Shift sheets NV+, and 385 of the 1295 rows came out
    with a range that runs downhill (`NV` to `7`) -- so the studio reads this table instead of the sources' own fields."""
    global _rarities, _rar_forms
    if _rarities is None:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rarities.json")
        try: _rarities = json.load(open(p, encoding="utf-8"))
        except Exception: _rarities = {}
        _rar_forms = {f: d for v in _rarities.values() for f, d in (v.get("forms") or {}).items()}
    return _rarities

def form_rarity(form):
    """{'rarity', 'shift', 'of'} for one form id, or {}"""
    rarities(); return _rar_forms.get(str(form)) or {}

def build_index():
    global _sprite_map, _locked, _idx_rows, _src
    _sprite_map = None; _locked = None; _idx_rows = None   # rescan the roots: packs may have been downloaded since the engine started
    packed = os.path.join(PACK, "catalog.json")
    if os.path.isfile(packed):
        _src = None
        out = json.load(open(packed, encoding="utf-8"))["units"]
        os.makedirs(OUT, exist_ok=True)
        json.dump(out, open(os.path.join(OUT, "ffbe_index.json"), "w", encoding="utf-8"), ensure_ascii=False)
        _idx_rows = {e["id"]: e for e in out}
        return out
    s = sources(); idx = {}
    for region in ("LIVE", "JPW", "JP", "GLW", "GL"):   # later regions win the display name (GL English last); LIVE only fills gaps
        for uid, u in s.get(region, {}).get("units", {}).items():
            forms = sorted((u.get("entries") or {}).keys())
            e = idx.setdefault(uid, {"id": uid, "regions": [], "forms": forms})
            e["regions"].append(region)
            nm = u.get("name")
            if nm and (region.startswith("GL") or "name" not in e or is_jp(e.get("name") or "")): e["name"] = nm
            if is_jp(nm or ""): e["jpname"] = nm
            e.setdefault("rarity_min", u.get("rarity_min")); e["rarity_max"] = u.get("rarity_max") or e.get("rarity_max")
            e["roles"] = u.get("roles") or e.get("roles")
            e["forms"] = sorted(set(e["forms"]) | set(forms))
    sm = sprite_map(); lk = locked_forms()
    owner = {}                                     # form id -> the unit whose entries list it (unit ids and form ids share one number space)
    for uid, e in idx.items():
        for f in e["forms"]: owner.setdefault(f, uid)
    out = []
    for uid, e in idx.items():
        sprite_forms = [f for f in e["forms"] if f in sm] or [f for f in sm if f.startswith(uid[:7]) and owner.get(f, uid) == uid]
        locked = [f for f in e["forms"] if f in lk and f not in sm]
        if not sprite_forms and not locked: continue
        en = next((en_name(f) for f in [uid] + list(e["forms"]) if en_name(f)), None) or translate("units", e.get("jpname") or e.get("name"))
        if en: e["name"] = en
        if sprite_forms:
            icon_form = next((f for f in sorted(sprite_forms, reverse=True) if os.path.exists(os.path.join(sm[f][0], f"unit_icon_{f}.png"))), sprite_forms[0])
            e.update({"spriteForms": sorted(sprite_forms), "iconForm": icon_form, "spriteSource": sm[sprite_forms[0]][1], "locked": False})
        else:
            e.update({"spriteForms": [], "iconForm": None, "spriteSource": lk[locked[0]][1], "locked": True})
        e.update({"source": "GL" if "GL" in e["regions"] or "GLW" in e["regions"] else "JP", "english": not is_jp(e.get("name") or ""),
                  "labels": [REGION_LABEL[r] for r in REGION_ORDER if r in e["regions"]]})
        out.append(e)
    # Brave Shift / Super Limit Break: FFBE gives the unit a second id ten above the first with the same name. One row, two looks.
    by_id = {e["id"]: e for e in out}
    merged = set()
    for e in out:
        try: other = by_id.get(str(int(e["id"]) + 10))
        except ValueError: other = None
        if not other or other["id"] in merged or e["id"] in merged: continue
        if (other.get("name") or "") != (e.get("name") or "") or other["id"][:7] != e["id"][:7]: continue
        e["pairOf"] = other["id"]; e["shift"] = {}
        for f in other.get("forms", []):
            base = str(int(f) - 10) if str(int(f) - 10) in e.get("forms", []) else (e.get("spriteForms") or e.get("forms") or [None])[-1]
            kind = "brave_shift" if "brave_shift" in sprite_anims(f) else "slb"
            e["shift"][f] = {"kind": kind, "base": base}
        e["forms"] = sorted(set(e["forms"]) | set(other.get("forms", [])))
        e["spriteForms"] = sorted(set(e.get("spriteForms") or []) | set(other.get("spriteForms") or []))
        e["regions"] = sorted(set(e["regions"]) | set(other["regions"]))
        e["labels"] = [REGION_LABEL[r] for r in REGION_ORDER if r in e["regions"]]
        merged.add(other["id"])
    out = [e for e in out if e["id"] not in merged]
    out = _apply_merges(out)
    for e in out:                       # the corrected ladder: rarities and which sheets are Brave Shift / Super Limit Break
        r = rarities().get(e["id"])
        if not r: continue
        e["rarity_min"], e["rarity_max"] = r["rarity_min"], r["rarity_max"]
        sh = {f: {"kind": d["shift"], "base": d["of"]} for f, d in (r.get("forms") or {}).items() if d.get("shift") and d.get("of")}
        if sh: e["shift"] = sh
        else: e.pop("shift", None)
    import ffbe_categories
    live_rows = json.load(open(LIVE_SRC, encoding="utf-8")).get("rows", []) if os.path.isfile(LIVE_SRC) else []
    ffbe_categories.enrich(out, s, live_rows)
    out.sort(key=lambda e: (e.get("name") or "", e["id"]))
    os.makedirs(OUT, exist_ok=True)
    json.dump(out, open(os.path.join(OUT, "ffbe_index.json"), "w", encoding="utf-8"), ensure_ascii=False)
    _idx_rows = {e["id"]: e for e in out}
    print(f"ffbe index: {len(out)} units ({sum(1 for e in out if e['locked'])} with encrypted sheets only, {sum(1 for e in out if e['source']=='GL')} GL, "
          f"{sum(1 for e in out if e['source']=='JP')} JP only, {sum(1 for e in out if not e['english'])} without an English name; "
          f"sprite roots {dict((l, sum(1 for v in sm.values() if v[1]==l)) for _,_,l in SPRITE_ROOTS)}; encrypted sheets {len(lk)})")
    return out

def _apply_merges(out):
    """One row per character: tools/devui/index_merges.json (docs/units/index_merges.md) drops the story / NPC copies and
    broken rows and folds the same unit's other ids (Global-vs-JP, re-issues, Neo Vision awakenings) into one row, their forms
    becoming extra looks. `mergedIds` records what was folded in so unit_detail and the add route can reach those forms."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index_merges.json")
    if not os.path.exists(p): return out
    try: plan = json.load(open(p, encoding="utf-8"))
    except Exception: return out
    by_id = {e["id"]: e for e in out}
    drop = set(plan.get("drop") or [])
    gone = set()
    def rank(r):
        r = str(r); return (2, r.count("+")) if r.startswith(("NV", "EX")) else (1, int(r)) if r.isdigit() else (0, 0)
    for m in plan.get("merge") or []:
        keep = by_id.get(m["into"])
        if not keep: continue
        for fid in m.get("from") or []:
            other = by_id.get(fid)
            if not other or fid == keep["id"] or fid in gone: continue
            keep["forms"] = sorted(set(keep.get("forms") or []) | set(other.get("forms") or []))
            keep["spriteForms"] = sorted(set(keep.get("spriteForms") or []) | set(other.get("spriteForms") or []))
            keep["regions"] = sorted(set(keep.get("regions") or []) | set(other.get("regions") or []))
            keep["labels"] = [REGION_LABEL[r] for r in REGION_ORDER if r in keep["regions"]]
            sh = dict(keep.get("shift") or {}); sh.update(other.get("shift") or {})
            if sh: keep["shift"] = sh
            ids = list(keep.get("mergedIds") or []) + [fid] + ([other["pairOf"]] if other.get("pairOf") else []) + list(other.get("mergedIds") or [])
            keep["mergedIds"] = sorted(set(ids) - {keep["id"]})
            for k in ("rarity_min", "rarity_max"):
                a, b = keep.get(k), other.get(k)
                if b is not None and (a is None or (rank(b) < rank(a) if k == "rarity_min" else rank(b) > rank(a))): keep[k] = b
            if not keep.get("iconForm") and other.get("iconForm"): keep["iconForm"] = other["iconForm"]
            if keep.get("english") is False and other.get("english") and other.get("name"): keep["name"] = other["name"]; keep["english"] = True
            gone.add(fid)
    return [e for e in out if e["id"] not in drop and e["id"] not in gone]

def load_index():
    # The shipped catalog lists all available looks. A cache created by an older
    # engine only knew downloaded sprites and could lose undownloaded BS pairs.
    packed = os.path.join(PACK, "catalog.json")
    if os.path.isfile(packed):
        return json.load(open(packed, encoding="utf-8"))["units"]
    p = os.path.join(OUT, "ffbe_index.json")
    if not os.path.exists(p): return build_index()
    return json.load(open(p, encoding="utf-8"))

def region_of(uid):
    s = sources()
    for r in REGION_ORDER:
        if uid in s.get(r, {}).get("units", {}): return r
    return None

def resolve_skill(region, sid):
    s = sources()[region]; sid = str(sid)
    for tbl, kind in (("skills_ability", "ABILITY"), ("skills_magic", "MAGIC"), ("skills_passive", "PASSIVE")):
        row = s[tbl].get(sid)
        if row:
            fx = []
            for e in row.get("effects") or []:
                fx.append(e if isinstance(e, str) else " / ".join(str(x) for x in e))
            name = row.get("name"); en = en_skill(sid) or translate("skills", name)
            if en and (is_jp(name or "") or not name): name = en
            icon = row.get("icon")
            return {"id": int(sid), "kind": kind, "name": name, "jpname": row.get("name") if row.get("name") != name else None, "effects": fx, "cost": row.get("cost"),
                    "icon": icon, "iconUrl": f"/api/ffbe/abilityicon/{os.path.basename(icon)}" if ability_icon_path(icon) else None,
                    "attack_type": row.get("attack_type"), "element": row.get("element_inflict"), "move_type": row.get("move_type"), "motion_type": row.get("motion_type"),
                    "attack_count": row.get("attack_count"), "attack_frames": row.get("attack_frames"), "effect_type": row.get("effect_type"), "magic_type": row.get("magic_type"),
                    "region": region, "unique": row.get("unique"),
                    "sourceRecord": skill_record(region, sid, tbl, row)}
    return {"id": int(sid), "kind": "?", "name": en_skill(sid), "effects": [], "missing": True}


def skill_record(region, sid, table, row):
    """Portable mechanics snapshot; names displayed by Studio are independent."""
    from copy import deepcopy
    source = {"GL":"GL_2022", "JP":"JP_2022", "GLW":"GL_2024", "JPW":"JP_2024", "LIVE":"JP_CLIENT"}.get(region)
    if source is None:
        raise ValueError(f"Unknown FFBE source revision {region}")
    kind = {"skills_ability":"ability", "skills_magic":"magic", "skills_passive":"passive"}[table]
    return {"source":source, "kind":kind, "id":str(sid), "data":deepcopy(row),
            "path":f"studio:{region}/{table}/{sid}"}

CGS_NEW = {"limitatk": "limit_atk", "magicatk": "magic_atk", "winbefore": "win_before"}   # newer archives spell them with an underscore
CGS_OLD = {v: k for k, v in CGS_NEW.items()}
def norm_anim(a): return CGS_OLD.get(a, a)

def cgs_file(d, form, anim):
    """the cgs file of an animation in a sprite folder, whichever spelling the archive used; None when absent"""
    for name in dict.fromkeys([anim, CGS_NEW.get(anim, anim), CGS_OLD.get(anim, anim)]):
        p = os.path.join(d, f"unit_{name}_cgs_{form}.csv")
        if os.path.exists(p): return p
    # Authored units explicitly use idle for omitted optional motions, just as
    # build_sprites does. Keep their editor previews consistent with the build.
    custom_root = os.path.abspath(os.path.join(ROOT, 'units', 'custom')) + os.sep
    if os.path.abspath(d).startswith(custom_root):
        idle = os.path.join(d, f'unit_idle_cgs_{form}.csv')
        if os.path.isfile(idle): return idle
    return None

def sprite_anims(form):
    d = sprite_dir(form)
    if not d: return []
    out = set()
    for f in os.listdir(d):
        m = re.match(r"unit_(\w+?)_cgs_%s\.csv$" % form, f)
        if m: out.add(norm_anim(m.group(1)))
    return sorted(out)

# ---- Brave Shift / Super Limit Break pairs: the index merges the two unit ids; a shifted sheet borrows what it lacks
# (victory, down) from its base form.
_idx_rows = None
def index_rows():
    global _idx_rows
    if _idx_rows is None:
        try: _idx_rows = {e["id"]: e for e in load_index()}
        except Exception: _idx_rows = {}
    return _idx_rows

def shift_info(form):
    """{'kind': 'brave_shift'|'slb', 'base': <base form>} for a shifted sheet, else None"""
    form = str(form)
    for e in index_rows().values():
        sh = (e.get("shift") or {}).get(form)
        if sh: return sh
    return None

def anim_source(form, anim):
    """(sprite dir, form) that provides an animation: the form itself, else its base form for the motions a shifted sheet lacks"""
    d = sprite_dir(form)
    if d and cgs_file(d, form, anim): return d, str(form)
    sh = shift_info(form)
    if sh and norm_anim(anim) in ("win", "winbefore", "dead"):
        b = str(sh["base"]); bd = sprite_dir(b)
        if bd and cgs_file(bd, b, anim): return bd, b
    return None, None

def _detail_forms(region, u, forms, shift):
    import lb_names
    s = sources()[region]
    for fid, ent in (u.get("entries") or {}).items():
        lbid = ent.get("limitburst_id")
        if isinstance(lbid, list): lbid = lbid[0] if lbid else None
        lb = s["limitbursts"].get(str(lbid))
        lb_name = lb and (lb_names.english_name(lbid, lb.get("name")) or translate("lb", lb.get("name")) or lb.get("name"))
        forms[fid] = {"rarity": form_rarity(fid).get("rarity", ent.get("rarity")), "stats": ent.get("stats"),
                      "limitburst": lb and {"name": lb_name, "jpname": lb.get("name") if lb.get("name") != lb_name else None,
                                            "effects": [e if isinstance(e, str) else " / ".join(str(x) for x in e) for e in (lb.get("min_level_effects") or lb.get("effects") or [])],
                                            "attack_count": lb.get("attack_count"), "attack_type": lb.get("attack_type"), "element": lb.get("element_inflict")},
                      "sprites": sorted(set(sprite_anims(fid)) | ({a for a in ("win", "winbefore", "dead") if anim_source(fid, a)[0]} if shift.get(fid) else set())),
                      "spriteSource": sprite_source(fid), "locked": fid in locked_forms() and not sprite_dir(fid),
                      "hasIcon": bool(sprite_dir(fid) and os.path.exists(os.path.join(sprite_dir(fid), f"unit_icon_{fid}.png"))),
                      "shift": shift.get(fid)}

def unit_detail(uid):
    uid = str(uid)
    if uid.isdigit():
        for path in glob.glob(os.path.join(ROOT, 'units', 'custom', '*', 'detail.json')):
            with open(path, encoding='utf-8') as file: custom = json.load(file)
            if custom.get('id') == uid: return custom
    packed = os.path.join(PACK, "unit_records", uid + ".json")
    if os.path.isfile(packed):
        doc = json.load(open(packed, encoding="utf-8"))["detail"]
        for fid, form in doc["forms"].items():
            form["sprites"] = anims_for(fid) if sprite_dir(fid) else []
        return doc
    row = index_rows().get(uid)
    if not row:   # a shifted id asked for directly: answer for its base
        for e in index_rows().values():
            if e.get("pairOf") == uid: uid = e["id"]; row = e; break
    region = region_of(uid)
    if not region: return None
    s = sources()[region]; u = s["units"][uid]
    forms = {}
    shift = (row or {}).get("shift") or {}
    # looks from every region that has entries for the unit, first region wins a form: the Global datamine lists JP-only
    # units without any entry, and a unit's looks must not vanish because that region came first
    def all_regions(some_uid):
        n = 0
        for reg in REGION_ORDER:
            ru = sources().get(reg, {}).get("units", {}).get(some_uid)
            if ru and ru.get("entries"): _detail_forms(reg, ru, forms, shift); n += 1
        return n
    if not all_regions(uid): _detail_forms(region, u, forms, shift)
    pair = (row or {}).get("pairOf")
    if pair: all_regions(pair)                            # the Brave Shift / SLB second id
    for mid in (row or {}).get("mergedIds") or []:      # the same character's other ids (one row per character): their looks too
        if mid != uid: all_regions(mid)
    skills = []
    for sk in u.get("skills") or []:
        skills.append({"rarity": sk.get("rarity"), "level": sk.get("level"), **resolve_skill(region, sk.get("id"))})
    seen = set(); uniq = []
    for sk in skills:
        if sk["id"] in seen: continue
        seen.add(sk["id"]); uniq.append(sk)
    def rank(f):
        r = str(forms[f]["rarity"])   # a shifted sheet (Brave Shift / SLB) ranks below its base: the base form is the default look
        return (not forms[f].get("shift"), r.startswith("NV") or r.startswith("EX"), r.count("+"), int(r) if r.isdigit() else 8, f)
    max_form = max(forms, key=rank) if forms else None
    stats_max = {k: v[1] for k, v in (forms[max_form]["stats"] or {}).items()} if max_form else {}
    name = u.get("name"); en = next((en_name(f) for f in [uid] + list(forms) if en_name(f)), None) or translate("units", name) or ((row or {}).get("name") if not is_jp((row or {}).get("name") or "") else None)
    return {"id": uid, "region": region, "regionLabel": REGION_LABEL.get(region, region), "name": en or name, "jpname": name if is_jp(name or "") else None, "names": u.get("names"),
            "description": en_desc(uid) or next((en_desc(f) for f in forms if en_desc(f)), None) or translate("desc", uid),
            "rarity": [u.get("rarity_min"), u.get("rarity_max")], "roles": u.get("roles"),
            "job": u.get("job"), "sex": u.get("sex"), "forms": forms, "maxForm": max_form, "statsMax": stats_max, "ffrStats": ffr_stats(stats_max),
            "skills": uniq, "abilities": [x for x in uniq if x["kind"] != "PASSIVE"], "passives": [x for x in uniq if x["kind"] == "PASSIVE"]}

def icon_png(form):
    import unit_downloads
    cached = unit_downloads.preview_file(str(form), 'icon')
    if cached: return str(cached)
    d = sprite_dir(form)
    p = d and os.path.join(d, f"unit_icon_{form}.png")
    return p if p and os.path.exists(p) else None

def render_frames(form, anim, scale=2):
    """FFBE animation -> (frames, durations ms); origin kept fixed so the unit does not wobble.
    The cgs file is found under either spelling; a shifted sheet's victory / down come from its base form."""
    from ffbe_frames import read_cgg, read_cgs, compose_frame
    d, src = anim_source(form, anim)
    if not d: raise FileNotFoundError(f"{form}/{anim}")
    atlas = Image.open(os.path.join(d, f"unit_anime_{src}.png")).convert("RGBA")
    cgg = read_cgg(os.path.join(d, f"unit_cgg_{src}.csv"))
    steps = read_cgs(cgs_file(d, src, anim))
    frames = []; boxes = []
    for st in steps:
        img = compose_frame(atlas, cgg[st["frame"]])
        if st["x"] or st["y"]:
            shifted = Image.new("RGBA", img.size, (0, 0, 0, 0)); shifted.alpha_composite(img, (st["x"], st["y"])); img = shifted
        bb = img.getchannel("A").getbbox() or (500, 500, 524, 524)
        frames.append((img, max(1, st["delay"]))); boxes.append(bb)
    x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes); x1 = max(b[2] for b in boxes); y1 = max(b[3] for b in boxes)
    out = []; durs = []
    for img, delay in frames:
        c = img.crop((x0, y0, x1, y1))
        if scale != 1: c = c.resize((c.size[0] * scale, c.size[1] * scale), Image.NEAREST)
        out.append(c); durs.append(int(delay * 1000 / 60))
    return out, durs

def render_apng(form, anim, scale=2):
    """browser preview"""
    out, durs = render_frames(form, anim, scale)
    buf = io.BytesIO()
    out[0].save(buf, format="PNG", save_all=True, append_images=out[1:], duration=durs, loop=0, disposal=1)
    return buf.getvalue()

def render_webp(form, anim, scale=2):
    """the native app's preview: lossless animated WebP, alpha kept, pixels crisp"""
    out, durs = render_frames(form, anim, scale)
    buf = io.BytesIO()
    out[0].save(buf, format="WEBP", save_all=True, append_images=out[1:], duration=durs, loop=0, lossless=True, quality=100, method=4)
    return buf.getvalue()

def motion_seconds(form, anim):
    """length of one Brave Exvius motion in seconds (frame delays are 1/60 s), or None"""
    from ffbe_frames import read_cgs
    d, src = anim_source(form, anim)
    if not d: return None
    total = sum(max(1, s["delay"]) for s in read_cgs(cgs_file(d, src, anim)))
    return total / 60.0 if total else None

def anims_for(form):
    """animation names available for a form, in the order the viewer shows them"""
    order = ["idle", "standby", "move", "jump", "atk", "magicatk", "limitatk", "limitmove", "limit_move", "brave_shift", "magic_standby", "win", "winbefore", "dying", "dead"]
    have = set(sprite_anims(form) or [])
    if shift_info(form): have |= {a for a in ("win", "winbefore", "dead") if anim_source(form, a)[0]}
    return [a for a in order if a in have] + sorted(a for a in have if a not in order)

if __name__ == "__main__":
    if os.path.exists(os.path.join(OUT, "ffbe_en.json")): os.remove(os.path.join(OUT, "ffbe_en.json"))
    english(); build_index()
