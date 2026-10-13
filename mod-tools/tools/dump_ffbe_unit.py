#!/usr/bin/env python
r"""dump_ffbe_unit.py - collect one FFBE unit (data + sprite sheets) into units/ffbe/<name>/

usage: python tools/dump_ffbe_unit.py <base-unit-id> <folder-name> [extra-form-id ...] [--source GL|JP|GLW|JPW]
   e.g. python tools/dump_ffbe_unit.py 401006805 esther 401012807 401012817

Data comes from the same sources the studio uses (tools/devui/ffbe_catalog.py: ffbeEquip GL/JP, the wiki datamine GL/JP 2024),
sprites from whichever root holds the form (BFFrameAnimator Units, the extracted JP live archives, the GL client dump).
Output:
  units/ffbe/<name>/unit.json      merged document: identity, per-rarity entries, skills by rarity/level (resolved), limit bursts
  units/ffbe/<name>/raw/*.json     raw source rows (unit, skills, limitbursts)
  units/ffbe/<name>/sprites/<id>/  copied sprite files (sheet + cgg + cgs + icon + illustration)
  units/ffbe/<name>/README.md
"""
import json, os, shutil, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "devui"))
import ffbe_catalog as fc

def dump(base, name, extra=(), source=None, forms=()):
    out = os.path.join(ROOT, "units", "ffbe", name)
    os.makedirs(os.path.join(out, "raw"), exist_ok=True)
    source = source or fc.region_of(base)
    if not source: raise KeyError(f"unit {base} is not in any FFBE data source")
    s = fc.sources()[source]
    units = s["units"]; ability = s["skills_ability"]; magic = s["skills_magic"]; passive = s["skills_passive"]; lbs = s["limitbursts"]
    ids = [base] + list(extra)
    doc = {"baseId": base, "source": source, "forms": {}}
    raw = {"units": {}, "skills_ability": {}, "skills_magic": {}, "skills_passive": {}, "limitbursts": {}}
    def resolve(t, i):
        i = str(i)
        for tbl, name_ in ((ability, "skills_ability"), (magic, "skills_magic"), (passive, "skills_passive")):
            if i in tbl:
                raw[name_][i] = tbl[i]
                r = tbl[i]
                return {"id": int(i), "table": name_, "name": fc.en_skill(i) or r.get("name"), "type": t, "cost": r.get("cost"), "attack_type": r.get("attack_type"),
                        "element": r.get("element_inflict"), "effects": r.get("effects"), "effects_raw": r.get("effects_raw"),
                        "attack_count": r.get("attack_count"), "attack_damage": r.get("attack_damage"), "attack_frames": r.get("attack_frames"),
                        "unique": r.get("unique"), "magic_type": r.get("magic_type"), "icon": r.get("icon")}
        return {"id": int(i), "type": t, "name": None, "missing": True}
    for uid in ids:
        u = units.get(uid)
        if not u:
            print("unit not found in ffbe data:", uid); continue
        raw["units"][uid] = u
        form = {"id": uid, "name": fc.en_name(uid) or u.get("name"), "jpname": u.get("name"), "rarity": [u.get("rarity_min"), u.get("rarity_max")], "roles": u.get("roles"),
                "job": u.get("job"), "sex": u.get("sex"), "tribe_id": u.get("tribe_id"), "equip": u.get("equip"), "entries": {}, "skills": [], "limitbursts": {}}
        for rid, ent in (u.get("entries") or {}).items():
            form["entries"][rid] = ent
            lbid = ent.get("limitburst_id")
            if isinstance(lbid, list): lbid = lbid[0] if lbid else None
            if str(lbid) in lbs:
                raw["limitbursts"][str(lbid)] = lbs[str(lbid)]; form["limitbursts"][rid] = lbs[str(lbid)]
        for sk in u.get("skills") or []:
            form["skills"].append({"rarity": sk.get("rarity"), "level": sk.get("level"), **resolve(sk.get("type"), sk.get("id"))})
        doc["forms"][uid] = form
    json.dump(doc, open(os.path.join(out, "unit.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for k, v in raw.items():
        if v: json.dump(v, open(os.path.join(out, "raw", k + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    sprite_ids = []
    for uid, form in doc["forms"].items():
        for rid in list(form["entries"].keys()) or [uid]:
            if rid not in sprite_ids: sprite_ids.append(rid)
    for rid in forms:                    # the looks the studio asked for: a region that lists the unit without entries
        rid = str(rid)                   # must not cost the unit its sprites (the chosen look would have none)
        if rid not in sprite_ids: sprite_ids.append(rid)
    copied = []
    for rid in sprite_ids:
        files = fc.sprite_files(rid)
        if files:
            dst = os.path.join(out, "sprites", rid); os.makedirs(dst, exist_ok=True)
            for f in files: shutil.copy(f, dst)
            copied.append((rid, len(files), fc.sprite_source(rid)))
        else:
            copied.append((rid, 0, None))
    lines = [f"# {doc['forms'].get(base, {}).get('name', name)} — FFBE unit {base} ({source} data)", ""]
    for uid, form in doc["forms"].items():
        top = form["entries"].get(max(form["entries"].keys(), default=""), {}) if form["entries"] else {}
        st = top.get("stats", {})
        lines.append(f"* form {uid} {form['name']}: rarity {form['rarity']}, roles {form['roles']}, "
                     f"max stats HP {st.get('HP',[None,None])[1]} MP {st.get('MP',[None,None])[1]} ATK {st.get('ATK',[None,None])[1]} DEF {st.get('DEF',[None,None])[1]} MAG {st.get('MAG',[None,None])[1]} SPR {st.get('SPR',[None,None])[1]}; "
                     f"{len(form['skills'])} skills, LBs: {[v.get('name') for v in form['limitbursts'].values()]}")
    lines.append("* sprites: " + ", ".join(f"{rid} ({n} files, {src})" if n else f"{rid} (missing)" for rid, n, src in copied))
    open(os.path.join(out, "README.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return doc, copied

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    source = None
    if "--source" in sys.argv: source = sys.argv[sys.argv.index("--source") + 1]; args = [a for a in args if a != source]
    dump(args[0], args[1], args[2:], source)

if __name__ == "__main__":
    main()
