r"""export_ability.py - everything one FFBE magic / ability plays, gathered into a folder: the effect files (.bmb, the particle
and frame data), the textures they draw with (the sprite sheets), the meshes (.m3r), the sound cues as .wav, and a manifest
with the timing (skill frame -> effect group -> spawns, in 60 fps frames).

    python tools/ffbe_effects/export_ability.py magic 20200 abilities/firaga [--name Firaga]
    python tools/ffbe_effects/export_ability.py ability 1502040 abilities/<folder>

Sounds come from the JP client's SE bank (S:\FFBE JP Data Export\public\SE.acb): cue id -> cue name via acb_cues.py, then the
stream of that name is decoded by vgmstream (tools/vgmstream/vgmstream-cli.exe).
"""
import json, os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools", "ffbe_effects")); sys.path.insert(0, os.path.join(ROOT, "tools", "devui"))
import catalog, ibmb, acb_cues

EFFECTS = catalog.EFFECTS_DIR
SE_ACB = r"S:\FFBE JP Data Export\public\SE.acb"
VGM = os.path.join(ROOT, "tools", "vgmstream", "vgmstream-cli.exe")

ANCHOR = {"1": "each target unit", "2": "the target group's centre (one instance)", "3": "the caster", "4": "the screen"}
LAYER = {"1": "in front of the unit sprites", "2": "behind the unit sprites"}


def find_file(stem):
    """A texture / model name from a .bmb -> the file in effects_dec (textures .png, models .m3r; some stems carry a stray .png.png twin)."""
    for ext in (".png", ".m3r", ""):
        p = os.path.join(EFFECTS, stem + ext)
        if os.path.isfile(p): return p
    return None


_names = None
def stream_index(cue_name):
    """vgmstream subsong number (1-based) of the SE bank stream with this cue name."""
    global _names
    if _names is None:
        out = subprocess.run([VGM, "-m", "-S", "0", SE_ACB], capture_output=True, text=True, errors="replace").stdout
        _names = [l.split("stream name:", 1)[1].strip() for l in out.splitlines() if "stream name:" in l]
    return _names.index(cue_name) + 1 if cue_name in _names else None


