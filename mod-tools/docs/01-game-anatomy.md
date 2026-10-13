# 01 — Game anatomy (findings from 2026-09-03)

## Engine / build
| item | value |
|---|---|
| Engine | Unreal Engine 5.6.1 (string in exe), project codename `mucha` |
| Exe | `FFRS/Binaries/Win64/FFRS-Win64-Shipping.exe` (490 MB, Oodle statically linked). `FFRS.exe` at the root is the stock UE bootstrap launcher (checks VC redist, launches the shipping exe) |
| Steam | app 4474710, build 24032336, `SteamAPI_RestartAppIfNecessary` present, so Steam must be running |
| Anti-cheat / DRM | none found (no Denuvo, EAC, BattlEye strings) |
| Containers | `FFRS-Windows.utoc` (v8 ReplaceIoChunkHashWithIoHash, container header SoftPackageReferencesOffset, 35 274 chunks, 23 323 packages), `FFRS-Windows.ucas` 4.4 GB, `FFRS-Windows.pak` (v11, 2 265 loose files: ini, locres, ufont, usm movies, AssetRegistry.bin), `global.utoc/ucas` (script objects) |
| Encryption | none (key GUID zero, flags = Compressed + Indexed) |
| Compression | Oodle Kraken |
| Property serialization | **unversioned** (PackageFlags 0x80002200), so a `.usmap` is needed for row data |
| Modules | `mucha` (runtime, C++), `mucha_custom_shader`, `mucha_autotest` (stripped from Shipping), editor extension |
| Key plugins | DebugMenuWidget, SpriteStudio6, CommonUI, ModelViewViewModel, EnhancedUI, CriWare (audio), SQEXSaveGameSystem, OnlineSubsystemSteam |
| GameInstance | `/Script/mucha.CPP_MuchaGameInstance`; boot map `/Game/Map/Boot/MUCHA_Boot` |
| Data-table registry | `[/Script/mucha.CPP_AppAssetManagerSetting] AppDataTableListPath=/Game/Datatable/CDT_AppDataTableList_Demo` (composite of `DT_AppDataTableList` + `DT_AppDataTableList_Demo`), `PreLoadTableListPath=/Game/Datatable/DT_PreLoadDataTableList` |
| Saved dir | `%LOCALAPPDATA%\FFRS\Saved\` |

## Content layout (28 688 files in the utoc)
```
FFRS/Content/Env        11568   maps/environment
FFRS/Content/Effect      3791
FFRS/Content/UI          2884   CommonUI/MVVM widgets (WBP_*), textures
FFRS/Content/Chara       2868   monster/ (415 monsters) Field_Unit/ (pcXXXX, npcXXXX) Face/ menu/ summon/ Unit/
FFRS/Content/Sequencer   1839   level sequences (battle skill animations)
FFRS/Content/Datatable   1397   ALL gameplay data (see below)
FFRS/Content/L10N         773
FFRS/Content/Debug        719   debug menu BPs, battle test UI, flag editor
FFRS/Content/BP           614   mostly enemy AI (BP_BtlUnitAI_*), map gimmicks, cameras. No gamemode/gameinstance BPs (core logic is C++)
FFRS/Content/Map          532
FFRS/Plugins/DebugMenuWidget  171 (+99 UI widgets)  debug menu framework, present in shipping
FFRS/Plugins/SpriteStudio6     53  materials for SS6 sprites
```
Asset classes: 8 357 Texture2D, 2 961 BlueprintGeneratedClass, 1 142 DataTable, 24 CompositeDataTable, 335 StringTable, **669 Ss6Project**, 1 802 LevelSequence, 707 WidgetBlueprint.

## Unit system: the tables that matter
Row structs come from the asset registry (`extracted/datatable_rowstructs.tsv`). Row keys are **Japanese unit/skill names** as FNames (for example `クラウド` = Cloud, `ビジョン_クラウド`).

| table (`/Game/Datatable/…`) | row struct | notes |
|---|---|---|
| `Unit/DT_UnitParameter` (404 KB) | `UNIT_PARAMETER` | every unit incl. monsters: element/resistance enums (`eElement::Fire`, `eResistance::Weakness`…), status-condition resist (`eUnitStatusCondition::*`), refs ST_UnitName/Description/Trait01-04 string tables |
| `Unit/DT_PlayableUnitParameter` | `UNIT_PLAYABLE_PARAMETER` | 8 story chars: レイン Rain, ラスウェル Lasswell, フィーナ Fina, 魔人フィーナ Dark Fina, リド Lid, ジェイク Jake, ニコル Nichol, サクラ Sakura. Enums `eUnitRole::{Attacker,Breaker,Defender,Healer,Jammer,Enhancer}`, `eEquipmentDetailType::{HeavyArmor,LightArmor,Robe}` |
| `Unit/LevelParameter/DT_UnitLevelParameterList` | `UNIT_LEVEL_PARAMETER_LIST` | maps unit to its per-level table |
| `Unit/LevelParameter/{Playable,Vision,summon}/DT_UnitLevelParameter<Name>` | `UNIT_LEVEL_PARAMETER` | 43 tables (8 playable, 26 visions, 9 summons): stat growth per level |
| `Item/Vision/DT_VisionItemData` | `VISION_ITEM_DATA` | the Vision roster as items. Row names: アイリーン Aileen, アメリア Amelia, アヤカ Ayaka, ウォーリアオブライト WoL, オニオンナイト Onion Knight, カーミル Camille, クライヴ Clive, クラウド Cloud, シャルロット Charlotte, シャントット Shantotto, ジタン Zidane, スコール Squall, セシル Cecil, **セフィロス Sephiroth (no level table, so unreleased)**, ティナ Terra, ティーダ Tidus, トロン Thran, ノクティス Noctis, バッツ Bartz, ビクトリア Victoria, フリオニール Firion, ヤ・シュトラ Y'shtola, ライトニング Lightning, リーア Lia, ヴァン Vaan, ヴィルヘルム Wilhelm |
| `Item/Vision/DT_VisionAwakeningMasteryData`, `DT_VisionSynchroMasteryData` | `VISION_MASTERY_DATA` | vision awakening / synchro mastery boards |
| `Item/Vision/DT_VisionUpgradeItemData` | `VisionUpgradeItemData` | |
| `Skill/DT_SkillData` (655 KB) | `SKILL_DATA` | about 1 000 skills; icon gameplay tags `UI.Skill.Action.Icon.*`; refs ST_SkillName/Description |
| `Skill/DT_SkillEffectData` | `SKILL_EFFECT_DATA` | effects applied by skills |
| `Skill/DT_PassiveSkillData` | `PASSIVE_SKILL_DATA` | |
| `Skill/DT_CommandSkillData` | `COMMAND_SKILL_DATA` | battle command entries |
| `Skill/DT_MasterSkillData` | `MASTER_SKILL_DATA` | |
| `Skill/Other/DT_Skill{Target,DamageCalc,RecoveryCalc,General,AttributeDetail,PowerThreshold,SealPoint,MapEffect,LinkSequencer}Data` | various | formulas / targeting |
| `Asset/Battle/Unit/DT_BtlUnitAsset` | `UNIT_ASSET_DATA` | unit id to sprite assets (`/Game/Chara/…/<id>`, `_tex`, `_normal`, `_mreo`) + material |
| `Asset/Battle/Unit/DT_BtlPlayableUnitAsset` | `BTL_PLAYABLE_UNIT_ASSET` | |
| `Asset/Skill/CDT_SkillAsset_Demo` (parent `DT_SkillAsset`) | `SKILL_ASSET_DATA` | skill id to level sequence / effect assets |
| `Battle/Unit/DT_BtlUnitDesignParameter` | `BTL_UNIT_DESIGN_PARAMETER` | |
| `Unit/DT_UnitBattleCmd` | `UNIT_BATTLE_CMD_DATA` | |
| `Strings/ST_Unit/ST_UnitName`, `ST_UnitDescription`, `ST_UnitTrait01-04`; `Strings/ST_Item/ST_VisionName`, `ST_VisionDescription`; `Strings/ST_Skill/ST_SkillName`, `ST_SkillDescription` | StringTable | display text (localized through `Content/Localization/Game/<lang>/Game.locres`) |
| `DT_AppDataTableList`, `DT_AppDataTableList_Demo`, `CDT_AppDataTableList_Demo` | `APP_DATA_TABLE_LIST_DATA` | master registry the app loads (the demo composite overrides 5 tables with `*_Demo` composites) |

## Per-unit asset set (what a new Vision needs)
Example Vision `summon13017` (visions are `summon13xxx`, espers `summon3000xx`, story chars `unit00x0`, monsters `monsterNNN`):
```
Chara/summon/summon13017/summon13017.uasset          Ss6Project (SpriteStudio 6 animation project)   190 KB
Chara/summon/summon13017/summon13017_tex.uasset      colour atlas   1 MB
Chara/summon/summon13017/summon13017_normal.uasset   normal map     256 KB
Chara/summon/summon13017/summon13017_mreo.uasset     metal/rough/emissive/occlusion 1 MB
Chara/menu/summon13017/summon13017.uasset  + _tex, summon130180.uasset   menu portrait sprites
Chara/Face/<id>_NN[_BU].uasset                        dialogue faces (story chars/NPCs)
```
Story characters additionally have `Chara/Field_Unit/pc00x0/` (field sprites, variants `_00/_01/_02`) and `Chara/Unit/unit00x0/` (battle sprites; `unit0011` = alt form/costume of Rain, which is the skin hook).
Battle visuals for skills are LevelSequences under `Content/Sequencer` bound via `DT_SkillAsset`, `DT_BattleSequencerBindUnitData`, `DT_BattleSequencerUnitAnimationData`.

## Debug menu (the shipping build still contains it)
* Config: `FFRS/Config/DefaultDebugMenu.ini` (extracted). Layout widget `/DebugMenuWidget/UI/DM_WBP_OverallLayout`, `IsAllowAutoCreate=False`.
* Implementations: `/Game/Debug/DebugMenu/BP/BP_DebugMenu_{Unit,PlayerData,Battle,Map,System,Event,…}`, `BP_DebugFlagEditor`, `BP_DebugProgressSetting`, Colosseum, Quest, Save.
* C++ (in exe): `CPP_DebugMenuSubsystem`, `CPP_DebugMenuManager`, `CPP_DebugMenuSettings`, `CPP_DM_GameLayoutSubsystem`, `CPP_DebugMenuInputManager`, `CPP_DMI_Subsystem`; gameplay tags like `DebugMenu.Root.Battle.Unit.FriendliesInvincible`, `DebugMenu.Root.Battle.System.ForceWin`.
* Input: `IMC_DM_BeforeOpening` / `DM_IA_Open` (Enhanced Input). The mapping is probably not applied in shipping; UE4SS can call the subsystem directly.
* Battle test UI: `Debug/BattleTest/UI/WBP_DBG_BtlTest_*` incl. `FriendliesUnitVisionInfo`.
* Debug-menu localization exists (`Localization/DebugMenu/en/DebugMenu.locres`).

## Useful native (BlueprintCallable) functions seen in the exe
`GetUnitParameterById`, `GetAllUnitParameterList`, `GetUnitParameterByLevel`, `GetPlayableUnitParameter`, `SetPlayableUnitParam`, `SetPlayableUnitExperience`, `FindVisionItemDataById`, `GetBattleUnitParameterWithVision`, `GetSkillDataById`, `GetSkillDataListFromCategory`, `GetPassiveSkillDataById`, `DBG_SetUnitParameterSelectedInUnitDM`, `InitPlayableUnitSaveData`, `GetSaveDataUnitParameterList`.
Classes: `UCPP_UnitParameter`, `UCPP_BtlUnitParameter`, `UCPP_BFL_UnitParameterCalc`, `UCPP_MapUnitParameterStorage`, `ACPP_BtlUnit`, `ACPP_BtlSequencerSsPlayerActor`, VM_* view-models for UI.
Full lists: `extracted/exe_strings/*.txt` (3 103 CPP_ classes).

## Source material on this machine
`S:\FFBE JP Data Export\` holds a full FFBE (mobile) export: 3 088 unit sprite sets (`BFFrameAnimator-master/Units/<unitId>`), `new units/` (unit_anime_*.png + cgg/cgs csv frame data), monsters, vision cards, .ssbp (SpriteStudio 5 binary) battle backgrounds, and the FFBE-sprite-sheet-assembler tool. FFBE unit IDs look like `401001417`. FFBE frames are cgg/cgs CSV, not SpriteStudio, so a converter to SS6 (.sspj/.ssae/.ssce) is needed for in-game sprites.
