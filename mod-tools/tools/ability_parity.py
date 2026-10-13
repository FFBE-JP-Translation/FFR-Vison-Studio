r"""ability_parity.py - put one Brave Exvius ability and one RESONANCE ability side by side, in the same shape, so a port can
be written against the differences instead of guessed at.

    python tools/ability_parity.py sample                 12 moves both games have, into docs/abilities/
    python tools/ability_parity.py sample --n 20 --seed 7
    python tools/ability_parity.py show Firaga            one move, to the console
    python tools/ability_parity.py power                  the damage-number relation across every shared move
    python tools/ability_parity.py ladder                 each game's own power distribution, by damage type
    python tools/ability_parity.py import                 12 Brave Exvius moves RESONANCE lacks, with a draft row for each

Sources
    RESONANCE  extracted/rows/Skill/DT_SkillData.json      every field the game reads
               build/devui/ffr_catalog.json                 English name / description (already through the string tables)
    BRAVE EXVIUS
               the 2024 datamine (GL then JP): name, English effect text, the damage multiplier, hit count, hit frames
               the live JP client tables: the effect groups a skill spawns and when, MP, targeting, the hit table
"""
import json, os, random, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "devui"))
sys.path.insert(0, os.path.join(ROOT, "tools", "ffbe_effects"))
OUT = os.path.join(ROOT, "docs", "abilities")

# ---------------------------------------------------------------- RESONANCE

def ffr_rows():
    d = json.load(open(os.path.join(ROOT, "extracted", "rows", "Skill", "DT_SkillData.json"), encoding="utf-8"))
    rows = d.get("rows", d) if isinstance(d, dict) else d
    rows = list(rows.values()) if isinstance(rows, dict) else rows
    cat = json.load(open(os.path.join(ROOT, "build", "devui", "ffr_catalog.json"), encoding="utf-8"))
    names = {s["id"]: s for s in cat["skills"]}
    seqs = {s["skillId"]: s for s in cat["sequences"]}
    effects = {e["id"]: e for e in cat["effects"]}
    out = {}
    for r in rows:
        i = r.get("ID")
        if i is None or i < 0: continue
        c = names.get(i, {})
        out[i] = {"raw": r, "name": c.get("name"), "desc": c.get("desc"), "row": c.get("row"),
                  "seq": seqs.get(i), "effects": [effects[e["effectId"]] for e in (r.get("effectBundleList") or [])
                                                  if e.get("effectId", -1) >= 0 and e["effectId"] in effects]}
    return out


def ffr_view(e):
    """One RESONANCE ability in the shared shape."""
    r = e["raw"]
    ratios = [x for x in (r.get("hitDamageRatioList") or []) if x]
    return {
        "game": "RESONANCE", "id": r["ID"], "name": e["name"], "jp": e["row"], "description": e["desc"],
        "kind": r.get("skillAttrType"),                       # Magic / Ability / MagicSword / ...
        "purpose": r.get("skillEffectType"),                  # DamageAndRecovery / None / ...
        "damageType": r.get("DamageType"), "calc": r.get("damageCalcType"),
        "parameter": r.get("parameterType"), "direction": r.get("parameterVariationType"),
        "element": r.get("element"),
        "target": {"shape": r.get("TargetType"), "side": r.get("defaultTargetRelation"), "state": r.get("defaultTargetState"),
                   "range": r.get("targetRage"), "ignoreSelf": r.get("isTargetIgnoreSelf")},
        "cost": {"MP": r.get("Cost"), "equip": r.get("equipCost")},
        "power": r.get("magnification"),                      # the whole ability's power; hits only split it
        "hits": r.get("hitCount"), "hitSplit": [round(x, 4) for x in ratios],
        "breakDamage": r.get("breakDamageValue"), "accuracy": r.get("accuracy"), "critRate": r.get("criticalHitRate"),
        "status": r.get("statusCondition"),
        "statusEffects": [{"id": x["id"], "type": x["type"], "status": x.get("status"), "chance": x.get("prob")} for x in e["effects"]],
        "animation": {"sequence": (e["seq"] or {}).get("path"), "sound": (e["seq"] or {}).get("sound"),
                      "icon": (r.get("SkillIcon") or {}).get("TagName"), "aura": r.get("auraSize"), "voice": r.get("voiceLabel")},
        "frames": None,   # RESONANCE keeps hit timing in the sequencer asset, not in the table (docs/09)
        "flags": {k: v for k, v in r.items() if k.startswith("is") and v},
        "groupVersion": r.get("skillIdAfterModeChange"),      # the "hits everything" twin, when there is one
    }

