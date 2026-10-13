# FFBE resonances

## Studio build 11

The user confirmed the common opening sound and requested the tested presentation as the Studio default.
Build 11 enables native host-format audio on new imports, ships both FFBE sound banks and decoded LB masters,
and extracts the installed game's audio settings on first use. Imported Cloud/Terra/Warrior of Light CG settings
migrate to the vision's own LB. See [build 11 notes](14-build-11.md) for validation and remaining coverage limits.

## Current local test: common LB opening sound

The user identified the missing charging sound by listening to `se_battle_limitopen_1` and confirmed the preview.
It is System.acb cue 45, waveform row 41 / AWB ID 14: 95,488 mono samples at 48 kHz, about 1.989 seconds including its tail.
The FFBE binary's `MissionBattleManager::touchEndedChild` checks reserved command 6 at `0x1426470`, then calls
`LapisSoundPlayer::playSystemSe(45)` at `0x1426480`. This common cue is separate from each unit's effect-group sounds;
Raegen's `se_slb_charge` at LB frame 6 was already imported.

`ffbe_audio.prepare` now adds the opening once at LB frame 0 for native audio, after approach and aligned with `LB1` at
0.5 seconds in the current FFR sequence. The source sound/hit lists remain unchanged. A shared single-recording bank uses
the confirmed host HCA format and 0.15 gain. The full source recording is retained without trimming or stretching.

