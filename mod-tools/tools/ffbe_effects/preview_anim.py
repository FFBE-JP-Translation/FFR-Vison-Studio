r"""preview_anim.py - what the port will look like: the unit's FFBE motion composited with its converted effect layers, as an APNG.

The effect layers are drawn from the *converted* SpriteStudio specs (what the game receives: plates dropped, oversized sprites
shrunk, additive gain, tints), not from the raw simulation, so a good preview here means a good render in-game apart from the
game's lighting. Caster-anchored layers sit on the unit (origin = its feet), target-anchored layers on a "target spot" to the
left (Brave Exvius puts enemies on the left), back layers behind the unit, front layers in front.

layers: [{"name", "source": "<file>.bmb", "anchor": "caster"|"target", "layer": "front"|"back", "time": seconds, "offset": [dx, dy] world units,
          "scale": 1.0, "add_gain": 0.6, "repeat": 7, "interval": 0.333, "exclude": [27], "max_units": 900}]   (see layer_spec.py)
"""
import json, os, sys, io
from PIL import Image, ImageDraw, ImageChops, ImageOps
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "tools", "devui")); sys.path.insert(0, os.path.join(ROOT, "tools", "ffbe2ss6"))
import to_ss6
EFFECTS_DEC = os.path.join(ROOT, "build", "ffbe_cpk", "effects_dec")
PREVIEW_DIR = os.path.join(ROOT, "build", "effects", "preview")

def unit_frames(form, anim):
    """[(RGBA 1024x1024 with the unit's origin at (512, 512), hold in 1/60 s)] for a cgs animation; falls back to idle"""
    import ffbe_catalog as fc
    from ffbe_frames import read_cgg, read_cgs, compose_frame, ALIASES
    d = fc.sprite_dir(form)
    if not d: raise FileNotFoundError(f"no sprites for {form}")
    atlas = Image.open(os.path.join(d, f"unit_anime_{form}.png")).convert("RGBA")
    cgg = read_cgg(os.path.join(d, f"unit_cgg_{form}.csv"))
    cands = [anim, ALIASES.get(anim, anim), {"limit_atk": "limitatk", "magic_atk": "magicatk"}.get(anim, anim), "idle"]
    path = next((os.path.join(d, f"unit_{a}_cgs_{form}.csv") for a in cands if os.path.exists(os.path.join(d, f"unit_{a}_cgs_{form}.csv"))), None)
    steps = read_cgs(path)
    out = []
    for st in steps:
        img = compose_frame(atlas, cgg[st["frame"]])
        if st["x"] or st["y"]:
            sh = Image.new("RGBA", img.size, (0, 0, 0, 0)); sh.alpha_composite(img, (st["x"], st["y"])); img = sh
        out.append((img, max(1, st["delay"])))
    return out

def ensure_layer_spec(layer, log=print):
    """doc (rendered once per bmb) + converted spec for this layer's settings -> spec dir"""
    import layer_spec
    _doc_path, d = layer_spec.load_doc_for(layer, log)
    name = layer.get("name") or f"fx_{layer_spec.spec_stem(layer)}"
    out = os.path.join(PREVIEW_DIR, name, "ss6")
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        to_ss6.convert(d, out, name, **layer_spec.convert_kwargs(layer))
    return out

