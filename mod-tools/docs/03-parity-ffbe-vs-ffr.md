# 03 — Parity: FFBE unit  ->  Resonance Vision

Reference material in the repo: `units/ffr/cloud/` (Resonance Cloud, Vision 13110) and `units/ffbe/{cloud,esther,tsukiko}/` (FFBE Cloud 207000105, Esther 401006805 + Storm Seeker forms, Tsukiko 401007105 + Shrine Maiden forms). Struct definitions: `extracted/row_structs.txt`, enums in `extracted/CXXHeaderDump/mucha_enums.hpp`.

## What a Vision is in Resonance (every row a converter has to write)

| # | table (`/Game/Datatable/…`) | row struct | row key | what to fill |
|---|---|---|---|---|
| 1 | `Unit/DT_UnitParameter` | `UNIT_PARAMETER` | JP display name (e.g. `クラウド`) | `ID`=VisionId (13xxx), `SortId`, `SaveId`=ID, `Level` 99, `LevelParamId` (10xxx), `Sex`, `Race`=Vision, `Category`=Vision, `MaxHitPoint/MaxMagicPoint/Attack/Defence/Intelligence/Mind/Agility` (base at Lv1), `ElementResistanceList` (8 elements -> `eResistance`), `StatusConditionResistanceList` (17 -> int %), `VisionId` -1, `passiveSkillList` [], `FaceIconId`=ID, `Name`/`Description` -> ST_UnitName/ST_UnitDescription keys `UnitName<ID>` / `UnitDescription<ID>` |
| 2 | `Item/Vision/DT_VisionItemData` | `VISION_ITEM_DATA` | JP name | `ID`=VisionId, `SortId`, `finishBlowSkill` (LB skill id), `CommandId` (-> 3), `attackType` Physic/Magic, `roles` [`eUnitRole::…`], `ItemType`=Equipment, `Name`/`Description` -> ST_VisionName/ST_VisionDescription keys `VisionName<ID>` / `VisionDescription<ID>` |
| 3 | `Skill/DT_CommandSkillData` | `COMMAND_SKILL_DATA` | `<name>の技` | `ID` (100+ for FF visions, 200+ for FFBE originals), `unitIdToUseSkill`=VisionId, `Name` -> `CommandSkillName<ID>`, `SkillIcon` tag `UI.Skill.Command.Icon.<VisionId>` |
| 4 | `Skill/DT_MasterSkillData` | `MASTER_SKILL_DATA` | JP name | `ID` = VisionId*100 (1311000), `VisionId`, `equipCost`, `Name`/`Description` -> `MasterSkillName<ID>` |
| 5 | `Unit/LevelParameter/DT_UnitLevelParameterList` | `UNIT_LEVEL_PARAMETER_LIST` | `ビジョン_<name>` | `ID`=LevelParamId, `DataTable` -> new `DT_UnitLevelParameter<Name>` |
| 6 | new `Unit/LevelParameter/Vision/DT_UnitLevelParameter<Name>` | `UNIT_LEVEL_PARAMETER` | `1`..`100` | per level `RequiredExperience`, `AddMaxHitPoint`, `AddMaxMagicPoint`, `AddAttack`, `AddDefence`, `AddIntelligence`, `AddMind`, `AddAgility`, `AddSkillEquipCost`, `AddSkills[3]` |
| 7 | `Item/Vision/DT_VisionAwakeningMasteryData` | `VISION_MASTERY_DATA` | `<name>覚醒度N の恩恵` | 4 rows (`Level` 0-3, `masteryPoint` 0-3): up to 8 `detailData` each `{parameterType: ActiveSkill|PassiveSkill|BaseParameter|MasterSkill, params:[id, x]}` — this is where the kit is granted |
| 8 | `Item/Vision/DT_VisionSynchroMasteryData` | `VISION_MASTERY_DATA` | `<name>SLvN` | 10 rows (`Level` 0-9, points 0,10,35,95,195,395,695,1195,2195,4195): passives, `BaseParameter [statType, amount]`, extra actives, `MasterSkill` at SLv9 |
| 9 | `Skill/DT_SkillData` | `SKILL_DATA` | JP skill name | one row per unique active skill (unit-specific ids 4xxxxx; shared magic 2xxxxx / 1xxxxx can be referenced as-is) — see field list below |
| 10 | `Skill/DT_PassiveSkillData` | `PASSIVE_SKILL_DATA` | JP name | one row per unique passive (ids 1xxx), `effectBundleList` -> effect ids |
| 11 | `Skill/DT_SkillEffectData` | `SKILL_EFFECT_DATA` | JP name | effects referenced by 9/10 (reuse existing ids wherever the effect already exists: stat buffs, crit, element imbue…) |
| 12 | `Asset/Battle/Unit/DT_BtlUnitAsset` | `UNIT_ASSET_DATA` | JP name | `ID`, `animationAssetList[0]` = `{isVisionCharacter:true, Ss6Project:/Game/Chara/summon/summon<ID>/summon<ID>, Material:/Game/BP/Map/Unit/Material/CharaPBR/M_Ss_Component_PBRBattle, textureBaseColor:…_tex, textureNormal:…_normal, textureMetallicRoughness:…_mreo}`, `shadowScale`, `Footstep` Common |
| 13 | `Battle/Unit/DT_BtlUnitDesignParameter` | `BTL_UNIT_DESIGN_PARAMETER` | JP name | `ID`, `Size` M, scale/offsets/shadow |
| 14 | `Unit/AI/DT_BtlUnitAIParameter` | `BTL_UNIT_AI_PARAMETER` | | (only if the vision needs AI; Cloud has none) |
| 15 | `Strings/ST_*` string tables + `Localization/Game/<lang>/Game.locres` | StringTable | key | JP source text in the string table; EN/other languages in locres (namespace = table name, key = `VisionName<ID>` etc.) |
| 16 | `Asset/Skill/DT_SkillAsset` | `SKILL_ASSET_DATA` | | skill id -> LevelSequence for the skill's battle visuals (reuse existing sequences for converted skills) |
| 17 | `Datatable/UI/...` icons | | | `UI.Skill.Command.Icon.<VisionId>` gameplay tag + icon texture (`Content/UI/Textures/Icon`) |
| 18 | sprites | Ss6Project + 3 textures (+ menu portrait project + tex) | | `Chara/summon/summon<ID>/` and `Chara/menu/summon<ID>/` |
| 19 | ID -> asset maps (`CPP_DA_RegularIdAsset` data assets, baked at cook time from folder scans) | `assetMap` TMap<int32, FSoftObjectPath> | ID | `Datatable/UI/Unit/Asset/DA_MenuUnitSsProject` (menu Ss6Project), `DA_UnitIcon_Timeline` (Vision_Face icon), `DA_UnitIconTexture` (Unit_Face_Timeline icon); plus `UI/Unit/UIUnitSs/Data/DA_UIUnitSsLayout.LayoutOverrideDataMap` for menu sprite scale. Without these entries the vision emblem shows an endless spinner (verified 2026-09-03). `ffr-dt patch` "objects/mapAdd" handles them |

