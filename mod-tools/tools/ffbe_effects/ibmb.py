"""
ibmb.py -- parser for FFBE (Final Fantasy Brave Exvius) ".bmb" battle-effect files.

Magic "IBMB".  The format is a *serialised object graph* produced by a 64-bit
build of a particle-effect middleware (BISHAMON-style): a flat stream of
fixed-size objects, followed by a string table, followed by a "pool" of
variable-length arrays (keyframe curves, child lists, resource descriptors).
All in-file pointers were replaced by offsets; NULL pointers are stored as
0xFFFFFFFFFFFFFFFF and uninitialised padding is 0xBA fill.

See FORMAT.md for the full spec and the evidence behind each field.

Public API
----------
    eff = parse("path/to/foo.bmb")          -> Effect
    eff.to_dict()                           -> JSON-able structural dump
    bake(eff, ...)                          -> {"fps","frameCount","loop",
                                                "textures":[...],
                                                "frames":[[part, ...], ...]}

`parse` is a faithful structural decode (high confidence).  `bake` runs an
*approximate* particle simulation to turn the emitter description into the
per-frame sprite list the renderer consumes (medium/low confidence -- the
emission model is only partly reverse engineered).
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import random
import struct
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

MAGIC = b"IBMB"

# ---------------------------------------------------------------------------
# header
# ---------------------------------------------------------------------------
# off  size  meaning                                            confidence
# 0x00  4    magic 'IBMB'                                       certain
# 0x04  4    version tag; 01 01 03 01 (almost all files),        high
#            or 51 00 00 00 in a handful of old files
# 0x08  4    always 0x41 ('A') -- unknown, constant              n/a
# 0x0C  4    always 0
# 0x10  4    texture count                                       certain
# 0x14  4    model count                                         certain
# 0x18  8    always 0
# 0x20 32    8 x u32: pool-relative offsets of resource-descriptor
#            arrays.  [0]=textures [1]=models, rest 0xFFFFFFFF   certain
# 0x40  4    number of pool bytes actually used                  certain
# 0x44  4    always 0
# 0x48  4    total effect duration in frames                     certain
# 0x4C  4    always 0x00010000 -- unknown                        n/a
# 0x50  4    always 0
# 0x54  4    float, always 1.0 -- playback speed?                low
# 0x58  8    string-table file offset                            certain
# 0x60  ...  object/chunk stream, runs up to the string table    certain
#
# After the string table (padded with 0xBA to 16 bytes) comes the pool.
# ---------------------------------------------------------------------------

HDR_TEX_COUNT = 0x10
HDR_MODEL_COUNT = 0x14
HDR_RESTABLE = 0x20
HDR_POOL_USED = 0x40
HDR_DURATION = 0x48
HDR_SPEED = 0x54
HDR_STRTAB = 0x58
HDR_POOL = 0x5C
CHUNKS_START = 0x60

# ---------------------------------------------------------------------------
# chunk (object) types.  Size is fixed per type; a couple of types have a
# second, slightly larger variant in old files.
# ---------------------------------------------------------------------------
T_NODE = 0        # 704  -- transform / group node, has children
T_EMIT_A = 2      # 2128 -- sprite emitter (25 curve slots)
T_EMIT_B = 3      # 1840 -- sprite emitter (22 curve slots)
T_EMIT_C = 4      # 592  -- small emitter (texture only)
T_EMIT_MODEL = 6  # 1904 -- model emitter: model + texture
T_EMIT_D = 7      # 1856 -- emitter variant
# 9(144) 10(224) 11(224) 12(176) 13(112) 15(208) -- rare, not decoded

TYPE_NAME = {
    0: "node",
    2: "emitterA",
    3: "emitterB",
    4: "emitterC",
    6: "emitterModel",
    7: "emitterD",
    9: "aux9", 10: "aux10", 11: "aux11", 12: "aux12", 13: "aux13", 15: "aux15",
}

EMITTER_TYPES = (2, 3, 4, 6, 7)

# --- common object header ---------------------------------------------------
OBJ_TYPE = 0x00
OBJ_SIZE = 0x04
OBJ_CHILD_COUNT = 0x08     # node only
OBJ_CHILD_ARRAY = 0x18     # node only: u64 pool offset of child pointer array
OBJ_RES1 = 0x40            # u64, string-table-relative.  model for type 6,
                           # texture for the sprite emitters.
OBJ_RES2 = 0x50            # u64, string-table-relative.  texture for type 6,
                           # secondary texture for the sprite emitters.

# --- type 0 (node) ----------------------------------------------------------
NODE_DELAY = 0x78          # u32 start delay in frames        (medium)
NODE_DURATION = 0x80       # u32 active duration in frames    (high: == header
                           #     duration in 58% of files)
NODE_ROT = 0x19C           # float3 static rotation in degrees, default 0
NODE_ROT_RANGE = 0x1A8     # float3 random rotation range in degrees (360 = any orientation)
                           # (high: sm_0071_Carbuncle1_back.bmb and its
                           #  ..._reverse.bmb sibling differ in exactly one
                           #  word in the whole file -- this field's Y going
                           #  0 -> 180, i.e. a horizontal mirror)
NODE_SCALE = 0x1E4         # float3, default (1,1,1); scales the whole subtree
                           # (high: (340,280,1) on the full-screen plate node
                           #  of Ariana's LB, (100,30,100) on a slash; and
                           #  lb_208000505 vs ...506_FFVIII_Selphie_front_unit
                           #  differ only here, 0.295 -> 0.592)
# Historical fallback guesses only. Native translation below establishes
# +0x160 as position variance, +0x16c as velocity and +0x178 as its variance.
# Selected native modes bypass the old launch/scatter interpretation.
NODE_VELOCITY = 0x170
NODE_VEL_SPREAD = 0x17C
NODE_EMIT_BOX = 0x160
# --- emission, all on the *node* above the emitter (see FORMAT.md 3.3) ------
NODE_EMIT_COUNT = 0x90     # u32 particles per burst, default 1     (medium)
NODE_EMIT_STREAM = 0x94    # u32 >1 => spawn continuously across the node's
                           # window rather than one burst, default 1 (medium)
NODE_EMIT_BURSTS = 0x98    # u32 number of bursts, default 1         (medium)
NODE_EMIT_INTERVAL = 0x9C  # u32 frames between bursts, default 0    (medium)
NODE_EMIT_STEP = 0xDC      # f32 frames between emission opportunities (native GL 9.1.0)
NODE_EMIT_MODE = 0x100     # u32: 0 regular window/step generator, nonzero curve generator
NODE_SLOTS = (0x230, 8)    # 8 curve slots, 16 bytes each

# --- emitters ---------------------------------------------------------------
# Emitter structs share sub-blocks but interleave type-specific fields, so the
# shifts between types differ per region.  These were located individually.
EMIT_COLOR = {2: 0xF8, 3: 0x98, 4: 0x58, 6: 0x78, 7: 0x78}  # float4 RGBA (high)
EMIT_COLOR_VAR = {2: 0x108, 3: 0xA8, 6: 0x88, 7: 0x88}   # float4 RGBA variance
EMIT_LIFE = {2: 0x15C, 3: 0x0F8, 6: 0x12C}               # u32 frames   (high)
EMIT_DELAY = {2: 0x154, 3: 0x0F0, 6: 0x124}              # signed frames + signed variance
# Native InitDrawData copies these render-state selectors to DrawData+0;
# Animation::Draw then copies them to DrawInfo+A4, the GL blend table index.
# The former +198/+134/+168 guesses were alpha animation selectors.
EMIT_BLEND = {2: 0x720, 3: 0x690, 4: 0x238, 6: 0x6D0, 7: 0x698}
# base size in world units.  Types 4 and 7 hold a scalar/float3 of their own
# (t4 +0xFC: present in 100% of type-4 emitters, 25 distinct values, median 1,
#  max 180; t7 +0x1DC: 25 distinct values, median 13, max 122 -- 80/100 on the
#  glow orbs of bm_2037_burst_front).                                 (medium)
EMIT_BASE_SCALE = {2: 0x36C, 3: 0x30C, 4: 0x0FC, 6: 0x34C, 7: 0x1DC}
# Native AssignModule selector, not presence of a curve, chooses scaling.
SCALE_MODE = {0: 0xB4, 2: 0x190, 3: 0x12C, 6: 0x160}
SCALE_BASE = {0: NODE_SCALE, 2: 0x36C, 3: 0x30C, 6: 0x34C}
ROTATION_MODE = {0: 0xB0, 2: 0x18C, 3: 0x128, 6: 0x15C}
ROTATION_BASE = {kind: offset - 72 for kind, offset in SCALE_BASE.items()}
TRANSLATION_MODE = {0: 0xAC, 2: 0x188, 3: 0x124, 6: 0x158}
TRANSLATION_BASE = {kind: offset - 72 for kind, offset in ROTATION_BASE.items()}
# Null alpha uses the same native module as drawable emitters. The Null
# wrappers at 0x28AEDA8/0x28AEDB8 read +F4/+F8 and Curve<1> at +118;
# NullSetupper::AssignModule (0x28B23E4) selects it from +BC.
EMIT_ALPHA_CURVE = {0: 0x118, 2: 0x280, 3: 0x220, 4: 0x178, 6: 0x260, 7: 0x280}
EMIT_ALPHA_MODE = {0: 0xBC, 2: 0x198, 3: 0x134, 6: 0x168}
EMIT_ALPHA_BASE = {0: 0xF4, 2: 0x220, 3: 0x1BC, 6: 0x1F0}
# Null PostUpdate (0x28AE450) interpolates local and parent alpha using +D4.
# Drawable VertexMaker builds Mod/Lerp coefficients from these fields:
# Quad 0x2940194/0x29401D8, Particle 0x293E82C/0x293E870,
# Model 0x293C460/0x293C49C. Operation1 is Mod; other values select Lerp.
ALPHA_PARENT_WEIGHT = {0: 0xD4, 2: 0x200, 3: 0x19C, 6: 0x1D0}
ALPHA_PARENT_OPERATION = {2: 0x264, 3: 0x204, 6: 0x244}
ALPHA_PARENT_EPSILON = 9.999999974752427e-7  # native float at 0x292289C
# u32 immediately before the constant 0x01010000 word; 1 in ~92% of emitters.
# Reads as an enable/visible flag: three pairs of "same LB, next star rank"
# files (lb_1000162 05/06, lb_2120015 05/06, lb_3360001 05/06, lb_3380004
# 04/05) differ in exactly this one word, 0 -> 1, i.e. the higher rank turns
# an extra emitter on.  It is independent of colour.a.            (medium)
EMIT_ENABLE = {2: 0x138, 3: 0x0D8, 6: 0x108}
# UV wrap / tile mode.  0 = clamp, 1 = repeat, 2 = MIRRORED 2x2 TILING: the
# quad is covered by a 2x2 mirrored copy of the texture, so art authored as one
# quadrant (a quarter arc) becomes a full symmetric shape.            (high)
EMIT_UV_MODE = {2: 0x734, 3: 0x6A4, 6: 0x6E4}
# optional {u32 count; u64 poolOffset} -> 32-byte record whose floats at +12
# and +16 are the (u, v) tiling factors; (2.0, 2.0) in 37 of the 38 cases in
# the corpus.  Type 2's copy of this descriptor has not been located.  (medium)
EMIT_UV_TILE = {3: 0x6E4, 6: 0x724}
# Native UV transform selectors: translation, rotation, scaling in each
# three-word group. Both texture channels have the same eight-mode tables.
UV_CHANNEL_SELECTORS = {2: (0x1C0, 0x1EC), 3: (0x15C, 0x188), 6: (0x190, 0x1BC)}
# Each channel starts with a float3 pivot, then three 72-byte blocks containing
# base/variance, velocity/variance, acceleration/variance. The first/second
# channels' native Curve<3> pairs occupy slots 6..11 / 12..17 respectively.
UV_CHANNEL_BASE = {2: (0x3CC, 0x4B0), 3: (0x36C, 0x450), 6: (0x3AC, 0x490)}
# Material mode, wrap/filter pairs, RGB selector/base/curve slots, alpha
# selector/base/curve descriptors, and distortion midpoint (byte-range RGB).
TEXTURE_MATERIAL_FIELDS = {
    2: (0x730, 0x734, 0x73C, (0x1B8, 0x1E4), (0xF8, 0x118), (23, 24),
        (0x1BC, 0x1E8), (0x234, 0x23C), (0x290, 0x2A0), 0x3B4),
    3: (0x6A0, 0x6A4, 0x6AC, (0x154, 0x180), (0x98, 0xB8), (20, 21),
        (0x158, 0x184), (0x1D0, 0x1D8), (0x230, 0x240), 0x354),
    6: (0x6E0, 0x6E4, 0x6EC, (0x188, 0x1B4), (0xA8, 0xC8), (20, 21),
        (0x18C, 0x1B8), (0x204, 0x20C), (0x270, 0x280), 0x394),
}
UV_MIRROR = 2
# tail curve-slot arrays: (first offset, slot count)
EMIT_SLOTS = {2: (0x590, 25), 3: (0x530, 22), 6: (0x570, 22), 0: (0x230, 8)}

# Slot index -> meaning.  Types 3 and 6 share the same 22-slot list; type 2 has
# the same 22 plus 3 extra at the end.  Derived from value-range statistics
# over ~600 files plus targeted diffs.  Only the starred ones are solid.
SLOT_NAMES = {
    0: "translate",      # * median |v| ~100, up to 1500
    1: "translate_var",
    2: "rotate",         # * up to exactly 360 (degrees)
    3: "rotate_var",
    4: "scale",          # * most-used slot; median |v| ~140 for models
    5: "scale_var",
    6: "uv1_translate", 7: "uv1_translate_add", 8: "uv1_rotate", 9: "uv1_rotate_add", 10: "uv1_scale",
    11: "uv1_scale_add", 12: "uv2_translate", 13: "uv2_translate_add", 14: "uv2_rotate",
    15: "uv2_rotate_add", 16: "uv2_scale", 17: "uv2_scale_add", 18: "unk18",
    19: "color",         # * always within [0,1], vec3 (offset 0x6A0 on type 6 = index 19; a v25 table mislabelled it 13)
    20: "color_var",     #   also within [0,1]
    21: "unk21", 22: "extra22", 23: "extra23", 24: "extra24",
}
SLOT_TRANSLATE, SLOT_TRANSLATE_VAR = 0, 1
SLOT_ROTATE, SLOT_ROTATE_VAR = 2, 3
SLOT_SCALE, SLOT_SCALE_VAR = 4, 5
SLOT_COLOR = 19

# Node slots use a shorter list.
NODE_SLOT_NAMES = {0: "translate", 1: "translate_var", 2: "rotate",
                   3: "rotate_var", 4: "scale", 5: "scale_var",
                   6: "unk6", 7: "color"}

# Native table at libgame.so 0x3020B88: 1=SRC_ALPHA/ONE_MINUS_SRC_ALPHA,
# 2=SRC_ALPHA/ONE, 3=ZERO/ONE_MINUS_SRC_ALPHA, 4=ONE/ONE. Mode 3 is
# represented by black source RGB with ordinary alpha compositing in bake().
# Mode 4 needs premultiplied source handling for exact export; current assets
# use modes 1/2/3. Other blend equations remain outside the sprite adapter.
BLEND_NAMES = {0: "normal", 1: "normal", 2: "add", 3: "normal", 4: "add"}

# keyframe stride for a curve of dimension N: N interp + 3N floats + 1 time
CURVE_STRIDE = {1: 20, 2: 36, 3: 52, 4: 68}


# ---------------------------------------------------------------------------
# data model
# ---------------------------------------------------------------------------
@dataclass
class Curve:
    """An animation curve.  `times` are normalised 0..1 over the owner's life."""
    dim: int
    pool_off: int
    keys: List[Tuple[float, List[float], List[int]]]  # (time, value[], interp[])
    # Per-key outgoing and incoming Hermite tangents, in normalized segment
    # units. The native Curve<3>::ValueN (GL 9.1.0, 0x28c63a4) reads these
    # arrays before the value array; they are not unused padding.
    tangents: Optional[List[Tuple[List[float], List[float]]]] = None

    def sample(self, t: float) -> List[float]:
        ks = self.keys
        if not ks:
            return [0.0] * self.dim
        if t <= ks[0][0]:
            return list(ks[0][1])
        if t >= ks[-1][0]:
            return list(ks[-1][1])
        for i in range(len(ks) - 1):
            t0, v0, interp = ks[i]
            t1, v1, _ = ks[i + 1]
            if t0 <= t <= t1:
                f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                result = []
                for axis, (a, b) in enumerate(zip(v0, v1)):
                    mode = interp[axis]
                    if mode == 0:
                        value = b if f >= 1.0 else a
                    elif mode == 1:
                        value = a + (b - a) * f
                    elif mode in (2, 3):
                        out_tangent = self.tangents[i][0][axis] if self.tangents else 0.0
                        in_tangent = self.tangents[i + 1][1][axis] if self.tangents else 0.0
                        f2, f3 = f * f, f * f * f
                        value = ((2*f3 - 3*f2 + 1)*a + (-2*f3 + 3*f2)*b
                                 + (f3 - 2*f2 + f)*out_tangent + (f3 - f2)*in_tangent)
                    else:
                        raise ValueError(f'Unsupported Bishamon interpolation mode {mode}')
                    result.append(value)
                return result
        return list(ks[-1][1])

    def to_dict(self):
        return {"dim": self.dim,
                "keys": [{"t": round(t, 5), "v": [round(x, 5) for x in v]}
                         for t, v, _ in self.keys]}


