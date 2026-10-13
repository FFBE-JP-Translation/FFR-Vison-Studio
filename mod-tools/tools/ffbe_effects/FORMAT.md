# FFBE `.bmb` battle-effect format ("IBMB") — reverse-engineering notes

Scope: the ~7,200 `.bmb` files in `build/ffbe_cpk/effects_dec/` (from
`battleEffect1..4.cpk`) and the ~800 `.m3r` meshes from `effectResource1..3.cpk`.

**Status:** the *container* — object stream, tree, string table, resource
tables, keyframe pool, mesh format — is decoded with high confidence and
verified against all 7,168 valid files. The *semantics* of individual emitter
parameters are partly decoded: enough to identify the texture, colour, opacity
envelope, lifetime, size and motion of every emitter, but the emission model
(how many particles, spawned when, over what shape) is still largely unknown.

---

## 1. Big picture

`.bmb` is not a keyframed sprite animation. It is a **serialised object graph
from a particle-effect middleware** (the layout matches BISHAMON-family
runtimes: a tree of transform nodes with particle emitters as leaves, each
emitter carrying ~22 animation curves). The developers' asset root leaks into
the string table as `D:/database/latest/` or `../../../../database/latest/`.

The file is essentially a memory image of a 64-bit C++ object tree:

* every pointer field was written out as an 8-byte value, `0xFFFFFFFFFFFFFFFF`
  for NULL;
* structure padding is filled with `0xBA` (the classic debug fill byte);
* pointers that had to survive were rewritten as **offsets** — into the string
  table (for names) or into a trailing arena we call the **pool** (for arrays).

Layout:

```
0x00  header (0x60 bytes)
0x60  object stream        -- fixed-size objects back to back
      string table         -- NUL-terminated names, 0xBA-padded to 16 bytes
      pool                 -- keyframe arrays, child lists, resource descriptors
```

Everything is little-endian.

---

## 2. Header (0x00–0x5F)

| off | type | meaning | confidence |
|-----|------|---------|------------|
| 0x00 | char[4] | `IBMB` | certain |
| 0x04 | u8[4] | version, `01 01 03 01` in ~all files; `51 00 00 00` in a few old ones | high |
| 0x08 | u32 | always `0x41` (`'A'`) — unknown | — |
| 0x0C | u32 | always 0 | — |
| 0x10 | u32 | **texture count** | certain |
| 0x14 | u32 | **model count** | certain |
| 0x18 | u64 | always 0 | — |
| 0x20 | u32[8] | pool-relative offsets of resource-descriptor arrays; `[0]` = textures, `[1]` = models, remaining slots `0xFFFFFFFF` | certain |
| 0x40 | u32 | pool bytes actually used | certain |
| 0x44 | u32 | always 0 | — |
| 0x48 | u32 | **total effect duration, in frames** | certain |
| 0x4C | u32 | always `0x00010000` — unknown | — |
| 0x50 | u32 | always 0 | — |
| 0x54 | f32 | always 1.0 — playback speed? | low |
| 0x58 | u32 | file offset of the string table | certain |
| 0x5C | u32 | file offset of the pool (= end of string table) | certain |

**Evidence for 0x48 = duration.** There is a family of 33 otherwise byte-identical
files named `bg_black_30f.bmb` … `bg_black_320f.bmb`. Diffing them, exactly four
words change: `0x48`, the emitter's lifetime field, and two floats in the pool
(the fade-in/out key times). `0x48` is always the number in the filename.

**Evidence for 0x10/0x14 and the 0x20 table.** For every one of the 7,168 files
the descriptor arrays sized by these counts resolve to exactly the set of
distinct texture/model names that the emitters reference; no emitter ever
references a name outside its declared table.

---

## 3. Object stream (0x60 … string table)

A flat, gapless run of objects. Each starts with

```c
struct ObjHeader { u32 type; u32 size; ... };
```

Walking `off += size` from `0x60` lands exactly on the string-table offset for
7,168 / 7,169 files. (The one exception, `lb_203001504_FFIII_une_front .bmb` —
note the space in the name — has no `IBMB` magic at all and appears to be a
truncated duplicate.)

Sizes are fixed per type:

| type | size | count in corpus | meaning |
|------|------|-----------------|---------|
| 0 | 704 | 131,175 | **node** — transform / group, has children |
| 2 | 2128 | 24,762 | sprite emitter (25 curve slots) |
| 3 | 1840 | 20,720 | sprite emitter (22 curve slots); used for full-screen plates |
| 4 | 592 | 4,837 | small emitter, texture only |
| 6 | 1904 | 45,230 | **model emitter** — mesh + texture |
| 7 | 1856 | 2,237 | emitter variant; 83% have colour alpha 0 → probably a distortion/post pass |
| 9,10,11,12,13,15 | 144…224 | 892 total | rare auxiliary objects, not decoded |

A handful of files use slightly larger variants of the same types (e.g. type 0
at 768 bytes), which the `size` field handles automatically.

### 3.1 Common object fields

| off | type | meaning | confidence |
|-----|------|---------|------------|
| 0x00 | u32 | type | certain |
| 0x04 | u32 | size | certain |
| 0x08 | u32 | child count (nodes only; 0 on emitters) | certain |
| 0x10 | u32 | child count again (capacity?) | high |
| 0x18 | u64 | pool offset of the child-pointer array (nodes) | certain |
| 0x18–0x37 | u64[…] | runtime pointer slots, all `-1` on emitters | high |
| 0x40 | u64 | **resource 1**, string-table-relative offset | certain |
| 0x50 | u64 | **resource 2**, string-table-relative offset | certain |

For type 6, resource 1 is the **model** (`.m3r`) and resource 2 the **texture**
(`.png`). For the sprite emitters, resource 1 is the texture and resource 2 an
optional second texture (mask / glow). Offset 0 always points at the asset-root
path string, i.e. it means "unset".

### 3.2 Tree reconstruction

The child-pointer arrays in the pool are all zeroed (they were runtime
pointers), so the tree is rebuilt from **document order + child count**: the
objects are a pre-order traversal, and each node consumes the next
`child_count` sub-trees.

Verified on `lb_401000106_Ariana_back.bmb`: chunk types
`0(1) 0(1) 0(2) 0(1) 3 0(3) 0(1) 6 0(1) 6 0(2) 2 2` consume exactly 13 objects
and yield a sensible tree (a chain of 4 nodes, then a group of three emitter
branches). The same reconstruction terminates exactly at the end of the object
list for every file in the corpus; 358 files have more than one root.

### 3.3 Node (type 0) fields

| off | type | meaning | confidence |
|-----|------|---------|------------|
| 0x78 | u32 | start delay, frames | high |
| 0x80 | u32 | active duration, frames | high |
| 0x90 | u32 | **particles per burst**, default 1 | medium |
| 0x94 | u32 | **emission window in frames**; 1 = a single burst | medium |
| 0x98 | u32 | **number of bursts**, default 1 | medium |
| 0x9C | u32 | **frames between bursts**, default 0 | medium |
| 0x160 | f32[3] | looks like the spawn box the children scatter over; default (0,0,0) | low |
| 0x19C | f32[3] | **static rotation, degrees**; default (0,0,0) | high |
| 0x1A8 | f32[3] | rotation *range* (values are 360 / 180) | medium |
| 0x1E4 | f32[3] | **scale applied to the whole sub-tree**; default (1,1,1) | high |
| 0x230 | slot[8] | curve slots (see §4) | high |

**Emission.** All four emission controls sit on the *node* above an emitter,
and all four default to "one particle". That default matters: rendering one
sprite per emitter, spawned at its node's start and driven only by the curves,
is what most of the corpus wants -- an invented swarm reads as wrong.