The older System.acb uses `CommandTable` and waveform `Id`; the reader now supports those fields alongside the newer
`TrackEventTable` / `MemoryAwbId` schema. These layouts are also described by
[vgmstream's ACB reader](https://github.com/vgmstream/vgmstream/blob/master/src/meta/acb.c).
Bank building expands shared dependencies before deduplication. Units without effect-group sounds can still receive the
common opening. `lb_charge: false` disables this addition; `audio_system_bank` selects a local System.acb explicitly.
Default lookup checks beside an explicit SE bank, then `data/ffbe/audio/System.acb`, then the local JP export.
Missing automatic sources emit a build message; missing explicit paths fail the build.

Installed test: `build/lb-charge/package`, based on the confirmed package below. All 37 regression tests pass and all
61 assets survive packing/extraction. The extracted schedules contain exactly one opening at `LB1`; every prior event,
duration, damage/field asset and attack bank is unchanged. The new bank passes bulk loading/registry checks, and vgmstream
decodes its host-format audio sample-for-sample to the source WAV. `build/lb-charge/verification.json` records the checks;
`install.json` records the hash-verified installation and backup. In-game validation is pending. Installed/hosted Studio
has not been updated.

## Confirmed local baseline: 200-unit spacing and host HCA format

The user reported that the 60-unit shift was still too close and the native one-shot bank still sounded distorted.
They confirmed the extracted FFBE sword preview sounds normal. `build/lb-sfx-reference/package` changes the default
right shift to 200 and adapts the selected recordings to FFR's HCA format. On 2026-09-07 the user confirmed this
package works and moved the task to attack effects. This is the working baseline for the effect port.

Comparison with the existing `SE_BTL_PP` bank found all 740 FFR streams use HCA 3.00, cipher type 56, four-byte AWB IDs
and AWB subkey `0xf79b`. FFBE uses HCA 2.00, cipher type 0, two-byte IDs and subkey zero. FFR's extracted
`DefaultEngine.ini` supplies its CriWare decryption key. The executable identifies its HCA decoder as version 3.10.00.
The combined host-format adaptation passed the user's game test; the contribution of each individual difference
has not been isolated.

`audio: "native"` with `audio_codec: "host"` enables the new test path. `hca_host.py` promotes only mono v2 recordings
without stereo coupling, HFR, loops or extra chunks; their encoded spectral data has identical v2/v3 interpretation
when minimum resolution 1 is retained. It applies type-56 encryption with the host key and AWB subkey, masks the header
tags and updates every checksum. Unsupported layouts fail instead of receiving a blind version edit.
The [vgmstream decoder](https://github.com/vgmstream/vgmstream/blob/master/src/coding/libs/clhca.c) documents these
version-dependent fields; its [key setup](https://github.com/vgmstream/vgmstream/blob/master/src/coding/hca_decoder.c)
describes the AWB subkey calculation. No new runtime dependency is required.

All 17 selected recordings decrypt and decode sample-for-sample to the originals. Their encryption independently
matches CriCodecs 1.2.0; vgmstream also decodes all 24 cues across both complete banks to the original PCM.
All 30 regression tests pass, and all 60 packages extract without failures. Cooked event schedules and loading metadata
are verified. Checks and native SFX/header inspection are saved in `build/lb-sfx-reference`; `install.json` records
the three installed, hash-verified files and their backup.
The new package preserves damage, hit/sound frames, colours and cleanup. Installed/hosted Studio remains deferred.
Attack-effect investigation and the native Cross-slash comparison are recorded in [13-lb-effects.md](13-lb-effects.md).

## Default resonance

The user confirmed damage in `build/lb-data-test/package` is correct. The later `build/lb-native-audio/package`
preserved damage but its 60-unit shift and audio failed the game test; it is superseded by the host-format test above.

The default for imported visions is an authored event-only sequence: own LB motion, element-derived field tint,
source hit reactions, vision-only approach/return, and grading/camera cleanup. No Cloud movie is played.
Cloud's cooked Cut package supplies the serializable event binding; it does not supply the choreography.
Both target variants point to the authored Master. `presentation: "template"` retains the advanced native-sequence path.

### Source mechanics

`tools/ffbe_lb.py` joins the exact form's `F_UNIT_MST.lb_id` with `F_LIMITBURST_MST` and effect-group rows.
It preserves each effect component's target/range and selects damage hits independently of buffs/debuffs.
Schema-2 manifests include raw rows, elements, movement offsets, effect groups and sound cues.
Old timing-only manifests are upgraded from source instead of hiding newer metadata. `ffbe_lb_id` selects a valid variant.
Data comes from packaged masters or the decoded local JP tables, then a wiki datamine fallback. The release pack builder
now includes all three master tables. Datamine fallbacks report unavailable movement offsets and sound references.

`mechanics: "ffbe"` is the default. Studio and the build use the same resolver (`GET /api/ffbe/lb/{form}`).
Supported damage components set target, physical/magic type, element/icon, hit count, per-hit weights and description.
The total base power is Cloud's skill 440110 magnification of 36. Its level scaling (effect 12966), critical bonus
(effect 13301), accuracy and critical rate are retained. The source hit weights sum to one, so adding hits does not
multiply the total power. Actual damage still depends on ATK/MAG, target defence/resistance, levels and criticals.
FFBE buffs/debuffs are recorded in the dump but are not imported by this adapter.

Automatic mechanics currently support one physical or magical damage component, up to 30 hits, targeting one/all enemies.
Unsupported cases require review or explicit `mechanics: "custom"`; they do not silently inherit a donor's mechanics.
FFR's `eElement` field is a scalar, so multi-element damage is flagged for review. The full element list is retained and
its field colour can still be blended. Healing, hybrid, unusual movement and multi-component damage need additional adapters.

### Field colour

`field_color_mode: "element"` is the default, including old specs without a mode. No attack element uses grey `#808080`.
Distinct elements blend equally in RGB: ice `#00FFFF` plus thunder `#FFFF00` gives `#80FF80`.
`field_color_mode: "custom"` applies the user's six-digit `field_color` instead. Studio retains the custom picker.
Private grading rows use the resonance skill ID. Tint gain is softened with neutral light so the battle stays readable.
Studio source advertises catalog schema 8; the installed/hosted Studio has not been deployed for this test.

### Movement

The FFBE engine has **separate normal-attack and LB offsets**. UnitMst `MoveOffset` stores two Vec2s:
normal first, LB second. `BattleCharacter::getMoveOffset(int)` at 0x13c35b4 selects +0x1c8 for action type 6,
and `UnitMst::getMoveOffsetLb()` at 0x1c43a80 returns that field (normal is +0x1c0).
Evidence: `T:/Projects/FFBE Patch/tools/workspace/apk-decoded/lib/arm64-v8a/libgame.so`.
This corrects the earlier assumption that UnitMst's offset applied only to regular attacks.

FFBE horizontal maps to FFR +Y (party side); ground depth maps to -X. The new sequence leaves native combatant spacing
**enabled** (`Unit_MoveToTarget_IsDisableOffset=false`) and adds the LB-specific offset plus 200 on Y. It does not measure the sprite
or animation bounds. It moves the vision, then returns the vision to its default location after LB1.
FFBE move type 1 approaches; type 4 stays in place. Other types require review. Source MoveSpeed/wait are preserved;
the adapter still uses 12 native FFR frames for approach/return, so cross-engine travel speed is not yet resolved.
`movement.right_shift` can override the extra 200. An explicit `movement.target_offset` remains absolute unless
`right_shift` is also supplied. The source dump retains the original FFBE offset separately.

| Unit | Form / selected LB | Damage target | Hits | First/last frame | Element / field | FFBE LB offset | FFR additive ground offset |
|---|---|---|---|---|---|---|---|
| Raegen | 100045807 / 100045800 | One enemy | 24 | 58 / 206 | Fire / red | [40, 0] | [0, 240, 0] |
| Lasswell | 100045307 / 100045307 | One enemy | 27 | 30 / 184 | Water / blue | [40, 25] | [-25, 240, 0] |

Raegen's LB IDs 100045800/801/802 are fire/ice/thunder variants. They share hit and sound timing.
Frames are at 60 fps relative to LB motion start; the authored FFR sequence begins LB1 at 0.5 seconds.
Validation: 28 Python tests passed. All 58 assets survive the container round trip. Extracted damage assets match the
previous package exactly; cooked events match source hit/sound frames, the extra 60 on Y and complete cleanup.
Both new banks pass bulk-resource validation after extraction; embedded ACB bytes and cue names match the authored banks.
`build/lb-native-audio/verification.json` records the checks, and `install.json` records installed hashes and the backup.
No Flutter source or installed/hosted Studio changes are included in this test.

### Dump and audio investigation

The following audio measurements describe the earlier `lb-native-audio` test. Its distorted playback was subsequently
resolved by the host-format package above. The source dump remains current. Audio is still opt-in in the code;
the successful local test has not yet been promoted to the installed/hosted Studio defaults.

Run `python -B tools/dump_ffbe_lb.py 100045807 abilities/raegenultimatesummon_lb`.
The folder contains `LB_DATA.md` (readable mechanics, movement, hit and sound tables), `source.json` (all variants,
raw rows, effect-group flags, min/max-level datamine cross-check), and `resonance.json` (selected source for the builder).
Existing `effects`, `textures`, `meshes` and decoded WAV `sounds` remain beside them. Lasswell has an equivalent folder.
These source game exports remain under the repository's ignored `abilities` folder; the reproducible dumper is committed.

The user's CPK extractor was located at `T:/Projects/FFBE Patch/cpk_2/DataExtractor.exe`.
The selected sound source is already a loose `SE.acb`, with 868 embedded HCA streams. All 868 declare cipher type 0
(unencrypted). The dump records the source SHA-256, cue IDs/names, frames, group offsets, durations and all resolved wave headers.
CPK file encryption does not explain these HCA headers. The cause of the distorted FFR playback remains unresolved.

`acb_cues.py` now resolves reference type 3 as a sequence and type 2 as a synth, following
[vgmstream's ACB parser](https://raw.githubusercontent.com/vgmstream/vgmstream/master/src/meta/acb.c).
The old lookup incorrectly treated type 3 as a synth, which produced incorrect waveform metadata. This finding alone
does not establish the cause of the old bank's distorted runtime playback.

The local specs opt into `audio: "native"`. `acb_native.py` rebuilds only the selected recordings using FFR's ACB 1.42.1
table schema and single-track cue structure. It supports immediate single-wave cues and equal-weight random alternatives;
each alternative gets its own named cue and repeated triggers cycle through them. Layered, delayed and unsupported graphs
are rejected. FFBE's old cue-limit/work indices, pitch commands and mobile routing are not imported.

The new banks use FFR's SE category (3), MasterOut and a conservative 0.15 gain. The source HCA bytes remain unchanged.
Cue 181 uses HCA-MX metadata; the adapter selects standard HCA playback for it. CRI documents that
[HCA-MX uses the same HCA stream format](https://game.criware.jp/manual/native/adx2_en/latest/criatom_feat_voice_codec.html),
but needs a [separate voice pool](https://game.criware.jp/manual/native/adx2_en/latest/craftv2_tips_program_decide_codec.html).

Raegen uses 9 recordings across 16 triggers; Lasswell uses 15 across 32. Across both banks, all 17 distinct recordings
decode byte-identically to their original HCA streams in vgmstream. Offline mixes at the configured gain peak at 0.376
and 0.471 of full scale, respectively, with no clipping. These are decoder/level checks, not proof of correct FFR playback.
Previews and decode results are in `build/lb-native-audio`; the user's next test must confirm the in-game audio.

LB sound playback remains **disabled by default** until validation. `audio: "experimental"` retains the rejected full-bank
routing path for diagnostics only. The unused old bank remains in this test's baseline assets. Particle effects remain deferred.

## Earlier startup and audio investigations

The following records describe previous test packages, not the current default.

### Startup crash correction

The user's two 2026-09-07 01:38 crash reports fail on `FAsyncLoadingThread`, zero seconds after startup. The minidump shows
a bulk-data copy of `0x0500ef20` (83,947,296 bytes), exactly the native `SE_BTL_PP` bank's length. The replacement FFBE ACB is
25,546,272 bytes. Its `DataResources[0]` still declared the donor size and offset, despite the payload bytes being correct.
The bulk reader therefore overran the replacement export before the game reached its menu.

The four bytes preceding `@UTF` select a **data-resource index**, not an unused serialization prefix. `patch.atomBanks` now
updates both `SerialSize` and `RawSize`, serializes the new cue properties, then measures and updates the export-relative
`SerialOffset`. In this test the offset changes from 108,433 to 57,470. The writer checks the final loading metadata and ACB
header before accepting the asset. `ffr-dt check-atom-bank <asset.uasset> --usmap <mappings>` exposes the same check separately.

The previous checks validated ACB bytes and generic asset/container parsing; those checks did not validate the bulk resource
Unreal actually reads. Regression coverage now reads the raw `.uexp` using the resource bounds, verifies it equals the source
ACB, and rejects independently stale offsets, serialized sizes and raw sizes. The new checker also rejects the preserved
crashing bank with the exact donor/replacement mismatch from the minidump.

`build/lb-startup-crash/package` is the corrected local test. Compared with the crashing build, only the private bank's
`.uasset` header differs; the `.uexp`, sound cues, movement, hit settings and colours are unchanged. Container verification
passes, all 56 packages extract, and the extracted bank passes the bulk-resource check. The previously confirmed working
package was restored before this investigation and remains available for rollback. **The user confirmed startup, the red/blue
fields and vision movement work.** Sound was still silent and the vision stood too close to the enemy. Its `install.json`
records the test installation and working backup.

### Spacing and audio routing test

The recording `Screen Recording 2026-09-07 102253.mp4` shows Lasswell overlapping the target during his slashes.
The default target offset is now `[-240,0,0]`; an explicit `movement.target_offset` still wins. FFBE supplies the move flag,
not this distance, so the new spacing needs a game check.

Static inspection of the demo's battle-event dispatcher confirms `SoundPlayHitSound` calls the sound manager's named-cue
playback path (event 85). The manager loads banks listed in `DT_SoundCueSheetAsset`; the private bank was already in both
the base and demo registries. The original FFBE ACB, however, declares `BATTLE`, `SYSTEM`, `JINGLE` and `BGM` categories and
`BUS1` through `BUS7`, while the native FFR battle bank declares `SE` (ID 3), `SE_BTL`, `MasterOut`, `BUS_INDOOR` and
`BUS_CRITICAL`. These are different audio configurations. CRI's [bus API documentation](https://game.criware.jp/manual/native/adx2_en/latest/group__ATOMEXLIB__PLAYER.html)
also specifies that sends to missing DSP buses are invalid. This is a concrete compatibility issue, **not yet a confirmed
explanation of all the silence**.

`tools/ffbe_effects/acb_routing.py` now removes sends to the FFBE-only buses and remaps category commands to FFR's shared
`SE` category. It declares only `SE` and `MasterOut` in the ACF reference table. The builder checks the host's native bank
for those resources and writes the adapted bank to its staging directory. Source files remain intact. Only the three
command tables and the ACF reference table change: the entire embedded AWB, cue names/IDs, graphs, hit timing and all other
commands stay byte-identical. Existing cue gains and MasterOut sends are preserved. Bulk-resource validation still applies.

`build/lb-spacing-audio/package` contains this next local test. Only the two Master `.uexp` files and the private bank's
`.uexp` differ from the last confirmed package. Red Raegen and blue Lasswell retain their source hit and sound schedules.
Regression coverage checks the cooked offset, explicit overrides, malformed commands, unchanged samples/graphs and the
absence of foreign bus/category commands. **Audible playback and the new spacing remain pending the user's game test.**

The previous Cloud trim passed structural checks but failed the user's game test: donor audio played and the battle stayed
orange. It is superseded as the default. Its Master had an opaque cooked schedule, and the trim did not rebuild that schedule;
this is a suspected contributor, not a proven explanation of the runtime failure.

Validation: real cooked assets round-trip with matching editor/cooked event schedules, correct function bindings, complete
motion windows and cleanup before the end, no donor movie/sound dependencies, both target variants and isolated colour rows.
Short and long LBs and a supportive mechanics donor are covered. `python -B -m unittest discover -s tools/tests -v` runs these
checks. UAssetAPI loses private object-locator state on a full JSON round-trip, so `patch.sequenceData` overlays only authored
properties onto the binary-read shell. Its Vector4 constructor also required explicit component assignments.

Local test package: `build/ffbe-resonance-test/package`, built from the user's two-unit engine output. Only two Masters and
four presentation tables are changed/added; other units, abilities, sprites and settings are preserved. Raegen's LB lasts
4.20 s (sequence 5.90 s); Lasswell's lasts 3.63 s (sequence 5.33 s). Both use orange for the first gameplay test. Container
validation reports 53 assets, zero failures. **The user confirmed this initial timeline worked.** Installed Studio and hosted
releases wait for the movement/audio test above. `build/ffbe-resonance-test/install.json` records the initial installation
hashes and previous package backup.

## Earlier template implementation

Written 2026-09-05 (v29.2). Everything here was read from the generator, the engine and the game's own sequence packages on
that date; the template timelines in section 4 were measured from the extracted `_Cut` / `_Effect` / `_Sound` packages.
Read `docs/08-data-locations.md` for where the files are.

## 1. What a Resonance is in the game's data

A vision's Resonance is its "finish blow" skill. The pieces, in the order the game resolves them:

| piece | table / asset | what it holds |
|---|---|---|
| the vision row | `DT_VisionItemData` (`finishBlowSkill`) | which skill id is this vision's Resonance |
| the skill row | `DT_SkillData` (attr `FinishBlow`) | name, description, icon tag, element, damage type, target type, magnification, hit count, effect list: the **mechanics** |
| the battle visuals | `DT_SkillAsset` / `CDT_SkillAsset_Demo`, keyed by *sequence id* = skill id + 1 (single-target variant) and + 2 (group variant) | the `LevelSequence` (Master) and the sound sequence to play |
| the sequence packages | `Sequencer/Battle/Skill/<skill>/<seq>/SEQ_Battle_<seq>_Master` + `Track/…_Cut`, `…_Effect`, `…_Sound` | Cut = unit motions (`UnitPlayAnimByName`), moves, camera; Effect = Niagara spawns, tints, blur, DoF; Sound = SE cues and `VO_` voice lines |
| hit reactions | `DT_BtlHitEffectData`, keyed by skill id | hit / critical / weakness effects on the targets |
| caption lines | `Datatable/Event/Text/BattleSequencerEvent/DT_BtlEv_<skill id>` (`TalkEventRowData`) | the dialogue windows shown during the cinematic; speaker is **Wol** (the protagonist), text from `ST_BtlLegendCGMV`. Tables exist only for the 17 shipped Resonances (ids 4400xx) |

Skill ids are not free: a custom skill outside the derived range played its mechanics but no motion or hit effects (v10). The
generator therefore puts every unit's Resonance at `lb_id(vid) = 440000 + (vid - 13099) * 10` (Cloud 13110 = 440110, Lightning
13125 = 440260) and its unique abilities at `445000 + (vid - 13100) * 100 + 10 * slot`.

## 2. Two ways a unit gets a Resonance

* **Borrowed** (`unit.lb`, an existing skill id): the vision row points at another vision's Resonance as it is: its name,
  mechanics, animation, captions. Nothing is cloned. The engine's default is `lb: 440090` (Terra's Riot Blade - Lotus) but every
  unit made by the app or the web Easy mode gets `lb_custom` at once, so this only matters when `lb_custom` is removed
  (web Advanced: "Use a borrowed Resonance instead").
* **Own** (`unit.lb_custom`): the generator clones a mechanics row (`from`) under `lb_id(vid)` with the unit's name and
  description and the `set` overrides, clones the caption table of `caption_from` under the new id, copies the `DT_SkillAsset`
  rows of the `visuals` template shifted to the new id, and, with `clone_sequence`, copies the template's Master / Cut / Effect /
  Sound packages to `Sequencer/Battle/Skill/<lb_id>/<lb_id + off>/` and edits the copies (mute, swaps, edits, stretch, FFBE
  effect spawns). The hit-effect row is copied from `visuals` too.

## 3. `lb_custom` field reference

| field | meaning | set by |
|---|---|---|
| `from` | skill id whose `DT_SkillData` row is cloned: power, hits, extra effects, default element / damage type / targets | app + web Easy ("Numbers like"), web Advanced ("Effect"), copy-a-vision |
| `visuals` | skill id whose battle sequence and hit effects are used; one of the six templates in section 4. Falls back to `from` | app + web ("Animation"); engine default 414090 (414100 for supportive units) |
| `clone_sequence` | copy the template's packages instead of pointing at them (needed for every edit below) | always `true` from the app / web |
| `jp`, `en`, `desc`, `descAuto` | row name (`jp` is the row key, unique), display name, description; `descAuto` regenerates `desc` from the mechanics on every change | app / web |
| `set` | column overrides on the cloned row: `element`, `DamageType` + `damageCalcType` (`Physic` / `Magic`), `TargetType` (`Single` / `Group` / `Random`), `SkillIcon.TagName` | app / web (kind, damage, element, targets pick these); web Advanced adds icon |
| `caption_from` | which `DT_BtlEv_<id>` is cloned (4400xx ids only). Default 440260 = the lines Wol says during **Zantetsuken**; 440240 for supportive defaults; the mechanics' own id when it is a 4400xx Resonance | web Advanced ("Caption lines"); the app has no control |
| `mute` | cue-name prefixes silenced in the copied Sound track; `["VO_"]` removes the template owner's voice lines | app / web default; web Advanced toggle |
| `sound_swaps` | `[[cue name, "/Game/Sound/…/NewCue"]]`: a section plays another cue (Ariana: Tronn's LB cue -> Leah's) | hand-edited `units.json` only |
| `sequence_edits` | `{master \| cut \| effect \| sound: [{match, set, skip_earliest?, enable_track?}]}` edits to the director-blueprint event constants; the default entry recolours the domain (`OtherChangeSubSpaceColor`, and re-enables that disabled track) | app / web write the domain colour; web Advanced colour picker; hand edits for the rest |
| `effect_swaps` | `[[old Niagara path or name, new]]` rewrites the template's effect references | web Advanced ("Effects" table); reset to `[]` on every animation change |
| `tint` | `DT_ColorGradingParameter` id applied to the copied sequence's colour-grading events | web Advanced ("Screen tint") |
| `stretch` | `"auto"` (default when absent), `false`, or seconds: how far keys after the last `LB1` trigger move, see section 5 | web Advanced ("Timing"); the app never writes it, so `auto` applies |
| `ffbe_effects` | Brave Exvius effect layers spawned as SpriteStudio actors (see `docs/06-effect-port-handoff.md`; paused) | web Advanced modal; hand edits |
| `motion` | (skills only) rewrites every Cut motion to one name; not used for Resonances | web Advanced Abilities |

## 4. The six animation templates

Only skills with a shipped battle sequence can be templates (`ffr_catalog.lb_templates`: attr `FinishBlow` and a sequence). Their
Cut tracks, measured from the game files (times in seconds from the sequence start; the unit's own motion names are the FFR
animation names the generated SpriteStudio project provides, see section 6):

| template (`visuals`) | owner, mechanics | unit motions in the Cut track | window for the unit's `LB1` | length | effects / sound |
|---|---|---|---|---|---|
| **414090 Hibernal Fury** | Tronn: random enemies, magic, 5 hits | step_front -0.4, command 0.5, **LB1 1.5** (re-triggered 1.63), idle 6.73 | **5.10 s** | 6.9 s | 12 ice Niagara spawns, 11 radial blurs, 13 colour-grading keys; cues `SE_BTL_PP_MAGIC_CAST`, `SE_BTL_VLB_414090_TRONN`, two `VO_` lines |
| **414100 Healing Wind** | Leah: all allies, heal | magic_idle 0.83, **LB1 1.87**, idle 4.13 | 2.27 s | 4.5 s | 5 spawns (heal aura on the party); `SE_BTL_VLB_414100_LEAH`, `SE_BTL_PP_HEAL`, two `VO_` lines |
| **412600 Resolute Bastion** | Charlotte: all allies, buff | command 0.17, **LB1 1.83**, idle 4.33 | 2.50 s | 5.7 s | 4 spawns; `SE_BTL_VLB_412600_CHARLOTTE`, two `VO_` lines |
| 440010 Crystal Braver | Warrior of Light: all enemies, physical, 5 hits | command 0, step_front 1.33, LB1_before 1.6, idle 3.0, LB1_after 17.97, cushion, step_back, idle 18.97 | **none: `LB1` is never played** | 19.0 s | 3 spawns, 7 chromatic keys; WoL's own SLB cues |
| 440090 Riot Blade - Lotus | Terra: all enemies, magic, 7 hits | command 0, step_front 1.33, LB1_before 1.6, LB1_after01 14.9, LB1_after02 x4, idle 18.23, step_back, command | **none: `LB1` is never played** | 19.2 s | 2 spawns, 19 chromatic keys; Terra's SLB cues |
| 440110 Ascension | Cloud: one enemy, physical, 10 hits | LB1_before 0, **LB1 14.83**, LB1 again 19.17, step_back 19.27, cushion, idle 19.63, step_back 24.03 | 4.3 s between the two LB1 keys, but the auto-stretch sees **0.10 s** (it measures from the *last* LB1 key) | 24.0 s | 6 random + 20 radial-blur keys; Cloud's SLB cues |

What this means for a ported unit:

* **Hibernal Fury, Healing Wind and Resolute Bastion play the unit's Brave Exvius limit-burst motion** (`LB1` = `limit_atk`).
  Hibernal Fury is the only one whose window (5.1 s) fits most units without moving keys; the two supportive templates give
  2.3-2.5 s and rely on the stretch (section 5). The heal / buff mechanics of those two apply to allies, so a *damaging*
  Resonance on Healing Wind visuals heals nobody but its ice-free aura plays on the party while the damage lands.
* **Crystal Braver and Riot Blade - Lotus never call `LB1`.** The unit stands in `LB1_before` (mapped to Brave Exvius
  `magic_standby`) for 15 s while the owner's cinematic effects run, then is asked for `LB1_after` / `LB1_after01` /
  `LB1_after02`, motions the generated sprite project does not contain (they are the owners' hand-made after-poses). What the
  SpriteStudio player does with an unknown animation name has not been checked in the game; at best the unit holds its last
  pose. The unit's own limit-burst motion is never shown.
* **Ascension** plays `LB1` at 14.8 s but re-triggers it 4.3 s later, so `auto_stretch` (which takes the last `LB1` key,
  because Hibernal Fury re-triggers 0.13 s after the first) measures a 0.10 s window and moves every key after 19.17 s by
  the motion's whole length, cutting the second `LB1` short and lengthening a 24 s cinematic further.
* **The three long templates are CG movies.** Their Master sequence spawns `BP_BtlSequencerMovieActor` and plays
  `Movies/Skill/MV_Skill<id>` through a CriWare `MovieSceneManaTrack` for the first 15-17 s; that is what the owner "hitting
  stuff" is. Since v29.7 `clone_sequence` (`movie_ops`) clears the movie sections' source and turns every key of the actor's
  spawn curve off in every copy (with fresh signatures), so an inherited Resonance never shows the owner's movie. The window the movie covered is not removed yet: the unit holds its cast pose
  through it (the "make the Resonance animations look better" roadmap item).
* The template's Niagara effects, camera work, tints, blur and the owner's non-voice sound effects (`SE_BTL_VLB_*`,
  `SE_BTL_SLB_*`) stay as they are unless swapped by hand. The three long templates are the owners' signature cinematics
  (WoL's crystal, Terra's riot blade, Cloud's ascension) drawn around a unit that is not them.

The app does this since v29.3: the three that play the unit's motion come first with a one-line blurb each (`ffr_catalog.TEMPLATE_NOTES`,
served in `lbTemplates` as `good` / `window` / `length` / `who` / `blurb`), the other three sit under a divider "the owner's cinematic,
no limit-burst motion" and show a warning when chosen. The step also compares the unit's motion length (`/api/ffbe/motion/<form>/limitatk`)
with the template's window and says whether the timing fits or is stretched (and that stretched timing is unverified).

## 4b. The default: Cloud's staging without his cinematic (v29.9)

Tronn's and Leah's Resonances play inside the blue domain; Warrior of Light's, Terra's and Cloud's do not, which reads better
for a ported unit. Cloud's (440110) is the studio's default `visuals`, with `make_vision_mod.apply_cinematic` taking the
owner's cinematic out of every copy:

| what | how |
|---|---|
| the CG movie of Cloud | `movie_ops` empties the movie sections and turns the movie actor's spawn keys off; the `UISetVisibility` events that raise the movie layer are set to `None` |
| his caption dialogue | `OtherTalkPlay` and `OtherSetVisibleCaptionWindow` set to `None` |
| the second trigger of `LB1` | the Cut track's later `UnitPlayAnimByName LB1` key set to `None` (`skip_earliest: 1`), so a long motion is not cut off |
| his slashes on the targets | `NS_EF_SKL440110_Slash_001_Root` and `_Finish_001` set to `None`; `_Slash_002_Center` is the slot the player's `target_effect` takes (or is silenced too) |
| the 13.3 s wait the movie filled, and his 4.4 s idle tail | two `frames` ops with negative deltas (tail first, then the window), so the sequence's playback range ends with the action |

Built result (Sakura -Dark Lineage-, thunder burst chosen): `LB1_before` 0 s, `LB1` 1.50 s, dash 1.63 s, hits 1.90-4.83 s,
the chosen burst on the targets 2.43 s, `step_back` 5.93 s, `idle` 6.30 s. `lb_custom.no_cinematic: false` keeps the owner's
version. Not yet watched in the game.

### Local Cloud crash fix (2026-09-06; game test pending)

The installed Raegen / Lasswell Cloud clones had a movie section from 2.0 s to 1.8 s and an inverted sound section.
The matching crash report asserts `IMovieSceneTrackVirtualAPI::RemoveSectionAt`. A negative frame shift had moved section
ends across their starts and left event keys unsorted. Cinematic trims now use `frames` with `cut: true`: remove the interval
`[after + delta, after)`, discard its event keys with their paired values, clip overlapping section ranges, and detach sections
wholly inside the cut. State-curve keys retain their final state at the splice. The idle-tail cut removes 19.7–23.6 s;
the opening cut removes 1.5–14.833 s. Positive stretches keep their existing behavior.

Regression checks: `python -B -m unittest discover -s tools/tests -v` after building `src/ffr-dt`. These use extracted Cloud
assets and check section ranges, event order and values, detached sound sections, movie muting, and positive stretches.
This is a local engine fix only; the app and hosted packs await the user's in-game test.

## 5. Timing: the auto-stretch

`make_vision_mod.auto_stretch` (Resonances only, `stretch` absent or `"auto"`):

1. Measure the unit's limit-burst motion: the sum of the frame delays in `unit_limit_atk_cgs_<form>.csv` (or
   `unit_limitatk_cgs_…`) at 60 fps. Dev units: 2.8 s (Grim Lord Sakura) to 6.7 s (Alice); Sora 5.65 s, Sylvie 5.6 s.
2. In the template's Cut track take the **first** `UnitPlayAnimByName LB1` key and the next key with a *different* motion;
   the gap is the window (v29.3; before, the *last* LB1 key was used, which made Ascension's re-trigger 4.3 s later measure a
   0.10 s window).
3. If the motion is longer than the window, push every key, section range and playback range after the LB1 key by
   `motion - window + 0.2 s`, rounded to 30 fps frames, in the Master, Cut, Effect and Sound packages (`ffr-dt patch` op
   `frames`), and give the packages fresh signatures.

`stretch: false` keeps the template timing; a number pushes by exactly that many seconds. A unit without a `limit_atk` sheet
gets no stretch (and `LB1` falls back to `idle`).

Verified in the game: Hibernal Fury with no stretch needed (Ariana 4.7 s, Esther, Sakura -Dark Lineage-) plays the whole
motion. **Not verified:** a stretched sequence. v18 shipped it untested, v20 found the stretched Healing Wind clone "still ended
early" and moved Ariana to Hibernal Fury instead. Units longer than 5.1 s on Hibernal Fury (Sora, Sylvie, Alice, Snow White)
depend on the stretch and have not been watched in the game since. The FFRProbe F8 trace (sequence player time and duration,
unit sprite state) exists for exactly this check; the probe files are in `build/game_backup/20260905_143543/`.

## 6. What the unit contributes: its own motions

`tools/ffbe2ss6/build_sprites.py` builds the unit's battle SpriteStudio project with the FFR animation names the sequences
call, each from a Brave Exvius `cgs` animation:

| FFR motion | Brave Exvius animation | notes |
|---|---|---|
| `LB1` | `limit_atk` (older sheets: `limitatk`) | the Resonance motion; 3530 of 3607 live sheets have it |
| `LB1_before`, `magic_idle` | `magic_standby` | 3528 sheets |
| `command`, `Lock`, `cushion` | `standby` (falls back to `idle`) | "selected for an action" pose (v20) |
| `idle`, `step_front`, `step_back` | `idle`, `move` | |
| `attack_A..E`, `M_attack01/02`, `magic_attack` | `atk`, `magicatk` | abilities |
| `jump`, `dying`, `dead` | same names | |
| `win`, `Rankup` (+ `_Loop`) | `win_before` + `win`, `win` | menu / victory |

Anything a Cut track calls that is not in this list (`LB1_after*`, `LB1_before` on a sheet without `magic_standby`) is not
in the project. Missing source animations fall back to `idle` at build time; unknown names at play time are the untested case
above. `limitmove` exists on 3 sheets only and is not used.

The animated previews the studio shows (`/api/ffbe/anim/<form>/<anim>.webp`, `render_webp`: lossless WebP at the sheet's
own frame delays, origin fixed at the feet) are drawn from the same `cgg` / `cgs` data, so a motion that looks right in the
preview is the motion the game gets. The preview does not show the template's timing, effects or the stretch.

## 7. Sound, captions, colour

* **Voice**: `mute: ["VO_"]` empties every Sound section whose cue starts with `VO_` (the template owner's lines). The
  owner's sound effects stay. Brave Exvius limit-burst sounds are not ported (the `.acb` banks are located, not wired).
* **Captions**: the dialogue windows during the cinematic are Wol's lines for the *caption_from* Resonance; every Easy-made
  Resonance therefore shows the lines written for Zantetsuken (or, for supportive defaults, 440240). The text itself is not
  edited by the generator; only the table is cloned under the new id so the game finds one.
* **Domain colour**: the default `sequence_edits` recolours `OtherChangeSubSpaceColor` to a blue-grey and re-enables the
  track the designers had disabled. The user did not see the colour change in the game and shelved it (the edit is still
  written; harmless). `tint` (colour grading preset) is the web-only alternative and was seen working for tinted abilities.
* **Hit effects**: copied from the `visuals` template (`DT_BtlHitEffectData`), so a magic template shows magic hit sparks
  even for a physical `from`.
* **Targets**: `set.TargetType` changes who takes the damage; the visuals keep spawning where the template spawns them
  (Hibernal Fury: random enemies). A "one enemy" Resonance on Hibernal Fury still shows five random ice bursts.

## 8. Where it is edited and previewed

| | app (Resonance step) | web Easy | web Advanced |
|---|---|---|---|
| name, kind (damage / heal / buff / debuff), physical / magical, element, targets, "numbers like", description + auto | yes | yes | name, description, effect, element, damage, icon |
| animation template | dropdown of all six (owner's name + skill) | same, plus "Show what happens" | same, plus "Preview sequence" and the effect-swap table |
| what the template does (motions, effects, hits, tints in time order, with this unit's sprites) | **no** (removed in v29.2 in favour of the animated motion) | Storyboard (`/api/seq/<id>`) | Storyboard |
| the unit's limit-burst motion, animated | yes (WebP, arrows to the other motions) | static APNG per motion (Sprites tab) | same |
| caption lines, domain colour, screen tint, voice mute toggle, icon, timing / stretch, effect swaps, FFBE effect layers, borrowed Resonance | no | no | yes |
| Brave Exvius limit-burst name and effects as a hint | no | yes | yes |

The engine's default for a freshly added unit (`server.default_spec`) already names the Resonance after the Brave Exvius limit
burst and uses its effect text as the description; the app's step then switches `descAuto` on at first open and overwrites that
description with the generated one.

## 9. In-game check list

1. Build and install (game closed), start the game, buy the vision in the Mitra item shop, equip it, enter a battle.
2. Select the unit: it should take its Brave Exvius `standby` pose (the `command` motion).
3. Use the Resonance: expect the template's opening (Hibernal Fury: a step forward, the cast pose), then the unit's whole
   limit-burst motion, then the hits / heal on the right targets with the chosen element, then idle. The name, description,
   icon and element in the command list come from the cloned row.
4. Symptoms: motion cut short = window shorter than the motion (stretch not applied or not effective); unit frozen in a
   cast pose for a long time = a template without `LB1` (Crystal Braver, Riot Blade); no motion at all = missing sequence
   rows (the build log prints "borrows visuals from … which has no battle sequence"); silence where the owner spoke = mute
   working as intended.
5. With UE4SS and FFRProbe installed, F8 before and after the Resonance writes a 100 ms trace of the sequence player's time
   and duration and the unit's sprite animation state to the UE4SS log; compare the LB1 key time and the motion length.