class Layer:
    def __init__(self, spec_dir):
        self.spec = json.load(open(os.path.join(spec_dir, "spec.json"), encoding="utf-8"))
        self.atlas = Image.open(os.path.join(spec_dir, "tex.png")).convert("RGBA")
        self.cells = {c["name"]: c for c in self.spec["cells"]}
        self.anim = next(a for a in self.spec["animations"] if not a.get("isSetup"))
        self.blend = {p["name"]: p.get("blend", "Mix") for p in self.spec.get("model", {}).get("parts", [])}
        self.frames = self.anim["frameCount"]
    @staticmethod
    def key_at(keys, t, default):
        v = default
        for kt, kv in keys:
            if kt <= t: v = kv
            else: break
        return v
    def draw(self, canvas, t, ox, oy, zoom):
        """composite frame t (60 fps ticks) with the effect origin at pixel (ox, oy)"""
        if t < 0 or t >= self.frames: return canvas
        for pn, attrs in self.anim["parts"].items():
            if pn == "root" or "Cell" not in attrs: continue
            if self.key_at(attrs.get("Hide", []), t, 0.0) >= 0.5: continue
            cell = self.cells.get(self.key_at(attrs["Cell"], t, None))
            if not cell: continue
            x, y, w, h = cell["pos"][0], cell["pos"][1], cell["size"][0], cell["size"][1]
            im = self.atlas.crop((int(x), int(y), int(x + w), int(y + h)))
            sx, sy = self.key_at(attrs.get("Sclx", []), t, 1.0), self.key_at(attrs.get("Scly", []), t, 1.0)
            tw, th = max(1, int(abs(sx) * w * zoom)), max(1, int(abs(sy) * h * zoom))
            im = im.resize((tw, th), Image.BILINEAR)
            if sx < 0: im = ImageOps.mirror(im)
            if sy < 0: im = ImageOps.flip(im)
            rot = self.key_at(attrs.get("Rotz", []), t, 0.0)
            if rot: im = im.rotate(rot, expand=True, resample=Image.BILINEAR)
            alpha = self.key_at(attrs.get("Alpha", []), t, 1.0)
            if alpha < 1.0: im.putalpha(im.getchannel("A").point(lambda v: int(v * alpha)))
            px = ox + self.key_at(attrs.get("Posx", []), t, 0.0) * zoom - im.size[0] / 2
            py = oy - self.key_at(attrs.get("Posy", []), t, 0.0) * zoom - im.size[1] / 2
            layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0)); layer.paste(im, (int(px), int(py)), im)
            if self.blend.get(pn) == "Add":
                rgb = Image.new("RGBA", canvas.size, (0, 0, 0, 255)); rgb.paste(layer, (0, 0), layer)
                pre = Image.merge("RGBA", [ImageChops.multiply(ch, layer.getchannel("A")) for ch in rgb.split()[:3]] + [Image.new("L", canvas.size, 255)])
                canvas = ImageChops.add(canvas, pre)
            else:
                canvas.alpha_composite(layer)
        return canvas

def ffbe_reference_layers(kind, sid):
    """The effect layers exactly as Brave Exvius' tables describe the skill, with none of the port's knobs: anchors from the group
    flags (1 each target / 2 target group -> the target spot, 3 -> the caster, 4 screen plates skipped), the FFBE frame timing,
    the group offsets (x right, y down the screen), repeated spawns, and the measured effect-unit scale. What the game shows,
    as far as the decoded data goes (FORMAT.md 4.4 lists what is still approximate: streak spawn shape, ember spread, brightness)."""
    sys.path.insert(0, os.path.join(ROOT, "tools", "devui")); import autoport, catalog
    info = catalog.skill_effects(kind, str(sid)) or {}
    out = []
    for g in info.get("groups") or []:
        grp = g.get("group") or {}; flags = g.get("flags") or []
        anchor = flags[1] if len(flags) > 1 else "1"
        if anchor == "4": continue
        runs = {}
        for e in grp.get("effects") or []:
            f = e.get("file") or ""
            if not f or not e.get("exists") or any(w in f.lower() for w in autoport.PLATE_WORDS): continue
            runs.setdefault(f, []).append(e)
        for f, es in runs.items():
            es.sort(key=lambda e: e.get("frame", 0)); e = es[0]
            ly = {"name": f"ref_{os.path.splitext(f)[0]}", "source": f, "anchor": "caster" if anchor == "3" else "target",
                  "layer": "back" if flags[:1] == ["2"] else "front", "time": (g.get("frame", 0) + e.get("frame", 0)) / 60.0,
                  "offset": [float(e.get("x", 0)), -float(e.get("y", 0))], "scale": autoport.EFFECT_UNIT_SCALE, "add_gain": 1.0, "ffbeGroup": grp.get("name")}
            if len(es) > 1:
                gaps = [b.get("frame", 0) - a.get("frame", 0) for a, b in zip(es, es[1:])]
                ly["repeat"] = len(es); ly["interval"] = sum(gaps) / len(gaps) / 60.0
            out.append(ly)
    return out