# ---------------------------------------------------------------- BRAVE EXVIUS

def ffbe_rows():
    import ffbe_catalog as fc
    src = fc.sources()
    out = {}
    for reg in ("GLW", "JPW", "GL", "JP"):                    # newest first; later regions only fill gaps
        for tab, kind in (("skills_magic", "magic"), ("skills_ability", "ability")):
            for sid, v in src[reg][tab].items():
                if sid not in out:
                    out[sid] = {"id": sid, "kind": kind, "region": reg, "data": dict(v)}
                else:
                    # the 2024 datamine has no attack_damage / effect_frames; the 2022 one does
                    for k, val in v.items():
                        if out[sid]["data"].get(k) in (None, [], {}) and val not in (None, [], {}):
                            out[sid]["data"][k] = val
    # the live client's own tables carry the effect groups and the hit table
    for tab, kind in (("F_MAGIC_MST", "magic"), ("F_ABILITY_MST", "ability")):
        try:
            import ffbe_live
            rows = ffbe_live.load_table(tab)["rows"]
        except Exception:
            continue
        key = "magic_id" if kind == "magic" else "ability_id"
        for r in rows:
            i = str(r.get(key))
            if i in out: out[i]["live"] = r
            else: out[i] = {"id": i, "kind": kind, "region": "LIVE", "data": {}, "live": r}
    return out


ELEMENTS = ["Fire", "Ice", "Thunder", "Water", "Wind", "Earth", "Light", "Dark"]
FFBE_TARGET = {"1": "Single", "2": "Group", "3": "All", "0": "Self"}


def ffbe_view(e):
    """One Brave Exvius ability in the shared shape."""
    d, live = e["data"], e.get("live", {})
    raw = (d.get("effects_raw") or [None])[0] or []
    params = raw[3] if len(raw) > 3 and isinstance(raw[3], list) else []
    mult = damage_multiple(d, params)
    frames = (d.get("attack_frames") or [[]])[0]
    split = (d.get("attack_damage") or [[]])[0]
    groups = []
    if live.get("effect_frames"):
        try:
            import catalog as effcat   # tools/ffbe_effects/catalog.py: which effect files a skill spawns
            for parts in effcat.parse_frames(live["effect_frames"]):
                g = effcat.group_detail(parts[1]) if len(parts) > 1 else None
                if g: groups.append({"atFrame": int(parts[0]) if parts[0].lstrip("-").isdigit() else 0,
                                     "groupId": g["groupId"], "name": g["name"],
                                     "files": [x["file"] for x in g["effects"]], "sounds": [s["seId"] for s in g["sounds"]]})
        except Exception: pass
    hit_table = []
    for item in (live.get("attack_frames") or "").split("-"):
        p = item.split(":")
        if len(p) >= 2 and p[0].lstrip("-").isdigit():
            hit_table.append({"frame": int(p[0]), "percent": int(p[1]) if p[1].isdigit() else None})
    return {
        "game": "BRAVE EXVIUS", "id": e["id"], "name": d.get("name") or live.get("name"), "jp": live.get("name"),
        "description": "; ".join(x if isinstance(x, str) else " ".join(map(str, x)) for x in (d.get("effects") or [])),
        "kind": d.get("magic_type") or e["kind"],             # Black / White / Green magic, or an ability
        "purpose": d.get("effect_type"),
        "damageType": d.get("attack_type"),                   # Magic / Physical / Hybrid / None
        "calc": None, "parameter": None, "direction": None,
        "element": (d.get("element_inflict") or [None])[0] or elements_from_live(live),
        "target": {"shape": FFBE_TARGET.get(first_token(live.get("target_range")), first_token(live.get("target_range"))),
                   "side": None, "state": None, "range": first_token(live.get("target")), "ignoreSelf": None},
        "cost": {"MP": (d.get("cost") or {}).get("MP") or (int(live["mp_cost"]) if live.get("mp_cost", "").isdigit() else None), "equip": None},
        "power": mult,                                        # a multiple of the caster's stat, per hit set
        "hits": (d.get("attack_count") or [None])[0], "hitSplit": [round(x / 100.0, 4) for x in split] if split else None,
        "breakDamage": None, "accuracy": None, "critRate": None,
        "status": None, "statusEffects": [],
        "animation": {"icon": d.get("icon"), "effectGroups": groups, "motionType": d.get("motion_type"), "moveType": d.get("move_type"),
                      "wait": live.get("wait")},
        "frames": {"hits": frames, "hitTable": hit_table, "effectStart": [g["atFrame"] for g in groups]},
        "flags": {"effectRaw": raw[:3], "params": params, "flags": live.get("flags")},
        "chainProxy": [g["groupId"] for g in groups] or None,  # what a port can key "these two chain" on (see the README)
    }


