# Mod: Esther & Tsukiko (first custom Visions)

Built by `python tools/make_vision_mod.py` (spec lives at the top of that file). Output `build/out/zzz_EstherTsukiko_P.{utoc,ucas,pak}`,
installed to `<game>/FFRS/Content/Paks/~mods/`. Loads on the next game launch (UE mounts `~mods` paks after the base content, `_P` = patch priority).

## What it adds
| | Esther | Tsukiko |
|---|---|---|
| Vision / unit ID | 13201 | 13202 |
| type, role | Physical Attacker, Thunder | Magic Attacker, Water |
| borrowed sprites, level curve, LB animation | Lightning (13125) | Terra (13108) |
| limit burst (Resonance) | Raikiri 470110 — Thunder physical, 10 hits, x33 | Houki Poki 470120 — Water magic, 7 hits, x33 |
| own skills | Lightning Kick 470111, Voltaic Slash 470112 (3 hits), Storm Rush 470113 (all enemies) | Moon Tide 470121 (x66), Lunar Deluge 470122 (all enemies) |
| shared skills | Thunder/Thundara/Thundaga Surge, Bravery, Haste, Esuna | Water/Watera/Waterga (single + group), Libra, Debrave, Drain |
| passives | Crit +10%, Phys Atk +30%/+20%, Resist/Immune Lightning, Speed +10%, Stagger +20%, Leaping Cleave | Magic Atk +10/20/30%, Resist/Immune Water, MP +10/20/30%, Magic Def +20%, Auto-Faith, Sharp Mind |
| command set / master skill | 301 "Esther's Skills" / 1320100 "Spirit of Esther" | 302 "Tsukiko's Skills" / 1320200 "Spirit of Tsukiko" |
| shop | Mitra item shop (chapter 1 list), 1500 gil, max 1 each | same |

Rows added: UNIT_PARAMETER, VISION_ITEM_DATA, COMMAND_SKILL_DATA, MASTER_SKILL_DATA, SKILL_DATA (7 clones), VISION_AWAKENING_MASTERY (4 tiers each),
VISION_SYNCHRO_MASTERY (10 levels each), UNIT_ASSET_DATA, BTL_UNIT_DESIGN_PARAMETER, VisionUpgradeData; DT_ShopList row `ミトラ_道具　1章` slots 4-5.
Packages cloned + renamed: `Chara/menu/summon<id>` (menu sprite + tex), `UI/Textures/Icon/{Vision_Face,Unit_Face_Timeline,menu}/*_summon<id>`.
ID -> asset maps patched (the UI resolves menu sprites and face icons through these `CPP_DA_RegularIdAsset` data assets, not by path):
`Datatable/UI/Unit/Asset/DA_MenuUnitSsProject`, `DA_UnitIcon_Timeline`, `DA_UnitIconTexture` (+ sprite scale in `UI/Unit/UIUnitSs/Data/DA_UIUnitSsLayout`).
v2 (2026-09-03 evening): price 1 gil; portrait fix above (v1 showed an endless spinner in the vision emblem because the maps lacked the new IDs).
Names/descriptions are literal text (no locres edit), so they show the same in every language.

## Test checklist (next launch)
1. Title screen loads, `ue4ss/UE4SS.log` shows no new errors.
2. Mitra item shop lists Esther and Tsukiko after Smoke Bomb, buy both (1500 each).
3. Vision menu: they appear, can be equipped in place of Lia / Thran, portrait + icon show (Lightning's / Terra's art for now).
4. Battle: command list shows "Esther's Skills" / "Tsukiko's Skills", skills deal Thunder / Water damage, Resonance plays (borrowed LB animation).
5. Awakening / synchro screens open without crashing.

## Rebuild / tweak / uninstall
* edit the specs in `tools/make_vision_mod.py` (stats, skills, tiers, prices) and run it again — it regenerates `build/visions_mod/patch.json`, patches the tables with `ffr-dt patch`, packs with retoc and reinstalls.
* `--no-install` builds only. Verify with `dotnet src/ffr-dt/... rows build/visions_mod/assets/FFRS/Content/Datatable/Item/Vision/DT_VisionItemData.uasset x.json --usmap extracted/Mappings.usmap`.
* uninstall: delete the three `zzz_EstherTsukiko_P.*` files from `FFRS/Content/Paks/~mods/`. Do it before loading a save that owns the visions, or the save will reference item IDs the game no longer knows. Save backup: `backup/saves/` (Steam userdata 205227389/4474710).

## v3 (2026-09-03 night): own sprites
Battle + menu SpriteStudio projects and textures are generated from the FFBE sheets (`tools/ffbe2ss6/build_sprites.py` ->
`ffr-dt make-ss6` / `make-texture`), no editor involved:
* `Chara/summon/summon<id>/summon<id>` (Ss6Project, 25 animations mapped from the 12 FFBE cgs files, 60 fps, origin at the feet),
  `_tex` (BGRA8 atlas 2048x2048 / 2048x1024), `_normal` (flat BC5 128/128), `_mreo` (flat 60/120/0/0 sampled from Cloud)
* `Chara/menu/summon<id>/summon<id>` + `_tex` (Rankup/Lock/idle/win/win_Loop, 512x512 / 512x1024)
* the model (part tree with the NULL_* attachment parts) is the donor's; only `part_0` shows cells, NULL_Head/Center/Weapon/Magic are
  keyed to fixed points above the feet
* UNIT_ASSET_DATA rows point at these packages; the DA_MenuUnitSsProject map points at the generated menu package
Expect: flat-lit sprites (no per-pixel normal/material yet), FFBE effects baked into frames, attack_A..E all play the FFBE `atk`,
LB1 plays `limitatk`, win/Rankup play `winbefore`+`win`. Timing of hits is whatever the game derives from the skill sequencer.

## v4 (2026-09-03 night): icons, uniform menu scale, Ariana + Katy
* Vision face icons (Vision_Face + Unit_Face_Timeline 128x128) and the command icon (ICON_Ability 64x64) are generated from the FFBE
  `unit_icon` painted into the game's frame (`tools/ffbe2ss6/build_icons.py`; mask = pixels that differ between donor icons).