@dataclass
class Chunk:
    index: int
    offset: int
    type: int
    size: int
    res1: Optional[str] = None
    res2: Optional[str] = None
    child_count: int = 0
    children: List["Chunk"] = field(default_factory=list)
    slots: Dict[int, Curve] = field(default_factory=dict)      # slot idx -> curve
    alpha_curve: Optional[Curve] = None
    color: Optional[List[float]] = None
    color_var: Optional[List[float]] = None
    quad_color_mode: Optional[int] = None
    quad_colors: Optional[List[List[float]]] = None
    particle_color_mode: Optional[int] = None
    particle_color_base: Optional[List[float]] = None
    particle_color_variance: Optional[List[float]] = None
    # Historical name retained for bake/API compatibility; the same native
    # global-alpha enum applies to Null, Quad, Particle, and Model chunks.
    quad_alpha_mode: Optional[int] = None
    quad_alpha_base: float = 1.0
    alpha_variance: float = 0.0
    parent_alpha_weight: float = 0.0
    parent_alpha_operation: int = 0
    texture_color_scale1_mode: Optional[int] = None
    texture_color_scale1_base: Optional[List[float]] = None
    life: int = 0
    emitter_delay: int = 0
    emitter_delay_variance: int = 0
    blend: int = -1
    base_scale: Optional[List[float]] = None
    scale_mode: Optional[int] = None
    scale_variance: Optional[List[float]] = None
    scale_velocity: Optional[List[float]] = None
    scale_velocity_variance: Optional[List[float]] = None
    scale_acceleration: Optional[List[float]] = None
    scale_acceleration_variance: Optional[List[float]] = None
    rotation_mode: Optional[int] = None
    rotation_base: Optional[List[float]] = None
    rotation_variance: Optional[List[float]] = None
    rotation_velocity: Optional[List[float]] = None
    rotation_velocity_variance: Optional[List[float]] = None
    rotation_acceleration: Optional[List[float]] = None
    rotation_acceleration_variance: Optional[List[float]] = None
    translation_mode: Optional[int] = None
    translation_base: Optional[List[float]] = None
    translation_variance: Optional[List[float]] = None
    translation_velocity: Optional[List[float]] = None
    translation_velocity_variance: Optional[List[float]] = None
    translation_acceleration: Optional[List[float]] = None
    translation_acceleration_variance: Optional[List[float]] = None
    delay: int = 0
    duration: int = 0
    node_scale: Optional[List[float]] = None
    node_rot: Optional[List[float]] = None
    rot_range: Optional[List[float]] = None
    emit_count: int = 1
    emit_stream: int = 1
    emit_bursts: int = 1
    emit_interval: int = 0
    emit_step: float = 1.0
    emit_mode: int = 0
    enabled: bool = True
    uv_mode: int = 1
    uv_tile: Optional[List[float]] = None
    uv_channels: List[dict] = field(default_factory=list)
    texture_material: Optional[dict] = None
    texture_alpha_curves: Dict[int, Curve] = field(default_factory=dict)
    emit_box: Optional[List[float]] = None
    velocity: Optional[List[float]] = None
    vel_spread: float = 0.0
    child_pool: int = 0
    # (kind, slot index, pool offset, key count, forced dim) resolved later
    pending: List[Tuple[str, int, int, int, Optional[int]]] = field(default_factory=list)

    @property
    def is_node(self) -> bool:
        return self.type == T_NODE

    @property
    def is_emitter(self) -> bool:
        return self.type in EMITTER_TYPES

    @property
    def texture(self) -> Optional[str]:
        """Best guess at which resource is the drawn texture."""
        if self.type == T_EMIT_MODEL:
            return self.res2 or self.res1
        return self.res1

    @property
    def model(self) -> Optional[str]:
        return self.res1 if self.type == T_EMIT_MODEL else None

    def tile_counts(self) -> Tuple[int, int]:
        """How many mirrored copies of the texture cover the quad."""
        if self.uv_mode != UV_MIRROR:
            return (1, 1)
        u, v = (self.uv_tile or [2.0, 2.0])[:2]
        return (max(1, min(4, int(round(u)) or 1)),
                max(1, min(4, int(round(v)) or 1)))

    def slot_name(self, i: int) -> str:
        return (NODE_SLOT_NAMES if self.is_node else SLOT_NAMES).get(i, "unk%d" % i)

    def to_dict(self):
        d = {"i": self.index, "off": self.offset, "type": self.type,
             "kind": TYPE_NAME.get(self.type, "t%d" % self.type)}
        if self.res1:
            d["res1"] = self.res1
        if self.res2:
            d["res2"] = self.res2
        if self.quad_alpha_mode is not None:
            d["globalAlphaMode"] = self.quad_alpha_mode
            d["globalAlphaBase"] = self.quad_alpha_base
            d["globalAlphaVariance"] = self.alpha_variance
            d["parentAlphaWeight"] = self.parent_alpha_weight
            d["parentAlphaOperation"] = self.parent_alpha_operation
        if self.is_emitter:
            d["enabled"] = self.enabled
            d["life"] = self.life
            d["emitterDelay"] = self.emitter_delay
            d["emitterDelayVariance"] = self.emitter_delay_variance
            d["blend"] = self.blend
            d["blendMode"] = BLEND_NAMES.get(self.blend, "add")
            d["color"] = [round(x, 4) for x in (self.color or [])]
            d["colorVar"] = [round(x, 4) for x in (self.color_var or [])]
            if self.texture_color_scale1_mode is not None:
                d["textureColorScale1Mode"] = self.texture_color_scale1_mode
                d["textureColorScale1Base"] = self.texture_color_scale1_base
            if self.quad_color_mode is not None:
                d["quadColorMode"] = self.quad_color_mode
                d["quadColors"] = self.quad_colors
                d["quadAlphaMode"] = self.quad_alpha_mode
            if self.particle_color_mode is not None:
                d["particleColor1Mode"] = self.particle_color_mode
                d["particleColor1Base"] = self.particle_color_base
                d["particleColor1Variance"] = self.particle_color_variance
            d["baseScale"] = [round(x, 4) for x in (self.base_scale or [])]
            d["uvMode"] = self.uv_mode
            if self.uv_channels:
                d["uvChannels"] = self.uv_channels
            if self.texture_material:
                d["textureMaterial"] = self.texture_material
            if self.texture_alpha_curves:
                d["textureAlphaCurves"] = {str(k): v.to_dict() for k, v in self.texture_alpha_curves.items()}
            if self.uv_tile:
                d["uvTile"] = [round(x, 3) for x in self.uv_tile]
            if self.tile_counts() != (1, 1):
                d["mirrorTiles"] = list(self.tile_counts())
        if self.is_node:
            d["delay"] = self.delay
            d["duration"] = self.duration
            d["nodeScale"] = [round(x, 4) for x in (self.node_scale or [])]
            d["nodeRotation"] = [round(x, 4) for x in (self.node_rot or [])]
            d["rotationRange"] = [round(x, 4) for x in (self.rot_range or [])]
            d["emitBox"] = [round(x, 4) for x in (self.emit_box or [])]
            if self.velocity: d["velocity"] = [round(x, 4) for x in self.velocity]
            if self.vel_spread: d["velocitySpread"] = round(self.vel_spread, 4)
            d["emission"] = {"count": self.emit_count, "stream": self.emit_stream,
                             "bursts": self.emit_bursts,
                             "interval": self.emit_interval}
        if self.alpha_curve:
            d["alphaCurve"] = self.alpha_curve.to_dict()
        if self.slots:
            d["curves"] = {self.slot_name(i): c.to_dict()
                           for i, c in sorted(self.slots.items())}
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


@dataclass
class Effect:
    path: str
    version: Tuple[int, int, int, int]
    duration: int
    speed: float
    textures: List[str]
    models: List[str]
    strings: List[str]
    chunks: List[Chunk]
    roots: List[Chunk]
    pool_used: int
    unknown: Dict[str, int]

    def emitters(self) -> List[Chunk]:
        return [c for c in self.chunks if c.is_emitter]

    def to_dict(self):
        return {
            "file": os.path.basename(self.path),
            "version": list(self.version),
            "durationFrames": self.duration,
            "speed": self.speed,
            "textures": self.textures,
            "models": self.models,
            "poolUsed": self.pool_used,
            "unknownHeaderFields": self.unknown,
            "tree": [r.to_dict() for r in self.roots],
        }


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------
def _u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def _u64(d, o):
    return struct.unpack_from("<Q", d, o)[0]


def _f32v(d, o, n):
    return list(struct.unpack_from("<%df" % n, d, o))


def _finite(x: float) -> bool:
    return x == 0.0 or (1e-12 < abs(x) < 1e9)


class _Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.strtab = _u32(data, HDR_STRTAB)
        self.pool = _u32(data, HDR_POOL)
        self.pool_used = _u32(data, HDR_POOL_USED)
        # the resource descriptor arrays live at the very end of the used pool;
        # everything before them is curve / child-list data.
        tbl = struct.unpack_from("<8I", data, HDR_RESTABLE)
        live = [x for x in tbl if x != 0xFFFFFFFF]
        self.data_end = min(live) if live else self.pool_used
        self.restable = tbl

    def string(self, rel: int) -> Optional[str]:
        # rel 0 is always the asset-root path string ("D:/database/latest/",
        # "../", ...) which every object carries as a default -- not a real
        # resource reference.
        if rel == 0xFFFFFFFF or rel is None or rel == 0:
            return None
        o = self.strtab + rel
        if not (self.strtab <= o < self.pool):
            return None
        e = self.d.index(b"\0", o)
        return self.d[o:e].decode("utf-8", "replace")

    def read_curve(self, pool_off: int, count: int, dim: int, allow_partial_domain=False) -> Optional[Curve]:
        """Read and validate `count` keys of dimension `dim` at pool_off."""
        stride = CURVE_STRIDE[dim]
        if pool_off % 4 or count < 1 or pool_off + count * stride > self.data_end:
            return None
        keys, tangents = [], []
        prev = -1e9
        for i in range(count):
            b = self.pool + pool_off + stride * i
            interp = list(struct.unpack_from("<%dI" % dim, self.d, b))
            if any(x > 3 for x in interp):
                return None
            fl = struct.unpack_from("<%df" % (3 * dim + 1), self.d, b + 4 * dim)
            if not all(_finite(x) for x in fl[:-1]):
                return None
            t = fl[-1]
            if not (-1e-6 <= t <= 1.0001) or t < prev - 1e-6:
                return None
            prev = t
            keys.append((t, list(fl[2 * dim:3 * dim]), interp))
            tangents.append((list(fl[:dim]), list(fl[dim:2 * dim])))
        # a real curve starts at t=0 and (if it has >1 key) ends at t=1
        if not allow_partial_domain and abs(keys[0][0]) > 1e-6:
            return None
        if not allow_partial_domain and count > 1 and abs(keys[-1][0] - 1.0) > 1e-3:
            return None
        return Curve(dim, pool_off, keys, tangents)