DAMAGE_WORDS = ("damage", "drain")


def damage_multiple(d, params):
    """How many times the caster's stat one use deals. The English effect text spells it out ("Fire magic damage (20x) to all
    enemies"), which beats guessing a parameter slot: which slot holds the multiplier depends on the effect id, and several
    effects put a duration or a chance in the same place."""
    for text in (d.get("effects") or []):
        t = text if isinstance(text, str) else " ".join(map(str, text))
        if not any(w in t.lower() for w in DAMAGE_WORDS): continue
        m = re.search(r"\((\d+(?:\.\d+)?)x\)", t)
        if m: return float(m.group(1))
    # a damage effect with no text: the multiplier is the parameter around 100..30000 that is a whole percentage
    cands = [p / 100.0 for p in params if isinstance(p, (int, float)) and 100 <= p <= 30000 and p % 10 == 0]
    return cands[0] if len(cands) == 1 else None


def first_token(v):
    """Level-indexed table values look like "1@1@1" or "2@2"; a port only cares about the value itself."""
    return str(v).split("@")[0] if v is not None else None


def elements_from_live(live):
    bits = (live.get("element_inflict") or "").split(",")
    named = [ELEMENTS[i] for i, b in enumerate(bits[:8]) if b.strip() not in ("", "0")]
    return named[0] if named else None

# ---------------------------------------------------------------- pairing

def norm(n): return re.sub(r"[^a-z0-9]", "", (n or "").lower())


def build():
    ffr = ffr_rows()
    ffbe = ffbe_rows()
    by_name_ffr, by_name_ffbe = {}, {}
    for i, e in ffr.items():
        if e.get("name"): by_name_ffr.setdefault(norm(e["name"]), []).append(i)
    for i, e in ffbe.items():
        n = norm((e["data"].get("name") or e.get("live", {}).get("name")))
        if n: by_name_ffbe.setdefault(n, []).append(i)
    return ffr, ffbe, by_name_ffr, by_name_ffbe


def damaging(v):
    return bool(v.get("power")) and (v.get("hits") or 0) >= 1


