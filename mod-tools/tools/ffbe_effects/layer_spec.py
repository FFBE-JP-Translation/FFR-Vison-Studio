"""layer_spec.py - how an `ffbe_effects` layer entry (units.json / studio modal) maps to a rendered effect doc and a converted spec.

Entry fields read here:
  source      "<file>.bmb"                       max_frames  cap on baked frames (default 320)     particles  per-emitter cap (64)
  repeat      play the file N times as one clip  interval    seconds between repeats (0.333 = 20 frames)
  exclude     [emitter indices] left out of the bake (e.g. bm_2020_fire3's invisible light_burst1 star, #27)
  add_gain    additive "glow": < 1 dims, > 1 brightens colour + texture alpha        scale   size multiplier (1.6 = effect units -> sprite px)
  max_units   sprite size cap in world units before a sprite counts as a screen plate (to_ss6.MAX_SPRITE_UNITS)
  min_frames  pad the clip with hidden frames to at least this length (default MIN_FRAMES): the game's SpriteStudio actor loops
              a clip that ends before the battle sequence does
  compose     [sub-entries] -> ONE clip / ONE actor made of several files: each sub-entry has source + the bake fields above plus
              "time" (seconds into the clip) and "offset" [x right, y up] in sprite pixels. Firaga = fire3 at (30, -150) from
              the target + fire1 x 7 from 0.33 s at (0, 0). One actor means one spawn and one move-to-target in the sequence.
The doc folder name encodes every option that changes the bake, so two entries of one file with different repeats / exclusions
never share a cache: build/effects/doc_<stem>[__x<repeat>i<frames>][__ex<a>-<b>]; a composite is written to
build/effects/doc_<name>__composite/ from its parts' docs.
"""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
EFFECTS_DEC = os.path.join(ROOT, "build", "ffbe_cpk", "effects_dec")
MIN_FRAMES = 270           # 4.5 s at 60 fps, longer than any battle skill sequence (Firaga's is 2.83 s)

def bake_options(fx):
    rep = max(1, int(fx.get("repeat") or 1))
    iv = int(round(float(fx.get("interval") or 0) * 60))
    ex = sorted({int(x) for x in (fx.get("exclude") or [])})
    return rep, iv, ex

def doc_stem(fx):
    """(bmb stem, doc folder stem) of a plain (non-composite) entry"""
    stem = os.path.splitext(os.path.basename(fx["source"]))[0]
    rep, iv, ex = bake_options(fx)
    suffix = (f"__x{rep}i{iv}" if rep > 1 else "") + ("__ex" + "-".join(str(x) for x in ex) if ex else "")
    return stem, stem + suffix

def spec_stem(fx):
    """folder stem for the converted spec: the composite's name, else the doc stem"""
    return fx["name"] if fx.get("compose") else doc_stem(fx)[1]

def render_argv(python, render_py, bmb, doc_dir, fx):
    """`python` is kept for callers; the interpreter actually used comes from ffrenv (the exe's --run when packaged)"""
    sys.path.insert(0, os.path.join(ROOT, "tools")); import ffrenv
    rep, iv, ex = bake_options(fx)
    argv = ffrenv.py(render_py, bmb, doc_dir) + ["--step", "1", "--max-frames", str(int(fx.get("max_frames", 320))), "--size", "512", "--ppu", "2.4",
            "--particles", str(int(fx.get("particles", 64))), "--doc"]   # emission counts come from the file; --particles is only a per-frame cap
    if rep > 1: argv += ["--repeat", str(rep), "--interval", str(iv)]
    if ex: argv += ["--exclude", ",".join(str(x) for x in ex)]
    return argv

def convert_kwargs(fx):
    sys.path.insert(0, HERE); import to_ss6
    return {"add_gain": float(fx.get("add_gain", 1.0)), "scale_mult": float(fx.get("scale", 1.0)),
            "max_units": float(fx.get("max_units", to_ss6.MAX_SPRITE_UNITS)), "min_frames": int(fx.get("min_frames", MIN_FRAMES))}