def parse(path: str) -> Effect:
    with open(path, "rb") as fh:
        d = fh.read()
    if d[:4] != MAGIC:
        raise ValueError("%s: not an IBMB file" % path)
    r = _Reader(d)

    ver = tuple(d[4:8])
    duration = _u32(d, HDR_DURATION)
    speed = struct.unpack_from("<f", d, HDR_SPEED)[0]
    ntex, nmodel = _u32(d, HDR_TEX_COUNT), _u32(d, HDR_MODEL_COUNT)

    def res_list(slot, n):
        off = r.restable[slot]
        if off == 0xFFFFFFFF or n == 0:
            return []
        return [r.string(_u32(d, r.pool + off + 8 * i)) for i in range(n)]

    textures = res_list(0, ntex)
    models = res_list(1, nmodel)

    strings = []
    i = r.strtab
    while i < r.pool and d[i] != 0xBA:
        e = d.index(b"\0", i)
        strings.append(d[i:e].decode("utf-8", "replace"))
        i = e + 1

    # ---- walk the flat chunk stream --------------------------------------
    chunks: List[Chunk] = []
    o = CHUNKS_START
    while o < r.strtab:
        t, sz = struct.unpack_from("<II", d, o)
        if sz < 8 or o + sz > len(d):
            raise ValueError("%s: bad chunk at 0x%x" % (path, o))
        c = Chunk(index=len(chunks), offset=o, type=t, size=sz)
        _read_chunk_scalars(r, d, c)
        chunks.append(c)
        o += sz
    if o != r.strtab:
        raise ValueError("%s: chunk stream overruns string table" % path)

    _resolve_curves(r, d, chunks)

    # ---- rebuild the tree: preorder, each node consumes childCount subtrees
    pos = 0

    def build():
        nonlocal pos
        c = chunks[pos]
        pos += 1
        for _ in range(c.child_count):
            if pos >= len(chunks):
                break
            c.children.append(build())
        return c

    roots = []
    while pos < len(chunks):
        roots.append(build())

    return Effect(path=path, version=ver, duration=duration, speed=speed,
                  textures=textures, models=models, strings=strings,
                  chunks=chunks, roots=roots, pool_used=r.pool_used,
                  unknown={"h08": _u32(d, 0x08), "h4C": _u32(d, 0x4C)})


def _read_chunk_scalars(r: _Reader, d: bytes, c: Chunk):
    o, t, sz = c.offset, c.type, c.size
    c.res1 = r.string(_u32(d, o + OBJ_RES1)) if sz > OBJ_RES1 + 8 else None
    c.res2 = r.string(_u32(d, o + OBJ_RES2)) if sz > OBJ_RES2 + 8 else None

    if t == T_NODE:
        c.child_count = _u32(d, o + OBJ_CHILD_COUNT)
        c.delay = _u32(d, o + NODE_DELAY)
        c.duration = _u32(d, o + NODE_DURATION)
        c.child_pool = _u32(d, o + OBJ_CHILD_ARRAY)
        c.node_scale = _f32v(d, o + NODE_SCALE, 3)
        c.node_rot = _f32v(d, o + NODE_ROT, 3)
        c.rot_range = _f32v(d, o + NODE_ROT_RANGE, 3)
        c.emit_count = _u32(d, o + NODE_EMIT_COUNT)
        c.emit_stream = _u32(d, o + NODE_EMIT_STREAM)
        c.emit_bursts = _u32(d, o + NODE_EMIT_BURSTS)
        c.emit_interval = _u32(d, o + NODE_EMIT_INTERVAL)
        c.emit_step = _f32v(d, o + NODE_EMIT_STEP, 1)[0]
        c.emit_mode = _u32(d, o + NODE_EMIT_MODE)
        c.emit_box = _f32v(d, o + NODE_EMIT_BOX, 3)
        if sz > NODE_VEL_SPREAD + 4:
            v = _f32v(d, o + NODE_VELOCITY, 3)
            c.velocity = v if v and any(abs(x) < 1e5 and x for x in v) else None
            sp = _f32v(d, o + NODE_VEL_SPREAD, 1)
            c.vel_spread = sp[0] if sp and abs(sp[0]) < 1e5 else 0.0
    if t in EMIT_UV_MODE and sz > EMIT_UV_MODE[t] + 4:
        v = _u32(d, o + EMIT_UV_MODE[t])
        c.uv_mode = v if v < 8 else 1
    if t in UV_CHANNEL_SELECTORS:
        for channel, selector in enumerate(UV_CHANNEL_SELECTORS[t]):
            base = UV_CHANNEL_BASE[t][channel]
            if sz < base + 216:
                continue
            params = {"pivot": _f32v(d, o + base - 12, 3)}
            for component, name in enumerate(("translation", "rotation", "scaling")):
                module = {"mode": _u32(d, o + selector + 4 * component),
                          "curveSlot": 6 + channel * 6 + component * 2}
                for field_name, delta in (("base", 0), ("variance", 12),
                                          ("velocity", 24), ("velocityVariance", 36),
                                          ("acceleration", 48), ("accelerationVariance", 60)):
                    module[field_name] = _f32v(d, o + base + component * 72 + delta, 3)
                params[name] = module
            c.uv_channels.append(params)
    if t in TEXTURE_MATERIAL_FIELDS:
        mode, wrap, filtering, cs, cb, slots, ats, atb, atc, mid = TEXTURE_MATERIAL_FIELDS[t]
        material_mode = _u32(d, o + mode)
        material = {"mode": material_mode, "primary": c.res2 if t == T_EMIT_MODEL else c.res1,
                    "wrap": [_u32(d, o + wrap + 4 * i) for i in range(2)],
                    "filter": [_u32(d, o + filtering + 4 * i) for i in range(2)],
                    "color": [], "alpha": [],
                    "distortionMid": [v / 255. for v in _f32v(d, o + mid, 3)]}
        if material_mode:
            material["secondary"] = r.string(_u32(d, o + 0x60)) if t == T_EMIT_MODEL else c.res2
        for i in range(2):
            material["color"].append({"mode": _u32(d, o + cs[i]), "base": _f32v(d, o + cb[i], 3),
                                      "variance": _f32v(d, o + cb[i] + 16, 3), "curveSlot": slots[i]})
            material["alpha"].append({"mode": _u32(d, o + ats[i]), "base": _f32v(d, o + atb[i], 1)[0],
                                      "variance": _f32v(d, o + atb[i] + 4, 1)[0]})
            cnt, _flags, po, hi = struct.unpack_from("<4I", d, o + atc[i])
            if hi == 0 and 0 < cnt < 5000:
                c.pending.append(("texture_alpha", i, po, cnt, 1))
        c.texture_material = material
    if t in EMIT_UV_TILE and sz > EMIT_UV_TILE[t] + 12:
        cnt, ptr, hi = struct.unpack_from("<3I", d, o + EMIT_UV_TILE[t])
        if cnt == 1 and hi == 0 and ptr % 4 == 0 and ptr + 32 <= r.data_end:
            u, v = struct.unpack_from("<2f", d, r.pool + ptr + 12)
            if 0.5 <= u <= 8.0 and 0.5 <= v <= 8.0:
                c.uv_tile = [u, v]
    if t in EMIT_ENABLE and sz > EMIT_ENABLE[t] + 4:
        c.enabled = (_u32(d, o + EMIT_ENABLE[t]) & 0xFF) != 0
    if t in EMIT_LIFE and sz > EMIT_LIFE[t]:
        c.life = _u32(d, o + EMIT_LIFE[t])
    if t in EMIT_DELAY and sz >= EMIT_DELAY[t] + 8:
        c.emitter_delay, c.emitter_delay_variance = struct.unpack_from("<2i", d, o + EMIT_DELAY[t])
    if t in EMIT_BLEND and sz > EMIT_BLEND[t]:
        c.blend = _u32(d, o + EMIT_BLEND[t])
    if t in EMIT_COLOR and sz > EMIT_COLOR[t] + 16:
        c.color = _f32v(d, o + EMIT_COLOR[t], 4)
        if t in EMIT_COLOR_VAR and sz > EMIT_COLOR_VAR[t] + 16:
            c.color_var = _f32v(d, o + EMIT_COLOR_VAR[t], 4)
    if t == T_EMIT_A and sz >= 0x198:
        # QuadSetupper::AssignModule selects color4 from +0x194. Its
        # per-corner RGB vectors are independent of texture tint at +0xF8.
        # Native vertex order: top-left, bottom-left, bottom-right, top-right.
        c.quad_color_mode = _u32(d, o + 0x194)
        c.quad_colors = [_f32v(d, o + offset, 3)
                         for offset in (0x68, 0xA8, 0xC8, 0x88)]
    if t == T_EMIT_B and sz >= 0x134:
        # ParticleSetupper::AssignModule 0x2909D34 selects native color1
        # independently from primary texture RGB at +0x98. Const/Curve
        # wrappers 0x2908584/0x29085A4 use +0x68 and Curve<3> +0x660.
        c.particle_color_mode = _u32(d, o + 0x130)
        c.particle_color_base = _f32v(d, o + 0x68, 3)
        c.particle_color_variance = _f32v(d, o + 0x78, 3)
    if t in EMIT_ALPHA_MODE:
        # The make-vertex table at 0x38F25B0 is 0 no module, 1 Zero,
        # 2 Const, 3 Curve, 4 RandomCurve, 5/6 CurveOffset variants.
        # Although mode1 has no initializer, its draw module writes zero.
        c.quad_alpha_mode = _u32(d, o + EMIT_ALPHA_MODE[t])
        c.quad_alpha_base = _f32v(d, o + EMIT_ALPHA_BASE[t], 1)[0]
        c.alpha_variance = _f32v(d, o + EMIT_ALPHA_BASE[t] + 4, 1)[0]
        c.parent_alpha_weight = _f32v(d, o + ALPHA_PARENT_WEIGHT[t], 1)[0]
        if t in ALPHA_PARENT_OPERATION:
            c.parent_alpha_operation = _u32(d, o + ALPHA_PARENT_OPERATION[t])
    if t == T_EMIT_MODEL and sz >= 0x18C:
        # ModelSetupper selects primary texture RGB independently of color1:
        # selector +188; Const reads+A8, Curve reads+6B0 (native Curve<3>).
        c.texture_color_scale1_mode = _u32(d, o + 0x188)
        c.texture_color_scale1_base = _f32v(d, o + 0xA8, 3)
    if t in EMIT_BASE_SCALE and sz > EMIT_BASE_SCALE[t] + 12:
        c.base_scale = _f32v(d, o + EMIT_BASE_SCALE[t], 3)
    if t in SCALE_MODE and sz >= SCALE_BASE[t] + 72:
        c.scale_mode = _u32(d, o + SCALE_MODE[t])
        for field_name, delta in (('scale_variance', 12), ('scale_velocity', 24),
                                  ('scale_velocity_variance', 36), ('scale_acceleration', 48),
                                  ('scale_acceleration_variance', 60)):
            setattr(c, field_name, _f32v(d, o + SCALE_BASE[t] + delta, 3))
    if t in ROTATION_MODE and sz >= ROTATION_BASE[t] + 72:
        c.rotation_mode = _u32(d, o + ROTATION_MODE[t])
        for field_name, delta in (('rotation_base', 0), ('rotation_variance', 12),
                                  ('rotation_velocity', 24), ('rotation_velocity_variance', 36),
                                  ('rotation_acceleration', 48), ('rotation_acceleration_variance', 60)):
            setattr(c, field_name, _f32v(d, o + ROTATION_BASE[t] + delta, 3))
    if t in TRANSLATION_MODE and sz >= TRANSLATION_BASE[t] + 72:
        c.translation_mode = _u32(d, o + TRANSLATION_MODE[t])
        for field_name, delta in (('translation_base', 0), ('translation_variance', 12),
                                  ('translation_velocity', 24), ('translation_velocity_variance', 36),
                                  ('translation_acceleration', 48), ('translation_acceleration_variance', 60)):
            setattr(c, field_name, _f32v(d, o + TRANSLATION_BASE[t] + delta, 3))

    # alpha-over-life curve (always dim 1)
    if t in EMIT_ALPHA_CURVE and sz > EMIT_ALPHA_CURVE[t] + 16:
        cnt, _flags, po, hi = struct.unpack_from("<4I", d, o + EMIT_ALPHA_CURVE[t])
        if hi == 0 and 0 < cnt < 5000:
            c.pending.append(("alpha", 0, po, cnt, 1))

    # tail curve-slot array
    if t in EMIT_SLOTS:
        base, n = EMIT_SLOTS[t]
        for i in range(n):
            k = base + 16 * i
            if k + 16 > sz:
                break
            cnt, _flags, po, hi = struct.unpack_from("<4I", d, o + k)
            if hi != 0 or cnt == 0 or cnt > 5000:
                continue
            # Native translation/rotation entry points take Curve<3>, including constant
            # one-key curves authored at an interior normalized time.
            native3 = ((t in ROTATION_MODE and i in range(6))
                       or (t == T_EMIT_A and i == 19)
                       or (t == T_EMIT_B and not c.res1 and not c.res2 and i == 19)
                       or (t == T_EMIT_MODEL and i == 20)
                       or (t in UV_CHANNEL_SELECTORS and i in range(6, 18))
                       or (t in TEXTURE_MATERIAL_FIELDS and i in TEXTURE_MATERIAL_FIELDS[t][5]))
            c.pending.append(("slot", i, po, cnt, 3 if native3 else None))