def sample(n=12, seed=3):
    ffr, ffbe, nffr, nffbe = build()
    shared = sorted(set(nffr) & set(nffbe))
    pairs = []
    for key in shared:
        a = ffr_view(ffr[nffr[key][0]])
        # prefer the Brave Exvius entry that has both a datamine row and live data, and that deals damage
        best = None
        for i in nffbe[key]:
            v = ffbe_view(ffbe[i])
            score = (damaging(v), bool(v["frames"]["hits"]), bool(v["animation"]["effectGroups"]))
            if best is None or score > best[0]: best = (score, v)
        b = best[1]
        if damaging(a) and damaging(b): pairs.append((a, b))
    rng = random.Random(seed)
    rng.shuffle(pairs)
    # the three the effect work already covered come first when both games have them, so the sheets line up with docs/06
    wanted = [norm(x) for x in ("Firaga", "Curaga", "Meteor", "Thundaga", "Blizzaga")]
    pairs.sort(key=lambda ab: wanted.index(norm(ab[0]["name"])) if norm(ab[0]["name"]) in wanted else len(wanted))
    chosen, seen = [], set()
    for a, b in pairs:
        if norm(a["name"]) in seen: continue
        seen.add(norm(a["name"])); chosen.append((a, b))
        if len(chosen) >= n: break
    os.makedirs(OUT, exist_ok=True)
    for a, b in chosen:
        slug = re.sub(r"[^a-z0-9]+", "-", a["name"].lower()).strip("-")
        json.dump({"move": a["name"], "resonance": a, "braveExvius": b}, open(os.path.join(OUT, slug + ".json"), "w", encoding="utf-8"),
                  indent=1, ensure_ascii=False)
    return chosen


def power_relation():
    """Every move both games have, with the two damage numbers, so the conversion can be fitted rather than guessed."""
    ffr, ffbe, nffr, nffbe = build()
    out = []
    for key in sorted(set(nffr) & set(nffbe)):
        a = ffr_view(ffr[nffr[key][0]])
        cands = [ffbe_view(ffbe[i]) for i in nffbe[key]]
        cands = [c for c in cands if damaging(c)]
        if not (damaging(a) and cands): continue
        b = min(cands, key=lambda c: abs((c.get("power") or 0) - a["power"] / 3.0))
        out.append({"move": a["name"], "ffrPower": a["power"], "ffrHits": a["hits"], "ffrType": a["damageType"], "ffrElement": a["element"],
                    "ffbePower": b["power"], "ffbeHits": b["hits"], "ffbeType": b["damageType"], "ffbeId": b["id"],
                    "ratio": round((b["power"] or 0) / a["power"], 3) if a["power"] else None})
    return out


# ---------------------------------------------------------------- turning one into the other

FFBE_TO_FFR_DAMAGE = {"Physical": "Physic", "Magic": "Magic", "Hybrid": "Physic", "None": "None", None: "None"}
FFBE_TO_FFR_TARGET = {"Single": "Single", "Group": "Group", "All": "Group", "Self": "Self"}
# the eight elements are the same eight, under one different name
FFBE_TO_FFR_ELEMENT = {"Lightning": "Thunder"}


def power_ladders():
    """Both games' damage numbers, sorted, per damage type. The two scales have nothing to do with each other -- one is a
    multiple of a stat, the other an integer the game's own formula reads -- so an ability is placed by where it sits among
    its own game's abilities, not by its number."""
    ffr, ffbe, _, _ = build()
    lad = {"RESONANCE": {}, "BRAVE EXVIUS": {}}
    for e in ffr.values():
        v = ffr_view(e)
        if v["power"] and v["damageType"] in ("Physic", "Magic") and v["calc"] == v["damageType"]:
            lad["RESONANCE"].setdefault(v["damageType"], []).append(v["power"])
    for e in ffbe.values():
        v = ffbe_view(e)
        t = FFBE_TO_FFR_DAMAGE.get(v["damageType"])
        if v["power"] and t in ("Physic", "Magic"):
            lad["BRAVE EXVIUS"].setdefault(t, []).append(v["power"])
    for game in lad:
        for k in lad[game]: lad[game][k].sort()
    lad["anchors"] = anchor_curve()      # the moves both games have decide the middle of the range
    return lad