| case | node fields | result |
|------|-------------|--------|
| `bg_black_30f` | count 1, window 1, bursts 1 | exactly 1 sprite, correct |
| `atk_cut2_red` | count 1, window 1, bursts 1 | exactly 1 slash |
| `bm_2037_burst_front` #88 (`tex_circle_quarter_004`) | window 1 | one expanding ring |
| `bm_2037_burst_front` #83 (`tex_circle_quarter_006`) | window 120, life 22 | a ring re-fired ~6 times over the window |
| `bm_2037_burst_front` #16/#30/#44 (lightning) | window 90, life 6 | a bolt re-fired ~15 times; with the three hand-duplicated branches (section 3.3) that is several bolts around the ring |
| `lb_401000106_Ariana_back` #11/#12 (hearts) | count 2, bursts 10, interval 7, life 40 | 20 hearts spawned 7 frames apart, ~12 alive at once -- the drifting heart shower |
| `lb_401000105_Ariana_front` #4/#6 (sparkles) | count 4, window 300 | 4 sparkles per burst, re-fired across the window |

Corpus support: `+0x90` is 1 in 93% of nodes, `+0x94` in 88%, `+0x98` in 97%
and `+0x9C` is 0 in 97%. The non-default values are frame-shaped (`+0x94` is
90 on a node whose duration is exactly 90) or count-shaped (`+0x90` is 2, 3, 4,
5, 10).

`bake()` reads `+0x94` as an emission *window* and re-fires one particle per
lifetime inside it, rather than as a particle count -- reading it as a count
produces dozens of overlapping copies that blow out to white. Emitters whose
lifetime is not decoded (types 4 and 7) always emit a single particle lasting
the node's window, since without a lifetime a streaming emitter would
accumulate forever.

**Near-duplicate evidence.** Grouping the corpus by file size and diffing every
pair inside a group turns up 458 pairs that differ in three words or fewer -
free single-parameter experiments. The decisive ones:

| pair | single differing word | reading |
|------|----------------------|---------|
| `sm_0071_Carbuncle1_back` vs `..._back_reverse` (and the `front` / `party_back` pairs) | node `+0x1A0` (= 0x19C+4, the Y component) 0 -> **180.0** | 0x19C is a static euler rotation; a 180 degree Y turn is the horizontal mirror that "reverse" means |
| `lb_0008_fina5` vs `lb_0008_fina5_front` | node `+0x78` 0 -> **60** | start delay in frames |
| `eff_lenseflare_001` vs `eff_lenseflare_001_normal` | node `+0x80` **120 -> 50** | active duration in frames |
| `lb_208000505` vs `...506_FFVIII_Selphie_front_unit` | node `+0x1E4` 0.295 -> **0.592** | sub-tree scale; the higher star rank makes the effect bigger |
| `lb_253000403` vs `...404_Alma_back_2` | node `+0x1E4` 0.788 -> **0.900** | ditto |
| `eff_bg_wind_pink` vs `..._purple` | emitter t6 `+0x78` | colour R |
| `eff_bg_wind_orange` vs `..._yellow` | emitter t6 `+0x7C` | colour G |
| `battle_buff1_blue_bg` vs `..._light_blue_bg` | emitter t3 `+0x6C` | a *second* colour block at 0x68 (the primary one is at 0x98) |
| `lb_100016205/06_hyo`, `lb_212001505/06_vaan`, `lb_336000105/06_alice` | emitter t6 `+0x108` 0 -> **1** | see the enable flag below |
| `lb_338000404/05/06_Riza` | emitter t2 `+0x138` 0 -> **1** | ditto |
| `lb_253000115/16_Ramza` | emitter t3 `+0xD8` 0 -> **1** | ditto |

**Evidence for 0x1E4.** In `lb_401000106_Ariana_back.bmb` the node above the
full-screen plate emitter holds `(340, 280, 1)` while the node above the heart
emitters holds `(25, 1, 1)`; in `atk_cut2_red.bmb` (a single horizontal slash)
it is `(100, 30, 100)`. Those three values reproduce, respectively, a
screen-sized plate, 25-unit hearts and a wide flat slash — and the sibling
model emitters in the same Ariana file independently declare a base size of
`(340, 240, 1)`, i.e. the same world scale. 86% of nodes hold the default.

### 3.4 Emitter fields

Emitter structs share sub-blocks but interleave type-specific fields, so the
byte shift between types differs from region to region; each field below was
located independently.

| field | type 2 | type 3 | type 6 | type 4 | type 7 | confidence |
|-------|--------|--------|--------|--------|--------|------------|
| colour RGBA (f32[4]) | 0x0F8 | 0x098 | 0x078 | — | 0x078 | high |
| colour variance | 0x108 | 0x0A8 | 0x088 | — | 0x088 | medium |
| particle lifetime, frames (u32) | 0x15C | 0x0F8 | 0x12C | — | — | high |
| blend / draw-mode enum (u32) | 0x198 | 0x134 | 0x168 | — | — | low |
| base size (f32[3]) | 0x36C | 0x30C | 0x34C | — | — | medium |
| alpha-over-life curve slot | 0x280 | 0x220 | 0x260 | 0x178 | 0x280 | high |
| enable flag (u32, 0/1) | 0x138 | 0x0D8 | 0x108 | — | — | medium |
| UV wrap / tile mode (u32) | 0x734 | 0x6A4 | 0x6E4 | — | — | high |
| UV tile factors ({u32 n; u64 ptr}) | — | 0x6E4 | 0x724 | — | — | medium |
| curve-slot array | 0x590 ×25 | 0x530 ×22 | 0x570 ×22 | — | — | high |

**UV mirror tiling — how a quarter arc becomes a full circle.** The wrap field
takes three values (0, 1, 2) and **2 means "cover the quad with a 2x2 mirrored
tiling of the texture"**, so art authored as a single quadrant assembles into a
full symmetric shape. Evidence:

* Every one of the 378 type-3 and 338 type-2 emitters in the corpus that
  reference a `tex_circle_quarter_*` texture has this field set to **2**, with
  no exceptions; the control population (emitters using any other texture) is
  1 in 72% and 0 in 19%.
* The textures used with value 2 are *quadrant-biased art*. Measuring how much
  of each texture's alpha-weighted luminance falls in its heaviest quadrant
  (0.25 = perfectly centred): value 0 median 0.272, value 1 median 0.265, and
  **value 2 median 0.410**, with 18% above 0.60 and 14% above 0.80 — versus
  **0%** above 0.60 in either of the other two groups. Only art meant to be
  mirrored is drawn off-centre like that.
* Its most distinctive textures are `tex_circle_quarter_006/007`,
  `glowring_016/017/018/020` and `tornado_001` — all quarter- or arc-shaped.
* An optional descriptor (`{u32 count; u64 poolOffset}` at type 3 `+0x6E4`,
  type 6 `+0x724`) points at a 32-byte pool record whose floats at +12 and +16
  are the (u, v) tiling factors. They are **(2.0, 2.0) in 37 of the 38 cases**
  in the corpus (the other is (1.0, 2.0)). Type 2's copy of this descriptor has
  not been located, so 2x2 is assumed there.

7.2% of all emitters (7,064 of 97,786) use mirror tiling.

`bake()` expands a mirror-tiled emitter into `tx * ty` sub-quads, each a
`1/tx x 1/ty` slice of the sprite, offset from the centre (rotated with the
sprite) and flipped on alternating rows and columns. The un-mirrored tile is
the *top*-left one because texture v runs downward while world y runs up; that
puts each tile's UV (1,1) corner at the quad centre, which is where the art
places the circle's centre. Getting this parity backwards produces a bow-tie
instead of a disc — a useful sanity check when looking at a render.