class RawLayer:
    """The baked simulation drawn straight from its doc.json (what Brave Exvius' data says), not from the converted SpriteStudio
    spec: no plates dropped, no size cap, no tint quantisation, no glow; 60 fps."""
    def __init__(self, doc, scale=1.0):
        self.doc = doc; self.ppu = float(doc.get("pixelsPerUnit") or 2.4); self.scale = scale
        self.frames = int(doc["frameCount"]); self.tex = {}
    def texture(self, i):
        if i not in self.tex: self.tex[i] = to_ss6.load_texture(self.doc["textures"][i])
        return self.tex[i]
    def draw(self, canvas, t, ox, oy, zoom):
        if t < 0 or t >= self.frames: return canvas
        k = zoom * self.scale / self.ppu          # doc pixels -> preview pixels
        for sp in self.doc["frames"][t]:
            tex = self.texture(sp["tex"]); x, y, w, h = sp["uv"]
            im = tex.crop((int(x), int(y), int(x + max(1, w)), int(y + max(1, h))))
            tw, th = max(1, int(abs(sp["scale"][0]) * w * k)), max(1, int(abs(sp["scale"][1]) * h * k))
            if tw > 4096 or th > 4096: continue
            im = im.resize((tw, th), Image.BILINEAR)
            if sp.get("flipX"): im = ImageOps.mirror(im)
            if sp.get("flipY"): im = ImageOps.flip(im)
            col = sp.get("color")
            if col and any(abs(float(c) - 1.0) > 0.02 for c in col[:3]):
                rgb = Image.merge("RGB", [ImageChops.multiply(ch, Image.new("L", im.size, int(min(1.0, max(0.0, float(c))) * 255))) for ch, c in zip(im.split()[:3], col[:3])])
                im = Image.merge("RGBA", list(rgb.split()) + [im.getchannel("A")])
            if sp.get("rot"): im = im.rotate(float(sp["rot"]), expand=True, resample=Image.BILINEAR)
            a = float(sp.get("alpha", 1.0))
            if a < 1.0: im.putalpha(im.getchannel("A").point(lambda v, a=a: int(v * a)))
            px = ox + float(sp["pos"][0]) * k - im.size[0] / 2; py = oy - float(sp["pos"][1]) * k - im.size[1] / 2
            layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0)); layer.paste(im, (int(px), int(py)), im)
            if str(sp.get("blend", "mix")).lower() in ("add", "additive", "screen"):
                rgb = Image.new("RGBA", canvas.size, (0, 0, 0, 255)); rgb.paste(layer, (0, 0), layer)
                pre = Image.merge("RGBA", [ImageChops.multiply(ch, layer.getchannel("A")) for ch in rgb.split()[:3]] + [Image.new("L", canvas.size, 255)])
                canvas = ImageChops.add(canvas, pre)
            else:
                canvas.alpha_composite(layer)
        return canvas