def anchor_curve():
    """The moves both games already carry, as a lookup from a Brave Exvius multiple to the RESONANCE number the designers
    actually gave it. Sorted by multiple, binned, each bin taking its median, then forced upward-only so a stronger source
    move can never convert to a weaker RESONANCE one. Outside the anchored range the ladder takes over."""
    pairs = {}
    for r in power_relation():
        if r["ffrType"] not in ("Physic", "Magic") or not r["ffbePower"] or not r["ffrPower"]: continue
        if r["ffrPower"] > 300: continue                     # fixed-damage oddities (Needles, potions) are not on the ladder
        pairs.setdefault(r["ffrType"], []).append((r["ffbePower"], r["ffrPower"]))
    curves = {}
    for t, pts in pairs.items():
        pts.sort()
        bins, size = [], max(4, len(pts) // 8)
        for i in range(0, len(pts), size):
            chunk = pts[i:i + size]
            if not chunk: continue
            xs = sorted(x for x, _ in chunk); ys = sorted(y for _, y in chunk)
            bins.append((xs[len(xs) // 2], ys[len(ys) // 2]))
        run = []
        for x, y in bins: run.append((x, max(y, run[-1][1] if run else 0)))
        curves[t] = run
    return curves


def from_anchors(mult, dmg_type, curves):
    """Read the anchored curve at `mult` (linear between the two nearest anchors)."""
    c = curves.get(dmg_type) or []
    if not c or mult is None: return None
    if mult <= c[0][0]: return c[0][1]
    if mult >= c[-1][0]: return c[-1][1]
    for (x0, y0), (x1, y1) in zip(c, c[1:]):
        if x0 <= mult <= x1:
            f = 0.0 if x1 == x0 else (mult - x0) / (x1 - x0)
            return int(round(y0 + (y1 - y0) * f))
    return c[-1][1]


def convert_power(mult, dmg_type, lad):
    """Where this multiple sits among Brave Exvius abilities of the same type, read off the RESONANCE ladder at the same
    place. Returns (power, percentile)."""
    src = lad["BRAVE EXVIUS"].get(dmg_type) or []
    dst = lad["RESONANCE"].get(dmg_type) or []
    if not src or not dst or mult is None: return None, None
    lo = sum(1 for x in src if x < mult)
    pct = lo / len(src)
    anchored = from_anchors(mult, dmg_type, lad.get("anchors") or {})
    if anchored: return anchored, round(pct, 3)
    return int(round(dst[min(int(pct * len(dst)), len(dst) - 1)])), round(pct, 3)


def propose(v, lad=None):
    """A draft RESONANCE skill row for a Brave Exvius ability: the fields the game reads, filled from the source where the
    two agree and from the RESONANCE ladder where they do not. Frame timing is left out on purpose -- it lives in a
    sequencer asset, not in this table (docs/09)."""
    lad = lad or power_ladders()
    dmg = FFBE_TO_FFR_DAMAGE.get(v["damageType"], "None")
    power, pct = convert_power(v["power"], dmg, lad)
    hits = v["hits"] or 1
    split = v["hitSplit"] or [round(1.0 / hits, 4)] * hits
    if len(split) != hits: split = [round(1.0 / hits, 4)] * hits
    return {
        "ID": None,                                   # the studio assigns this out of the unit's own range
        "Name": v["name"], "Description": v["description"],
        "skillAttrType": {"Black": "Magic", "White": "Magic", "Green": "Magic"}.get(v["kind"], "Ability"),
        "skillEffectType": "DamageAndRecovery" if power else "None",
        "DamageType": dmg, "damageCalcType": dmg, "parameterType": "HitPoint",
        "parameterVariationType": "Decrease" if dmg != "None" else "None",
        "element": FFBE_TO_FFR_ELEMENT.get(v["element"], v["element"]) or "None",
        "TargetType": FFBE_TO_FFR_TARGET.get(v["target"]["shape"], "Single"),
        "defaultTargetRelation": "Enemies" if power else "Friendlies",
        "Cost": v["cost"]["MP"], "magnification": power, "hitCount": hits,
        "hitDamageRatioList": split,
        "accuracy": 100, "criticalHitRate": 2, "breakDamageValue": None,   # no source: pick from the RESONANCE ladder
        "_from": {"game": "BRAVE EXVIUS", "id": v["id"], "multiple": v["power"], "percentile": pct,
                  "hitFrames": (v["frames"] or {}).get("hits"), "effectGroups": [g["groupId"] for g in v["animation"].get("effectGroups", [])]},
        "_todo": ["breakDamageValue: no equivalent in the source",
                  "hit timing: author the sequencer, the source's hit frames are in _from.hitFrames",
                  "status effects: the source's effect ids need a table of their own"],
    }


def unmatched(n=12, seed=3):
    """Brave Exvius abilities RESONANCE has no version of - the case the aggregator actually has to handle."""
    ffr, ffbe, nffr, nffbe = build()
    lad = power_ladders()
    pool = []
    for i, e in ffbe.items():
        v = ffbe_view(e)
        if not damaging(v) or not v["name"]: continue
        if norm(v["name"]) in nffr: continue
        if not v["frames"]["hits"]: continue
        pool.append(v)
    rng = random.Random(seed)
    rng.shuffle(pool)
    picked, seen = [], set()
    for v in pool:
        if norm(v["name"]) in seen: continue
        seen.add(norm(v["name"])); picked.append((v, propose(v, lad)))
        if len(picked) >= n: break
    os.makedirs(OUT, exist_ok=True)
    for v, draft in picked:
        slug = re.sub(r"[^a-z0-9]+", "-", v["name"].lower()).strip("-")
        json.dump({"move": v["name"], "braveExvius": v, "proposedResonance": draft},
                  open(os.path.join(OUT, "import-" + slug + ".json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return picked


def line(v):
    t = v["target"]
    return (f"{v['game']:13s} {str(v['id']):9s} {v['name'][:22]:22s} {str(v['kind'])[:9]:9s} {str(v['damageType'])[:8]:8s} "
            f"{str(v['element'])[:7]:7s} {str(t['shape'])[:6]:6s} MP {str(v['cost']['MP']):>4s}  power {str(v['power']):>6s}  "
            f"hits {str(v['hits']):>2s}  split {str(v['hitSplit'])[:28]}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sample"
    arg = lambda n, d: (type(d)(sys.argv[sys.argv.index(n) + 1]) if n in sys.argv else d)
    if cmd == "sample":
        for a, b in sample(arg("--n", 12), arg("--seed", 3)):
            print(line(a)); print(line(b)); print()
        print("written to", OUT)
    elif cmd == "show":
        want = norm(sys.argv[2])
        ffr, ffbe, nffr, nffbe = build()
        if want in nffr: print(json.dumps(ffr_view(ffr[nffr[want][0]]), indent=1, ensure_ascii=False))
        for i in nffbe.get(want, [])[:3]: print(json.dumps(ffbe_view(ffbe[i]), indent=1, ensure_ascii=False))
    elif cmd == "import":
        for v, draft in unmatched(arg("--n", 12), arg("--seed", 3)):
            print(f"{v['name'][:24]:24s} {str(v['damageType'])[:8]:8s} {str(v['power']):>7s}x x{str(v['hits']):<2s} -> "
                  f"{draft['DamageType']:6s} power {str(draft['magnification']):>4s} hits {draft['hitCount']} "
                  f"({draft['TargetType']}, {draft['element']}, MP {draft['Cost']})")
        print("written to", OUT)
    elif cmd == "anchors":
        for t, c in anchor_curve().items():
            print(f"  {t}: " + "  ".join(f"{x:g}x->{y}" for x, y in c))
    elif cmd == "ladder":
        lad = power_ladders()
        for game in lad:
            if game == "anchors": continue
            for t, v in lad[game].items():
                q = [v[int(len(v) * f)] for f in (0.1, 0.25, 0.5, 0.75, 0.9)]
                print(f"  {game:13s} {t:7s} n={len(v):5d}  10/25/50/75/90th: {q}")
    elif cmd == "power":
        rows = power_relation()
        print(f"{len(rows)} moves in both games with a power number on each side")
        for r in sorted(rows, key=lambda r: r["ratio"] or 0):
            print(f"  {r['move'][:24]:24s} FFR {r['ffrPower']:5d} x{r['ffrHits']:<2d} {str(r['ffrType'])[:6]:6s} | "
                  f"FFBE {str(r['ffbePower']):>6s} x{str(r['ffbeHits']):<3s} {str(r['ffbeType'])[:8]:8s} | ratio {r['ratio']}")