def _resolve_curves(r: _Reader, d: bytes, chunks: List[Chunk]):
    """Assign pool ranges to curves.

    The pool is a tightly packed arena holding (a) node child-pointer arrays
    and (b) keyframe arrays.  A curve reference only stores a key *count*, not
    the key width, so the width has to be inferred.  Claiming the child arrays
    first and then taking the widest non-overlapping reading resolves this:
    it tiles 93-99% of the pool byte-exactly on every file tested.
    """
    claimed = bytearray(max(r.data_end, 1))

    def free(a, n):
        return a >= 0 and a + n <= len(claimed) and not any(claimed[a:a + n])

    def claim(a, n):
        for i in range(a, a + n):
            claimed[i] = 1

    # child-pointer arrays: 8 bytes per child
    for c in chunks:
        if c.type == T_NODE and c.child_count:
            n = c.child_count * 8
            if free(c.child_pool, n):
                claim(c.child_pool, n)

    cands = []
    for c in chunks:
        for kind, idx, po, cnt, forced in c.pending:
            dims = (forced,) if forced else (3, 4, 2, 1)
            for dim in dims:
                nbytes = cnt * CURVE_STRIDE[dim]
                cands.append((nbytes, c, kind, idx, po, cnt, dim))
    cands.sort(key=lambda x: (x[1].type in ROTATION_MODE and x[2] == 'slot' and x[3] in range(6), x[0]), reverse=True)

    done = set()
    for nbytes, c, kind, idx, po, cnt, dim in cands:
        key = (id(c), kind, idx)
        if key in done or not free(po, nbytes):
            continue
        # Native Curve<3> transform/color modules and Curve<1> alpha modules
        # clamp outside their authored key domain. A final key before 1.0 (or
        # a lone interior key) is valid, not an empty/dormant curve. Rain & Fina
        # node40's 81→206 scale ends at .811; discarding it made the LB tiny.
        native_curve = kind in ('alpha', 'texture_alpha') or (kind == 'slot' and (
            c.type in ROTATION_MODE and idx in range(6) or c.type == T_EMIT_A and idx == 19
            or c.type == T_EMIT_MODEL and idx == 20
            or c.type in UV_CHANNEL_SELECTORS and idx in range(6, 18)
            or c.type in TEXTURE_MATERIAL_FIELDS and idx in TEXTURE_MATERIAL_FIELDS[c.type][5]))
        cur = r.read_curve(po, cnt, dim, allow_partial_domain=native_curve)
        if not cur:
            continue
        claim(po, nbytes)
        done.add(key)
        if kind == "alpha":
            c.alpha_curve = cur
        elif kind == "texture_alpha":
            c.texture_alpha_curves[idx] = cur
        else:
            c.slots[idx] = cur


# ---------------------------------------------------------------------------
# approximate simulation -> per-frame sprite list
# ---------------------------------------------------------------------------
@dataclass
class _EmitterCtx:
    emitter: Chunk
    chain: List[Chunk]     # node ancestors, root first
    start: int             # absolute first frame the emitter is live
    span: int              # frames over which it keeps emitting


def _collect(eff: Effect) -> List[_EmitterCtx]:
    out = []

    def rec(c: Chunk, chain: List[Chunk], start: int, span: int):
        if c.is_node:
            start = start + c.delay
            span = c.duration if c.duration else span
            chain = chain + [c]
            for ch in c.children:
                rec(ch, chain, start, span)
        elif c.is_emitter:
            if c.enabled:
                out.append(_EmitterCtx(c, chain, start, span or eff.duration))
        else:
            for ch in c.children:
                rec(ch, chain, start, span)

    for root in eff.roots:
        rec(root, [], 0, eff.duration)
    return out


def _xy(v: Optional[List[float]], default=1.0) -> Tuple[float, float]:
    """Read a scale-ish float3 as a 2D (width, height) factor.

    The files use two conventions in the same field: a genuine non-uniform
    scale (340, 280, 1) and a "uniform, only x is meaningful" form such as
    (25, 1, 1) or (1, 0, 0).  Treating y as uniform-with-x when it is exactly
    0 or exactly 1-while-x-differs reproduces both correctly on every case
    checked by hand.  MEDIUM confidence."""
    if not v:
        return default, default
    x = v[0]
    y = v[1] if len(v) > 1 else x
    if y == 0.0 or (y == 1.0 and x != 1.0):
        y = x
    return x, y


def _curve_peak(cur: Curve) -> float:
    return max((abs(v[0]) for _t, v, _i in cur.keys), default=0.0)


def _is_absolute(cur: Curve) -> bool:
    """Scale-slot reading: absolute world size, or a 0..1-ish envelope on the
    base size?  A peak above 2 says absolute -- except for the common template
    `2.5 -> 0.5 -> 0.25`, a pop-in envelope that ends well under 1."""
    if not cur.keys:
        return False
    peak = _curve_peak(cur)
    last = abs(cur.keys[-1][1][0])
    return peak > 2.0 and not (peak <= 3.0 and last <= 1.0)


# When a node's scale curve *and* the emitter's own scale curve are both
# absolute world sizes (608 of ~30,000 emitters in a corpus sample; the fireball
# groups of bm_2020_fire3 are the textbook case: node 90 -> 197, emitter
# 90 -> 197), multiplying them gives tens of thousands of units.  They cannot
# both apply.  Which one the runtime uses is not decoded; "node" (the artist's
# transform animation wins, the emitter keeps its template default) is the
# reading that matches the authoring workflow, "emitter" is the alternative.
ABS_SCALE_RULE = "node"


class _CanonicalVariation:
    """Stable instance samples, with native ranges but no RNG-stream claim."""
    def __init__(self, seed, source):
        self.seed = seed
        self.source = os.path.basename(source)
        self.instances = {}

    def instance(self, identity):
        identity = tuple(identity)
        if identity not in self.instances:
            self.instances[identity] = _TransformVariation(self, identity)
        return self.instances[identity]


class _TransformVariation:
    def __init__(self, owner, identity):
        self.owner, self.identity, self.cache = owner, identity, {}

    def sample(self, parameter, base, spread, *, uniform=False, nonnegative=False):
        if parameter not in self.cache:
            key = [self.owner.seed, self.owner.source, self.identity, parameter]
            digest = hashlib.sha256(json.dumps(key, separators=(',', ':')).encode('utf8')).digest()
            values = []
            # Texture alpha is a scalar; transforms and RGB are float3. Keep
            # the existing vector samples unchanged instead of padding alpha.
            for axis in range(1 if uniform else len(base)):
                # Native generators construct [0,1) from 23 mantissa bits.
                u = (int.from_bytes(digest[axis*4:axis*4+4], 'little') >> 9) / 8388608.
                radius = spread[axis] if spread else 0.
                value = base[axis] - radius + 2. * radius * u
                values.append(max(0., value) if nonnegative else value)
            self.cache[parameter] = tuple(values * 3 if uniform else values)
        return list(self.cache[parameter])

    def delay(self, base, spread):
        """Native generator delay uses an integer, half-open ±range."""
        if 'emitter_delay' not in self.cache:
            key = [self.owner.seed, self.owner.source, self.identity, 'emitter_delay']
            word = int.from_bytes(hashlib.sha256(json.dumps(key, separators=(',', ':'))
                                                .encode('utf8')).digest()[:4], 'little')
            self.cache['emitter_delay'] = max(0, base - spread + word % (2 * spread)) if spread > 0 else max(0, base)
        return self.cache['emitter_delay']


def _node_variation(variation, chain, instance_keys, node_index, copy_index):
    if variation is None or instance_keys is None:
        return None
    lineage = tuple((node.index, ordinal) for node, ordinal
                    in zip(chain[:node_index+1], instance_keys[:node_index+1]))
    return variation.instance((('copy', copy_index), *lineage))


def _emitter_variation(variation, ctx, instance_keys, copy_index):
    if variation is None or instance_keys is None:
        return None
    lineage = tuple((n.index, ordinal) for n, ordinal in zip(ctx.chain, instance_keys))
    return variation.instance((('copy', copy_index), *lineage, ('emitter', ctx.emitter.index)))


def _native_scale(chunk: Chunk, u: float, age: float, variation=None):
    """Confirmed native scaling modes; None keeps unknown modes explicit.

    The +14 variants use only X for all three axes. Curves contain absolute
    local scaling, not envelopes inferred from their value ranges. Random
    curve modes retain their existing limits. Optional canonical variation
    samples active constant/velocity/acceleration payloads once per instance.
    """
    mode = chunk.scale_mode
    if mode is None:
        return None
    uniform = mode >= 15
    kind = mode - 14 if uniform else mode
    if kind not in (1, 2, 3, 4, 5, 6):
        return None
    base = list((chunk.node_scale if chunk.is_node else chunk.base_scale) or [1., 1., 1.])
    if kind == 1:
        values = [1., 1., 1.]
    elif kind in (5, 6):
        curve = chunk.slots.get(SLOT_SCALE)
        values = curve.sample(u) if curve else [1., 1., 1.]
    else:
        if variation is not None:
            base = variation.sample('scale_base', base, chunk.scale_variance,
                                    uniform=uniform, nonnegative=True)
        values = base
        if kind in (3, 4):
            velocity = chunk.scale_velocity or [0., 0., 0.]
            acceleration = chunk.scale_acceleration if kind == 4 else None
            if variation is not None:
                velocity = variation.sample('scale_velocity', velocity, chunk.scale_velocity_variance, uniform=uniform)
                if kind == 4:
                    acceleration = variation.sample('scale_acceleration', acceleration or [0., 0., 0.],
                                                    chunk.scale_acceleration_variance, uniform=uniform)
            values = [value + velocity[i] * max(0., age)
                      + .5 * (acceleration[i] if acceleration else 0.) * max(0., age)**2
                      for i, value in enumerate(base)]
    if uniform:
        values = [values[0]] * 3
    return [max(0., value) for value in values]


def _curve_displacement(curve: Curve, u: float, age: float, cache=None):
    """Integrate per-frame velocity samples using the particle's birth phase."""
    if age <= 0:
        return [0., 0., 0.]
    whole = int(age)
    fraction = age - whole
    clock = u / age
    key = (id(curve), round(clock, 12), round(fraction, 9))
    sums = cache.get(key) if cache is not None else None
    if sums is None:
        sums = [[fraction * value for value in curve.sample(clock * fraction)]]
        if cache is not None:
            cache[key] = sums
    for frame in range(len(sums), whole + 1):
        velocity = curve.sample(clock * (fraction + frame))
        sums.append([sums[-1][i] + velocity[i] for i in range(3)])
    return list(sums[whole])


def _native_translation(chunk: Chunk, u: float, age: float, cache=None, variation=None):
    """Selected local displacement in source units; no guessed axis remapping.

    The GL tables select Zero/Const/Velocity/AccelVelocity at 1/2/3/4,
    absolute position curves at 5/6, and velocity curves at 7/8. Random
    variants retain the authored mean until native per-key RNG is ported.
    Their constant base/velocity payloads remain dormant where appropriate.
    """
    mode = chunk.translation_mode
    if mode not in range(9):
        return None
    if mode in (0, 1):
        return [0., 0., 0.]
    if mode in (5, 6):
        curve = chunk.slots.get(SLOT_TRANSLATE)
        return curve.sample(u) if curve else [0., 0., 0.]
    base = list(chunk.translation_base or [0., 0., 0.])
    if variation is not None and mode in (2, 3, 4):
        base = variation.sample('translation_base', base, chunk.translation_variance)
    age = max(0., age)
    if mode in (3, 4):
        velocity = chunk.translation_velocity or [0., 0., 0.]
        acceleration = chunk.translation_acceleration if mode == 4 else None
        if variation is not None:
            velocity = variation.sample('translation_velocity', velocity, chunk.translation_velocity_variance)
            if mode == 4:
                acceleration = variation.sample('translation_acceleration', acceleration or [0., 0., 0.],
                                                chunk.translation_acceleration_variance)
        return [base[i] + velocity[i] * age
                + .5 * (acceleration[i] if acceleration else 0.) * age**2
                for i in range(3)]
    if mode in (7, 8):
        curve = chunk.slots.get(SLOT_TRANSLATE_VAR)
        if curve:
            movement = _curve_displacement(curve, u, age, cache)
            return [base[i] + movement[i] for i in range(3)]
    return base


def _native_uv_channel(chunk: Chunk, channel: int, age: float, *, variation=None, cache=None):
    """Evaluate one texture's authored UV controls, independently of geometry.

    `channel` is zero-based; age is the emitter instance's age in source
    frames. Translation uses texture periods and rotation uses degrees.
    These are controls for the native inverse UV transform, not a direct
    source-coordinate matrix: the renderer must apply pivot/inverse scale
    and rotation before texture wrapping. In particular, UV scaling is not
    particle scaling and its signed values are never clamped to zero.

    Random-curve modes 5/7 remain explicit unsupported modules. Constant
    variance uses the existing fixed instance sampler when supplied. This
    keeps siblings distinct without changing a particle's offset each frame.
    """
    if channel < 0 or channel >= len(chunk.uv_channels):
        raise IndexError('texture UV channel is unavailable')
    params = chunk.uv_channels[channel]
    age = max(0., float(age))
    u = age / max(1., float(chunk.life))
    result = {"pivot": list(params["pivot"]), "unsupported": []}
    for name in ("translation", "rotation", "scaling"):
        module = params[name]
        mode = module["mode"]
        neutral = [1., 1., 1.] if name == "scaling" else [0., 0., 0.]
        if mode == 0:
            result[name] = neutral
            continue
        if mode not in (1, 2, 3, 4, 6):
            result[name] = neutral
            result["unsupported"].append({"module": name, "mode": mode})
            continue
        if mode == 4:
            curve = chunk.slots.get(module["curveSlot"])
            result[name] = curve.sample(u) if curve else neutral
            if curve is None:
                result["unsupported"].append({"module": name, "mode": mode, "reason": "missing curve"})
            continue

        def sampled(field_name, variance_name):
            values = list(module[field_name])
            if variation is not None:
                values = variation.sample(f'uv{channel + 1}_{name}_{field_name}', values,
                                          module[variance_name])
            return values

        values = sampled("base", "variance")
        if mode in (2, 3):
            velocity = sampled("velocity", "velocityVariance")
            acceleration = sampled("acceleration", "accelerationVariance") if mode == 3 else [0., 0., 0.]
            values = [values[i] + velocity[i] * age + .5 * acceleration[i] * age * age
                      for i in range(3)]
        elif mode == 6:
            curve = chunk.slots.get(module["curveSlot"] + 1)
            if curve:
                movement = _curve_displacement(curve, u, age, cache)
                values = [values[i] + movement[i] for i in range(3)]
        result[name] = values
    return result