def render_preview(form, anim, layers, seconds=4.0, fps=30, size=720, zoom=0.8, log=print, mode="ffr", ref=None):
    """-> APNG bytes. mode "ffr": the layers as converted for the game (the default); mode "ffbe": the Brave Exvius reference --
    the skill's own effect groups (ref = {"kind", "sid"}) drawn from the raw bake, ignoring `layers`."""
    frames = unit_frames(form, anim); total = sum(d for _, d in frames)
    specs = []
    if mode == "ffbe":
        import layer_spec
        layers = ffbe_reference_layers(ref["kind"], ref["sid"]) if ref else []
        log(f"Brave Exvius reference: {len(layers)} layer(s) from the effect tables")
        for ly in layers:
            try:
                specs.append((ly, RawLayer(layer_spec.load_doc_for(ly, log)[1], float(ly.get("scale", 1.0)))))
            except Exception as ex:
                log(f"layer {ly.get('name')}: {ex}")
    for ly in ([] if mode == "ffbe" else layers):
        try:
            specs.append((ly, Layer(ensure_layer_spec(ly, log))))
        except Exception as ex:
            log(f"layer {ly.get('name')}: {ex}")
    W = H = size
    caster = (int(W * 0.66), int(H * 0.72)); target = (int(W * 0.26), int(H * 0.72))
    def anchor_pos(ly):
        base = target if ly.get("anchor") == "target" else caster
        off = ly.get("offset") or [0, 0]
        return (base[0] + float(off[0]) * zoom, base[1] - float(off[1]) * zoom)
    bg = Image.new("RGBA", (W, H), (14, 18, 30, 255))
    d = ImageDraw.Draw(bg)
    for yy in range(H): d.line([(0, yy), (W, yy)], fill=(10 + yy * 18 // H, 14 + yy * 24 // H, 28 + yy * 34 // H, 255))
    d.ellipse([target[0] - 70, target[1] - 18, target[0] + 70, target[1] + 18], outline=(90, 90, 110, 255), width=2)
    d.text((target[0] - 22, target[1] + 22), "targets", fill=(150, 150, 170, 255))
    d.ellipse([caster[0] - 60, caster[1] - 14, caster[0] + 60, caster[1] + 14], outline=(70, 90, 120, 255), width=2)
    out = []
    n = int(seconds * fps)
    for k in range(n):
        t = k / fps
        canvas = bg.copy()
        tick = int(t * 60)
        for ly, sp in specs:
            if ly.get("layer", "front") == "back":
                ox, oy = anchor_pos(ly); canvas = sp.draw(canvas, tick - int(float(ly.get("time", 0)) * 60), ox, oy, zoom)
        # unit frame at this time (loop)
        u = int(t * 60) % max(1, total); acc = 0
        for img, hold in frames:
            acc += hold
            if u < acc: break
        us = img.resize((int(1024 * zoom), int(1024 * zoom)), Image.NEAREST)
        canvas.alpha_composite(us, (int(caster[0] - us.size[0] / 2), int(caster[1] - us.size[1] / 2)))
        for ly, sp in specs:
            if ly.get("layer", "front") != "back":
                ox, oy = anchor_pos(ly); canvas = sp.draw(canvas, tick - int(float(ly.get("time", 0)) * 60), ox, oy, zoom)
        dd = ImageDraw.Draw(canvas); dd.text((8, 8), f"{t:4.2f} s  {anim}  {'Brave Exvius data' if mode == 'ffbe' else 'FF Resonance conversion'}", fill=(200, 200, 210, 255))
        out.append(canvas.convert("RGB").convert("RGBA"))
    buf = io.BytesIO()
    out[0].save(buf, format="PNG", save_all=True, append_images=out[1:], duration=int(1000 / fps), loop=0)
    return buf.getvalue()

if __name__ == "__main__":
    form, anim, outp = sys.argv[1], sys.argv[2], sys.argv[3]
    layers = json.loads(sys.argv[4]) if len(sys.argv) > 4 else []
    ref = {"kind": sys.argv[5], "sid": sys.argv[6]} if len(sys.argv) > 6 else None      # ... <kind> <sid> renders the Brave Exvius reference instead
    open(outp, "wb").write(render_preview(form, anim, layers, mode="ffbe" if ref else "ffr", ref=ref))
    print("wrote", outp)
