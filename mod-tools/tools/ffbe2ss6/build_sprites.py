r"""build_sprites.py - FFBE unit sprites -> SpriteStudio6 spec + atlas + texture payloads for FINAL FANTASY RESONANCE.

usage: python tools/ffbe2ss6/build_sprites.py <ffbe sprite dir> <ffbe unit id> <vision id> <out dir> [--menu-only|--battle-only]
                                              [--base <base sprite dir> <base unit id>]

Produces in <out dir>:
  battle/spec.json, battle/atlas.png, battle/tex.bgra, battle/normal.bc5, battle/mreo.bgra    (Chara/summon/summon<id>)
  menu/spec.json,   menu/atlas.png,   menu/tex.bgra                                            (Chara/menu/summon<id>)
The spec is consumed by `ffr-dt make-ss6` (see src/ffr-dt/Ss6Builder.cs).

--base: a second sheet (the unit's base form) that supplies the animations the first one lacks. Brave Shift sheets have no
victory, no win_before and no dead: the game reverts to the base form for those, and so does the mod.

Conventions (from the SS6 plugin player + Cloud's data): animation origin = character feet, +Y up, 60 fps.
Cell pivot = normalized offset of the origin from the cell center (-0.5..0.5, +Y up).
"""
import json, os, struct, sys
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ffbe_frames import load_unit, compose_frame, trim

# FFR animation name -> (FFBE cgs name, loop, extra options)
BATTLE_ANIMS = [
    ("idle", "idle"), ("command", "standby"), ("Lock", "standby"), ("cushion", "standby"),   # command = selected for an action: FFBE battle-ready pose
    ("step_front", "move"), ("step_back", "move"),
    ("attack_A", "atk"), ("attack_B", "atk"), ("attack_C", "atk"), ("attack_D", "atk"), ("attack_E", "atk"),
    ("M_attack01", "magicatk"), ("M_attack02", "magicatk"), ("magic_idle", "magic_standby"), ("magic_attack", "magicatk"),
    ("LB1_before", "magic_standby"), ("LB1", "limitatk"),
    ("jump", "jump"), ("dying", "dying"), ("dead", "dead"),
    ("win", "winbefore+win"), ("win_Loop", "win"), ("Rankup", "winbefore+win"), ("Rankup_Loop", "win"),
]
MENU_ANIMS = [("Rankup", "winbefore+win"), ("Rankup_Loop", "win"), ("Lock", "standby"), ("idle", "idle"), ("win", "winbefore+win"), ("win_Loop", "win")]

FLAT_NORMAL = (128, 128)          # BC5 x,y  -> (0,0,1)
FLAT_MREO = (60, 120, 0, 0)       # R,G,B,A sampled from Cloud's atlas (metal/rough/emissive/occlusion packing)


class Sheets:
    """the unit's own sheet ("a") and, optionally, its base form's ("b"); steps carry the sheet they come from"""
    def __init__(self, main, base=None):
        self.src = {"a": main}
        if base: self.src["b"] = base
    def anims(self, key): return self.src[key][2]
    def compose(self, key, frame): atlas, cgg, _ = self.src[key]; return compose_frame(atlas, cgg[frame])

    def steps_for(self, spec):
        """'winbefore+win' -> concatenated cgs steps; an animation the main sheet lacks comes from the base sheet;
        standby falls back to idle; anything still missing falls back to idle"""
        out = []
        for name in spec.split("+"):
            for key in self.src:
                anims = self.anims(key)
                if name in anims: out += [dict(s, src=key) for s in anims[name]]; break
                if name == "standby" and "idle" in anims: out += [dict(s, src=key) for s in anims["idle"]]; break
        if not out: out = [dict(s, src="a") for s in self.anims("a").get("idle", [])]
        return out


def _shelf(items, W):
    x = y = shelf_h = 0; pos = {}
    for k, im in items:
        w, h = im.size
        if x + w + 1 > W: x = 0; y += shelf_h + 1; shelf_h = 0
        pos[k] = (x, y); x += w + 1; shelf_h = max(shelf_h, h)
    return y + shelf_h + 1, pos