def _native_texture_material(chunk: Chunk, u: float, *, variation=None):
    """Selected source shader inputs for primary/secondary texture sampling.

    Mode 0 samples primary only, 1 multiplies complete primary RGBA by the
    secondary alpha, 2 adds secondary RGB*alpha without changing alpha, and
    6 uses the secondary texture as an RG distortion map and alpha mask.
    Those equations are copied from the packaged native GLSL; other modes
    remain explicit until their shader paths are implemented by the adapter.
    """
    params = chunk.texture_material
    if params is None:
        return None
    result = {k: params[k] for k in ("mode", "primary", "wrap", "filter", "distortionMid")}
    if params.get("secondary") and params["mode"]:
        result["secondary"] = params["secondary"]
    result["unsupported"] = []
    if params["mode"] not in (0, 1, 2, 6):
        result["unsupported"].append({"module": "material", "mode": params["mode"]})
    for channel in range(2):
        rgb = [1., 1., 1.]
        alpha = 1.
        # A dormant secondary color curve must not create a render dependency.
        if channel == 0 or "secondary" in result:
            color = params["color"][channel]
            if color["mode"] == 1:
                rgb = list(color["base"])
                if variation is not None:
                    rgb = variation.sample(f'texture{channel + 1}_color', rgb, color["variance"])
            elif color["mode"] == 2:
                curve = chunk.slots.get(color["curveSlot"])
                if curve:
                    rgb = curve.sample(u)
                else:
                    result["unsupported"].append({"module": f'texture{channel + 1}_color', "mode": 2, "reason": "missing curve"})
            elif color["mode"] != 0:
                result["unsupported"].append({"module": f'texture{channel + 1}_color', "mode": color["mode"]})
            at = params["alpha"][channel]
            if at["mode"] == 1:
                alpha = at["base"]
                if variation is not None:
                    alpha = variation.sample(f'texture{channel + 1}_alpha', [alpha], [at["variance"]])[0]
                alpha = max(0., alpha)
            elif at["mode"] == 2:
                curve = chunk.texture_alpha_curves.get(channel)
                if curve:
                    alpha = max(0., curve.sample(u)[0])
                else:
                    result["unsupported"].append({"module": f'texture{channel + 1}_alpha', "mode": 2, "reason": "missing curve"})
            elif at["mode"] != 0:
                result["unsupported"].append({"module": f'texture{channel + 1}_alpha', "mode": at["mode"]})
        result[f'colorScale{channel + 1}'] = [*rgb, alpha]
    return result


def _native_rotation(chunk: Chunk, u: float, age: float, variation=None):
    """Selected rotation module, in signed source degrees.

    GL 9.1.0 rotation modules 1/2/3 initialize from base/velocity/acceleration;
    4 samples an absolute angle curve, and 6 integrates an angular-velocity
    curve (slot 3) from the initial angle. Random curve variants remain
    unsupported. Canonical constant/velocity/acceleration variation stays in
    authored degrees; no scaling-style zero clamp applies.
    """
    mode = chunk.rotation_mode
    if mode not in (0, 1, 2, 3, 4, 6):
        return None
    if mode == 0:
        return [0., 0., 0.]
    base = list(chunk.rotation_base or chunk.node_rot or [0., 0., 0.])
    if variation is not None and mode in (1, 2, 3):
        base = variation.sample('rotation_base', base, chunk.rotation_variance)
    if mode == 4:
        curve = chunk.slots.get(SLOT_ROTATE)
        return curve.sample(u) if curve else [0., 0., 0.]
    age = max(0., age)
    if mode in (2, 3):
        velocity = chunk.rotation_velocity or [0., 0., 0.]
        acceleration = chunk.rotation_acceleration if mode == 3 else None
        if variation is not None:
            velocity = variation.sample('rotation_velocity', velocity, chunk.rotation_velocity_variance)
            if mode == 3:
                acceleration = variation.sample('rotation_acceleration', acceleration or [0., 0., 0.],
                                                chunk.rotation_acceleration_variance)
        return [base[i] + velocity[i] * age
                + .5 * (acceleration[i] if acceleration else 0.) * age**2
                for i in range(3)]
    if mode == 6:
        # Native InitModuleOf[6] is InitConst: the stored constant velocity
        # is dormant. AddValueCurve samples slot 3 at each update's new age.
        curve = chunk.slots.get(SLOT_ROTATE_VAR)
        if curve and age:
            whole = int(age)
            fraction = age - whole
            if fraction:
                value = curve.sample(u * fraction / age)
                base = [base[i] + fraction * value[i] for i in range(3)]
            for frame in range(1, whole + 1):
                value = curve.sample(u * (fraction + frame) / age)
                base = [base[i] + value[i] for i in range(3)]
    return base


def _accumulate_rotation(rot, mirror, tilt, angles):
    """Existing 2D projection boundary; same-axis cancellation is exact.

    Mixed-axis Euler composition, billboard modes and full parent matrices
    still require a native transform adapter. Keep those limits explicit.
    """
    rot += angles[2]
    tilt = list(tilt)
    if abs(abs(angles[1]) % 360.0 - 180.0) < 1.0:
        mirror = not mirror
    else:
        tilt[1] += angles[1]
    tilt[0] += angles[0]
    return rot, mirror, tilt


def _local_point_matrix(angles, scale):
    """Native locator basis: Ry * Rx * Rz * diag(local scale).

    GL transform_locator::update::Default (0x28af220) builds these columns
    at 0x28af558–0x28af690 and multiplies by the inherited full matrix.
    Mesh projection still has its separate documented approximation.
    """
    x, y, z = map(math.radians, angles)
    sx, cx = math.sin(x), math.cos(x)
    sy, cy = math.sin(y), math.cos(y)
    sz, cz = math.sin(z), math.cos(z)
    rows = ((cy*cz + sy*sx*sz, -cy*sz + sy*sx*cz, sy*cx),
            (cx*sz, cx*cz, -sx),
            (-sy*cz + cy*sx*sz, sy*sz + cy*sx*cz, cy*cx))
    return tuple(tuple(row[j] * scale[j] for j in range(3)) for row in rows)


def _point_in_frame(matrix, point):
    return [sum(matrix[i][j] * point[j] for j in range(3)) for i in range(3)]


def _compose_point_frames(parent, local):
    return tuple(tuple(sum(parent[i][k] * local[k][j] for k in range(3))
                       for j in range(3)) for i in range(3))


def _node_transform(chain: List[Chunk], frame: int, effect_dur: int, instance_starts=None,
                    translation_cache=None, return_matrix=False, variation=None,
                    instance_keys=None, copy_index=0):
    """Accumulate ancestor node translate / scale / rotate at `frame`.

    Returns (pos, scale2, rotZdeg, mirrorX, tiltXY, absScale).  A static Y
    rotation of ~180 deg is a horizontal mirror, which a 2D renderer expresses
    as flipX + negated x -- see `sm_0071_Carbuncle1_back_reverse.bmb`; any
    other static X / Y rotation is returned as `tiltXY` for the mesh
    rasteriser.  `absScale` is True when an ancestor's scale curve was read as
    an absolute world size (see ABS_SCALE_RULE)."""
    pos = [0.0, 0.0, 0.0]
    scale = [1.0, 1.0]
    rot = 0.0
    mirror = False
    tilt = [0.0, 0.0]
    abs_scale = False
    point_matrix = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))
    start = 0                       # a node's delay is relative to its parent's start
    for node_index, n in enumerate(chain):
        samples = _node_variation(variation, chain, instance_keys, node_index, copy_index)
        start = instance_starts[node_index] if instance_starts is not None else start + n.delay
        dur = n.duration or effect_dur
        t = 0.0 if dur <= 0 else min(1.0, max(0.0, (frame - start) / dur))
        # AddValueCurve integrates the original lifetime clock even if a
        # descendant outlasts its parent. Curve.sample clamps the domain.
        rotation_u = max(0., (frame - start) / dur) if dur > 0 else 0.
        angles = _native_rotation(n, rotation_u, frame - start, samples)
        if angles is None:
            angles = list(n.node_rot or [0., 0., 0.])
            cur = n.slots.get(SLOT_ROTATE)
            if cur:
                value = cur.sample(t)
                angles[2] += value[-1] if value else 0.
        rot, mirror, tilt = _accumulate_rotation(rot, mirror, tilt, angles)
        movement = _native_translation(n, rotation_u, frame - start, translation_cache, samples)
        cur = n.slots.get(SLOT_TRANSLATE) if movement is None else None
        if movement is not None or cur:
            v = movement if movement is not None else cur.sample(t)
            if movement is not None:
                v = _point_in_frame(point_matrix, v)
            for i in range(min(3, len(v))):
                pos[i] += v[i]
        native_scale = _native_scale(n, t, frame - start, samples)
        sx, sy = native_scale[:2] if native_scale is not None else _xy(n.node_scale)
        cur = n.slots.get(SLOT_SCALE) if native_scale is None else None
        if cur:
            cx, cy = _xy(cur.sample(t))
            # same envelope-vs-absolute rule as the emitter scale slot
            if _is_absolute(cur):
                sx, sy = cx, cy
                abs_scale = True
            else:
                sx, sy = sx * cx, sy * cy
        scale[0] *= sx
        scale[1] *= sy
        local_scale = native_scale if native_scale is not None else [sx, sy, 1.]
        point_matrix = _compose_point_frames(point_matrix, _local_point_matrix(angles, local_scale))
    result = (pos, scale, rot, mirror, tilt, abs_scale)
    return result + (point_matrix,) if return_matrix else result


_MODEL_CACHE: Dict[str, Optional[List[float]]] = {}


def model_half_extent(name: Optional[str], search_dirs, rx=0., ry=0.) -> Tuple[float, float]:
    """Half the XY extent of a .m3r mesh, i.e. its radius in world units.

    The overwhelmingly common mesh is a unit quad spanning -1..+1, whose half
    extent is 1.0, so multiplying by this is a no-op for ordinary sprites and
    only matters for the genuinely large meshes (e.g. model_aura_047 is
    160 x 201, so a lightning emitter scaled 0.01 x 1.0 is a 0.8 x 100 bolt,
    not a 0.01-unit dot)."""
    if not name:
        return (1.0, 1.0)
    key = (name, rx, ry)
    if key not in _MODEL_CACHE:
        ext = None
        for d in search_dirs:
            p = os.path.join(d, name + ".m3r")
            if os.path.exists(p):
                try:
                    m = parse_m3r(p)
                    if m["vertexCount"]:
                        points = project_mesh_vertices(m, rx, ry)
                        ext = [(max(p[a] for p in points)-min(p[a] for p in points))/2 for a in (0,1)]
                except Exception:
                    ext = None
                break
        _MODEL_CACHE[key] = ext
    ext = _MODEL_CACHE[key]
    if not ext:
        return (1.0, 1.0)
    return (ext[0] or 1.0, ext[1] or 1.0)


# Sizes.  Every size in the file -- an emitter's base size, a scale curve, a
# node scale -- is a HALF extent: the unit quad / unit mesh spans -1..+1, so a
# value of 90 draws 180 world units across.  Measured on the phone recording
# of Firaga (docs/06-effect-port-handoff.md): the fireball's ring mesh (node
# curve 197 x base 1.16) reaches a screen radius that only fits twice the file
# value, the flame quads of bm_2001_fire1 (21 x node scale 3) are ~125 units
# wide on screen, and Ariana's 340 x 280 plate is screen-sized only doubled.
SIZE_IS_HALF_EXTENT = True

# Bump when bake() output changes meaning (sizes, colour, timing); layer_spec re-renders cached docs with an older stamp.
# 3 = v26: half extents, colour slot 19, per-axis curves, radial streaks, repeat / interval.
BAKE_VERSION = 15


def _axis_mode(cur: Curve, i: int) -> str:
    """How one component of a scale curve reads: "abs" (world half-size),
    "env" (0..1-ish envelope on the base size) or "unset" (all keys ~0, or a
    constant 1.0 on y while x varies -- the file's "uniform, only x matters"
    convention, see _xy)."""
    vals = [abs(v[i]) if i < len(v) else 0.0 for _t, v, _ in cur.keys]
    if not vals or max(vals) < 0.05:
        return "unset"
    if i > 0 and all(abs(x - 1.0) < 1e-6 for x in vals):
        xs = [abs(v[0]) for _t, v, _ in cur.keys]
        if any(abs(x - 1.0) > 1e-6 for x in xs):
            return "unset"
    peak, last = max(vals), vals[-1]
    return "abs" if (peak > 2.0 and not (peak <= 3.0 and last <= 1.0)) else "env"