* All converted units use menu sprite scale 2.52 (Esther was inheriting Lightning's 1.8 override and looked small).
* New Visions, both bought in the Mitra item shop for 1 gil:
  | | Dangerous Ariana (13203) | A.I. Katy (13204) |
  |---|---|---|
  | type / role | Magic Enhancer, Thunder + Dark | Physical Attacker + Healer, Light |
  | Resonance | Touch It 470130 (Dark magic, all enemies) | Unexpected Malfunction 470140 (physical, single, x33) |
  | own skills | Dance Tune (party ATK up), Slow Ballad (party MAG up), Mesmerize (slow all), Pre-chorus (party Haste) | Directive - Offensive Measures, Crossed Wires (3x Light), Hacking System (Debrave), Full Scan (Libra), System Update (party Protect), Defensive Measures (party Shell) |
  | shared skills | Thunder/Thundara/Thundaga (+group), Dark/Darkra/Darkga (+group), Libra, Drain | Cure/Cura/Curaga, Raise, Drain, Ultima, Meteor |
  | sprites | FFBE 401000106 (6★) | FFBE 401007407 (7★) |
  | donors (level curve, project template) | Terra | Lightning |
* Addison Rae is NOT in the FFBE export on this machine (she was a GL-only login unit; every Neo Vision sprite folder maps to a known unit),
  so she needs her `unit_anime/cgg/cgs/unit_icon` files supplied before she can be converted.

## v5 (2026-09-03 late): existing skills only
Cloned skills (new ids) have no battle visuals: the game finds a skill's animation by id through asset paths
(`Sequencer/Battle/{Magic,Skill}/<id>/<id+1>/SEQ_Battle_<id+1>_Master`, `Effect/03_SKL/skl<id>/`, `Movies/Skill/MV_Skill<id>` for
Resonance cinematics, `Datatable/Event/Text/BattleSequencerEvent/DT_BtlEv_<id>`). Until those are cloned too, every custom Vision
uses existing skill ids with their original names, and an existing Resonance:
Esther = Zantetsuken 440260 / Lightning Strike, Thunderfall, Cross-Slash, Braver, Thunder Surge line, Bravery, Haste, Esuna;
Tsukiko = Riot Blade - Lotus 440090 / Water line (+all), Libra, Debrave, Drain, Ultima;
Ariana = Colossal Shantotto II 440240 / Thunder + Dark lines, Bravery, Faith, Slow, Haste, Libra, Drain;
Katy = Armiger Unleashed 440290 / Braver, Cross-Slash, Debrave, Cure line, Raise, Protect, Shell, Ultima, Meteor, Drain, Libra.
`DT_SkillData` is no longer overridden by the mod.

## v6 (2026-09-03 22:15): icons v2, battle command icon, canvas fix, Orlandeau
* Icons: the frame interior is transparent (like the originals), the FFBE `unit_icon` sits in the upper part at 2x, and a small blue gem
  fills the diamond's lower point = "custom unit" marker (`tools/ffbe2ss6/build_icons.py`).
* Battle command icon: each custom command set now uses a gameplay tag the registry already defines for an unused vision id
  (`UI.Skill.Command.Icon.13104/13106/13107/13109/13111`, see `UNUSED_ICON_TAGS`) and gets brush rows in `DT_CommandSkillIcon` +
  `CDT_SkillIcon` pointing at `ICON_Ability_summon<id>` (`ffr-dt patch` can now add texture imports for ObjectProperty values).
* Cropped menu sprites: animation canvases are sized from the real extents around the feet (`2*max extent + 16`, pivot 0,0), so wide
  effects (Katy's hologram, Ariana's hearts) are no longer clipped.
* Sword Saint Orlandeau (13205, FFBE 253000807, donor Lightning): Physical Attacker/Breaker, Light. Resonance Knight of Duality (Cecil);
  Banish/Banishra/Banishga Blade, Thunder/Thundara/Thundaga Blade, Cross-Slash, Sacred Wave, Moonlightbringer, Braver, Bravery.
  Command icon tag 13111.

## v7 (2026-09-03 22:30): command icon dependency + own level tables
* The battle command icon rendered as a white box: a DataTable row that references another package's texture needs that import in the
  export's `CreateBeforeSerializationDependencies` (the donor lists all 38 icon textures there). `ffr-dt patch` now adds new imports to that list.
* Two Orlandeaus in battle when Esther/Katy were equipped: first blamed on the shared `LevelParamId` (all Lightning-based Visions used
  10013, Terra-based 10006), so every custom Vision got its own level table (`DT_UnitLevelParameter<Name>`, ids 10100+, registered in
  `DT_UnitLevelParameterList`). That was not the cause (see v9) but the tables stay: they make per-unit stat curves possible later.

## v8 (2026-09-03 22:40): probe mod
* Brush rows got `bIsDynamicallyLoaded` + `ResourceName` as a load fallback (no effect on its own).
* `mods/FFRProbe` (UE4SS Lua, F9 in battle): logs every `CPP_BtlUnit`'s unit id and the `Ss6Project` bound to its sprite component, the
  loaded Ss6Projects, the custom icon textures and the icon tables. It showed units 13201/13204 bound to `summon13205` while their own
  battle projects were never loaded, and every icon texture/table loading fine.

## v9 (2026-09-03 23:20): the real fixes
* Duplicate sprites: `ffr-dt patch` cloned rows with UAssetAPI's `Clone()`, which copies the property list but shares array elements.
  Setting `animationAssetList[0].Ss6Project` on a clone therefore rewrote the donor row and every earlier clone: after the build, Lightning,
  Esther, Katy and Orlandeau all pointed at `summon13205`, Terra/Tsukiko/Ariana at `summon13203`. Rows (and map entries, array elements)
  are now deep-cloned; a verify pass compares every patched table with the original and reports changed pre-existing rows (only the shop
  row and the five icon rows below differ).
* White command icon: the gameplay tags borrowed for the custom command sets (`UI.Skill.Command.Icon.13104/13106/13107/13109/13111`)
  already had placeholder rows in `DT_CommandSkillIcon` / `CDT_SkillIcon` (Command_カイン, ファリス, ロック, セリス, ティファ: no texture,
  128px) which the lookup found before the rows we appended. Those placeholder rows are now overwritten instead (texture, 64px,
  dynamic-load fallback). `ffr-dt patch` learned 2D vectors (`{"X":64,"Y":64}` for a brush's ImageSize).

## v10 (2026-09-03 23:50): Raegen Blast (first custom-named skill with visuals)
* How a skill finds its battle visuals (all keyed by skill id): a `DT_SkillAsset` row -> LevelSequence (about 50 skills), else the
  default path `Sequencer/Battle/{Skill,Magic}/<id>/<id+1>/SEQ_Battle_<id+1>_Master` (about 130), plus a `DT_BtlHitEffectData` row
  (hit / critical / weakness / additional effects, about 450). Vision abilities such as Thunderfall have no sequence at all: the unit
  plays its own attack motion and the hit-effect row does the rest. The v3 clones failed because none of these rows existed for the
  new ids. `DT_BtlEv_<id>` tables exist only for the 17 Resonance skills and hold their caption dialogue.
* The generator now copies those rows for every custom skill (`visuals` in a skill spec = the skill whose animation to borrow,
  default = the cloned skill). `ffr-dt patch` accepts "" for an empty soft object path.
* Esther: **Raegen Blast** 470110 (awakening tier 1): Thunderfall's row with magnification 0, break 9999, accuracy 500, MP 0,
  all enemies, paralysis effect removed, damage numbers hidden. Meant to stagger everything at once so Resonance can be tested.

## v11 (2026-09-04 00:30): derived skill ids (test build)
* v10 result: Raegen Blast staggered everything but played no motion and no hit effects. Datatable-wise nothing else keys off a
  vision ability's id, and the original vision sprite projects contain a single attack motion (`attack_A`), so there is no
  per-skill motion table: the game must gate the generic vision attack on the id itself. Every vision's own abilities sit at
  `445000 + (vid - 13100) * 100 + 10 * slot` and its Resonance at `440000 + (vid - 13099) * 10` (all 27 visions follow it).
* Raegen Blast moved to 455100 (Esther's slot 0). Esther's Resonance is now her own id 441020 "Raikiri": Zantetsuken's row,
  hit-effect row and caption table (`DT_BtlEv_441020`, a renamed clone of `DT_BtlEv_440260`) under the new id.
  If both animate, the id scheme is the rule and custom-named abilities / Resonances are unlocked; the generator asserts it.
* FFRProbe now logs every `PlayAnimByName` call on battle units (unit id + animation name) to `UE4SS.log`.

## v12 (2026-09-04 01:00): sequence ids
* v11 result: still no motion. The real key: `DT_SkillAsset` maps a *sequence id* to a LevelSequence, and the sequence id is the
  skill id + 1 (single-target variant) or + 2 (group variant); a few shared magic-sword sequences sit at the skill id itself.
  Braver 446000 -> row 446001 -> `Sequencer/Battle/Skill/446000/446001/SEQ_Battle_446001_Master`. A skill without such a row
  plays nothing, and the demo ships sequences for only part of the table: Lightning Strike, Thunderfall, Dark line, Ultima,
  Meteor, Banish line, Moonlightbringer and four of the five borrowed Resonances (Zantetsuken, Colossal Shantotto II, Phantom
  Sword, Duality Knight) have none. The build log now lists every granted skill without a sequence per unit.
* Custom skills copy the visuals donor's asset rows shifted to the new id (455100 -> 455101). Raegen Blast is now based on
  Sacred Wave 445020 (Warrior of Light, all enemies, one hit, sequence 445021) with the same zero-damage / 9999-break tweaks.
* The id-range scheme from v11 stays (it is how the game's own data is organised) but is not what gated the visuals.

## v13 (2026-09-04 01:40): first custom Resonance (Raikiri = muted Hibernal Fury copy)
* v12 result: Raegen Blast animates (Sacred Wave's sequence). Its cut asks the unit for `magic_idle`, so Esther loops her cast
  pose; the icon was Light (now Thunder via `SkillIcon.TagName`).
* Sequence packages parse and re-serialize byte-identically with UAssetAPI, so they can be copied and edited. A battle sequence
  is a Master (references the blue-domain subspace level `Btl_99Aku_60_BG0`) plus Track/Cut (unit motions, camera; animation
  names such as `LB1` sit in the director blueprint bytecode as string constants), Track/Effect (Niagara) and Track/Sound
  (CRI Atom sections: SE + voice cues).
* `clone_sequence` in the generator copies a sequence's packages under the new sequence id (`Sequencer/Battle/Skill/<skill>/<seq>/`,
  names rewritten, extracted from the container on demand) and a second `ffr-dt patch` pass nulls the `Sound` of every Atom
  section whose cue matches a `mute` prefix (`VO_` = voice). `ffr-dt patch` accepts `null` for object properties.
* Esther's Resonance 441020 "Raikiri": Hibernal Fury's row (5 random hits, x45) as Thunder / physical, Tronn's voice muted,
  hit-effect row and Zantetsuken's caption table under the new id. Expected: blue domain, Esther's LB1 (FFBE limit burst),
  ice burst effects, no Tronn lines. Hue change and per-unit motion choice are the next experiments.
* Templates with sequences in the demo: cast-in-place damage = Hibernal Fury 414090 (Tronn); heal allies = Leah 414100;
  buff allies = Charlotte 412600; rush + slash = Climhazzard 440110 (Cloud, has a movie), Crystal Braver 440010, Lotus Riot
  Sword 440090 (Terra, also movies).

## v14 (2026-09-04 02:30): recoloured Resonances (sequence event editing)
* v13 result: the muted Hibernal Fury copy plays for Esther (blue domain, her limit-burst motion, ice bursts, no Tronn lines);
  Tsukiko's Lotus Riot Sword plays her FFBE limit burst too.
* The director-blueprint bytecode parses in UAssetAPI, and every event is one `BTL_SEQUENCE_PARAMETER` constant, so
  `ffr-dt seqdump <sequence>` now lists each event with its non-default fields (mapped through the usmap schema) and a
  `bytecode` patch op edits constants in place (`{"asset", "export": "*", "match": {"EventType": ...}, "set": {field: value}}`;
  string edits adjust the buffer size, object edits add imports). Round trips stay byte-identical.
* What the dumps showed: the domain colour is the Master's `OtherChangeSubSpaceColor` event (Hibernal Fury 0.05/0.30/0.54 blue,
  Leah 0.23/0.48/0.44 teal); the effects are `EffectSpawnNiagaraAt*` events pointing at Niagara imports (Effect track); the
  motions are `UnitPlayAnimByName` events (Cut track: step_front, command, LB1, idle for Hibernal Fury; magic_idle, LB1, idle
  for Leah's). Screen tints come from `PostSetColorGradingGlobalParameter` ids (table-driven, untouched so far).
* Esther "Raikiri": yellow domain (0.62/0.46/0.04), ice effects swapped for Dark Fina's Thunderga set (`skl408030`:
  Thunderga_001 on targets, BallThunder_001 bursts, Thunderga_Charge_001 at the weapon).
* Ariana "Touch It" 441040: Leah's healing Resonance (party heal, `LB1` on Ariana = her FFBE limit burst, allies framed),
  dark grey domain (0.10/0.10/0.11), the green Cure sparkle on each ally replaced by the charm hearts effect
  (`NS_EF_BTL_BadStatusCharm_Center`); Leah's staff charge/burst kept for now. Voice muted, caption from Colossal Shantotto II.
* Spec knobs per Resonance: `from`, `clone_sequence`, `mute` (cue prefixes), `caption_from`, `sequence_edits`
  ({"master"|"cut"|"effect"|"sound": [{"match", "set"}]}), `effect_swaps` ([old name, new name] pairs, incl. package paths).

## v15 (2026-09-04): FFR Vision Studio (dev web UI) + eight more units
* v14 result: Thunderga effects took, the domain stayed blue for both (the colour event is not what tints the arena; colour
  grading ids / ground flags are next), Ariana's limit-burst motion was cut short (sequence shorter than the animation).
* `tools/devui/`: FastAPI server (`python tools/devui/server.py`, http://localhost:8765) + Vite/React front end
  (`tools/devui/web`, `npm run build`). The specs now live in `mods/EstherTsukiko/units.json`; the generator reads that file.
  Catalogues: `ffr_catalog.py` (skills with English names/descriptions, sequence availability, passives, effects, visions,
  icon textures exported to png, Niagara list, Resonance templates, enums) and `ffbe_catalog.py` (GL + JP ffbeEquip data,
  sprite forms, unit icons, APNG previews of any FFBE animation, Terra-ratio stat formula).
* Pages: dashboard (units, build / verify / install, log), identity & stats, sprites (motion previews), skills (FFBE
  abilities -> drag or "port" into FFR skills: mechanics donor, sequence donor, unit motion, icon, cost, element, target,
  multiplier, hits, break), mastery (FFBE passives -> awakening grants; awakening tiers + synchro levels editors),
  Resonance (FFBE limit burst name, template sequence, mechanics row, domain colour, effect swaps from the template's
  spawns, mute, caption). "Auto-port whole kit" applies the default rules (`tools/devui/autoport.py`).
* Icons: `assets/border 1` (menu diamond: face + ability icons) and `border 2` (battle circle: timeline icon) with the FFBE
  unit_icon and the rarity chip (`assets/Rarity-N`, `NV`, `NV-plus`) = legacy-FFBE marker; the five old units switched too.
* Stats: FFR = FFBE max stats at max rarity x (FFR Terra / Magitek Warrior Terra 7*): HP x0.180, MP x0.347, ATK x0.182,
  DEF x0.208, INT (MAG) x0.045, MND (SPR) x0.101, AGI 15.
* Custom skill `motion`: the copied sequence's Cut events are rewritten to the chosen unit motion (attack_A = FFBE atk,
  magic_attack = magicatk, LB1 = limitatk ...).
* New units (all FFBE data + sprites in `units/ffbe/<key>`): Sora (KHIII) 13206, Elena 13207, Sylvie 13208, Hyoh 13209,
  Grim Lord Sakura 13210, Alice 13211, Snow White 13212, Raegen -The Return- 13213 (the JP data has no "Ultimate Summon"
  Raegen; this NV form is the closest match). Kits auto-ported: first 10 abilities -> skills, passives -> grants.

## v16 (2026-09-04): studio round 2
* The domain colour never changed because the template Masters keep their `OtherChangeSubSpaceColor` event on a track flagged
  `bIsEvalDisabled` (Hibernal Fury track 6, Leah track 5). Copies now enable that track and give the track and the sequence fresh
  `Signature` GUIDs so the game recompiles the sequence instead of reusing the cooked evaluation data (`ffr-dt patch` accepts
  `"Signature": "new"` for GUID properties). Untested until the next launch; the tint presets stay.
* English names/descriptions: the FFBE English patch tables (`T:\Projects\FFBE Patch\english_patch\swapped`, column G4L0YIB2
  is the name) give every unit an English name (0 Japanese unit names), ability names (86% English), limit burst names and
  unit descriptions. Units missing from those tables keep their Japanese name (Alice, Snow White). "Raegen -Ultimate Summon-"
  is 100045807 there, but no sprite sheet for it exists locally, so it cannot be ported yet; 13213 stays "Raegen -The Return-".
* FFBE ability icons (`jp_extracted/on_demand_asset2/item1/ability_N.png`) are shown next to abilities and ported skills.
* Studio: friendlier wording (no raw ids), search by English name, drag bonuses between awakening / synchro tiers, icon frame
  editor on the Home page (portrait / chip size and position per frame, live preview, cropped to the frame, applied to every
  unit at build), generated ability descriptions ("Deal Light physical damage to one enemy (3 hits).") that follow the
  dropdowns, "Preview sequence" storyboards for any Resonance skill (motions with this unit's sprites, effects, hits, tints,
  sounds with their times; particles are described, not rendered), auto-port when adding a unit.
* New units get ids from 13500 (room for the full game's own visions). Command icon tags limit the mod to 16 units for now.

## v17 (2026-09-04): FFBE source reconciliation + the real Raegen -Ultimate Summon-
* `ffbe_catalog` now reads four data regions (ffbeEquip GL/JP + the 2024-10 wiki datamine GL/JP) and four sprite roots
  (BFFrameAnimator Units, the JP live client archives extracted to `build/ffbe_cpk/jp_live` by the new `tools/devui/cpk.py`,
  the GL client dump, the JP memorial packs): 1843 units with sprites in the picker, provenance chips (GL / JP / GL 2024 /
  JP 2024, "JP live sprites"). Details in `docs/05-ffbe-sources.md`; `tools/devui/ffbe_live.py` decrypts the live JP tables.
* Names the English patch lacks come from `tools/devui/jp_glossary.json` (Raegen's kit, limit burst "Skyfang Mirror Blades",
  his unit description); the unit list still shows a "JP name" chip when neither source has English.
* 13213 is now the real Raegen -Ultimate Summon- (FFBE 100045807, NV+ form 100045827 data: kit, limit burst, stats HP 5747 / ATK 470
  → FFR 1033 / 86), shown as "Ultimate Raegen", with his own NV+ sprites (form 100045827) from the JP live client archives,
  decrypted with the user's DataExtractor tool through `tools/devui/ffbe_decrypt.py` (docs/05). The vision id, command
  icon and master skill ids were kept so an existing save stays valid (`autoport.py --renumber VID[:COMMAND]`).
* Auto-port ranks a kit before filling the 10 skill slots: signature moves with real effects (damage multipliers, buffs,
  imbues, unit-exclusive ids) first, common spells last, unlock / multicast / LB-filler abilities skipped; the FFBE element
  (or none) now always overrides the donor's element.

## v18 (2026-09-04): Resonance timing
* Ariana's Resonance stopped midway because Leah's template forces the idle motion 2.3 s after LB1 starts while her FFBE
  limit-burst animation runs 4.7 s. Every cloned Resonance is now stretched automatically: `ffr-dt patch` gained a `frames`
  op (every key time / section range / playback range / evaluation field at or after a tick moves by a delta, sub-section
  offsets untouched) and the generator (`auto_stretch`) measures the unit's `unit_limitatk_cgs` length against the template's
  gap between LB1 and the next motion key, then shifts everything after LB1 by the difference (+0.2 s, rounded to 30 fps
  frames) in the Master, Cut, Effect and Sound packages and gives them fresh Signatures. `lb_custom.stretch`: `"auto"`
  (default), `false`, or a number of seconds. Untested in-game until the next launch.

## v19 (2026-09-04): decrypted live archives, real Raegen art, NV+ chip
* `tools/devui/ffbe_decrypt.py` runs the user's `DataExtractor.exe` on the 31 live `unit*.cpk`: 3607 sprite sheets, every
  JP unit through 100047727 now has readable art; the picker's "sprites locked" state is gone.
* 13213 uses Raegen -Ultimate Summon-'s own NV+ sheet; the stand-in is removed.
* The NV+ rarity chip resolved to the 7-star chip (case mix-up in `build_icons.rarity_chip`); fixed for every unit. The Icon
  frames page now has a size slider per rarity chip (`icon_layout.json` → `chips`, NV 0.7 / NV+ 0.55 by default) with live
  previews, and the Profile tab's icon previews follow the style / rarity dropdowns before saving.

## v20 (2026-09-04): FFBE effect port pipeline (first test)
* Battle sequences can spawn SpriteStudio actors (`SsActorSpawnSpriteStudioActor` with `SsActor_SsData`: Ss6Project, anim pack /
  animation, part to follow, offset) and destroy / recolour / move them by id. That is the vehicle for FFBE battle effects:
  `tools/ffbe_effects/to_ss6.py` turns an effect document (frames of sprites: texture rect, position, scale, rotation, alpha,
  blend) into an Ss6Project spec with one Normal part per sprite slot and blend mode (Mix / Add), `ffr-dt make-ss6` now rebuilds
  the part model from the spec (`model.parts`), and the generator builds `Chara/effect/<name>/<name>(+_tex)` for every
  `lb_custom.ffbe_effects` entry, repurposes a matched Niagara event of the cloned Effect track into the spawn event and moves
  that key to the LB1 motion (new `ffr-dt patch` op `retime`; runs after the stretch). `ffbe_effects` entry: `name`, `spec`
  (folder with spec.json + tex.bgra), `id`, `spawn.match` (event to repurpose), `time` (`LB1` | seconds), `delay`, `part`
  (e.g. NULL_Center), `follow`, `offset` [x, y, z].
* First test: `ariana_heart_test` (three additive hearts from `10Ariana_heart.png` rising for 2 s) replaces Leah's weapon charge
  effect at LB1 on Ariana. The real IBMB effect parser is in progress (`tools/ffbe_effects/ibmb.py`, `FORMAT.md`).
* FFBE data for the mapping: `F_LIMITBURST_MST` / `F_ABILITY_MST` / `F_MAGIC_MST` carry `effect_frames`
  (`frame:effectGroupId:..`), `F_EFFECT_GROUP_MST` (group -> effect ids with x/y offsets + sound cue ids), `F_EFFECT_MST`
  (effect id -> `.bmb` file); the 31 live archives decrypt with `ffbe_decrypt.py --out` (battleEffect1-4, effectResource1-3 done:
  `build/ffbe_cpk/effects_dec`, 7,200 bmb + 800 m3r + 2,900 png).
* Selection pose: the FFR `command` animation (unit selected for an action) now maps to FFBE `standby` instead of `idle`.
* Ariana's Resonance now borrows Hibernal Fury's timeline (`visuals` 414090: 5.1 s for the LB1 motion, no stretch) with Leah's heal
  mechanics: ice bursts and four of the five hit reactions / camera shakes switched off (`sequence_edits` with `skip_earliest`), the
  target effect swapped to the Cure aura, Tronn's cue swapped to Leah's (`lb_custom.sound_swaps`), hearts at LB1. The stretched
  Leah clone played its hearts but still ended early in-game, so long motions should pick a long template instead.
* FFRProbe: F8 (F10 is the UE4SS console) toggles a 100 ms timeline trace (sequence players' current time / duration, each battle unit's sprite player
  state, sequencer sprite actors) to find out why Ariana's Resonance still ends early in-game.

## v21 (2026-09-04): real FFBE effect on Ariana
* FFBE `.bmb` effects decoded far enough to simulate (see docs/05): Ariana's limit burst "Touch It" = four layers
  (`lb_401000106_Ariana_back` = screen-fill plate, `_back_unit` = growing heart + glow + light streaks around her,
  `lb_401000105_Ariana_front` = sparkles, `_front_unit`). The back-unit layer is exported as a sprite list
  (`render.py --doc`, 320 frames, ≤17 sprites a frame, 3 textures), converted with `to_ss6.py` (21 sprite slots: 5 Mix + 16 Add,
  512x256 atlas) and spawned at LB1 following NULL_Center in place of the test hearts. Scale: 1 FFBE world unit = 1 sprite pixel
  (`--scale 1/pixelsPerUnit`). Distortion-pass textures are skipped. `flipbook.py` bakes rendered PNG frames instead when a
  sprite list is impractical; `preview_ss6.py` draws what a converted spec will show.
* All four layers are now spawned at LB1 (one Effect-track event each, `spawn.index` picks among identical matches): back
  layers with `offset` +15 on X, front layers −15 (a depth guess, to verify in-game). Sprite colours are exported
  (`color`) and baked into tinted atlas cells (the front-unit pillar is gold, the heart glow pink). Screen-filling plates
  (both sides > 260 units) are dropped; FFR's tint / domain stands in for them.

## v22 (2026-09-04): first FFBE ability animation (Sakura -Dark Lineage-, Burst)
* Sakura -Dark Lineage- (FFBE 100041107) is vision 13500; "Burst (FFBE)" (magic 20370, lightning, all enemies) is her first
  level-1 ability. Its FFR mechanics come from Thunder (225060) and its sequence is a clone of Thundaga's (225080: cast motion
  at 0.5 s, strike on every enemy, three hits) with the FFBE `bm_2037_burst_front.bmb` layer spawned on her at the cast; the
  back layer is a screen-filling lightning plate and is left out. `ffbe_effects` on a skill works like on a Resonance; `time`
  may be a number of seconds or `"event"` (keep the repurposed event's own time). Any event type can be repurposed (the two
  radial-blur events became the spawns), and the converter now shrinks oversized textured sprites to 260 units instead of
  dropping them (only uniform plates are dropped). The simulation still draws one quarter of the burst circle (emission
  copies not decoded yet).
* Mass-import groundwork: the Profile tab's "port Brave Exvius effects" switch makes auto-port attach every ability's FFBE
  effect layers (`ffbe_effects` with `source` = bmb file, `spawn.any` + index = the Nth event of the cloned Effect track,
  `time` = the FFBE frame / 60, offsets from the effect group; plates / strobes / sound-only groups skipped, 3 layers max).
  The generator renders + converts missing specs on demand (cached per bmb under `build/effects/<bmb>/ss6`, shared across
  units), so the first build with many effects is slow and later builds are not.
* FFBE effect-group flags decoded from the tables: `[layer, anchor, ?]` with layer 1 = front / 2 = back and anchor 1 = caster,
  2 = the targets, 4 = screen, 7 = caster overlay. Auto-port and the generator use them: target-anchored layers spawn relative
  to the targets (`at_target`, no following) and all-enemy skills get them at 1.6x so one ring covers the whole enemy group
  (FFR AoE effects are not per-unit). Sakura's Burst ring now sits over the enemies and the game's own Thundaga strike is off.
* Battle geometry from the F8 trace: camera at (-2800, 0, 800) looking along +X (yaw 0, pitch -10); the party stands at
  +Y (screen right), enemies at -Y (screen left), ground Z 0. So "toward the camera" is -X: effect layers use X offsets of
  -80 (front) / +80 (back). Sakura's Burst actor sat at the enemy's coordinates after the move-to-target event, and the
  recording shows the ball over the enemies at 1 s.
* Ariana after the first in-game run: stays in her party slot (the ice template's walk-up removed), Cure aura on every ally,
  no radial blur / chromatic aberration / shakes, additive layers at 60%, depth offsets flipped (the gold pillar had drawn behind
  her). The FFBE effects appeared at the right moment and the full song motion played on Hibernal Fury's timeline.

## v23 (2026-09-04): Brave Exvius animation preview in the studio
* Abilities tab (every ported ability) and Resonance tab: "Brave Exvius animation" opens a preview of the unit's FFBE motion
  (magic_attack / attack / limit burst) with the effect layers exactly as they will be converted for the game (plates dropped,
  oversized sprites shrunk, additive gain, tint), targets on the left as in FFBE. Each layer can be switched off, anchored to the
  unit or the targets, drawn in front or behind, timed, resized, dimmed and offset; "Render preview" produces an APNG (first
  render of a file takes about a minute, later ones seconds), and "Use these layers in the mod" writes the reviewed set into the
  skill (`ffbe_effects`, `clone_sequence`). Backend: `tools/ffbe_effects/preview_anim.py`, `/api/ffbe/effects/layers/{kind}/{id}`,
  `/api/ffbe/effects/preview` (job) + `/{job}/state` + `/{job}/image`.

## v24 (2026-09-04): effect emission decoded
* The particle "swarm" was the wrong reading; the port is now driven by the files' own data. Emission lives on the node above
  each emitter: particles per burst (+0x90), emission window in frames (+0x94), number of bursts (+0x98), frames between bursts
  (+0x9C), all defaulting to one sprite; the emitter's curves animate each sprite. Model emitters size from their `.m3r` mesh
  extent (model_aura_047 is 160x201, which had turned Burst's lightning into single pixels), and types 4 / 7 got their base-size
  fields. Verified: bg_black = 1 sprite, Ariana's drifting hearts = 2 at a time x 10 bursts 7 frames apart, Burst = charge ball,
  white expanding spoked ring, re-fired lightning bolts. `render.py --particles` is now only a per-frame cap (64).
* Additive gain defaults to 1.0 (single sprites no longer stack); all effect documents re-rendered with the new parser.

## v25 (2026-09-04): Firaga on Sora, model emitters drawn through their meshes
* Sora's last skill (455690, was Stellar Inception) is now Firaga (FFBE magic 20200) on FFR's Firaga sequence 225010/225011,
  moved to awakening tier 0 slot 1 so it is usable at level 1. Layers: bm_2020_fire3 at the target (0.67 s, scale 1.6) and
  bm_2001_fire1 on the caster (0.5 s); the donor's Niagara fire strike and chromatic aberration are switched off.
* Effect parser: a node's absolute size curve no longer multiplies the emitter's identical one (`ibmb.ABS_SCALE_RULE`), node
  curves run from the node's accumulated start, and model emitters are rasterised through their `.m3r` mesh (vertex colour x
  texture, tilt from ancestor rotation) instead of a full-texture square. Burst and Firaga docs re-rendered; preview sheets
  in build/effects/preview/. Handoff for a fresh session: docs/06-effect-port-handoff.md.
* Studio: the Resonance preview no longer fails on `time: "LB1"` layers.

## v26 (2026-09-05): Firaga calibrated on the phone recording
* The user recorded Firaga in Brave Exvius (docs/06-effect-port-handoff.md has the timeline). Against it: file sizes are
  half extents (everything drew at half size), the flame is on the *enemy* seven times over (group rows are comma-separated
  spawns; flag b = 1 means each target, not the caster), the light_burst star never shows, the first 50 frames are a
  shower of streaks converging on the target, and the group offset y points toward the camera.
* Parser: `ibmb.SIZE_IS_HALF_EXTENT`, per-axis scale curves, emission fields from the nearest configured ancestor, radial
  streak heuristic, `bake(repeat, interval)`; `render.py --repeat/--interval/--exclude`, `to_ss6 --max-units` (cap 900);
  `layer_spec.py` names doc folders per option set. Studio modal shows and edits "x N every S s". Colour-over-life curves
  live in slot 19, not 13, so the yellow -> red ramps of flames and fireballs are applied for the first time.
* Sora's Firaga: fire3 at the target 0.67 s, scale 1.6, depth -230, without emitter 27; fire1 at the target from 1.0 s, x 7
  every 0.333 s, scale 1.6, glow 2. 1.6 is now the default scale of every layer (effect units -> sprite pixels, measured on
  both layers); glow above 1 brightens additive colour and alpha. Preview + recording side by side:
  build/effects/preview/sora_firaga_vs_recording_v26.jpg.
* Not re-rendered yet: Burst (Sakura) and Ariana's LB docs are still at v25 half size; delete build/effects/doc_* to redo.

## v27 (2026-09-05): first in-game Firaga, one actor per skill, Brave Exvius reference in the studio
* In-game test of v26 (docs/06): the SpriteStudio actor loops its clip and outlives the sequence (the fireball restarted after
  2.67 s), only the first actor's move-to-target took effect (the flame sat on the caster), the target-relative X offset is
  not camera depth, and FFR's additive is ~3x hotter than the preview. Fixes: every clip is padded to 4.5 s (`min_frames`),
  a skill's files are composed into ONE actor (`compose` sub-entries with their own time / offset / repeats), target layers keep
  offset [-80, x, 0], flame glow back to 1.
* Studio: the Brave Exvius animation modal has a "Show" switch: the FF Resonance conversion (the layers as the game gets
  them) or the Brave Exvius data (the skill's own effect groups drawn from the raw bake with FFBE anchors, timing and offsets,
  none of the port knobs).
* Install by hand with `python tools/build_mod.py build/visions_mod/assets EstherTsukiko --install` (the `assets` subfolder;
  the v26 notes named the parent folder, which packs a broken mod). The studio's Build button was always right.

## v28 (2026-09-05): Easy mode and the packaged studio
* **Easy mode** (default; the old UI is "Advanced" behind the switch in the sidebar). Add a unit, then in four steps pick from
  what the game already ships: abilities (the game's own skills, dragged onto awakening tiers 1-4), bonuses (stat boosts and the
  game's passives), stats (sliders, or copy a vision's, or the Brave Exvius-based values), and a Resonance built from one of
  the six demo Resonance animations plus one existing Resonance's mechanics (damaging: physical / magical, element, targets,
  "numbers like Cloud's Ascension"; or healing / buffing / debuffing). Nothing custom is generated, so every animation, icon and
  hit effect exists. One button installs into the game.
* **Packaged studio**: `python tools/release/build_release.py --zip` makes `build/release/FFR Vision Studio/` (+ zip): one
  folder with `FFR Vision Studio.exe` (PyInstaller), `bin/ffr-dt.exe` (self-contained .NET), retoc, the scripts, the web UI and
  shipped data (table mappings, enum names, skill catalog, icons, container listing, English text, Brave Exvius index). No
  Python, .NET or Node on the user's machine. First run: the exe finds the game through Steam (or asks), converts the tables,
  the three template visions and the icon textures with retoc and reads every table with ffr-dt (tools/devui/setup.py),
  then works exactly like the source tree. `tools/release/build_ffbe_pack.py` gathers the Brave Exvius tables and chosen sprite
  forms into `data/ffbe` (a full sprite pack is several GB; the release decides what to ship).
* Paths now come from `tools/ffrenv.py` (game folder, ffr-dt / retoc commands, how to run helper scripts); the game folder is
  detected through Steam or set in `config.json`.

## v29 (2026-09-05 afternoon): the native app and the hosted packs
* **FFR Vision Studio is a Windows app** (`app/ffr_vision_studio`, Flutter). It looks like a strategy-guide spread (white page on a grey
  desk, black frames around anything from the game, colour bands per section, a red GO). Left page: your visions / the unit's entry.
  Right page: install status, or the four steps (Abilities, Bonuses, Stats, Resonance) with drag-and-drop onto awakening tiers.
  "Advanced studio" opens the old web UI in the browser; both work on the same units.
* **Nothing to install but the app.** First start downloads the engine (the v28 package, now started hidden with `--engine`) and
  the game-side data into `%LOCALAPPDATA%\FFR Vision Studio`, finds the game (Steam registry, library folders, common drive
  roots, or a folder picker), prepares its data (about two minutes) and opens the spread. Closing the window stops the engine.
* **Hosting on Hostinger** (`tools/release/build_host_pack.py`): ffbe.luminest.io holds manifest.json, the download page, the app
  zip, data/base, ffbe/tables, ffbe/index.json and one sprite zip per form (14 forms, 21 units today); ffr.luminest.io holds the
  engine zip. Sprites are downloaded when a unit is added. Adding a unit whose sprites are not hosted yet is refused in the app
  (the Advanced studio can still import from a local datamine).
* Tested end to end from a clean folder against the live hosts: boot, preparation, Esther added (7★ look), Braver granted at
  tier 1, build without installing.
* **v29.1 (same afternoon): backups and restore, Rain, logos.** Every install now goes through the engine's `install_files`:
  the three pak files are copied into `FFRS/Content/Paks/~mods`, whatever those names held before is copied first to
  `<engine>/backups/<timestamp>/`, and `<engine>/game_state.json` records what the studio placed. "Restore the original game"
  (Install page, "Your game files") removes everything the studio placed, puts back files that were there before it, and removes
  the `~mods` folder if the studio created it; any earlier backup can be put back on its own ("Put back"). Endpoints:
  `GET /api/game/files`, `POST /api/game/restore {backup?}`. The build never installs by itself any more (`--no-install` always;
  the server installs after the table check). Rain's Brave Exvius face is the app icon and sits in the wordmark (FFR band +
  VISION STUDIO); the download page opens with the FINAL FANTASY RESONANCE and BRAVE EXVIUS logos. Engine updates no longer
  overwrite `mods/` (the user's units). Host pack 1.0.1 keeps one version per host.

## v29.2 (2026-09-05 evening): every sprite, animated previews, copy a vision, night edition
* **All 3,800 Brave Exvius forms are hosted** (621 MB), spread over sprite shards `sprites<n>.luminest.io` (the static deploy
  caps a site near 80 MB); `ffbe/index.json` carries each form's absolute URL. Every unit's 56×38 face icon is on the ffbe
  site (`ffbe/icons/<form>.png`), so the add-unit list shows faces before any download. Picking a unit fetches its sprite pack
  (a loader says so), then shows its motions.
* **Animated previews**: the engine renders any motion as lossless animated WebP (`/api/ffbe/anim/<form>/<anim>.webp`,
  `/api/ffbe/anims/<form>`). The `AnimViewer` (arrows + motion name) sits in the add-unit dialog, the unit's left page and the
  Resonance step (limit-burst motion; the event list is gone). Rarity reads 1★..7★, NV, NV+.
* **"Play like a vision the game has"** (unit page): copies a game vision's awakening grants (the catalog now carries each
  vision's `awakening` from `DT_VisionAwakeningMasteryData`), stats, type, roles and Resonance numbers onto the unit.
* **Night edition** toggle (header and setup page, remembered in `settings.json`): charcoal paper, off-white ink, same bands.
* The app's exe is `FFR Vision Studio.exe`; the add-unit dialog fits without scrolling (compact stat grid, no tooltips).

## v29.3 (2026-09-05 night): the release audit, worked through; version 1.0.0 build 4
Versioning: the product stays 1.0.0 while the first release is being finished; each packaging run is a build. Files, the
manifest and the app compare the tag `1.0.0.<build>` (`build_host_pack.py 1.0.0 --build 4 --build-app`). The exe carries the
version and a proper name (`FFR Vision Studio.exe`, product name, description, disclaimer as copyright); the app shows
"version 1.0.0 · build 4" in the header and an About page (engine version, paths, trademark line, font licence, logs).

From docs/10-app-release-audit.md:
* R1/R2 (Resonance): the six animations are listed as three that play the unit's limit-burst motion (Hibernal Fury, Healing
  Wind, Resolute Bastion) with one-line blurbs, then the owner cinematics under a divider, marked. The catalog's `lbTemplates`
  carry `good`, `window`, `length`, `who`, `blurb` (`ffr_catalog.TEMPLATE_NOTES`, docs/09 §4). The step warns when the unit's
  limit-burst motion (`/api/ffbe/motion/<form>/limitatk`) is longer than the template's window ("stretched, not verified
  in the game"), and says so when it fits. `auto_stretch` measures from the first `LB1` key (Ascension's re-trigger no
  longer collapses the window). New units default to Hibernal Fury visuals whatever their mechanics.
* R3: a "Show the timeline" link under the animation reveals the storyboard (motions, effects, hits, tints, camera in
  order); a "Caption lines" picker chooses whose Wol lines are cloned; the Brave Exvius limit burst (name + effects) is
  shown under the name as a hint.
* R4: offline start (manifest unreachable + engine installed = run what is installed, gold banner). R5: the engine's exit is
  watched; a red banner offers "Restart the engine"; status failures mark the engine down. R6: closing during a build asks
  first. R7: exe metadata, window class, version stamping.
* S2 errors routed to the header notice; S3 engine log files in `%LOCALAPPDATA%\FFR Vision Studio\logs\engine-<date>.log`
  with "Logs folder" buttons (setup, build console, About); S4 update notice from `manifest.version` vs the app tag,
  `minApp` guard (an older app keeps its packs and is pointed at the download page); S5 minimum window 960×600; S6 sprite
  packs carry a `.complete` marker and need sheet + parts file; S7 downloads resume (`.part` + Range) and retry four times;
  S8 one instance per machine (lock file; a second copy shows "Already open"); S9 zip entries that would escape the target
  are skipped; S10 radios replaced by the framed `Choice`, lints fixed, four unit tests, the app README rewritten.
* Nice-to-have: About page; Enter in the add-unit search picks the first hit; the unit's Resonance entry names the animation
  and element (and flags an owner cinematic); the download page says "Looks with sprites 3 800".

## v29.4 (2026-09-06): the first tester's bug; build 5
* **Adding a unit on a machine without the developer's sprite sources lost its sprites.** `ffbe_catalog.sprite_map()` scanned the
  sprite roots once at engine start and cached the result, so a pack the app downloaded afterwards (`data/ffbe/sprites/<form>/`)
  was invisible: the per-unit copy got no files, and the build's sprite step later crashed on the missing sheet. On the developer's
  machine the fallback roots on S:/T: hid this. Now the downloaded root is checked live and wins (`_pack_dir`), the index rebuild
  rescans, and a build first heals units whose per-unit sprite copy is missing (`server.heal_sprites`).
* **Crashes were message boxes, not log lines.** A tool script (`--run` child, e.g. the sprite conversion) that raised showed
  PyInstaller's "Failed to execute script" box and blocked the build. `launcher.py` now catches everything, writes the traceback to
  stderr and to `logs/engine-errors.log` in the app's logs folder (the app passes `FFR_LOG_DIR`), and exits with code 1. Each build's
  console is also written to `logs/build-<stamp>.log`.
* The setup and build consoles are selectable and have a Copy button.

## v29.5 (2026-09-06): docs/11 worked through; build 6; the app is ready for its own repository
* **Previews for SLB / OD / newer units** (docs/11 item 1): `ffbe_catalog.cgs_file` finds the cgs under either spelling
  (`limitatk` / `limit_atk` ...); `render_frames`, `motion_seconds` and `anims_for` use it.
* **Brave Shift / Super Limit Break pairs** (item 2): the index merges the two ids (same name, ids ten apart, same 7-digit
  prefix: 346 pairs, 1843 -> 1497 rows) into one row with `pairOf` and `shift = {form: {kind: brave_shift|slb, base}}`; the
  add-unit dialog labels the looks "· Brave Shift" / "· Super Limit Break" and downloads the base form's pack too. A shifted
  sheet borrows `win` / `winbefore` / `dead` from its base: in the viewer (`anim_source`), and in the mod (`build_sprites.py
  --base <dir> <id>`, `Sheets` composes frames from two sheets; `make_vision_mod` passes `ffbe.baseDir` / `baseForm`, written
  by `/api/spec/add`; `dump` copies both units' forms).
* **Live JP units** (item 3): fifth region `LIVE` from the decrypted `F_UNIT_MST.json` (developer machine) shipped as
  `data/ffbe/live_units.json` in the tables pack, lowest priority; the 53 forms newer than the datamine (Rain & Lasswell
  100047707 / 100047727 ...) are rows with JP names, stats and looks; their sprite zips go to the shards.
* **Studio moves** (item 4): `ffr_catalog.STUDIO_SKILLS` (Raegen Blast) served as `studioSkills`; the Abilities library shows a
  "Studio moves" group; granting one clones the recipe into the unit's own skill range (first free slot) and adds the grant.
* **Unit page header** (item 5): "All visions" back button before the wordmark; "Play like a vision the game has" and
  "Remove" on the right (theme toggle, version and update controls stay on the home page); the left column is the entry only.
* **Update now** (item 6): downloads the new app zip, verifies, stages it under the app data, writes `update.ps1` (waits for
  this process, robocopy over the exe's folder, starts the new exe, deletes itself), starts it through `cmd /c start /min`
  and quits. A PowerShell child started detached straight from Dart dies with the app, and a `.cmd` helper with
  `tasklist | find` hangs without a console; the `cmd /c start` route is the one that survives (docs/11 item 6). Read-only
  app folders fall back to the download page. After an update the header says "Updated to ..." once (`settings.lastRun`).
* **Dev environment**: `python tools/release/devenv.py --build N [--reset] [--no-build] [--engine-local]` builds the pack,
  serves `build/release/host` on 127.0.0.1:8766 and starts the app with `LOCALAPPDATA=build/devhome` and `FFR_STUDIO_HOST`.
* **Repository-ready app**: `app/ffr_vision_studio` has `CHANGELOG.md` (by build), `LICENSE` (MIT for the code; game art and
  data excluded), `CONTRIBUTING.md`, `.github/workflows/windows.yml` (analyze, test, build, artifact), a README.

## v29.6 (2026-09-06): the first public day; the host rate-limited the pickers
The mod's first public users hit 429s and 404s on ffbe.luminest.io. Cause: `add_unit_dialog._icon` fetched
`ffbe/icons/<form>.png` from the host for every visible row and for every look in the detail dialog, and the host only had
the unit's `iconForm` icon (1896 files for 3932 forms): every look picker fired 404s, and the burst of tiny requests from
many people tripped Hostinger's limit (`Server: hcdn`), which then also refused the pack downloads.
* **Icons pack** (build 7): `build_host_pack.py` copies every form's icon to `ffbe/icons/` (3932, kept for builds 5/6) and
  zips them as `ffbe/icons-<tag>.zip` (`packs.icons`, ~4 MB); the app downloads it once (fourth setup step, optional when a
  host has none) into `%LOCALAPPDATA%\FFR Vision Studio\icons` and the pickers read `Image.file`; the engine's
  `/api/ffbe/icon` is the fallback. No per-row host request remains.
* **Backoff**: `Downloader.transient` (429 / 408 / 5xx) and `backoff` (Retry-After capped at 60 s, else 2, 4, 8 s) for the
  manifest, the index and the pack downloads (six tries); other 4xx still fail at once.
* **Stable packs**: `stable_zip` keeps an earlier build's zip (and tag, `packs.<name>.version`) when its source did not
  change; the engine's `VERSION` is only rewritten when the engine changed; `live_units.json` only when its content
  changed. The app compares each pack's own version, so build 7 reuses the build 6 engine and data: no engine deploy,
  and an update downloads the app (12 MB) and the icons (4 MB) only. The builder prints which sites need a deploy.
* Still on the table if the limit keeps biting: a CDN in front of luminest.io (Cloudflare's free plan caches every static
  file at the edge, so Hostinger sees one request per file instead of one per user).

## v29.7 (2026-09-06): one row per character, English names, no inherited CG movies
* **Unit list** (docs/units): `tools/devui/index_merges.json` is applied by `ffbe_catalog.build_index` after the Brave Shift /
  SLB pairing: 85 story / NPC / broken rows dropped, 161 rows folded into 151 characters as extra looks (Global-vs-JP ids,
  re-issues, Neo Vision awakenings; `mergedIds` on the kept row), 1541 -> 1295 units, 3806 looks. `unit_detail` and
  `/api/spec/add` reach the folded ids' forms, so a merged look can be picked and its sprites are dumped. The prefix fallback
  that gave three JP-live rows another unit's art (401008507 / 607 / 707) now skips forms owned by another unit.
* **English names**: `jp_glossary.json` gained `units` (87 exact JP names -> English, from docs/translations); `build_index` falls
  back to it after the English patch tables. 0 units without an English name.
* **No inherited CG movie**: the owners' Resonances (Crystal Braver, Riot Blade - Lotus, Ascension) play a full-screen CriWare
  movie (`Movies/Skill/MV_Skill<id>`) from a `MovieSceneManaTrack` on a spawned `BP_BtlSequencerMovieActor` in the Master
  sequence. `clone_sequence` now silences it in every copy (`movie_ops`): the movie sections lose their `ManaSource`, every
  key of the movie actor's spawn curve is turned off, and the tracks, sections and sequence get fresh signatures. Only
  existing properties are edited: the game serialises no defaults, so a track's `bIsEvalDisabled` cannot be set from the
  outside (`ffr-dt patch` refuses missing properties). A unit that borrows Cloud's Resonance no longer shows Cloud's movie;
  the wait the movie filled is still there (the unit holds its cast pose), and the template blurbs and the app's warning say so.
* App: "Play like a vision the game has" no longer switches the Resonance animation to the copied vision's own cinematic (the
  dialog always promised the animation stays); the warning text for the three owner templates updated. Catalog schema bumped.
* **Lost table dumps** (a tester's build died on `extracted/rows/Unit/DT_UnitParameter.json`): the preparation counted itself done
  as soon as `DT_SkillData.json` existed, so a run that lost any other table (interrupted, or a dump that failed) never came back.
  `setup.REQUIRED_TABLES` lists the 20 tables the studio reads; `missing()` names the absent ones, the dump step logs why a needed
  table failed, `/api/build` refuses to start while the preparation is incomplete, `make_vision_mod.rows` dumps a missing table on
  demand and otherwise says which one and that the game's data must be prepared again. App: the home page returns to the setup
  page when the engine reports the preparation incomplete; closing during a preparation asks first.

## v29.8 (2026-09-06, build 9): looks from every data region, translated names in the unit detail
* `unit_detail` took the first region that listed a unit; the Global datamine lists JP-only units (Black Thunder Claw Calice) with
  no form entries, so those units came back without looks, stats or animations and could not be added. Forms are now gathered
  from every region that has entries (first region wins a form), for the unit, its Brave Shift / SLB pair and its merged ids;
  Rain gained his 7★ and NV forms the same way. The base sheet ranks above a shifted one, so the default look is the base form.
* The detail's name (the header and "Name in the game") falls back to the `units` glossary like the index does: Alice/Half
  Nightmare and the other translated names now read in English everywhere.

## v29.9 (2026-09-06 night, build 10): Cloud's staging as the default Resonance, corrected rarities, sprites for every look
* **The new default Resonance** is Cloud's Ascension (440110), whose staging has no domain (Tronn's and Leah's do). The copy
  is not his cinematic: `make_vision_mod.CINEMATIC` / `apply_cinematic` silence the CG movie layer and the movie itself
  (`movie_ops`), silence his caption dialogue, disable the second trigger of the unit's motion, drop his own slashes on the
  targets, and pull every key from the unit's motion onward to the front (two `frames` ops: his 4.4 s idle tail first, then
  the 13.3 s cinematic window). Measured on the built sequence: LB1_before at 0 s, the unit's own motion at 1.5 s, the dash
  and the hits 1.9-4.8 s, recovery 5.9 s, end ~7 s instead of 24 s.
* **What plays on the targets** is a choice: `lb_custom.target_effect` is null (nothing beyond the hits, the default), a
  Niagara path, or `"keep"` for Cloud's own slashes. The catalog serves nine ready ones (`targetEffects`: fire, ice, thunder,
  water, wind, earth and light bursts, the healing wind, or nothing) and the Resonance step shows them as "On the targets"
  whenever the chosen animation is one of the owner cinematics.
* **Rarities** (`tools/devui/rarities.json`, rules in docs/units/rarities.md): 385 of the 1295 rows were wrong -- 244 ranges
  ran downhill (`NV` to `7`), 342 units that awaken to NV showed a star maximum, 44 NV+ forms were missing and 13 Brave Shift
  sheets were counted as NV+. The live table's `rarity` string is derived from the id suffix and lies; `nv_level` is the only
  trustworthy signal, a second sheet is detected per record, and its base is always the form ten below. `build_index` applies
  the table to every row's range and shift map, and `unit_detail` to every look's label. Warrior of Light Bartz is 5* -> NV
  with a Brave Shift on the NV form; World Wayfarer Bartz is NV; Sora (KHIII) is NV with a Brave Shift.
* **Missing portraits**: a unit whose chosen look was listed by a region without form entries got no sprite folder at all
  (both Tifa rows). `/api/spec/add` now tells `dump_ffbe_unit.dump` which looks to copy (the chosen one first).

## Later (user's roadmap)
* roles: e.g. "Pop Star" for Ariana/Katy (needs a new eUnitRole value or reuse of an existing one + UI strings).
* custom ability names that borrow existing animations (e.g. "Deluge" = Watera visuals + a casting motion): requires cloning
  `Sequencer/Battle/<kind>/<id>/…`, `Effect/03_SKL/skl<id>`, `DT_BtlEv_<id>` under the new skill id, or a runtime id redirect.
* Resonance: the blue "domain" area + LB animation per unit; mix area with the unit's LB1 motion (slash vs sing).

## Known limitations / next steps
* Lighting maps are flat (a real normal/mreo could be derived from the FFBE frames later).
* Custom-named skills need their sequence/effect/event assets cloned under the new id (or a UE4SS redirect) to animate.
* The Resonance (LB) cinematic reuses the donor's LB1 animation + whatever the game does for the background; custom backgrounds are a later topic.
* Master skills are name-only clones (the effect of a master skill is not in the tables I have patched yet — need to find where `MASTER_SKILL_DATA` ids get their effects).
* Command icon tags reuse the donors' (`UI.Skill.Command.Icon.13125/13108`); new gameplay tags would need `DefaultGameplayTags.ini` + icon rows.
