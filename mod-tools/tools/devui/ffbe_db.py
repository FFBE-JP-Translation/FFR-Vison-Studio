r"""ffbe_db.py - unified FFBE database (SQLite) reconciling every local source: ffbeEquip GL + JP data, the user's FFBE English
patch tables (English names / descriptions), and every folder holding unit sprite sheets. GL and JP each have exclusive units,
JP ran months ahead of GL, and the JP memorial (offline) edition dropped the collab units, so the DB keeps provenance per row.

python tools/devui/ffbe_db.py            -> build/devui/ffbe.sqlite (+ prints a reconciliation summary)
Tables: units (one row per form id), unit_names, skills, unit_skills, limitbursts, sprites, sources.
Add new sprite/data sources to SPRITE_ROOTS / importers as the inventories in build/inventory/*.md are confirmed.
"""
import json, os, re, sqlite3, sys, zipfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import ffbe_catalog as fc

DB = os.path.join(ROOT, "build", "devui", "ffbe.sqlite")
# every folder that may hold unit_anime_<form>.png (+ cgg/cgs); scanned recursively to a small depth
SPRITE_ROOTS = [
    (r"S:\FFBE JP Data Export\BFFrameAnimator-master\Units", "jp_export", 1),
    (os.path.join(ROOT, "build", "ffbe_cpk", "jp_live_dec"), "jp_live", 0),                                   # JP live client unit*.cpk extracted by tools/devui/cpk.py (3,529 ids through 2025-10)
    (r"S:\FFBE JP Data Export\BFFrameAnimator-master\new units", "jp_export_new", 0),
    (r"S:\FFBE JP Data Export\BFFrameAnimator-master\new ones", "jp_export_new2", 0),
    (r"S:\FFBE JP Data Export\new units", "jp_export_new3", 0),
    (r"T:\ffbe_patch\jp_extracted\on_demand_asset3", "patch_jp_memorial", 2),          # JP memorial edition on-demand packs (813 ids)
    (r"T:\ffbe_patch\gl_extracted\common_lang\sd\unit", "patch_gl_extracted", 1),     # GL client dump, 3,690 ids through 100045137 (most complete)
    (r"T:\Projects\FFBE Patch\gl_extracted\common_lang\sd\unit", "patch2_gl_extracted", 1),
]
SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (name TEXT PRIMARY KEY, kind TEXT, path TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS units (form_id TEXT PRIMARY KEY, base_id TEXT, name_en TEXT, name_jp TEXT, name_ffbeequip TEXT, rarity TEXT, rarity_min TEXT, rarity_max TEXT,
    roles TEXT, job TEXT, in_gl INTEGER, in_jp INTEGER, in_patch INTEGER, description_en TEXT, stats_max TEXT, limitburst_id TEXT, is_brave_shift INTEGER);
CREATE TABLE IF NOT EXISTS skills (skill_id INTEGER PRIMARY KEY, kind TEXT, name_en TEXT, name_jp TEXT, effects_en TEXT, cost_mp INTEGER, icon TEXT, attack_type TEXT, element TEXT,
    move_type INTEGER, motion_type INTEGER, attack_count TEXT, in_gl INTEGER, in_jp INTEGER);
CREATE TABLE IF NOT EXISTS unit_skills (base_id TEXT, skill_id INTEGER, rarity TEXT, level INTEGER, region TEXT, PRIMARY KEY (base_id, skill_id, region));
CREATE TABLE IF NOT EXISTS limitbursts (form_id TEXT PRIMARY KEY, lb_id TEXT, name_en TEXT, name_jp TEXT, effects_en TEXT, attack_count TEXT, attack_type TEXT, element TEXT);
CREATE TABLE IF NOT EXISTS sprites (form_id TEXT, source TEXT, folder TEXT, has_cgg INTEGER, anims TEXT, has_icon INTEGER, has_illustration INTEGER, PRIMARY KEY (form_id, source));
"""

def is_png(path):
    try:
        with open(path, 'rb') as fh: return fh.read(8) == b'\x89PNG\r\n\x1a\n'
    except OSError: return False

def scan_sprites(root, source, depth):
    out = {}
    if not os.path.isdir(root): return out
    base_depth = root.rstrip("\\/").count(os.sep)
    for dp, dirs, fs in os.walk(root):
        if dp.count(os.sep) - base_depth > depth: dirs[:] = []; continue
        forms = {}
        for f in fs:
            m = re.match(r"unit_anime_(\d+)\.png$", f)
            if m: forms.setdefault(m.group(1), {})["png"] = True
            m = re.match(r"unit_cgg_(\d+)\.csv$", f)
            if m: forms.setdefault(m.group(1), {})["cgg"] = True
            m = re.match(r"unit_(\w+?)_cgs_(\d+)\.csv$", f)
            if m: forms.setdefault(m.group(2), {}).setdefault("anims", []).append(m.group(1))
            m = re.match(r"unit_icon_(\d+)\.png$", f)
            if m: forms.setdefault(m.group(1), {})["icon"] = True
            m = re.match(r"unit_ills_(\d+)\.png$", f)
            if m: forms.setdefault(m.group(1), {})["ills"] = True
        for fid, info in forms.items():
            if info.get("png"): out[fid] = (dp, info)
    return out

def build():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    if os.path.exists(DB): os.remove(DB)
    con = sqlite3.connect(DB); con.executescript(SCHEMA)
    src = fc.sources(); en = fc.english()
    con.execute("INSERT INTO sources VALUES (?,?,?,?)", ("ffbeequip_gl", "data", fc.ZIP, "tools/GL/sources/*.json"))
    con.execute("INSERT INTO sources VALUES (?,?,?,?)", ("ffbeequip_jp", "data", fc.ZIP, "tools/JP/sources/*.json"))
    con.execute("INSERT INTO sources VALUES (?,?,?,?)", ("datamine_gl", "data", os.path.join(fc.DATAMINE, "gl"), "aEnigmatic wiki datamine 2024-10 (units/skills/limitbursts.json)"))
    con.execute("INSERT INTO sources VALUES (?,?,?,?)", ("datamine_jp", "data", os.path.join(fc.DATAMINE, "jp"), "aEnigmatic wiki datamine 2024-10, newest JP units (Raegen -Ultimate Summon-)"))
    con.execute("INSERT INTO sources VALUES (?,?,?,?)", ("english_patch", "names", fc.PATCH, "unit / ability / magic / limit burst names + unit descriptions (column G4L0YIB2)"))
    # units: every form of every unit in either region
    forms = {}
    for region in ("JPW", "JP", "GLW", "GL"):
        for uid, u in src[region]["units"].items():
            for fid, ent in (u.get("entries") or {}).items():
                row = forms.setdefault(fid, {"form_id": fid, "base_id": uid, "in_gl": 0, "in_jp": 0, "in_patch": 0})
                row["in_" + region.lower()[:2]] = 1
                row["name_ffbeequip"] = u.get("name"); row["rarity"] = str(ent.get("rarity")); row["rarity_min"] = str(u.get("rarity_min")); row["rarity_max"] = str(u.get("rarity_max"))
                row["roles"] = json.dumps(u.get("roles") or []); row["job"] = u.get("job")
                row["stats_max"] = json.dumps({k: v[1] for k, v in (ent.get("stats") or {}).items()}); row["limitburst_id"] = str(ent.get("limitburst_id"))
                if region.startswith("JP"): row["name_jp"] = u.get("name")
            if not (u.get("entries") or {}):
                row = forms.setdefault(uid, {"form_id": uid, "base_id": uid, "in_gl": 0, "in_jp": 0, "in_patch": 0}); row["in_" + region.lower()[:2]] = 1; row["name_ffbeequip"] = u.get("name")
    for fid, name in en["units"].items():
        row = forms.setdefault(fid, {"form_id": fid, "base_id": fid[:7] + "05" if len(fid) == 9 else fid, "in_gl": 0, "in_jp": 0, "in_patch": 0})
        row["in_patch"] = 1; row["name_en"] = name
    for fid, row in forms.items():
        row.setdefault("name_en", None)
        if not row["name_en"] and row.get("name_ffbeequip") and not fc.is_jp(row["name_ffbeequip"]): row["name_en"] = row["name_ffbeequip"]
        if not row.get("name_jp") and row.get("name_ffbeequip") and fc.is_jp(row["name_ffbeequip"]): row["name_jp"] = row["name_ffbeequip"]
        row["description_en"] = en["unit_desc"].get(fid)
        row["is_brave_shift"] = 1 if fid.endswith(("17", "27", "37")) and len(fid) == 9 else 0
        con.execute("INSERT INTO units (form_id, base_id, name_en, name_jp, name_ffbeequip, rarity, rarity_min, rarity_max, roles, job, in_gl, in_jp, in_patch, description_en, stats_max, limitburst_id, is_brave_shift) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    tuple(row.get(k) for k in ("form_id", "base_id", "name_en", "name_jp", "name_ffbeequip", "rarity", "rarity_min", "rarity_max", "roles", "job", "in_gl", "in_jp", "in_patch", "description_en", "stats_max", "limitburst_id", "is_brave_shift")))
    # skills
    skills = {}
    for region in ("JPW", "JP", "GLW", "GL"):
        s = src[region]
        for tbl, kind in (("skills_ability", "ABILITY"), ("skills_magic", "MAGIC"), ("skills_passive", "PASSIVE")):
            for sid, r in s[tbl].items():
                row = skills.setdefault(int(sid), {"skill_id": int(sid), "kind": kind, "in_gl": 0, "in_jp": 0})
                row["in_" + region.lower()[:2]] = 1
                nm = r.get("name")
                if region.startswith("GL") or "name_src" not in row: row["name_src"] = nm
                if fc.is_jp(nm or ""): row["name_jp"] = nm
                row["effects_en"] = json.dumps([e if isinstance(e, str) else " / ".join(str(x) for x in e) for e in (r.get("effects") or [])], ensure_ascii=False)
                row["cost_mp"] = (r.get("cost") or {}).get("MP"); row["icon"] = r.get("icon"); row["attack_type"] = r.get("attack_type")
                el = r.get("element_inflict"); row["element"] = json.dumps(el) if el else None
                row["move_type"] = r.get("move_type"); row["motion_type"] = r.get("motion_type"); row["attack_count"] = json.dumps(r.get("attack_count"))
        for uid, u in s["units"].items():
            for sk in u.get("skills") or []:
                con.execute("INSERT OR IGNORE INTO unit_skills VALUES (?,?,?,?,?)", (uid, int(sk.get("id")), str(sk.get("rarity")), int(sk.get("level") or 0), region))
    for sid, row in skills.items():
        row["name_en"] = fc.en_skill(sid) or (row.get("name_src") if not fc.is_jp(row.get("name_src") or "") else None) or fc.translate("skills", row.get("name_jp"))
        con.execute("INSERT INTO skills (skill_id, kind, name_en, name_jp, effects_en, cost_mp, icon, attack_type, element, move_type, motion_type, attack_count, in_gl, in_jp) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    tuple(row.get(k) for k in ("skill_id", "kind", "name_en", "name_jp", "effects_en", "cost_mp", "icon", "attack_type", "element", "move_type", "motion_type", "attack_count", "in_gl", "in_jp")))
    # limit bursts per form
    for region in ("JPW", "JP", "GLW", "GL"):
        s = src[region]
        for uid, u in s["units"].items():
            for fid, ent in (u.get("entries") or {}).items():
                lb = s["limitbursts"].get(str(ent.get("limitburst_id")))
                if not lb: continue
                name = lb.get("name"); fx = [e if isinstance(e, str) else " / ".join(str(x) for x in e) for e in (lb.get("min_level_effects") or lb.get("effects") or [])]
                con.execute("INSERT OR REPLACE INTO limitbursts VALUES (?,?,?,?,?,?,?,?)", (fid, str(ent.get("limitburst_id")), fc.en_lb(fid) or (name if not fc.is_jp(name or "") else None), name if fc.is_jp(name or "") else None,
                                                                                  json.dumps(fx, ensure_ascii=False), json.dumps(lb.get("attack_count")), lb.get("attack_type"), json.dumps(lb.get("element_inflict")) if lb.get("element_inflict") else None))
    # sprites from every root
    for root, source, depth in SPRITE_ROOTS:
        found = scan_sprites(root, source, depth)
        con.execute("INSERT OR REPLACE INTO sources VALUES (?,?,?,?)", (source, "sprites", root, f"{len(found)} unit forms"))
        for fid, (folder, info) in found.items():
            con.execute("INSERT OR REPLACE INTO sprites VALUES (?,?,?,?,?,?,?)", (fid, source, folder, 1 if info.get("cgg") else 0, json.dumps(sorted(info.get("anims", []))), 1 if info.get("icon") else 0, 1 if info.get("ills") else 0))
            if fid not in forms:   # a sprite for a form no data source knows: keep it visible
                con.execute("INSERT OR IGNORE INTO units (form_id, base_id, name_en, in_gl, in_jp, in_patch) VALUES (?,?,?,?,?,?)", (fid, fid[:7] + "05" if len(fid) == 9 else fid, en["units"].get(fid), 0, 0, 1 if fid in en["units"] else 0))
    con.commit()
    # summary
    q = lambda sql: con.execute(sql).fetchone()[0]
    print(f"units (forms): {q('select count(*) from units')} | GL {q('select count(*) from units where in_gl=1')} | JP {q('select count(*) from units where in_jp=1')} | patch names {q('select count(*) from units where in_patch=1')}")
    print(f"  GL-only {q('select count(*) from units where in_gl=1 and in_jp=0')} | JP-only {q('select count(*) from units where in_jp=1 and in_gl=0')} | English name {q('select count(*) from units where name_en is not null')} | no English name {q('select count(*) from units where name_en is null')}")
    print(f"skills: {q('select count(*) from skills')} (English name {q('select count(*) from skills where name_en is not null')}) | unit_skills {q('select count(*) from unit_skills')} | limit bursts {q('select count(*) from limitbursts')}")
    for name, note in con.execute("select name, note from sources where kind='sprites'"): print(f"  sprites {name}: {note}")
    print(f"forms with sprites in any source: {q('select count(distinct form_id) from sprites')} | with cgg: {q('select count(distinct form_id) from sprites where has_cgg=1')} | forms without any sprite: {q('select count(*) from units u where not exists (select 1 from sprites s where s.form_id=u.form_id)')}")
    for fid, in con.execute("select form_id from units where name_en like 'Raegen -Ultimate%'"):
        print("  Raegen -Ultimate Summon- form", fid, "sprites:", con.execute("select source, folder from sprites where form_id=?", (fid,)).fetchall())
    con.close()

if __name__ == "__main__":
    build()