# Which world axes of the launch velocity land on the screen. The files are 3D and this renderer is 2D. "x-z" is the
# default because it is the one mapping checked against a recording: the meteor's boulders carry (-3, 0, 5) and fall down
# and to the left, which needs the third component as the screen's vertical, negated (+y is up here). It is not settled --
# `bm_2001_fire1` carries (0, 0, 0.5) and a flame should rise, which wants "xz" instead; the sign may follow a node
# rotation nobody has decoded yet. Set FFBE_VEL_AXIS to xy / xz / x-z / -yx to compare against another recording.
VEL_AXIS = os.environ.get("FFBE_VEL_AXIS", "x-z")


def _launch(node: Optional[Chunk], rng) -> Optional[Tuple[float, float]]:
    """A particle's velocity in screen units per frame: the node's vector turned by a random angle inside its rotation
    range, plus its spread speed in a random direction. None when the node asks for neither."""
    if node is None: return None
    v = list(node.velocity or [0.0, 0.0, 0.0])
    while len(v) < 3: v.append(0.0)
    if VEL_AXIS == "xz": vx, vy = v[0], v[2]
    elif VEL_AXIS == "x-z": vx, vy = v[0], -v[2]
    elif VEL_AXIS == "-yx": vx, vy = -v[1], v[0]
    else: vx, vy = v[0], v[1]
    rng_deg = max(abs(x) for x in (node.rot_range or [0.0])) if node.rot_range else 0.0
    if rng_deg:
        a = math.radians((rng.random() - 0.5) * rng_deg)
        ca, sa = math.cos(a), math.sin(a)
        vx, vy = vx * ca - vy * sa, vx * sa + vy * ca
    s = node.vel_spread or 0.0
    if s:
        a = rng.random() * 2 * math.pi
        vx += math.cos(a) * s * rng.random()
        vy += math.sin(a) * s * rng.random()
    return (vx, vy) if (vx or vy) else None


def _emission_node(chain: List[Chunk]) -> Optional[Chunk]:
    """The node whose emission fields drive this emitter: the nearest ancestor
    with a non-default count / window / burst setting, else the parent.  In
    bm_2020_fire3 the streak count (50) and the spark count (10 x 10) sit one
    node above the emitters' own parent."""
    for n in reversed(chain):
        if max(n.emit_count, n.emit_stream, n.emit_bursts) > 1 or n.emit_interval > 0:
            return n
    return chain[-1] if chain else None


def _full_rotation(node: Optional[Chunk]) -> bool:
    """The node orients each particle freely (>= 180 degrees on two axes), so whatever it launches sprays outward."""
    return bool(node and node.rot_range and sum(1 for v in node.rot_range if abs(v) >= 180.0) >= 2)


def _is_shatter(node: Optional[Chunk], has_velocity: bool) -> bool:
    """A free-orienting node with a launch velocity and a small window: the window is a piece count fired at once, not a
    span of frames. `bm_2043_meteor` #21 (window 7, rotation range 360 on all three axes, velocity (8, 8, 5) with a spread
    of 5) is the reference - the recording shows a boulder breaking into about seven chunks that fly apart. Windows above
    64 stay frame-shaped: those are the long "keep emitting" values."""
    return bool(node and _full_rotation(node) and has_velocity and 1 < node.emit_stream <= 64)


def _is_radial_streak(node: Optional[Chunk], em: Chunk) -> bool:
    """An emission node with a full random orientation (rotation range >= 180
    on two axes) and a particle count, above an emitter whose quad is at
    least 8x longer than wide: the "energy gathering" shower -- N thin
    streaks spawned around the origin, pointing at it and flying in.
    Firaga's bm_2020_fire3 node #3 (50 particles, 8 x 400 and 4 x 305 ball3
    quads) is the reference; the recording shows a dozen streaks converging on
    the target over the first ~50 frames and merging into the glowing ball
    the explosion grows out of.  The spawn-shape / velocity fields are not
    decoded (FORMAT.md 7), so this is a reproduction of the look, not a
    reading of the file."""
    if node is None or not node.rot_range:
        return False
    if sum(1 for v in node.rot_range if abs(v) >= 180.0) < 2:
        return False
    if max(node.emit_stream, node.emit_count) < 4:
        return False
    native_scale = _native_scale(em, 0., 0.)
    bx, by = native_scale[:2] if native_scale is not None else _xy(em.base_scale)
    cur = em.slots.get(SLOT_SCALE) if native_scale is None else None
    if cur:
        v = cur.sample(0.0)
        if _axis_mode(cur, 0) == "abs":
            bx = abs(v[0])
        if len(v) > 1 and _axis_mode(cur, 1) == "abs":
            by = abs(v[1])
    lo, hi = min(bx, by), max(bx, by)
    return hi >= 8.0 * max(lo, 1e-6)


def _emitter_size(em: Chunk, u: float, nscale, node_abs: bool, dirs, age=None, model_rotation=(0.,0.), variation=None):
    """Full drawn size (w, h) in world units of `em` at life fraction `u`."""
    mx, my = model_half_extent(em.model, dirs, *model_rotation)
    native_scale = _native_scale(em, u, u * em.life if age is None else age, variation)
    if native_scale is not None:
        k = 2.0 if SIZE_IS_HALF_EXTENT else 1.0
        return k * mx * native_scale[0] * nscale[0], k * my * native_scale[1] * nscale[1]
    bx, by = _xy(em.base_scale)
    bx, by = bx * mx, by * my
    nscale = list(nscale)
    cur = em.slots.get(SLOT_SCALE)
    if cur:
        v = cur.sample(u)
        vx = v[0] if v else 1.0
        vy = v[1] if len(v) > 1 else 0.0
        ax, ay = _axis_mode(cur, 0), _axis_mode(cur, 1)
        if ay == "unset":                      # uniform: y follows x
            vy, ay = vx, ax
        # an "unset" x (bm_2020_fire3 #6: -0.006 .. 0.015 next to a 305-unit y)
        # keeps the base width instead of becoming a hairline
        any_abs = "abs" in (ax, ay)
        if any_abs and node_abs and ABS_SCALE_RULE == "node":
            # the node's absolute curve already sized the sub-tree; the
            # emitter's absolute axes are its template default
            if ax == "env":
                bx *= vx
            if ay == "env":
                by *= vy
        else:
            if ax == "abs":
                bx = abs(vx) * mx
            elif ax == "env":
                bx *= vx
            if ay == "abs":
                by = abs(vy) * my
            elif ay == "env":
                by *= vy
            if any_abs and node_abs:
                nscale = [1.0, 1.0]            # ABS_SCALE_RULE == "emitter": the node's is the dead one
    k = 2.0 if SIZE_IS_HALF_EXTENT else 1.0
    return k * bx * nscale[0], k * by * nscale[1]


def _native_alpha(chunk: Chunk, u: float, variation=None):
    """Local native opacity; inheritance is combined separately.

    GL 9.1.0 alpha::make_vertex::Zero (0x28B37DC) writes zero for mode1.
    Const init (0x28BEB2C) samples base +/- variance once and clamps [0,1].
    Curve update (0x28BF0EC) samples normalized local age and also clamps.
    Random/offset curves retain the previous center/zero-offset fallback;
    bake() reports these selectors rather than claiming native parity.
    """
    mode = chunk.quad_alpha_mode
    if mode in (None, 0):
        return 1.0
    if mode == 1:
        return 0.0
    if mode == 2:
        value = chunk.quad_alpha_base
        if variation is not None:
            value = variation.sample('global_alpha', [value] * 3,
                                     [chunk.alpha_variance] * 3, uniform=True)[0]
    else:
        value = chunk.alpha_curve.sample(u)[0] if chunk.alpha_curve else 1.0
    return max(0., min(1., float(value)))


def _alpha_fidelity(chunks):
    """List local-opacity approximations on the active emitter lineages."""
    fallbacks = []
    for c in sorted({c.index: c for c in chunks}.values(), key=lambda c: c.index):
        mode = c.quad_alpha_mode
        reason = None
        if c.is_emitter and c.type not in EMIT_ALPHA_MODE:
            reason = 'unmapped-alpha-selector-and-inheritance'
        elif mode not in (None, 0, 1, 2, 3):
            reason = 'random-or-offset-curve-center-fallback' if mode in (4, 5, 6) else 'unknown-alpha-mode'
        elif mode == 3 and c.alpha_curve is None:
            reason = 'selected-alpha-curve-unavailable'
        if reason:
            fallbacks.append({'chunk': c.index, 'type': c.type, 'mode': mode, 'reason': reason})
    return {'supportedLocalModes': [0, 1, 2, 3], 'fallbacks': fallbacks}


def _combine_drawable_alpha(local, parent, weight, operation):
    # Setupper omits alpha_blend entirely for abs(weight)<epsilon. This is
    # essential for Mod with weight0: omitted means local, not invisible.
    if abs(weight) < ALPHA_PARENT_EPSILON:
        return local
    if operation == 1:
        return local * weight * parent
    return (1. - weight) * local + weight * parent


def _node_alpha(chain, frame, effect_dur, instance_starts=None, *, variation=None,
                instance_keys=None, copy_index=0):
    """Evaluate each Null instance's locator alpha, not an ancestor product.

    Null PostUpdate 0x28AE450..458 writes (1-D4)*local + D4*parent to the
    locator. Mode0's local value is1 (context+130 default at 0x28AE05C),
    so a weight0 intermediate node resets, rather than inherits, an ancestor.
    Parent clocks retain their own birth times when children are delayed.
    """
    parent, start = 1., 0.
    for index, node in enumerate(chain):
        start = instance_starts[index] if instance_starts is not None else start + node.delay
        duration = node.duration or effect_dur
        u = max(0., (frame - start) / max(1, duration))
        samples = _node_variation(variation, chain, instance_keys, index, copy_index)
        local = _native_alpha(node, u, samples)
        weight = node.parent_alpha_weight
        parent = (1. - weight) * local + weight * parent
    return parent


def _native_quad_colors(em: Chunk, u: float):
    """Native color4 RGB, separate from alpha and texture color scaling.

    Constants use the authored centers of the variance ranges, one fixed
    variation. Per-corner alpha fields are not part of color4: its native
    make-vertex module copies twelve RGB floats and alpha has its own module.
    """
    mode = em.quad_color_mode
    if mode in (1, 2) and em.quad_colors:
        colors = [em.quad_colors[0]] * 4
    elif mode in (3, 4):
        curve = em.slots.get(SLOT_COLOR)
        colors = [curve.sample(u)[:3] if curve else [1., 1., 1.]] * 4
    elif mode is not None and 5 <= mode <= 20 and em.quad_colors:
        colors = em.quad_colors
    else:
        return None
    return [[max(0., min(1., float(v))) for v in color] for color in colors]


def _native_texture_color_scale1(em: Chunk, u: float):
    """Model primary texture RGB; unsupported random-curve mode stays neutral."""
    if em.texture_color_scale1_mode == 1:
        return em.texture_color_scale1_base or [1., 1., 1.]
    if em.texture_color_scale1_mode == 2:
        curve = em.slots.get(20)
        if curve:
            return curve.sample(u)[:3]
    return [1., 1., 1.]


def _native_particle_color(em: Chunk, u: float, variation=None):
    """Resource-free Particle color1; texture RGB has no role in shader 0."""
    mode = em.particle_color_mode
    if mode == 0:
        return [1., 1., 1.]
    if mode in (1, 2):
        color = list(em.particle_color_base or [1., 1., 1.])
    elif mode in (3, 4):
        curve = em.slots.get(SLOT_COLOR)
        color = curve.sample(u)[:3] if curve else [1., 1., 1.]
    else:
        raise ValueError(f'Unsupported untextured Particle color1 mode {mode}')
    spread = em.particle_color_variance or [0., 0., 0.]
    if mode in (2, 4) and any(spread):
        raise ValueError('Untextured Particle synchronized color variance is not decoded')
    if variation is not None and any(spread):
        # Cache the instance's variation, not the time-varying curve value.
        offset = variation.sample('particle_color1_offset', [0., 0., 0.], spread)
        color = [value + offset[i] for i, value in enumerate(color)]
    return [max(0., min(1., float(v))) for v in color]


def _regular_instances(chain: List[Chunk], limit: int):
    """Native regular generation branch: count each step within each window.

    NullEmitterNode::ActivateGenerator (GL 9.1.0 0x28aa538) computes
    count * bursts * ceil(window / step); Update (0x28aab70) advances at
    step*10000 fixed-point ticks and inserts the inter-burst gap. Children
    generate relative to each actual parent instance, not just one flattened
    start. Keep fractional birth times and instance identities for sibling
    transforms/velocities. Curve generators remain on the legacy fallback.
    """
    if any(n.emit_mode != 0 or not math.isfinite(n.emit_step) or n.emit_step <= 0 for n in chain):
        return None
    instances = [(0., [], [])]
    for node in chain:
        window = max(1, node.emit_stream)
        step = max(.0001, int(node.emit_step * 10000) / 10000)
        opportunities = max(1, math.ceil(window / step))
        times = []
        for burst in range(max(1, node.emit_bursts)):
            for tick in range(opportunities):
                at = burst * (window + node.emit_interval) + tick * step
                times.extend([at] * min(max(1, node.emit_count), max(0, limit - len(times))))
                if len(times) >= limit: break
            if len(times) >= limit: break
        children = []
        for parent_start, starts, keys in instances:
            for ordinal, offset in enumerate(times):
                born = parent_start + node.delay + offset
                children.append((born, starts + [born], keys + [ordinal]))
                if len(children) >= limit: break
            if len(children) >= limit: break
        instances = children
    return instances