def export(kind, sid, out, name=None):
    se = catalog.skill_effects(kind, sid)
    if not se: sys.exit(f"no {kind} {sid} in the live tables")
    name = name or se.get("name") or f"{kind}_{sid}"
    for sub in ("effects", "textures", "meshes", "sounds"): os.makedirs(os.path.join(out, sub), exist_ok=True)
    manifest = {"name": name, "kind": kind, "id": str(sid), "nameJp": se.get("name"), "fps": 60,
                "skill": {"motion": se["motion"], "attackFrames": se["attack_frames"], "wait": se["wait"], "moveType": se["move_type"],
                          "target": se["target"], "targetRange": se["target_range"], "effectType": se["effect_type"]},
                "groups": [], "effects": {}, "sounds": {}}
    cue_table = acb_cues.cues(SE_ACB) if os.path.exists(SE_ACB) else {}
    for g in se["groups"]:
        gd = g["group"]
        if not gd: continue
        flags = g["flags"]
        entry = {"skillFrame": g["frame"], "groupId": gd["groupId"], "groupName": gd["name"],
                 "layer": LAYER.get(flags[0] if flags else "", flags[0] if flags else None), "anchor": ANCHOR.get(flags[1] if len(flags) > 1 else "", flags[1] if len(flags) > 1 else None),
                 "rawFlags": flags,
                 "spawns": [{"frame": e["frame"], "file": e["file"], "label": e["label"], "scale": e["scale"], "loop": e["loop"], "x": e["x"], "y": e["y"]} for e in gd["effects"]],
                 "sounds": [{"frame": s["frame"], "cueId": s["seId"]} for s in gd["sounds"]]}
        manifest["groups"].append(entry)
        for e in gd["effects"]:
            f = e["file"]
            if not f or f in manifest["effects"]: continue
            src = os.path.join(EFFECTS, f)
            if not os.path.exists(src): manifest["effects"][f] = {"missing": True}; continue
            shutil.copy2(src, os.path.join(out, "effects", f))
            eff = ibmb.parse(src)
            tex, mod = [], []
            for t in eff.textures:
                p = find_file(t)
                if p: shutil.copy2(p, os.path.join(out, "textures", os.path.basename(p))); tex.append(os.path.basename(p))
                else: tex.append(t + " (missing)")
            for m in eff.models:
                p = find_file(m)
                if p: shutil.copy2(p, os.path.join(out, "meshes", os.path.basename(p))); mod.append(os.path.basename(p))
                else: mod.append(m + " (missing)")
            manifest["effects"][f] = {"durationFrames": eff.duration, "speed": eff.speed, "textures": tex, "meshes": mod}
        for s in gd["sounds"]:
            cid = s["seId"]
            if cid is None or cid in manifest["sounds"]: continue
            cue = cue_table.get(int(cid)) if str(cid).isdigit() else None
            rec = {"cueId": cid, "cueName": cue and cue.get("name"), "file": None}
            if cue and cue.get("name"):
                idx = stream_index(cue["name"])
                if idx:
                    wav = os.path.join(out, "sounds", f"{cue['name']}.wav")
                    r = subprocess.run([VGM, "-s", str(idx), "-o", wav, SE_ACB], capture_output=True, text=True, errors="replace")
                    if r.returncode == 0 and os.path.exists(wav): rec["file"] = os.path.basename(wav)
                    else: rec["error"] = (r.stderr or r.stdout)[-300:]
                else: rec["error"] = "cue name not among the bank's streams"
            manifest["sounds"][cid] = rec
    json.dump(manifest, open(os.path.join(out, "manifest.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    readme = [f"# {name} (FFBE {kind} {sid}, JP name {se.get('name')})", "",
              "What the game plays for this skill, pulled from the JP client. Frame numbers are 60 fps; skill frame 0 is the start of the",
              "caster's motion. `manifest.json` holds the same data as JSON.", "",
              "* `effects/` - the `.bmb` particle-effect files (IBMB: emitters, curves, timing; see `tools/ffbe_effects/FORMAT.md`).",
              "* `textures/` - the sprite sheets those effects draw with (`.png`, shared between effects).",
              "* `meshes/` - the `.m3r` meshes some emitters render their sprites through.",
              "* `sounds/` - the sound cues, decoded to `.wav` from the client's `SE.acb` bank (cue id -> name in the manifest).", "",
              "## Timing", ""]
    for g in manifest["groups"]:
        readme.append(f"* skill frame {g['skillFrame']}: group {g['groupId']} `{g['groupName']}`, drawn {g['layer']}, anchored at {g['anchor']}")
        for sp in g["spawns"]:
            off = f", offset ({sp['x']}, {sp['y']})" if sp["x"] or sp["y"] else ""
            readme.append(f"  * +{sp['frame']} frames: `{sp['file']}` scale {sp['scale']}{off}")
        for s in g["sounds"]:
            rec = manifest["sounds"].get(s["cueId"], {})
            readme.append(f"  * +{s['frame']} frames: sound cue {s['cueId']} `{rec.get('cueName')}` -> `{rec.get('file')}`")
    readme += ["", f"Hits (`attack_frames`, frame:percent:...): `{se['attack_frames']}`; wait `{se['wait']}`.", ""]
    for f, info in manifest["effects"].items():
        if info.get("missing"): readme.append(f"* `{f}`: missing from the extracted effects"); continue
        readme.append(f"* `{f}`: {info['durationFrames']} frames; textures {', '.join('`' + t + '`' for t in info['textures'])}" + (f"; meshes {', '.join('`' + m + '`' for m in info['meshes'])}" if info["meshes"] else ""))
    open(os.path.join(out, "README.md"), "w", encoding="utf-8").write("\n".join(readme) + "\n")
    print(name, "->", out, "| effects", len(manifest["effects"]), "| textures", len(os.listdir(os.path.join(out, "textures"))), "| meshes", len(os.listdir(os.path.join(out, "meshes"))),
          "| sounds", [(k, v.get("cueName"), v.get("file") or v.get("error")) for k, v in manifest["sounds"].items()])


if __name__ == "__main__":
    a = sys.argv[1:]
    name = a[a.index("--name") + 1] if "--name" in a else None
    export(a[0], a[1], os.path.join(ROOT, a[2]) if not os.path.isabs(a[2]) else a[2], name)