def pack(images, max_w=2048):
    """shelf packer: images {key: PIL} -> (atlas size, {key: (x,y)}); smallest power-of-two atlas (W >= H) that fits"""
    items = sorted(images.items(), key=lambda kv: -kv[1].size[1])
    W = 64
    while True:
        H, pos = _shelf(items, W)
        p = 64
        while p < H: p *= 2
        if p <= W or W >= max_w: return (W, p), pos
        W *= 2

def build(sheets, anim_list, prefix, max_w):
    if any(name == "LB1" for name, _ in anim_list) and any("super_limitatk_before" in sheets.anims(key) for key in sheets.src):
        # Native CGS19 is distinct from magic standby. Explicit opening profiles
        # can request it without changing other LBs' LB1_before fallback.
        anim_list = [*anim_list, ("LB1_charge", "super_limitatk_before")]
    # 1. unique frames -> composed, trimmed cells (keyed by sheet + frame)
    frames_used = {}
    for ffr_name, cgs in anim_list:
        for s in sheets.steps_for(cgs):
            frames_used.setdefault((s["src"], s["frame"]), None)
    cells = {}   # (src, frame) -> dict(img, w, h, pivot)
    for key in frames_used:
        img = sheets.compose(*key); cr, tl = trim(img)
        if cr is None:
            cr = Image.new("RGBA", (2, 2), (0, 0, 0, 0)); tl = (img.size[0]//2 - 1, img.size[1]//2 - 1)
        c = img.size[0] // 2
        L, T = tl[0] - c, tl[1] - c            # cell top-left relative to origin (screen space, +y down)
        w, h = cr.size
        ox, oy = -L, -T                        # origin inside the cell (pixels from top-left)
        pivot = ((ox - w / 2.0) / w, ((h / 2.0) - oy) / h)
        name = f"{prefix}_{key[1]}" if key[0] == "a" else f"{prefix}_{key[0]}{key[1]}"
        cells[key] = dict(img=cr, w=w, h=h, pivot=pivot, name=name, L=L, T=T)   # L,T: cell top-left relative to the origin (+y down)
    (W, H), pos = pack({k: c["img"] for k, c in cells.items()}, max_w)
    atlas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for k, c in cells.items(): atlas.paste(c["img"], pos[k])
    # 2. animations
    animations = []
    idle_steps = sheets.steps_for("idle")
    head_y = 0
    if idle_steps:
        c = cells[(idle_steps[0]["src"], idle_steps[0]["frame"])]; head_y = int(round((0.5 - c["pivot"][1]) * c["h"]))  # top of the idle cell above origin
    for ffr_name, cgs in anim_list:
        steps = sheets.steps_for(cgs)
        t = 0; cell_keys = []; posx = []; posy = []
        for s in steps:
            cell_keys.append([t, cells[(s["src"], s["frame"])]["name"]]); posx.append([t, float(s["x"])]); posy.append([t, float(-s["y"])])
            t += max(1, s["delay"])
        frame_count = max(1, t)
        def dedupe(keys):
            out = []
            for k in keys:
                if out and out[-1][1] == k[1]: continue
                out.append(k)
            return out
        parts = {
            "root": {"Hide": [[0, 0.0]]},
            "part_0": {"Cell": cell_keys, "Posx": dedupe(posx), "Posy": dedupe(posy), "Posz": [[0, 1.0]], "Sclx": [[0, 1.0]], "Scly": [[0, 1.0]], "Hide": [[0, 0.0]]},
            "NULL_Head": {"Posx": [[0, 0.0]], "Posy": [[0, float(head_y)]]},
            "NULL_Center": {"Posx": [[0, 0.0]], "Posy": [[0, float(head_y // 2)]]},
            "NULL_Weapon": {"Posx": [[0, 20.0]], "Posy": [[0, float(head_y // 2)]], "Rotz": [[0, 0.0]]},
            "NULL_SKL000000_Magic": {"Posx": [[0, 0.0]], "Posy": [[0, float(head_y // 2)]]},
        }
        # canvas: the origin (feet) sits at the canvas centre (pivot 0,0), so it must reach the farthest extent on every side
        ext = 32
        for s in steps:
            c = cells[(s["src"], s["frame"])]; L, T = c["L"] + s["x"], c["T"] + s["y"]
            ext = max(ext, -L, L + c["w"], -T, T + c["h"])
        canvas_w = float(2 * ext + 16); canvas_h = float(2 * ext + 16)
        animations.append({"name": ffr_name, "fps": 60, "frameCount": frame_count, "canvas": [canvas_w, canvas_h], "pivot": [0.0, 0.0], "isSetup": False, "parts": parts})
    # setup animation (default pose) first? keep donor order: put Setup last
    first_cell = cells[(idle_steps[0]["src"], idle_steps[0]["frame"])]["name"] if idle_steps else next(iter(cells.values()))["name"]
    animations.append({"name": "Setup", "fps": 60, "frameCount": 1, "canvas": [0.0, 0.0], "pivot": [0.0, 0.0], "isSetup": True,
                       "parts": {"root": {"Hide": [[0, 0.0]]}, "part_0": {"Cell": [[0, first_cell]], "Posz": [[0, 1.0]], "Sclx": [[0, 1.0]], "Scly": [[0, 1.0]], "Hide": [[0, 0.0]]}}})
    spec = {"pixelSize": [float(W), float(H)],
            "cells": [{"name": c["name"], "pos": [float(pos[k][0]), float(pos[k][1])], "size": [float(c["w"]), float(c["h"])], "pivot": [c["pivot"][0], c["pivot"][1]]} for k, c in cells.items()],
            "animations": animations}
    return atlas, spec

def write_bgra(img, path):
    px = img.convert("RGBA").tobytes()
    out = bytearray(len(px))
    out[0::4] = px[2::4]; out[1::4] = px[1::4]; out[2::4] = px[0::4]; out[3::4] = px[3::4]
    open(path, "wb").write(bytes(out))

def write_flat_bgra(w, h, rgba, path):
    open(path, "wb").write(bytes([rgba[2], rgba[1], rgba[0], rgba[3]]) * (w * h))

def write_flat_bc5(w, h, xy, path):
    # BC5: two BC4 blocks (x then y) per 4x4 texel block; color0=color1=value, indices 0 -> constant
    blk = bytes([xy[0], xy[0], 0, 0, 0, 0, 0, 0, xy[1], xy[1], 0, 0, 0, 0, 0, 0])
    open(path, "wb").write(blk * ((w // 4) * (h // 4)))

def main():
    sdir, uid, vid, out = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    main_sheet = load_unit(sdir, uid)
    base = None
    if "--base" in sys.argv:
        i = sys.argv.index("--base"); bdir, bid = sys.argv[i + 1], sys.argv[i + 2]
        if os.path.exists(os.path.join(bdir, f"unit_anime_{bid}.png")):
            base = load_unit(bdir, bid); print(f"base sheet {bid}: {sorted(base[2].keys())}")
        else:
            print(f"base sheet {bid} not found under {bdir}; missing animations fall back to idle")
    sheets = Sheets(main_sheet, base)
    for kind, anim_list, max_w in (("battle", BATTLE_ANIMS, 2048), ("menu", MENU_ANIMS, 512)):
        if f"--{'menu' if kind == 'battle' else 'battle'}-only" in sys.argv: continue
        d = os.path.join(out, kind); os.makedirs(d, exist_ok=True)
        atlas, spec = build(sheets, anim_list, f"summon{vid}", max_w)
        W, H = atlas.size
        atlas.save(os.path.join(d, "atlas.png"))
        write_bgra(atlas, os.path.join(d, "tex.bgra"))
        if kind == "battle":
            write_flat_bc5(W, H, FLAT_NORMAL, os.path.join(d, "normal.bc5"))
            write_flat_bgra(W, H, FLAT_MREO, os.path.join(d, "mreo.bgra"))
        spec["cellmapName"] = f"summon{vid}"; spec["animePackName"] = f"summon{vid}"; spec["imagePath"] = f"summon{vid}_tex.png"
        json.dump(spec, open(os.path.join(d, "spec.json"), "w", encoding="utf-8"), indent=1)
        print(f"{kind}: atlas {W}x{H}, cells {len(spec['cells'])}, animations {[(a['name'], a['frameCount']) for a in spec['animations']]}")

if __name__ == "__main__":
    main()