def bake(eff: Effect, max_frames: int = 600, max_particles: int = 64,
         seed: int = 12345, model_dirs=None, repeat: int = 1, interval: int = 0,
         canonical_variation: bool = False) -> dict:
    """Turn the emitter description into a flat per-frame sprite list.

    Emission model (MEDIUM confidence, see FORMAT.md 3.3): the emission node
    (nearest ancestor with a non-default setting, else the parent) carries
    `count` particles per burst (+0x90), a `stream` window (+0x94) that
    spreads the emission across the node's window instead of firing one
    burst, a `bursts` count (+0x98) and an `interval` between bursts (+0x9C).
    All four default to a *single* particle, which is what the overwhelming
    majority of emitters want; `max_particles` is only a safety cap for the
    handful of emitters that ask for hundreds.

    `repeat` / `interval`: play the whole file `repeat` times, `interval`
    frames apart, as one sequence -- FFBE effect groups spawn the same file
    several times (Firaga's Lvup_Figa_B: bm_2001_fire1 x 7, 20 frames apart)
    and the port wants that as a single actor.
    """
    rng = random.Random(seed)
    variation = _CanonicalVariation(seed, eff.path) if canonical_variation else None
    unsupported_lineage = set()
    # One node spawns a whole branch, and everything under it travels together: the meteor's boulder, the fire around it, its
    # rings and its dust all leave on the same vector. So a launch is drawn once per (velocity node, spawn frame) and shared.
    # A shatter is the exception - its pieces are the point, and each gets its own direction.
    launches = {}
    ctxs = _collect(eff)
    repeat = max(1, int(repeat)); interval = max(0, int(interval))
    dur = min(max(eff.duration + interval * (repeat - 1), 1), max_frames)
    dirs = list(model_dirs or [os.path.dirname(os.path.abspath(eff.path))])

    # pre-roll the particle spawn schedule so it is stable across frames
    schedule = []  # (ctx, spawn_frame, jitter[3], rot_jitter, life, radial (theta, k) | None, copy time offset)
    for ctx in ctxs:
        span = max(1, ctx.span)
        node = _emission_node(ctx.chain)
        count = max(1, node.emit_count if node else 1)
        stream = max(1, node.emit_stream if node else 1)
        bursts = max(1, node.emit_bursts if node else 1)
        interval_n = node.emit_interval if node else 0
        radial = _is_radial_streak(node, ctx.emitter)
        # the launch velocity may sit on a node below the one that carries the count (the meteor's shatter: count on #21,
        # velocity on its child #22), so the whole chain decides
        vnode = next((n for n in reversed(ctx.chain)
                      if n.translation_mode not in range(9) and (n.velocity or n.vel_spread)), None)
        shatter = _is_shatter(node, vnode is not None) and not radial

        if ctx.emitter.life:
            life = ctx.emitter.life
        else:
            # types 4 and 7 have no decoded lifetime; without it a streaming
            # emitter would pile up particles that never die, so fall back to
            # a single particle lasting the node's window
            life, stream, bursts, count = span, 1, 1, 1

        if shatter:
            # every piece leaves at the same moment, in its own direction
            spawns = [ctx.start] * max(1, min(stream * count, max_particles))
        elif radial:
            # the window value is the streak count; spread the spawns over the
            # emission node's own window
            n = max(1, min(max(stream, count), max_particles))
            window = max(1, node.duration or span)
            spawns = [ctx.start + int(window * i / n) for i in range(n)]
        elif stream > 1:
            # emission window in frames; re-emit one particle each lifetime so
            # a short-lived emitter under a long node keeps flickering without
            # piling up overlapping copies
            window = min(int(stream), span)
            iv = max(1, life)
            n = max(1, min(window // iv + 1, max_particles))
            spawns = [ctx.start + iv * i for i in range(n)]
        else:
            iv = interval_n if interval_n > 0 else life
            n = max(1, min(bursts, max_particles))
            spawns = [ctx.start + int(iv * i) for i in range(n)]
        if count > 1 and not radial:
            room = max(1, max_particles // len(spawns))
            spawns = [s for s in spawns for _ in range(min(count, room))]

        instances = _regular_instances(ctx.chain, max_particles)
        if instances is None:
            instances = [(spawn, None, None) for spawn in spawns]
            if canonical_variation:
                unsupported_lineage.add(ctx.emitter.index)

        var = ctx.emitter.slots.get(SLOT_TRANSLATE_VAR) if ctx.emitter.translation_mode not in range(9) else None
        # In native mode6 slot3 is angular velocity, not random orientation.
        rvar = ctx.emitter.slots.get(SLOT_ROTATE_VAR) if ctx.emitter.rotation_mode is None else None
        box = [0.0, 0.0, 0.0]
        for nd in ctx.chain:
            if nd.translation_mode not in range(9) and nd.emit_box:
                for j in range(3):
                    box[j] = max(box[j], nd.emit_box[j])
        single = len(instances) == 1
        for spawn, instance_starts, instance_keys in instances:
            # a lone particle sits exactly on the emitter origin; only a real
            # swarm gets scattered
            jitter = [0.0, 0.0, 0.0] if single else \
                [(rng.random() - 0.5) * box[j] for j in range(3)]
            if var and not single:
                v = var.sample(0.0)
                for j in range(3):
                    jitter[j] += (rng.random() * 2 - 1) * (v[j] if j < len(v) else 0.0)
            rj = 0.0
            if rvar and not single:
                v = rvar.sample(0.0)
                rj = (rng.random() * 2 - 1) * (v[-1] if v else 0.0)
            rad = (rng.random() * 360.0, 0.6 + rng.random() * 1.6) if radial else None
            born = 0     # how long the branch had already been travelling when this particle appeared
            if vnode is None or shatter or radial:
                launch = _launch(vnode, rng)
            else:
                # everything under one spawn of the branch shares its vector, and a particle born later starts further
                # along it, so a re-emitted flame keeps up with the boulder it wraps instead of falling back to the origin
                vi = ctx.chain.index(vnode)
                if instance_starts is not None:
                    born = spawn - instance_starts[vi]
                    key = (vnode.index, tuple(instance_keys[:vi + 1]))
                else:
                    vstart = sum(n.delay for n in ctx.chain[:vi + 1])
                    period = max(1, vnode.duration or span)
                    inst = max(0, (spawn - vstart) // period)
                    born = spawn - (vstart + inst * period)
                    key = (vnode.index, inst)
                if key not in launches: launches[key] = _launch(vnode, rng)
                launch = launches[key]
            schedule.append((ctx, spawn, jitter, rj, life, rad, 0, launch, born, instance_starts, instance_keys, 0))

    if repeat > 1:
        base = list(schedule)
        for k in range(1, repeat):
            # the copy's time offset t0 is subtracted from the frame counter when sampling, so `spawn` stays file-relative
            schedule += [(ctx, spawn, jitter, rj, life, rad, k * interval, vel, born, starts, keys, k)
                         for (ctx, spawn, jitter, rj, life, rad, _t0, vel, born, starts, keys, _copy) in base]

    # Each emitter generator starts with a negative delay clock. The parent
    # locator has already been born and continues advancing during that wait.
    # Do not shift its instance_starts when delaying the emitted particle.
    delayed_schedule = []
    for entry in schedule:
        ctx, spawn, jitter, rj, life, rad, t0, vel, born, starts, keys, copy_index = entry
        samples = _emitter_variation(variation, ctx, keys, copy_index)
        delay = samples.delay(ctx.emitter.emitter_delay, ctx.emitter.emitter_delay_variance) if samples else max(0, ctx.emitter.emitter_delay)
        delayed_schedule.append((ctx, spawn + delay, jitter, rj, life, rad, t0, vel, born, starts, keys, copy_index))
    schedule = delayed_schedule

    frames = []
    tex_index = {}
    tex_list = []

    def tex_id(name):
        if name not in tex_index:
            tex_index[name] = len(tex_list)
            tex_list.append(name)
        return tex_index[name]

    size0_cache = {}
    translation_cache = {}
    for f in range(dur):
        parts = []
        for ctx, spawn, jitter, rj, life, rad, t0, vel, born, instance_starts, instance_keys, copy_index in schedule:
            fl = f - t0                     # frame within this copy of the file
            age = fl - spawn
            if age < 0 or age >= life:
                continue
            u = age / max(1, life)
            em = ctx.emitter
            tex = em.texture
            untextured = (em.type == T_EMIT_B and not em.res1 and not em.res2
                          and not (em.texture_material or {}).get('mode'))
            if not tex and not untextured:
                continue
            if untextured:
                # GL 9.1.0 selector 0x289C3D4 chooses shader0 for this
                # resource-free Particle. Its fragment shader emits vertex
                # RGBA directly; the white cell carries that exact value.
                tex = 'solid:white'
            npos, nscale, nrot, mirror, tilt, node_abs, point_matrix = _node_transform(
                ctx.chain, fl, eff.duration, instance_starts, translation_cache, return_matrix=True,
                variation=variation, instance_keys=instance_keys, copy_index=copy_index)
            samples = _emitter_variation(variation, ctx, instance_keys, copy_index)
            if em.quad_alpha_mode is not None:
                parent_alpha = _node_alpha(ctx.chain, fl, eff.duration, instance_starts,
                                           variation=variation, instance_keys=instance_keys,
                                           copy_index=copy_index)
                alpha = _combine_drawable_alpha(_native_alpha(em, u, samples), parent_alpha,
                                                em.parent_alpha_weight, em.parent_alpha_operation)
            else:
                # Undecoded emitter types retain their legacy opacity path;
                # alphaFidelity records that their inheritance is unmapped.
                alpha = em.color[3] if em.color and len(em.color) > 3 else 1.
                if em.alpha_curve:
                    alpha *= em.alpha_curve.sample(u)[0]
            if alpha <= 0.002:
                continue
            angles = _native_rotation(em, u, age, samples)
            if angles is None:
                cur = em.slots.get(SLOT_ROTATE)
                angles = [0., 0., cur.sample(u)[-1]] if cur else [0., 0., 0.]
            nrot, mirror, tilt = _accumulate_rotation(nrot, mirror, tilt, angles)

            pos = list(npos)
            movement = _native_translation(em, u, age, translation_cache, samples)
            cur = em.slots.get(SLOT_TRANSLATE) if movement is None else None
            if movement is not None or cur:
                v = movement if movement is not None else cur.sample(u)
                if movement is not None:
                    v = _point_in_frame(point_matrix, v)
                for i in range(min(3, len(v))):
                    pos[i] += v[i]
            pos = [pos[i] + jitter[i] for i in range(3)]
            if vel:
                travelled = born + age
                for i in range(2):
                    pos[i] += vel[i] * travelled
            if mirror and movement is None:
                pos[0] = -pos[0]

            # A model emitter draws a mesh, so its size is the mesh's own
            # radius times the scale factors; nearly every mesh is a unit quad
            # (extent exactly 2.0), which makes this a no-op, but the few
            # world-sized meshes matter a lot -- model_aura_047 is 160 x 201,
            # so the lightning emitters of bm_2037_burst_front go from
            # sub-pixel dots to bolts tens to hundreds of units tall.
            sc = list(_emitter_size(em, u, nscale, node_abs, dirs, age, tilt, samples))
            material = _native_texture_material(em, u, variation=samples)
            channel_count = (2 if material and material['mode'] else 1) if em.uv_channels else 0
            uv_states = [_native_uv_channel(em, channel, age, variation=samples,
                                           cache=translation_cache)
                         for channel in range(channel_count)]
            native_uv = not untextured and bool(uv_states) and not any(state['unsupported'] for state in uv_states)
            native_uv = native_uv and (material is None or not material['unsupported'])
            if native_uv:
                payload = {'texture': em.texture, 'channels': uv_states,
                           'wrap': em.uv_mode}
                if material:
                    payload['material'] = material
                if em.model:
                    payload.update(model=em.model, tilt=[round(tilt[0], 4), round(tilt[1], 4)])
                tex = 'nativeuv:' + json.dumps(payload, sort_keys=True, separators=(',', ':'))
            elif em.model:
                # drawn through the mesh (vertex alpha / colour + tilt), see rasterise_mesh
                tex = mesh_sprite_key(em.model, tex, tilt[0], tilt[1])

            rot = nrot + rj

            if rad is not None:
                # radial streak: born k streak-lengths out along `theta`, long
                # axis pointing at the origin, near tip arriving there at death
                theta, kk = rad
                key = (id(ctx), samples.identity) if samples is not None else id(ctx)
                if key not in size0_cache:
                    size0_cache[key] = _emitter_size(em, 0.0, nscale, node_abs, dirs, variation=samples)
                w0, h0 = size0_cache[key]
                long_axis_y = sc[1] >= sc[0]
                L0 = max(w0, h0); L = sc[1] if long_axis_y else sc[0]
                dist = kk * L0 * (1.0 - u) + 0.5 * L
                a = math.radians(theta)
                pos[0] += math.cos(a) * dist
                pos[1] += math.sin(a) * dist
                rot += theta - (90.0 if long_axis_y else 0.0)

            col = list((em.color or [1, 1, 1, 1])[:3])
            if native_uv and em.type in (T_EMIT_A, T_EMIT_B):
                # F8/98 is texture1 RGB, already selected by the material
                # module. It is not a second emitter/vertex colour.
                col = [1., 1., 1.]
            cur = em.slots.get(SLOT_COLOR)
            vertex_colors = _native_quad_colors(em, u)
            if not native_uv and vertex_colors is not None and all(c == vertex_colors[0] for c in vertex_colors):
                col = [col[i] * vertex_colors[0][i] for i in range(3)]
                vertex_colors = None
            elif vertex_colors is None and em.quad_color_mode not in (1, 2, 3, 4) and cur:
                v = cur.sample(u)
                col = [col[i] * (v[i] if i < len(v) else 1.0) for i in range(3)]
            texture_rgb = [1., 1., 1.] if native_uv else _native_texture_color_scale1(em, u)
            col = [col[i] * texture_rgb[i] for i in range(3)]
            if untextured:
                col = _native_particle_color(em, u, samples)
                vertex_colors = None
            if native_uv:
                # Native secondary-add adds RGB after vertex colour, so even
                # uniform vertex tints must precede the texture operation.
                payload['color'] = col
                if vertex_colors is not None:
                    payload['vertexColors'] = vertex_colors
                tex = 'nativeuv:' + json.dumps(payload, sort_keys=True, separators=(',', ':'))
                col = [1., 1., 1.]
                vertex_colors = None
            if em.blend == 3:
                # Native ZERO, ONE_MINUS_SRC_ALPHA is exactly a black source
                # under ordinary alpha blending. Keep texture/global alpha.
                col = [0., 0., 0.]
                vertex_colors = None

            # UV mirror tiling: mode 2 covers the quad with a tx x ty mirrored
            # copy of the texture, so a quarter-authored arc becomes a full
            # circle.  A 2D sprite renderer expresses that as tx*ty sub-quads
            # with alternating flipX / flipY.
            tx, ty = (1, 1) if native_uv or untextured else em.tile_counts()
            base = {
                "tex": tex_id(tex),
                "uv": [0.0, 0.0, 1.0, 1.0],
                "rot": round(rot, 2),
                "alpha": round(alpha, 4),
                "color": [round(x, 4) for x in col],
                "blend": "mix" if em.blend == 3 else BLEND_NAMES.get(em.blend, "add"),
                "emitter": em.index,
            }
            if vertex_colors is not None:
                base["vertexColors"] = vertex_colors
            if tx * ty == 1:
                parts.append(dict(base, pos=[round(pos[0], 3), round(pos[1], 3),
                                             round(pos[2], 3)],
                                  scale=[round(sc[0], 4), round(sc[1], 4)],
                                  flipX=mirror, flipY=False))
            else:
                tw, th = sc[0] / tx, sc[1] / ty
                a = math.radians(rot)
                ca, sa = math.cos(a), math.sin(a)
                for iy in range(ty):
                    for ix in range(tx):
                        dx = (ix - (tx - 1) / 2.0) * tw
                        dy = (iy - (ty - 1) / 2.0) * th
                        parts.append(dict(
                            base,
                            **({"colorRegion": [ix / tx, 1 - (iy + 1) / ty,
                                                 (ix + 1) / tx, 1 - iy / ty],
                                "colorTextureFlip": [bool(ix % 2), not (iy % 2)]}
                               if vertex_colors is not None else {}),
                            pos=[round(pos[0] + dx * ca - dy * sa, 3),
                                 round(pos[1] + dx * sa + dy * ca, 3),
                                 round(pos[2], 3)],
                            scale=[round(tw, 4), round(th, 4)],
                            # Texture v runs downward while our y runs up, so
                            # the un-mirrored tile (UV 0..1) is the *top*-left
                            # one -- hence the inverted parity on y.  With a
                            # quarter texture this puts every tile's UV (1,1)
                            # corner at the quad centre, which is where the
                            # art places the circle's centre.
                            flipX=bool(mirror) ^ bool(ix % 2),
                            flipY=not (iy % 2)))
        frames.append(parts)

    result = {"fps": 60, "frameCount": dur, "loop": False,
            "textures": tex_list, "frames": frames,
            "durationDeclared": eff.duration, "repeat": repeat, "interval": interval,
            "bakeVersion": BAKE_VERSION}
    result['alphaFidelity'] = _alpha_fidelity(
        [chunk for ctx in ctxs for chunk in (*ctx.chain, ctx.emitter)])
    result['alphaFidelity']['constantVariance'] = 'fixed-instance' if canonical_variation else 'authored-center'
    if canonical_variation:
        result['canonicalVariation'] = {'seed': seed, 'revision': 1,
            'unsupportedLineageEmitters': sorted(unsupported_lineage)}
    return result


# ---------------------------------------------------------------------------
# .m3r model files ("BR3M") -- effect meshes referenced by type-6 emitters
# ---------------------------------------------------------------------------
# 0x00 magic 'BR3M'; 0x04 version (0x23); 0x08 sub-mesh count
# 0x10 material-name offset; 0x14 material block; 0x18 index buffer;
# 0x1C vertex buffer; 0x20 per-triangle cumulative-area table; 0x24/0x28 size
# 0x70 vertex stride (36); 0x74 vertex count; 0x7C index count;
# 0x88 float total surface area
# vertex = float3 position, uint32 RGBA colour, float3 normal, float2 uv
def parse_m3r(path: str) -> dict:
    with open(path, "rb") as fh:
        d = fh.read()
    if d[:4] != b"BR3M":
        raise ValueError("%s: not a BR3M file" % path)
    ver = _u32(d, 4)
    name_off, mat_off, idx_off, vtx_off, area_off = struct.unpack_from("<5I", d, 0x10)
    # the vertex descriptor sits at a fixed offset inside the material block,
    # which itself moves with the length of the material-name string
    stride, vcount = struct.unpack_from("<II", d, mat_off + 0x20)
    icount = _u32(d, mat_off + 0x2C)
    area = struct.unpack_from("<f", d, mat_off + 0x38)[0]
    e = d.index(b"\0", name_off)
    mat_name = d[name_off:e].decode("utf-8", "replace")
    verts, uvs, cols = [], [], []
    for i in range(vcount):
        b = vtx_off + stride * i
        px, py, pz = struct.unpack_from("<3f", d, b)
        u, v = struct.unpack_from("<2f", d, b + 28)
        verts.append((px, py, pz))
        uvs.append((u, v))
        cols.append(tuple(x / 255.0 for x in struct.unpack_from("<4B", d, b + 12)))
    idx = list(struct.unpack_from("<%dH" % icount, d, idx_off))
    xs = [v[0] for v in verts] or [0.0]
    ys = [v[1] for v in verts] or [0.0]
    zs = [v[2] for v in verts] or [0.0]
    return {"version": ver, "material": mat_name, "vertexCount": vcount,
            "bounds": [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)],
            "extent": [max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)],
            "indexCount": icount, "stride": stride, "surfaceArea": area,
            "vertices": verts, "uvs": uvs, "colors": cols, "indices": idx,
            "materialColors": [struct.unpack_from("<4B", d, mat_off + 4 * i)
                               for i in range(4)]}


def project_mesh_vertices(mesh, rx=0., ry=0.):
    """Static local XY projection, shared by texture and output-size calculation."""
    matrix = _local_point_matrix([rx, ry, 0.], [1., 1., 1.])
    return [_point_in_frame(matrix, vertex) for vertex in mesh['vertices']]


class MeshRasterPlanCache:
    """Exact projected triangle data, bounded across animated mesh tilts."""

    def __init__(self, max_bytes=64 * 1024 * 1024, max_entries=32):
        self.max_bytes = max(0, int(max_bytes))
        self.max_entries = max(0, int(max_entries))
        self.plans = OrderedDict()
        self.bytes = 0
        self.hits = 0
        self.misses = 0

    def clear(self):
        self.plans.clear()
        self.bytes = self.hits = self.misses = 0

    def triangles(self, mesh, rx, ry, size):
        # Content, not object identity: callers may parse a new mesh dict for
        # each UV state. Every field used by projection/interpolation belongs
        # in the key; source coordinates and tilt are never quantized.
        stamp = hashlib.sha256()
        stamp.update(struct.pack('<ddq', rx, ry, size))
        for field in ('vertices', 'uvs', 'colors', 'indices'):
            stamp.update(json.dumps(mesh.get(field), separators=(',', ':')).encode())
            stamp.update(b'\0')
        key = stamp.digest()
        if key in self.plans:
            self.hits += 1
            triangles, _ = self.plans[key]
            self.plans.move_to_end(key)
            yield from triangles
            return
        self.misses += 1
        retained, retained_bytes = [], 0
        cacheable = bool(self.max_bytes and self.max_entries)
        for triangle in _mesh_raster_triangles(mesh, rx, ry, size):
            if cacheable:
                cost = sum(array.nbytes for array in triangle[4:])
                retained_bytes += cost
                if retained_bytes > self.max_bytes:
                    # Large meshes still stream one triangle at a time. Do
                    # not retain an oversized plan just to discover its size.
                    retained.clear()
                    cacheable = False
                else:
                    while self.plans and self.bytes + retained_bytes > self.max_bytes:
                        _, (_, evicted) = self.plans.popitem(last=False)
                        self.bytes -= evicted
                    retained.append(triangle)
            yield triangle
        if cacheable:
            while self.plans and len(self.plans) >= self.max_entries:
                _, (_, evicted) = self.plans.popitem(last=False)
                self.bytes -= evicted
            self.plans[key] = retained, retained_bytes
            self.bytes += retained_bytes


_MESH_RASTER_PLANS = MeshRasterPlanCache()


def _mesh_raster_triangles(mesh, rx, ry, size):
    """Yield exact old rasterizer regions in their original alpha-over order."""
    import numpy as np
    V = np.asarray(mesh["vertices"], dtype=np.float32)
    if not len(V) or not mesh.get("indices"):
        return None
    C = np.asarray(mesh.get("colors") or [(1, 1, 1, 1)] * len(V), dtype=np.float32)
    UV = np.asarray(mesh["uvs"], dtype=np.float32)
    I = np.asarray(mesh["indices"], dtype=np.int64)
    I = I[: len(I) - len(I) % 3].reshape(-1, 3)
    P = np.asarray(project_mesh_vertices(mesh, rx, ry), dtype=np.float32)
    bx0, by0 = P[:, :2].min(axis=0)
    bx1, by1 = P[:, :2].max(axis=0)
    cx, cy = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
    hw, hh = max(1e-6, (bx1 - bx0) / 2.0), max(1e-6, (by1 - by0) / 2.0)
    P = P - np.array([cx, cy, 0.0], dtype=np.float32)
    px = (P[:, 0] / hw + 1.0) * 0.5 * size
    py = (1.0 - P[:, 1] / hh) * 0.5 * size
    order = np.argsort(P[I].mean(axis=1)[:, 2])          # far (small z) first
    for ti in order:
        i0, i1, i2 = I[ti]
        x0, y0, x1, y1, x2, y2 = px[i0], py[i0], px[i1], py[i1], px[i2], py[i2]
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-6:
            continue
        xa, xb = int(max(0, math.floor(min(x0, x1, x2)))), int(min(size - 1, math.ceil(max(x0, x1, x2))))
        ya, yb = int(max(0, math.floor(min(y0, y1, y2)))), int(min(size - 1, math.ceil(max(y0, y1, y2))))
        if xa > xb or ya > yb:
            continue
        gx, gy = np.meshgrid(np.arange(xa, xb + 1) + 0.5, np.arange(ya, yb + 1) + 0.5)
        w0 = ((x1 - gx) * (y2 - gy) - (x2 - gx) * (y1 - gy)) / area
        w1 = ((x2 - gx) * (y0 - gy) - (x0 - gx) * (y2 - gy)) / area
        w2 = 1.0 - w0 - w1
        m = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
        if not m.any():
            continue
        u = w0 * UV[i0, 0] + w1 * UV[i1, 0] + w2 * UV[i2, 0]
        v = w0 * UV[i0, 1] + w1 * UV[i1, 1] + w2 * UV[i2, 1]
        vertex_color = w0[..., None] * C[i0] + w1[..., None] * C[i1] + w2[..., None] * C[i2]
        yield xa, xb, ya, yb, u, v, vertex_color, m


def rasterise_mesh(mesh: dict, tex, rx: float = 0.0, ry: float = 0.0, size: int = 256,
                   texture_sampler=None, *, geometry_cache=None):
    """Project source meshes with ordered straight-alpha triangle compositing.

    Repeated UV/material frames reuse exact geometry; the current texture
    sampler still runs for every triangle, including transparent overlaps.
    """
    import numpy as np
    if not len(mesh['vertices']) or not mesh.get('indices'):
        return None
    out = np.zeros((size, size, 4), dtype=np.float32)
    if tex is None:
        tex = np.ones((2, 2, 4), dtype=np.float32)
    th, tw = tex.shape[:2]
    cache = _MESH_RASTER_PLANS if geometry_cache is None else geometry_cache
    for xa, xb, ya, yb, u, v, vertex_color, m in cache.triangles(mesh, rx, ry, size):
        if texture_sampler is not None:
            col = texture_sampler(u, v, vertex_color)
        else:
            tx = (np.floor(u * tw).astype(np.int64)) % tw
            ty = (np.floor(v * th).astype(np.int64)) % th
            col = tex[ty, tx] * vertex_color
        a = np.clip(col[..., 3:4], 0, 1) * m[..., None]
        dst = out[ya:yb + 1, xa:xb + 1]
        dst[..., :3] = dst[..., :3] * (1.0 - a) + np.clip(col[..., :3], 0, 1) * a
        dst[..., 3:4] = dst[..., 3:4] + a * (1.0 - dst[..., 3:4])
    # The accumulation above is premultiplied. TextureCache and the atlas
    # exporter consume straight RGBA, so divide exactly once at this boundary.
    # Returning premultiplied RGB here multiplied every mesh's vertex/texture
    # alpha a second time at playback and made soft rings/glows too dark.
    np.divide(out[..., :3], out[..., 3:4], out=out[..., :3], where=out[..., 3:4] > 0)
    return out


def mesh_sprite_key(model: str, texture: str, rx: float, ry: float) -> str:
    """Synthetic texture name bake() hands out for a model emitter; the
    renderer's texture cache recognises the prefix and rasterises on demand."""
    return "mesh:%s|%s|%d|%d" % (model, texture, int(round(rx)), int(round(ry)))


# ---------------------------------------------------------------------------
def main():
    import argparse
    ap = argparse.ArgumentParser(description="Parse an FFBE .bmb effect file")
    ap.add_argument("path")
    ap.add_argument("-o", "--out", help="write JSON here (default: stdout)")
    ap.add_argument("--bake", action="store_true",
                    help="emit the baked per-frame sprite list instead")
    ap.add_argument("--max-frames", type=int, default=600)
    a = ap.parse_args()
    eff = parse(a.path)
    doc = bake(eff, max_frames=a.max_frames) if a.bake else eff.to_dict()
    text = json.dumps(doc, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("wrote %s (%d bytes)" % (a.out, len(text)))
    else:
        print(text)


if __name__ == "__main__":
    main()