IDs used by the game today: visions 13017…13130 (FF visions 13100+, FFBE-original visions 13017…13080), level tables 10001…, command sets 100…130 / 200…209, master skills VisionId*100, LB skills 4401x0 / 41xxx0, unit skills 42xxxx / 446xxx, passives 12xx–14xx. New content should use unused ranges (e.g. visions 13200+, level 10100+, commands 300+, skills 47xxxx, passives 5000+).

## Field-level mapping FFBE -> FFR

| FFBE (ffbeEquip sources) | Resonance |
|---|---|
| `entries[<7★ id>].stats.HP[1]` (max at 7★) etc. | `UNIT_PARAMETER.MaxHitPoint` at Lv1 + `UNIT_LEVEL_PARAMETER.AddMaxHitPoint` per level so that Lv100 total ≈ FFBE max. Cloud (FFR) is Lv1 800 HP/25 ATK growing +1 per level per stat, so Resonance numbers are ~1/20 of FFBE numbers: scale HP by 1/6 (4856 -> ~800) and ATK/DEF/MAG/SPR by 1/8, then split into base + linear growth |
| `stats.MP` | `MaxMagicPoint` (FFR visions use 100) |
| `ATK`, `DEF`, `MAG`, `SPR` | `Attack`, `Defence`, `Intelligence`, `Mind` (there is no FFBE→`Divine`; leave 0) |
| (no FFBE stat) | `Agility` — derive from role (Breaker/Attacker ~15, Jammer/Healer ~12) |
| `element_resist[8]` (%) | `ElementResistanceList` -> `eResistance::{Weakness(<0), None(0), Halved(>0), Invalid(100), Absorb}` (order Fire, Ice, Thunder, Water, Wind, Earth, Light, Dark in FFBE; FFR enum eElement) |
| `status_resist[8]` (%) | `StatusConditionResistanceList` (17 conditions; map poison/blind/sleep/silence/paralyze/confuse/disease→none/petrify) |
| `roles` (Attacker, Tank, Mage, Breaker, Support, Healer, Jammer…) | `roles` -> `eUnitRole::{Attacker,Breaker,Defender,Healer,Jammer,Enhancer}` (Tank→Defender, Mage→Attacker, Support→Enhancer, Debuffer→Jammer) |
| physical vs magical damage skills majority | `attackType` Physic/Magic |
| `limitbursts[<id>]` (name, attack_count, attack_damage[], damage_type, element_inflict, min_level/max_level effects, levels) | `SKILL_DATA` row with `skillAttrType`=FinishBlow, `skillEffectType`=DamageAndRecovery, `DamageType`, `element`, `magnification` (FFR LB Ascension = 36 for a 10-hit 4.x FFBE-style modifier: use `max_level` modifier*~9), `hitCount`=attack_count, `hitDamageRatioList` from attack_damage, `accuracy` 500, `criticalHitRate`; referenced by `VISION_ITEM_DATA.finishBlowSkill` |
| `skills[]` entries with `type`=ABILITY/MAGIC + resolved `skills_ability`/`skills_magic` (`effects`, `effects_raw`, `cost.MP`, `attack_type`, `element_inflict`, `attack_count`, `attack_damage`) | `SKILL_DATA` rows: `skillAttrType` Ability/Magic/MagicSword, `Cost`=MP, `DamageType` Physic/Magic/None, `element`, `TargetType` Single/All/Self/…, `magnification` (FFBE % modifier /10: Cross-Slash 45 ≈ FFBE 4.5x), `hitCount`, `effectBundleList` -> `SKILL_EFFECT_DATA` ids (buffs/debuffs/imbues map onto existing effect rows; e.g. 19049 Bravery, 19051 Haste, 19052 Debrave, 13300/13301 crit multipliers, 1045 Libra) |
| `skills[]` with `type`=PASSIVE + `skills_passive` (`effects_raw` codes: stat%, killer, crit, etc.) | `PASSIVE_SKILL_DATA` rows (ids 1xxx) with effect bundles; unlock them through awakening/synchro tiers |
| `skills[].rarity/level` (unlock order) | distribute over awakening tiers 1-4 (actives + passives, 8 slots each) and synchro SLv1-9 (passives / base parameter bumps / SLv9 master skill); Cloud pattern: tier1 = 4 skills + 2 passives |
| `TMR` / `sTMR` (equipment/materia) | closest FFR analogue is the **master skill** (`MASTER_SKILL_DATA`, an equippable passive with `equipCost`) at SLv9 — or an `EQUIPMENT_ITEM_DATA` row if we want the item itself |
| `names[]` (EN, ZH, KO, FR, DE, ES…) | string table (JP) + locres per language |
| `job`, `sex`, `tribe_id` | `Sex`, `Race`=Vision (job only as description text) |
| NV brave shift (`braveShift` id, 2nd form) | Resonance has `skillIdAfterModeChange` + a second `UNIT_ASSET_DATA` animation entry (Rain's alt form `unit0011`) — possible later, not needed for a first version |

## Sprite mapping (FFBE cgg/cgs -> SpriteStudio 6)

FFBE (`units/ffbe/<name>/sprites/<id>/`):
* `unit_anime_<id>.png`: atlas of parts (no fixed grid).
* `unit_cgg_<id>.csv`: one line per composed **frame**: `anchor, partCount, then per part: xPos, yPos, nextType(flip), blendMode, opacity, rotate, imgX, imgY, imgW, imgH, pageId`.
* `unit_<anim>_cgs_<id>.csv`: one line per animation step: `frameIndex, xOffset, yOffset, holdFrames` (FFBE runs at 60 fps; hold 12 = 200 ms). Animations: idle, standby, move, atk, magic_standby, magicatk, limitatk, jump, dying, dead, win, winbefore (+ brave_shift, some units have extra like `atk1`).
* The FFBE-sprite-sheet-assembler (in `S:\FFBE JP Data Export\FFBE-sprite-sheet-assembler-0.3.1`, JS) already composites cgg frames into full images.

Resonance (`units/ffr/cloud/ss6_summary.json`):
* one `Ss6Project` = 1 cellmap (`summon<ID>.ssce`, 1024x1024 atlas, ~185 cells named `summon_<row>_<col>`) + 1 animepack (`summon<ID>.ssae`) with a 31-part rig: `root` > `position` > `part_0..7`, `part_add_0..12`, `weapon`/`NULL_Weapon`/`NULL_End`/`NULL_Tip`, `NULL_Center`, `NULL_Head`, `NULL_SKL000000_Magic`, `NULL_Root`. Null parts are attachment points the battle code uses (weapon tip for effects, head for status icons, magic origin).
* 25 animations at 60 fps: `idle`(49f), `command`(49f), `step_front`/`step_back`(5f), `attack_A`(149f), `attack_B`(32f), `attack_C`(36f), `attack_D`(83f), `attack_E`(149f), `magic_idle`(33f), `magic_attack`(17f), `M_attack01/02`(10f), `LB1_before`(194f), `LB1`(320f, canvas 752x914), `cushion`(10f), `jump`(5f), `dying`(5f), `dead`(5f), `win`(290f), `win_Loop`(49f), `Rankup`(290f), `Rankup_Loop`(49f), `Lock`(10f), `Setup`(1f).
* Cell-swap style: most frames just switch the `Cell` of a part and move `Posx/Posy`, so pre-composed FFBE frames can become cells directly.

Proposed converter mapping:
| FFBE cgs | FFR animation | notes |
|---|---|---|
| idle | idle, command | loop |
| standby | Lock, cushion | |
| move | step_front, step_back (mirrored) | |
| atk | attack_A (also copy to attack_B..E) | |
| magic_standby | magic_idle | |
| magicatk | magic_attack, M_attack01/02 | |
| limitatk | LB1 (+ idle for LB1_before) | LB canvases are large; keep offsets |
| jump | jump | |
| dying / dead | dying / dead | |
| win / winbefore | win_Loop / win, Rankup_Loop / Rankup | |

Pipeline (implemented 2026-09-03, no Unreal editor needed):
1. `tools/ffbe2ss6/ffbe_frames.py` composes cgg frames exactly like the assembler (parts drawn last-to-first, flips, rotation, opacity, blendMode 1 = premultiplied "additive" glow) with the FFBE origin at the canvas centre.
2. `tools/ffbe2ss6/build_sprites.py` trims every frame used by the mapped animations into a cell, packs a power-of-two atlas, sets the cell pivot to the FFBE origin (`pivot = ((ox - w/2)/w, (h/2 - oy)/h)`, +Y up), writes keys (`Cell` per cgs step, `Posx`/`Posy` = cgs offsets with Y flipped, cumulative hold frames as key times, 60 fps) and emits `spec.json` + raw texture payloads (BGRA8 atlas, flat BC5 normal, flat BGRA8 mreo).
3. `ffr-dt make-ss6 <donor project> <spec> <out> <oldPkg> <newPkg>` clones a donor `Ss6Project`, rebuilds `CellmapList[0]` and `AnimeList[0].AnimeList` from the spec (keyframe/attribute/part structs cloned from the donor), and regenerates the export's custom tail: `USs6Project::Serialize` writes, per animation/part/attribute/key, `FSsValue::Serialize` — float keys = 4 bytes; Cell keys = `int32 2, FName mapId, 80 09 0e 03, float 0, FName name, 80 09 0e 01, FString cellName` (the 4-byte blocks are the unversioned property header of the nested FSsValue). Verified byte-exact against Cloud's projects with `tools/ffbe2ss6/ss6_tail.py`.
4. `ffr-dt make-texture <single-mip donor> <payload> <w> <h> <out> ...` splices new pixels into a cooked Texture2D (header: SizeX @0x2c, SizeY @0x30, int64 skip offset @0x14; one inline bulk data resource; footer = mip dims + None). Use Cloud's textures as donors (Lightning's carry a mip chain).
5. `retoc to-zen` packs everything; `DA_MenuUnitSsProject` / icon maps get the new IDs (row 19).
Scale matches: FFBE frames are ~75 px tall with the origin at the feet, Cloud's head null sits at +61 px.

## Numbers to keep in mind (from Cloud)
* Lv1 base: HP 800, MP 100, ATK 25, DEF 30, INT 10, MND 20, AGI 15; +1 per level for HP/MP/ATK/DEF/INT/MND/AGI (levels 2-100); EXP curve 19, 38 … 96 772 at Lv100.
* LB "Ascension": Physic, Thunder, Single, 10 hits, magnification 36, accuracy 500, crit 25, effect 13301 (CritMul).
* Braver: 18 MP, mag 33, 1 hit; Cross-Slash: 42 MP, mag 45, 3 hits; Thunder Surge line 5/15/44 MP, mag 12/24/39.
* Master skill "Spirit of Cloud": equipCost 105, filters [2].