**Worked example.** `bm_2037_burst_front.bmb` (Sakura's Burst) has two type-3
emitters, #83 (`tex_circle_quarter_006`) and #88 (`tex_circle_quarter_004`),
both with wrap 2 and tile factors (2.0, 2.0). Rendered as a single quad they
show one quarter arc; expanded to 2x2 mirrored tiles they form the expanding
ring of light the effect is named for. Note that the same file also builds a
*three*-fold arrangement the other way, by hand: nodes #19 and #33 are
byte-identical copies of node #3's sub-tree with the static node rotation
(section 3.3) set to Z = 120 and 240 degrees. So the format has no general
"arrange N radially" parameter — 3-fold symmetry is duplicated in the file,
and 2-fold/4-fold symmetry comes from this UV mirror flag.

**Enable flag.** The word immediately before the constant `0x01010000` is 1 for
92% of emitters (5.8% of all 97,786 emitters in the corpus are 0). Six
"same limit burst, next star rank" file pairs differ in *exactly* this one word
in the whole file, always 0 -> 1: the higher rank switches an extra emitter on.
It is statistically independent of colour.a (212 emitters have flag 0 with
alpha 1, 301 have flag 1 with alpha 0), so the two are different switches.
`bake()` skips emitters whose flag is 0.

**Colour.** Found by diffing colour variants that share everything else:
`BFF_chinmokudance_color_20220722_{blue,red,…}` and
`atk_aerialslash_001_{blue,red,…}` differ *only* in these floats (plus a couple
of colour-curve keys). E.g. `atk_cut2_red` vs `atk_cut2_blue` differ in exactly
three float32s, at type-6 `+0x78/+0x7C/+0x80`.

The 4th component is 1.0 for 93% of emitters and 0.0 for the rest; the zero
ones read as invisible passes — 83% of type-7 emitters are zero, and one
carries the texture literally named `distortiontest`. The renderer treats it as
a base alpha.

**Lifetime.** Confirmed by the `bg_black_*f` family (type 3, `+0xF8` follows the
filename) and then located for the other types by scanning for the field whose
per-file maximum equals the header duration (type 6 `+0x12C`: 57 files; type 2
`+0x15C`: 21 files; no other offset comes close).

**Blend enum - still unproven.** The three offsets carry the same value
histogram (`3` >> `0` > `2` > `4`) and sit at exactly the lifetime offset + 0x3C
in all three types, so they are the same field. Ariana's LB assigns `4` to the
two heart sprites (opaque cut-out art) and `3`/`2` to the glow and aura layers,
so `3`/`2` read as additive and `4`/`0` as normal alpha - but two attempts to
confirm this **failed**, and the reading should be treated as a guess:

* Correlating the enum with the referenced texture's alpha statistics over
  ~5,900 emitters shows no separation at all (median mean-alpha 0.26 / 0.33 /
  0.33 / 0.22 for values 0 / 2 / 3 / 4; median opaque-pixel fraction 0.10 /
  0.10 / 0.09 / 0.08).
* Searching *every* u32 field of types 2/3/6 for the one that best predicts
  "black but fully opaque pixels" (a texture that can only be drawn additively)
  found nothing convincing either: the best separations are ~0.2 on groups of
  fewer than 50 emitters, at offsets that are curve-slot flag words. FFBE's
  effect art almost always carries a correct alpha channel, so additive and
  alpha blending look similar and this line of evidence is weak by nature.
* No near-duplicate pair in the corpus differs only in this field, so there is
  no known-plaintext case for it either.

The `bg_black_*f` family remains the counter-example: it is `3` while drawing a
*white*, fully opaque texture, which under "3 = additive" would be a white-out
rather than a black-out.

---

## 4. Curves

### 4.1 Slot descriptor (16 bytes)

```c
struct CurveSlot { u32 keyCount; u32 flags; u64 poolOffset; };
```

Empty slots are `{0, 0, (u64)-1}`.

The slot arrays sit at the tail of each emitter (see the table above) and at
`0x230` in nodes. Extents were found by scanning for the longest run of 16-byte
records matching the descriptor pattern, over 200 files: type 0 → 8 slots at
0x230, type 2 → 25 at 0x590, type 3 → 22 at 0x530, type 6 → 22 at 0x570
(consistent in >99% of chunks).

### 4.2 Keyframe record

A curve of dimension *N* stores *N*-wide interpolation, tangents and values:

```c
struct Key<N> { u32 interp[N]; f32 inTangent[N]; f32 outTangent[N];
                f32 value[N];  f32 time; };
```

so the stride is `4*(4N+1)`: **20** bytes scalar, 36 (N=2), **52** (N=3), 68 (N=4).
`time` is normalised to 0…1 over the owner's life, starts at 0 and — for
multi-key curves — ends at exactly 1.0.

The descriptor stores only a key *count*, not the width, so the width must be
inferred. Claiming the node child-lists first and then taking the widest
non-overlapping reading tiles **93–99%** of every pool tested byte-exactly
(bg_black 91%, atk_cut2 93%, Ariana 97%, `lb_401000104_Ariana_front` 99%,
`fusion_001` 93% over 146 curves), which is what the parser does.

Worked example — `bg_black_30f.bmb`, pool data is 0x58 bytes:
0x00–0x07 is the root node's 1-entry child list, 0x08–0x57 is a 4-key scalar
curve, 0x58 is where the texture descriptor begins. The curve reads
`(t=0, v=0) (0.166, 0.701) (0.708, 0.701) (1.0, 0)` — a fade in, hold, fade out
over the file's 30 frames, exactly what a `bg_black_30f` should do.

### 4.3 Slot meanings

Types 3 and 6 share a 22-slot list; type 2 has the same 22 plus 3 extra at the
end (established by matching the colour slot, which is the only slot whose
values are always inside [0,1]). So slot *i* lives at
`0x570 + 16i` (type 6), `0x530 + 16i` (type 3), `0x590 + 16i` (type 2).

| slot | offset (t6) | evidence | meaning | confidence |
|------|-------------|----------|---------|------------|
| 0 | 0x570 | median \|v\| ≈ 100, max 1500 | translate | medium |
| 1 | 0x580 | median ≈ 10 | translate variance | low |
| 2 | 0x590 | values cap at exactly 360 | rotation, degrees | medium |
| 3 | 0x5A0 | median 15 | rotation variance | low |
| 4 | 0x5B0 | most-populated slot; median 140 for models | scale | medium |
| 5 | 0x5C0 | | scale variance | low |
| 6 | 0x5D0 | Ariana's aura layers hold (0,0,0)→(0,−1.5,0) | gravity / drift? | low |
| 7–18 | 0x5E0–0x690 | | unknown (slot 8: `0 -> 180` over life, not a size) | — |
| 19 | 0x6A0 | *always* inside [0,1] (400-file sample: 809 of 809 curves), vec3; second-most populated | colour over life (RGB multiplier) | high |
| 20 | 0x6B0 | also always inside [0,1], vec3 | colour variance / secondary colour | medium |
| 21 | 0x6C0 | | unknown | — |

(The v25 version of this table labelled the 0x6A0 slot "13": the offset was right, the index was not, and `bake()` read slot
13 -- so no colour ramp was ever applied until v26. Firaga's flames are yellow -> red through this slot: `(1, 1, 0.42) ->
(1, 0.215, 0)` on `bm_2001_fire1` #2, `(1, 1, 0) -> (1, 0.195, 0)` on the fireball spheres and rings.)

Node slots use a shorter list; slot 0 (0x230, median 100) and slot 4 (0x270,
median 1.4) behave like translate and scale respectively.

**Sizes are half extents.** Every size in the file (emitter base size,
scale curve, node scale) is a half extent: the unit quad / unit mesh spans
-1..+1, so a value of 90 draws 180 world units across (`ibmb.SIZE_IS_HALF_EXTENT`).
Established on the phone recording of Firaga (see "Ground truth" below): the
ring mesh of `bm_2020_fire3` (`circle014` under a node curve peaking at 197,
base 1.16 x 1.28) sweeps out of the explosion with a screen radius that only
fits twice the file value; the flame quads of `bm_2001_fire1` (21 x node scale
3) are ~125 units wide against a ~75-unit-tall unit; and Ariana's 340 x 280
plate is screen-sized only doubled. `bake()` reports full extents.

**Mesh extent.** A model emitter's world size is
`2 x baseScale x scaleCurve x nodeScale x meshHalfExtent`, where the half extent
comes from the `.m3r` bounding box (section 6). 90% of meshes span exactly
2.0, i.e. a unit quad whose half extent is 1.0, so this term is normally a
no-op -- but a few meshes are authored at world size and then it is decisive:
`model_aura_047` is 160 x 201, so the lightning emitters of
`bm_2037_burst_front` go from sub-pixel dots to 24-131 unit bolts. Measured
world sizes for that file after the fix: `glow_008` 80-100, `thunder6_2` /
`thunder24` 24-131, `ball3` 200, `ball1` 0-341, `tex_circle_quarter_004`
0-119, `white` 36, `ring17` 5.

Types 4 and 7 keep their base size in fields of their own (t4 `+0xFC`,
t7 `+0x1DC`); before those were decoded every type-4/7 emitter fell back to
1 unit and rendered as a dot.

The scale slot is used two different ways in the corpus — as a 0…1 envelope
multiplying the static base size (Ariana's hearts: base 1, curve 0→1→0), and as
the absolute world size with the base holding an unused authoring default
(`lb_401000106_Ariana_back_unit` emitter 15: base 80, curve peaking at 90). The
parser disambiguates on the curve's peak (>2 ⇒ absolute, except the common
pop-in template `2.5 → 0.5 → 0.25`, which ends under 1 and is an envelope).
**This is a heuristic, not a decoded flag** — the real selector is presumably
one of the undecoded enum fields.

**Node scale curve vs. emitter scale curve.** Nodes carry the same scale slot
(node slot 4 at 0x270; 4,199 of them in a 2,500-file sample, median peak 2.4,
90th percentile 177 — so node curves are absolute world sizes about as often
as emitter curves are). In 608 emitters of a 2,000-file sample *both* the
emitter and an ancestor node hold an absolute curve, and multiplying them is
impossible: `bm_2020_fire3` (Firaga) has node `90 → 161 → 197` above emitter
`90 → 161 → 197` (separate pool records, identical values), which multiplied
gives a 39,000-unit fireball. The two curves are equally template-like (82 vs
80 distinct value sets over those 608 cases; the emitter template
`39.05 → 74.18 → 85.95` recurs under different node curves in
`eff_dark_ball_pink`, `bm_2020_fire3`, …), so the corpus does not say which one
the runtime honours. `bake()` follows `ABS_SCALE_RULE = "node"`: the node's
absolute curve sizes the sub-tree and the emitter's absolute curve is ignored
(an artist animates the node transform and leaves the emitter's default in
place). `"emitter"` is the alternative reading; a recording of Firaga from the
phone is the intended check — under "node" the three nested fireball groups
are 90–197 / 64–149 / 20–70 units across, under "emitter" 90–197 / 39–86 /
20–70.

Static node scale (`+0x1E4`, e.g. Burst's 30) always multiplies, whichever
curve applies.

**Per-axis curves.** A scale curve's components are read separately: a
component whose keys peak above 2 is an absolute half size, one that stays
below is an envelope on the base, and one that is ~0 everywhere (or a constant
1.0 on y while x varies) is unset -- y then follows x (the file's "uniform"
convention), an unset x keeps the base width. `bm_2020_fire3` #6 is the
motivating case: x `-0.006 -> 0.015` next to y `305 -> 302 -> 0`, a streak that
shortens to nothing; read as one curve it became a 0.06 x 122,000 hairline.

### 4.4 Ground truth: the Firaga recording (2026-09-05)

A 120 fps phone recording of Firaga (JP, magic 20200: `bm_2020_fire3` at the
enemy group + `bm_2001_fire1` x 7 on the enemy) is the first comparison of the
parser against the running game. What it settled:

* **Frame rate 60.** The cast motion starts 0.67 s before the effect appears
  (group frame 40), the first damage number 2 frames later (attack frame 42),
  the fireball group (node delay 60) 1.0 s after the effect starts, the last
  flame (spawn 140 + life ~50) 3.1 s in. Everything lines up at 60 fps.
* **Half-extent sizes** (above). `ABS_SCALE_RULE = "node"` was kept: the
  ring mesh, which has no curve of its own, matches the node curve, and the
  middle sphere cannot be measured inside the additive glare.
* **Slot 8 is not a size.** The three "ground ring" emitters (`cloud2`,
  `fire_wall1`, `circle002` disc, base 1-2, slot-8 curve `0 -> 180` over 160
  frames) leave no visible trace in the recording; a 360-unit quad growing
  over the file's life would have been obvious. Ignoring the slot is right.
* **`light_burst1` (#27, base 220, 15 frames) is invisible in the game.** No
  flash, star or line appears at the target in the first 15 frames. Left out
  of the port with `exclude: [27]`; the reason (a draw-mode / layer field, or
  a base size that is really 220 x 1) is undecoded.
* **The streak shower.** The first 50 frames are a "charge": a dozen thin
  streaks at random angles converge on the target and merge into a growing,
  then fading, red ball -- exactly the two ball3 quads (#5 8 x 400, #6 4 x
  305 -> 0) under node #3 (`+0x94` = 50, rotation range 360 on three axes,
  duration 20). So `+0x94` is a particle *count* here, and the spawn shape /
  velocity (undecoded) is "around the origin, flying in". `bake()` reproduces
  the look for such nodes (`_is_radial_streak`); it is a port heuristic, not a
  decoded field.
* **Emission fields sit on the nearest configured ancestor**, not always the
  parent: the streak count is two levels above the emitters, so is the spark
  count (`+0x90` 10, `+0x94` 10 on node #23 above #24 -> #25/#26).
  `_emission_node()` walks up.
* **No caster effect, no ground ring.** Nothing plays on the caster beyond
  the game's generic green hand glow; the skill-level flag `b = 1` on the
  second group means "each target", not "caster" (catalog.py). The flame
  pillar burns on the enemy from 1.0 s to 3.1 s because the group spawns
  `bm_2001_fire1` seven times, 20 frames apart, with a crackle cue each time.
* **Group offsets** `x:y` = right : toward the camera. Firaga's `30:150` puts
  the fireball about 150 units below the flying bat's centre on screen (the
  screen-down reading gives the same picture; the port maps y to camera depth).
* **The fireball is big.** Explosion ~5-7 unit heights across including the
  additive bloom, the red ring's radius 4.2-4.6 unit heights when it leaves
  the frame, the flame pillar ~1.7 unit heights wide and 3-4 tall, streaks
  clipped by the screen edge. With half extents that is the file's numbers
  x 1.6 for *both* layers (the per-target flame too), so 1.6 is the effect-unit
  to sprite-pixel factor (`autoport.EFFECT_UNIT_SCALE`), while the group
  offsets are 1:1 sprite pixels.
* **Additive brightness.** The flame pillar is yellow-white on screen although
  `fire20` / `fire25` carry ~0.4 mean alpha and the emitter alpha peaks at
  0.81: colour x texture alpha x emitter alpha would be a faint wisp. The game
  draws additive sprites much hotter than that (texture alpha barely
  attenuates); `to_ss6` approximates it with the layer's glow > 1.

Still unexplained after the recording: a red, crystal-textured sphere that
outlives the fireball nodes by ~20 frames (F 110-130), and where the game's
embers get their spread (the spark emitters have no decoded box / velocity, so
`bake()` draws them stacked).


### 4.5 Meteor (`bm_2043_meteor`), against a phone recording

The user recorded the JP client casting Meteor (magic 20430) on two enemies:
`docs/media/meteor-jp-recording.mp4` (4.3 s, 30 fps). What it shows, in order:
a rain of thin white streaks that never stops; the battle background replaced
by a purple nebula with drifting sparkles; then a barrage of ten or more
boulders that fall from the top of the screen, flash white on landing, throw an
orange ring outward and break into angular chunks.

Every one of those is in the two files, and the tree maps onto the recording
cleanly (`abilities/meteor/README.md` has the group timing):

| what the recording shows | where it lives |
|---|---|
| the nebula the battlefield fades into | `bm_2043_meteor_bg` #5: `lapis_eff_material_016_bg` on `model_board_wall_1pl`, base scale 400x450, life = the whole 400 frames |
| the sparkles over it | `bg` #3/#4: `ball1` on a 48-plane circle, alpha 0 -> 1 -> 0 |
| the streak rain | `meteor` nodes #3 and #5: `ball1`, life 20, window 400, node #5 count 30, rotation ranges (60, 0, 80) and (80, 360, 0) - a wide cone of streaks re-fired for the whole effect |
| the boulders | #24 -> #26: `lapis_eff_material_020_uv_0019_rock01` on `model_stone081_162pl`, blend 0 (opaque, the only opaque emitter in the file), life 30 |
| the fire around a falling boulder | #12 -> #13/#14: `thunder_cloud_loop2` and `ice42` on `model_ball_196pl`, base scale 15 and 50 |
| where each boulder lands | #11: spawn box (10, 10, 10) plus a `translate_var` curve, under #10 whose rotation range is (45, 45, 30) - a random direction per boulder |
| the ring on impact | #15 -> #16/#17: `cloud2` and `white` on the 128- and 48-plane discs, base scale 400, with `scale` curves |
| the white flash | #18 -> #19/#20: two `ball1` sprites, one stretched (2.0, 0.1) |
| **the boulder breaking apart** | #21 -> #22 -> #23: the same `rock01` on `model_stone081_162pl` at scale 12, delay 30 frames after the boulder, window 7, rotation range (360, 360, 360) - seven chunks thrown in random directions |
| the dust it kicks up | #27 -> #28: `cloud2` on a 48-plane circle, node scale 35, spawn box (5, 5, 5), window 30, with a `translate` curve |

So nothing about this animation is missing from the files, and no second file
is referenced: the break-up is a sub-branch of the same effect, and the barrage
comes from one spawn of one `.bmb`.

What `render.py` does not reproduce is the *motion*: it draws one boulder,
standing still, and no streak rain. Both are the emission model (section 7),
not missing data. The recording adds a second ground truth after Firaga:

* Node #10 (the boulder branch) has window 240 and a 45-degree rotation range,
  and the recording shows ten or more boulders. `bake()` re-fires one particle
  per lifetime inside a window, which for the life-30 rock emitter under it
  gives eight - the right order, so the window reading survives this case.
* The boulders enter from off screen and travel down the frame. Nothing the
  parser reads today moves them.

**That motion is now read** (bake version 4). Node `+0x170` is a launch
velocity in world units per frame and `+0x17c` a speed given in a random
direction on top of it; `bake()` turns each into a per-particle vector, rotated
by a random angle inside the node's rotation range. Three readings came with
it, all checked against the recording:

* **A branch travels as one.** A node spawns a whole sub-tree, so the boulder,
  the fire around it, its rings and its dust must share one vector - drawn
  once per (velocity node, spawn) and reused. A particle re-emitted later
  starts that much further along it, which is what keeps the flame wrapped
  around a falling boulder instead of snapping back to the origin.
* **A small window on a free-orienting node is a piece count.** Node #21 has
  window 7, rotation range 360 on all three axes and a velocity below it; the
  recording shows about seven chunks. `_is_shatter()` fires all of them at
  once, each in its own direction. Windows above 64 stay frame-shaped.
* **Density.** `--particles` had to come up from 64 to 256 for the streak rain:
  node #5 asks for 30 per burst re-fired across 400 frames, and the old cap
  thinned it to eight on screen.

What is left open is which world axes land on the screen. The boulders carry
(-3, 0, 5) and fall down and to the left, which needs the third component as
the screen's vertical, negated - so `x-z` is the default. `bm_2001_fire1`
carries (0, 0, 0.5) and a flame should rise, which wants `xz`. The sign may
follow a node rotation that is not decoded; `FFBE_VEL_AXIS` switches between
them for the next recording.

**How the field was found.** Node `+0x170` is a float triple immediately
after the spawn box at `+0x160`, with a fourth float at `+0x17c`. On the
boulder node #11 it is (-3, 0, 5) with 4 at `+0x17c`; the still container nodes
of the same file have all four at zero. Across the corpus (20,139 nodes in
7,169 files) 832 nodes set only the spawn box, 703 only `+0x170`, and 568 both,
so the two are separate fields rather than one six-float box. The values are
small and signed where particles travel (Ariana's drifting hearts 2.0, fire3's
spark node -25, fire1 0.5) and the field is absent on nodes whose particles sit
still, which fits a per-frame velocity with the fourth word as a speed spread
or a gravity. Untested: no renderer reads it yet.

Confirmed on the way: `+0x160` really is a spawn area. `wm_1016_cure4_front`
#3 pairs a (100, 75, 0) box with count 12 over an 18-frame window, and the
healing sparkles in that spell are scattered across a patch that size.

---

## 5. Resource descriptors

At the end of the used pool, addressed by the header's `0x20` table:

```c
struct ResourceDesc { u32 nameOffset;   // relative to the string table
                      u32 pad; };       // always 0
```

Textures resolve to `<name>.png` and models to `<name>.m3r` in the extracted
asset directory. Every emitter's referenced name is present in the file's own
table for all 7,168 files.

---

## 6. `.m3r` meshes ("BR3M")

Not a texture container — a small static mesh with a surface-area table for
emitting particles from the surface.

| off | type | meaning | confidence |
|-----|------|---------|------------|
| 0x00 | char[4] | `BR3M` | certain |
| 0x04 | u32 | version, 0x23 | high |
| 0x08 | u32 | sub-mesh / material count (1 in every file seen) | medium |
| 0x10 | u32 | offset of the material name string | high |
| 0x14 | u32 | offset of the material block | high |
| 0x18 | u32 | offset of the index buffer (u16) | certain |
| 0x1C | u32 | offset of the vertex buffer | certain |
| 0x20 | u32 | offset of the cumulative-area table | high |
| 0x24, 0x28 | u32 | file size (twice) | certain |
| 0x70 | u32 | vertex stride, 36 | certain |
| 0x74 | u32 | vertex count | certain |
| 0x7C | u32 | index count | certain |
| 0x88 | f32 | total surface area | high |

Material block: four RGBA8 colours (ambient / diffuse / specular / emissive)
then a f32 shininess.

Vertex (36 bytes): `f32 position[3]; u32 rgba; f32 normal[3]; f32 uv[2]`.

The trailing table holds one f32 per triangle, monotonically increasing and
ending at the value stored at 0x88 — a cumulative-area table for uniformly
sampling spawn points on the mesh.

Worked example, `mod_quad_001b.m3r` (6,808 bytes): 134 vertices × 36 = 4,824
bytes at 0x4E8 (padded with `0xBA` to 0x17C8), 544 u16 indices at 0xA8, 180 area
entries at 0x17C8 rising to 4.00518 = the float at 0x88. Despite the name it is
not a quad but a 180-triangle disc.

---

## 7. What is still unknown

* **Emission - partly decoded.** The four node fields in section 3.3 give
  particles-per-burst, an emission window, a burst count and a burst interval,
  which is enough to separate "one sprite" from "a stream" from "a shower".
  What is still missing is the spawn *shape* (node `+0x160` is a guess at a
  spawn box) and the exact rate inside an emission window -- `bake()` assumes
  one particle per lifetime, which is conservative and matches the known
  cases, but the file may specify something finer. Node `+0x170` (launch
  velocity) and `+0x17c` (a random-direction speed) are read since bake 4;
  which world axes of that vector land on the screen is the open part, see
  section 4.5. Two earlier hypotheses
  were tested and rejected: node `+0x98`/`+0x9C` as (repeat count, interval) taken
  alone, and a node field equal to `nodeDuration / particleLife`. The Firaga
  recording (section 4.4) shows `+0x94` acting as a plain particle count (50
  streaks) on a node with a full rotation range, and the streaks flying in
  from around the origin -- the spawn shape and velocity fields are still
  undecoded; node #3's unique words `+0xC4` = 1 and `+0xDC` = 0.5 are the
  candidates.
* **Why `light_burst1` in `bm_2020_fire3` (#27) never shows** (section 4.4).
* **Slot 8** (`0 -> 180` over life on ~200 emitters) is not a size (section
  4.4); a rotation about the view axis or a UV sweep are the remaining guesses.

* **Slots 7–18 and 21** of the emitter curve list, and node slots 1–3, 5–7.
* **Blend enum** — which value is additive vs. subtractive vs. multiply, and why
  a white texture in `bg_black_*` should render as a black-out.
* **The base-size / scale-curve selector** (see §4.3).
* **Types 4, 7, 9–15** are only partly (or not at all) decoded.
* **UV animation.** The mirror-tiling mode is decoded (section 3.4), but no
  field has been found for sub-rect UVs or texture-sheet frame stepping, so
  `bake()` always emits the whole texture. Several textures are obviously
  flipbooks (`effect_anime_025_042`), so those fields exist somewhere.
* **Model rendering** — now done through the mesh. `rasterise_mesh()` draws
  the `.m3r` orthographically into a 256² sprite (vertex colour × texture,
  triangles back to front, ancestor X/Y tilt applied), and `bake()` hands a
  model emitter that sprite instead of the raw texture. The vertex colours
  are what shape these effects: `model_circle*_out_alpha` fades to alpha 0 at
  the rim, `*_in_out_*` at both rims, `model_ball021_480pl_updown_alpha` at the
  poles, `model_aura_047` is black at the ends of the strip. Before this, a
  cloud texture on the ball model drew as a hard-edged square. Still missing:
  perspective (the FFBE camera is a real 3D camera), UV scrolling on the
  `*_loop*` textures, and mesh animation.
* **Header 0x08 (`0x41`) and 0x4C (`0x00010000`)** are constant across the whole
  corpus and remain unexplained.
* **Frame rate.** `bake()` reports 60 fps because limit-burst durations
  (747 frames ≈ 12.5 s) only make sense at 60; there is no fps field in the file.


---

## 8. Exporting for the SS6 pipeline

### Native-runtime corrections (2026-09-12)

The GL 9.1.0 ARM64 `libgame.so` has exported Bishamon symbols (`ml::bm` and
`ml::bmfw`), including the original curve sampler. This confirms the middleware
identity and provides a path to decode the remaining simulation selectors.
The inspected binary is under the local FFBE 9.1.0 dump's
`xapk_unpacked/extracted/lib/arm64-v8a/` directory.

`ml::bm::Curve<3>::ValueN<3>` at virtual address `0x28c63a4`, with jump tables
at `0x30210ec`, `0x30210f0`, and `0x30210f4`, dispatches separately per axis:

| Interpolation value | Native behavior |
| --- | --- |
| 0 | Hold previous value until the next key |
| 1 | Linear interpolation |
| 2 or 3 | Cubic Hermite interpolation |

Each key contains interpolation enums, an outgoing tangent array, an incoming
tangent array, a value array, and normalized time. Hermite uses the first key's
outgoing tangent and the next key's incoming tangent; the tangents are **not**
multiplied by segment duration. Bake version 5 retains and evaluates these
fields. Previously the decoder discarded both tangent arrays and linearly
interpolated every channel. Of the original 44 Sora trial files, 41 use a
nonlinear or hold channel: 734 cubic mode-2 segments, 12 cubic mode-3 segments,
24 hold segments, and 2,389 linear segments were found across all parsed
channels. These counts include channels the simulation has not yet implemented.

Version 5 also corrects a separate renderer defect: mesh rasterization now
returns straight RGBA after its premultiplied accumulation. Otherwise playback
multiplied texture and vertex alpha twice, darkening soft geometry. Cached mesh
sprites now include the decoder revision and source mesh/texture content hashes.
Signed particle scales retain their mirror flags. SpriteStudio export preserves
the decoded frame's interleaved additive/normal draw order instead of moving
every additive sprite in front of every normal sprite.

Preparation now decodes the complete declared duration, then trims only empty
trailing frames. The two Brave Shift LB sources declare 1,217 and 1,055 frames;
the former 600-frame preparation cap truncated them. Each source audit records
declared duration and empty tail separately.

These corrections **do not** decode emission shape, transform inheritance,
UV animation, animated mesh projection, or native depth/culling. Native symbols
show `RotateParentNodeInfluenceType`/`ScaleParentNodeInfluenceType` and UV
translation/rotation/scaling/flipping modules. These remain necessary before
claiming near-pixel parity. Native tracing of the
normal casting groups 9000110/9000120 confirms that they instantiate the same
whole source BMB twice at different Cocos sorting priorities; there is no
front/back emitter-subset selector on that call path.

Bake version 6 decodes the regular emission schedule from
`NullEmitterNode::ActivateGenerator` at `0x28aa538` and `Update` at `0x28aab70`:
node `+0xdc` is the emission step in frames. Each window (`+0x94`) has
`ceil(window / step)` opportunities, each producing `+0x90` children. The
window repeats `+0x98` times with a `+0x9c` gap between windows. Fractional
steps use the runtime's 1/10,000-frame fixed-point precision. Children repeat
relative to **every** generated parent instance, and node curves start at each
instance's birth; sibling velocities share their actual ancestor instance.
The previous simulation substituted particle lifetime for emission step and
selected just one configured ancestor, losing nested emissions.

All 627 parsed node records in the 45-source Sora preparation use the regular
generator (`+0x100 == 0`). The alternative curve generator, emission randomness
(delay/lifetime/gap variance), spawn shapes and complete transform inheritance
remain unimplemented. The largest Sora source demand with the new schedule is
116 births per emitter and 156 simultaneous decoded sprites, within the 256
preparation budgets. The two long shift LB declarations still yield visible
content only through frames 273/267 in this decoder; unused authoring tail
versus missing behavior cannot be distinguished without a native comparison.

Bake version 7 follows the native scaling selector: null `+0xb4`, quad
`+0x190`, particle `+0x12c`, model `+0x160`. All four native `AssignModule`
routines dispatch through the same 29-entry table. Modes 1/2/3/4/5 select
One/Const/Velocity/AccelVelocity/ValueCurve; adding 14 selects the uniform-X
variant. Mode 6/20 is ValueRandomCurve, currently sampled at the authored mean.
The value, variation, velocity, variation, acceleration, variation vectors are
consecutive float3s at null `+0x1e4`, quad `+0x36c`, particle `+0x30c`, model
`+0x34c`. Constant modules ignore dormant saved curves. Direct curves specify
local scaling and multiply the parent's scale; their amplitude is not an
envelope/absolute-world-size hint. Uniform-X behavior is selected explicitly,
including when the stored Y component is 1.

This fixes a concrete 100x error in `eff_quick_slash_white.bmb`: nodes 3/7/11/14
select ConstX with value 0.7, but the old decoder replaced it with an inactive
curve reaching 70. Native `scaling::init::Const` (`0x28b86d0`),
`update::Velocity` (`0x28b8ea8`), `update::AccelVelocity` (`0x28b8f1c`) and
`update::ValueCurve` (`0x28c6be0`) explicitly clamp negative scaling to zero.
Acceleration uses a half-step velocity update before and after the scale
update (Verlet). The baker uses the corresponding closed-form trajectory;
shrink-to-zero followed by regrowth can still differ from per-step clamping.
Per-instance scale randomness remains at its mean and is reported in source
audits. AddValueCurve/old compatibility modes and types4/7 keep the prior
approximation and are reported explicitly. The 45-file Sora corpus has no
old compatibility modes. The scaling module tables and initializer assembly
are recorded locally under `build/sora-presentation/native-scale-*.asm`.

Bake version 8 also follows native rotation selectors at null `+0xb0`, quad
`+0x18c`, particle `+0x128`, model `+0x15c`. The six float3 parameter vectors
start 72 bytes before scaling: base, variance, velocity, variance,
acceleration, variance. All four native tables select 0=None, 1=Const,
2=Velocity, 3=AccelVelocity, 4=ValueCurve, 6=AddValueCurve for the modes used
by this Sora corpus. Angles and velocity parameters are signed degrees and
degrees/frame; unlike scaling, rotation has no zero clamp. Mode 4 reads slot
2 directly. Mode 6 initializes only the base angle, then integrates slot 3
as angular velocity at each new frame age; saved constant velocity values
are dormant in that mode. Random/old compatibility modes remain unported.

Emitter rotations previously disappeared completely. This made Flash Step's
`sp_20151_barholy` parent1 `+25X` survive despite model10's compensating
`-25X`, and froze standard-cast `sp_20000_activation_01` model14 despite
its selected `+2Z` degrees/frame velocity. These now cancel/animate, with
checks against the actual decoded source fixtures. The existing projection
still adds Euler components instead of multiplying complete parent matrices;
same-axis cancellation is exact, mixed-axis rotations are approximate.
Models use projected images with nearest-degree XY orientation, and plain
sprites still lack the native billboard/quad XY transform. Per-instance
rotation randomness is held at its authored mean and reported explicitly.

Bake version 9 follows native translation selectors at null `+0xac`, quad
`+0x188`, particle `+0x124`, and model `+0x158`. The six float3 parameter
vectors start at `+0x154`, `+0x2dc`, `+0x27c`, and `+0x2bc`, respectively:
base position, variance, velocity, variance, acceleration, variance. Native
null wrappers `0x28aed34` through `0x28aed78` establish these offsets; notably
the actual null velocity is at `+0x16c`, whereas the legacy launch heuristic
started at `+0x170` and remapped its axes.

The native null selector tables at `0x38f1aa0` and `0x38f1850` select 0=None,
1=Zero, 2=Const, 3=Velocity, 4=AccelVelocity, 5=ValueCurve,
6=ValueRandomCurve, 7=AddValueCurve, and 8=AddValueRandomCurve. The decoder
evaluates the selected local displacement using source XYZ units per frame.
Velocity and acceleration use `base + velocity*age + 0.5*acceleration*age²`;
the symmetric half-step update is visible at `0x28b7488`. Modes 5/6 read
absolute position from slot 0 and ignore dormant base values. Modes 7/8
initialize base position and integrate slot 1 as velocity, sampling at each
new frame age; `0x28aefac` selects slot 1 and `0x28cabe4` implements that
integration. Additive integration caches discrete prefix sums during a bake.
Modes 6/8 currently use the authored mean: native per-key random curve
sampling and initial random variance have not been ported. Their stored
variance vectors are retained for that work. Old modes 9–14 and unknown
types retain the explicit legacy fallback.

Selected native translation disables the former unrelated launch/scatter
heuristics, preventing double movement. Dormant slot 1 data is no longer
treated as particle jitter. Rain & Fina LB `100032707` provides concrete regression
fixtures: opposing back-center sweep origins at X `-122/+88`, front-center
origins at `-122/+177`, the front-center glow's `+2 X/frame`, and front-unit
flames with velocity `(3,-8,-1)` and acceleration `(0.2,0,0)`. All of these
positions or velocities were previously omitted. Native wrapper/table
evidence is retained under `build/rain-fina-reference/native-translation-*`.

Local translations are placed through the inherited full affine matrix before
adding the parent's origin; an object's own Y180 rotation must not mirror its
world position. `transform_locator::update::Default` (`0x28af220`) composes
the local `Ry*Rx*Rz*diag(scale)` basis with the inherited matrix and retains
that product. Native scaling updates put local scale at context `+0xf0`;
it is included once in this matrix. Point placement now follows that path,
including noncommuting parent/child rotations and inherited scaling. This
does not replace the separate approximate mesh/billboard projection. Other
coordinate inheritance selectors still need a complete adapter. Rain & Fina's
mode0/mode6 nodes share their parent position/frame; mode6's separate scale
inheritance behavior remains outside this point-placement change.

`render.py --doc` writes `<out dir>/doc.json` in the shape
`tools/ffbe_effects/to_ss6.py` consumes. `--repeat N --interval F` plays the
file N times F frames apart as one clip (FFBE groups spawn one file
repeatedly: Firaga's flame x 7), `--exclude a,b` leaves emitters out of the
bake; `layer_spec.py` maps an `ffbe_effects` entry (`repeat`, `interval` in
seconds, `exclude`, `max_units`) onto these and names the doc folder
`doc_<stem>[__x<N>i<F>][__ex<a>-<b>]` so option variants never share a cache:

```json
{"fps": 60, "frameCount": N, "pixelsPerUnit": 2.4, "originWorld": [0, 0],
 "textures": ["10Ariana_heart.png", "..."],
 "frames": [[{"tex": 0, "uv": [0, 0, 128, 128], "pos": [12.5, 40.0],
              "scale": [0.47, 0.47], "rot": 0.0, "alpha": 0.35,
              "blend": "mix", "flipX": false, "flipY": false}]]}
```

* `uv` is in texture pixels; sub-rects are not decoded, so it is always the
  whole image and `scale` is `spritePixels / textureSize`.
* `pos` is in pixels with **+Y up**, measured from `originWorld` (default the
  effect origin, world 0,0 - the unit's feet). The PNG frames use the same
  pixels-per-unit; their canvas additionally recentres on the content bounding
  box, and `_info.json` records that offset as `canvasOriginPx`.
* `--ppu <float>` fixes the scale instead of auto-fitting, so several layers of
  one effect (back / back_unit / front / front_unit) share one coordinate
  system. Without it a single runaway emitter can squash the auto-fit until
  every other sprite rounds away to sub-pixel.
* `--max-sprites` (default 64) caps the sprites per frame, dropping the
  faintest (lowest `alpha x area`) first.
* Native Quad `color4` uses selector `+0x194`, independently of texture
  color scale at `+0xF8` and alpha selector `+0x198`. Constant modes 1/2 use
  RGB at `+0x68`; modes 5–20 use four RGB vectors in native vertex order
  TL/BL/BR/TR at `+0x68/+0xA8/+0xC8/+0x88`. CurveFlat modes 3/4 select
  slot 19 (`Curve<3>`), replacing the constant. The exporter uses each
  variance range's authored center as its fixed variation. Native corner
  alpha fields are not multiplied into RGB: `color4::make_vertex::Const`
  copies 12 floats while the separate alpha module provides transparency.
  Nonuniform corner RGB becomes a `quadcolor__*.png` synthetic texture,
  interpolated over the source's two triangles. UV mirror tiles use the
  corresponding subregion of the original gradient. Texture resolution may
  increase to 64 pixels to retain a gradient over a tiny white source image;
  its world size stays unchanged. Native partial alpha curves are valid,
  including the NV border's final zero key at normalized time `.975`.
* Model emitters are exported with a synthetic texture
  `mesh__<model>__<texture>__x<rx>_y<ry>.png`, rasterised once into
  `build/effects/textures/` (the renderer's `TextureCache` resolves the
  `mesh:` key; `to_ss6.py` looks in that directory too).
* A mirror-tiled emitter (section 3.4) becomes 4 sprites with alternating
  `flipX` / `flipY`, so the sprite count per frame can quadruple; the
  `--max-sprites` cap absorbs that.
* `flipX` is set when an ancestor node carries the 180 degree Y rotation
  described in section 3.3 (and the sprite's x is negated to match).

### Decoder 10: recorded Crimson Judgment corrections

The Rain & Fina reference exposed several independent errors. Transform
slots 0–5 are native `Curve<3>`; valid single-key and partial-domain curves
must not be discarded for failing to span normalized time 0–1. Mesh
rasterization bounds and half-extents are computed after the authored X/Y
tilt. An XZ disc rotated 90 degrees about X then has its full XY extent,
rather than being clipped against its original zero-height plane.

GPU blend selection is separate from alpha selection. Confirmed field
offsets are Quad `+0x720`, Particle `+0x690`, SimpleParticle `+0x238`,
Model `+0x6D0`, Stripe `+0x698`. Native mode 1 is source-alpha mixing,
mode 2 source-alpha additive, and mode 3 multiplies destination by
`1-sourceAlpha`; a black sprite with the same alpha and normal mixing
reproduces mode 3 exactly. Other GL factor combinations still need their
own material handling. All selected Rain & Fina emitters use modes 1–3.
The full pointer chain and native GL factor table are recorded in
`build/rain-fina-reference/native-blend-evidence.md`.

Emitter generator delay and delay variance are signed integers at Quad
`+0x154/+0x158`, Particle `+0xF0/+0xF4`, Model `+0x124/+0x128`.
Activation initializes a negative fixed-point generator clock; update waits
until it reaches zero. Delaying a particle birth must not delay ancestor
locator clocks. Crimson Judgment's final white and gold flashes provide
nonzero-delay fixtures: parent birth 84 plus delays 188/200 gives births
272/284. Their source lifetimes are 44 frames.

`bake(..., canonical_variation=True)` selects a reproducible transform
variation using the native base/variance ranges. Samples are cached by
source, seed, repeated copy and complete ancestor instance lineage.
Supported constant/velocity/acceleration payloads use
`base - variance + 2*variance*U`; uniform scale consumes X for all axes.
This is an accepted fixed variation, not the original runtime's RNG stream
or the seed used by a recorded battle. Unsupported random-curve modules
remain approximate. Other bake callers retain their previous variation
policy unless explicitly opted in.

Decoder 11 also decodes Model primary texture color scaling. Selector
`+0x188` chooses neutral (0), constant RGB `+0xA8` (1), or `Curve<3>`
descriptor `+0x6B0` / slot 20 (2). Its valid partial-domain curves multiply
the primary texture color. Crimson Judgment model emitters 49 and 55 shift
from blue toward gold through this channel; treating slot 20 only as generic
color variance left their rims pale. This is separate from model vertex
color selection and the still-incomplete secondary texture path.


### Native FFR SpriteStudio serialization and validation

Decoder 15 supports resource-free type-3 Particles. On the original GL 9.1.0
ARM64 binary (SHA-256 `01d2aa87a9ce893b071a044a048af179eac3caae0147065e8ca398e1adb7d051`),
shader selector `0x289C3D4` chooses vertex/fragment shader 0 when both particle
resource pointers are absent and no texture operation is selected. Its fragment
shader emits interpolated vertex color multiplied by the global color scale;
it performs no texture lookup. A generated opaque white cell is therefore a
neutral transport for the authored vertex RGB and independent alpha channels.

Particle color1 is selected at `+0x130`: 0 no module, 1 Const, 2 ConstSync,
3 Curve, 4 CurveSync. Constants read RGB at `+0x68`, variance at `+0x78`;
curves read `Curve<3>` at `+0x660` (slot 19). The primary texture RGB at
`+0x98` is unrelated and must be ignored for the resource-free shader. The
`eff_fadeblack_a50_f90` and `a75` fixtures both select constant black with
zero variance. Their dormant white-to-black slot-19 curve must not override
that selection. The independent global-alpha curve supplies their 50%/75%
fade with authored interpolation and timing. This path does not reinterpret
existing textured particles. Evidence: `build/sora-final-audio/untextured-native/`
contains the original shader strings, relocation-resolved enum tables and both
source checksums; `tools/tests/test_ffbe_untextured.py` checks their actual
decoded RGB, alpha ramps, geometry and exported cell transport.

Decoded FFBE frames and an offline comparison do not validate the cooked FFR
player. The host uses SpriteStudio 6 version 1.6.20; its typed value accessors
must be reproduced by independent readback checks.

* Nested `Cell.mapId` is `IntType` with an int32 payload. A FloatType payload
  with empty conversion caches reads as page zero in the native integer
  accessor, although a permissive JSON comparison can appear to pass.
* Effect animations explicitly select `Priority` sorting. Native character
  donors may select Z sorting, whose equal-depth ties reverse model indices.
* Additive parts use a neutral `PartsColor` Setup key (Whole, Mul, white,
  rate 1) to select native AddMul instead of the game's emissive-boost branch.
  Whole/Mul are typed integers, `color` is a nested hash, `rgba` is ColorType,
  and `rate` is FloatType. Native `SsColor` has **four uint32 channels**, each
  constrained to 0–255. Four byte channels corrupt the subsequent value.
* Optional `runtimeViewport` expands screen layers around an explicit source
  center at cook time. Its horizontal stretch affects root Sclx and adds
  `runtimeScale * centerX * (1-stretchX)` to root Posx; all source child keys
  stay unchanged. Neutral root position/scale keys must be explicit. This
  adapter lets a wider host camera preserve character proportions.
* Optional `runtimeScale` is a positive finite host multiplier applied only
  to explicit root Sclx/Scly keys, including inherited Setup keys. Source
  texture pixels, part geometry and source timing remain unchanged. All
  layers sharing a stage must use the vision's host scale consistently.

The native donor `unit0030` supplies the byte-level ColorType fixture, and
malformed map-index and color-layout assets are retained as failing controls.
See `tools/tests/test_effect_cellmaps.py`,
`tools/tests/test_effect_parts_color.py`, and
[the actual-game verification record](../../docs/35-rain-fina-native-playback.md).
Validate loading, complete action playback and cleanup in the game before
marking an exported presentation accepted or extending it to a bulk release.