def _current(doc_dir):
    """does the cached doc carry the current ibmb.BAKE_VERSION stamp (in _info.json)?"""
    sys.path.insert(0, HERE); import ibmb
    try: return json.load(open(os.path.join(doc_dir, "_info.json"), encoding="utf-8")).get("bakeVersion") == ibmb.BAKE_VERSION
    except Exception: return False

def ensure_doc(entry, log=print):
    """doc.json of a plain entry, rendering the bmb once per option set (about a minute)"""
    _stem, dstem = doc_stem(entry)
    doc_dir = os.path.join(ROOT, "build", "effects", f"doc_{dstem}"); doc = os.path.join(doc_dir, "doc.json")
    if os.path.exists(doc) and not _current(doc_dir):
        log(f"{dstem}: rendered by an older parser, re-rendering"); os.remove(doc)
    if not os.path.exists(doc):
        bmb = os.path.join(EFFECTS_DEC, entry["source"])
        if not os.path.exists(bmb): raise FileNotFoundError(f"{bmb} (run tools/devui/ffbe_decrypt.py --out build/ffbe_cpk/effects_dec on the battleEffect archives)")
        log(f"rendering {entry['source']} (first time, about a minute)")
        r = subprocess.run(render_argv(sys.executable, os.path.join(HERE, "render.py"), bmb, doc_dir, entry), capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0 or not os.path.exists(doc): raise RuntimeError(f"render failed for {entry['source']}: {(r.stderr or r.stdout)[-400:]}")
    return doc

def compose_docs(parts):
    """parts: [(doc dict, start frame, dx px, dy px, gain)] with one pixelsPerUnit -> one doc, frames padded to the longest part"""
    ppu = float(parts[0][0].get("pixelsPerUnit") or 2.4)
    n = max(t0 + len(d["frames"]) for d, t0, _dx, _dy, _g in parts)
    tex, tex_index = [], {}
    def tid(name):
        if name not in tex_index: tex_index[name] = len(tex); tex.append(name)
        return tex_index[name]
    frames = [[] for _ in range(n)]
    for d, t0, dx, dy, g in parts:
        remap = [tid(t) for t in d["textures"]]
        for i, fr in enumerate(d["frames"]):
            for sp in fr:
                s = dict(sp); s["tex"] = remap[sp["tex"]]; s["pos"] = [sp["pos"][0] + dx, sp["pos"][1] + dy]
                if g != 1.0: s["gain"] = g
                frames[t0 + i].append(s)
    return {"fps": 60, "frameCount": n, "pixelsPerUnit": ppu, "originWorld": [0.0, 0.0], "textures": tex, "frames": frames}

def load_doc_for(fx, log=print):
    """(doc.json path, doc dict) for a plain or composite entry; a composite is (re)written from its parts' cached docs"""
    if not fx.get("compose"):
        p = ensure_doc(fx, log); return p, json.load(open(p, encoding="utf-8"))
    scale = float(fx.get("scale", 1.0)); parts = []
    for part in fx["compose"]:
        d = json.load(open(ensure_doc(part, log), encoding="utf-8")); ppu = float(d.get("pixelsPerUnit") or 2.4)
        ox, oy = (part.get("offset") or [0, 0])[:2]
        # sub-offsets are sprite pixels; the converter scales positions by the layer scale, so pre-divide to keep them 1:1
        parts.append((d, int(round(float(part.get("time", 0)) * 60)), float(ox) * ppu / scale, float(oy) * ppu / scale, float(part.get("add_gain", 1.0))))
    doc = compose_docs(parts)
    doc_dir = os.path.join(ROOT, "build", "effects", f"doc_{fx['name']}__composite"); os.makedirs(doc_dir, exist_ok=True)
    p = os.path.join(doc_dir, "doc.json"); json.dump(doc, open(p, "w", encoding="utf-8"), separators=(",", ":"))
    return p, doc
