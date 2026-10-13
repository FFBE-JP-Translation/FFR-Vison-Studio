# 02 — Mod plan

Goal: custom Visions (FFBE units) with their own movesets, a mod menu, and later skins for the main cast.

## Two complementary layers
1. **Data layer (asset override paks)**: edit or append rows in the data tables, add string-table entries and (later) sprite assets.
   Pipeline (all steps verified on this game except the in-game load, which needs a restart):
   `retoc to-legacy` -> edit legacy `.uasset` with UAssetAPI / `ffr-dt` (needs `Mappings.usmap`) -> `tools/build_mod.py <dir> <Name> --install` (`retoc to-zen --version UE5_6`) -> `FFRS/Content/Paks/~mods/zzz_<Name>_P.{utoc,ucas,pak}`.
2. **Runtime layer (UE4SS)**: Lua (later C++) mods that hook `mucha` functions: open the built-in debug menu, grant Visions/items to the save, hot-patch DataTable rows in memory, and provide a keybind-driven mod menu (UE4SS ImGui or a UMG widget spawned from Lua).

## Phase A: mappings + SDK (blocked only on one game launch)
* UE4SS is installed in `FFRS/Binaries/Win64` (`dwmapi.dll` proxy + `ue4ss/`), `EngineVersionOverride 5.6`, GUI console enabled (hidden by default), `FFRAutoDump` mod generates `Mappings.usmap` + `CXXHeaderDump/` once.
* Deliverables: `extracted/Mappings.usmap`, CXX headers for `UNIT_PARAMETER`, `VISION_ITEM_DATA`, `SKILL_DATA`, `SKILL_EFFECT_DATA`, `UNIT_LEVEL_PARAMETER`, `UNIT_ASSET_DATA`, `APP_DATA_TABLE_LIST_DATA`, and the `CPP_DebugMenuSubsystem` / `CPP_MuchaGameInstance` / save-data classes.
* Risk: UE4SS experimental vs UE 5.6.1. If it fails to init, read `ue4ss/UE4SS.log`; fall back to Dumper-7 for the SDK plus a usmap dumper.

## Phase B: data pipeline proof
* `ffr-dt tojson` every table in `Datatable/Unit`, `Item/Vision`, `Skill`, `Asset/Battle/Unit`, `Strings/ST_*` into `extracted/json/` (human-readable, diffable).
* Proof mod: clone Cloud's rows (UNIT_PARAMETER, UNIT_LEVEL_PARAMETER, VISION_ITEM_DATA, UNIT_ASSET_DATA reusing Cloud's sprites) under a new row name, add the new level table to `DT_UnitLevelParameterList`, add name/description to `ST_VisionName` / `ST_VisionDescription`, package with `build_mod.py`, grant it via the debug menu or UE4SS, confirm it appears in the Vision list and in battle.
* Decide the edit strategy: override whole tables (simple, conflicts with future patches) vs. register extra tables through `CDT_AppDataTableList_Demo` (cleaner if the app merges composite tables; verify with the CXX dump of `CPP_AppAssetManagerSetting` / `APP_DATA_TABLE_LIST_DATA`).

## Phase C: mod menu
* First re-enable the game's own debug menu from UE4SS Lua: find `CPP_DebugMenuSubsystem` (a GameInstance subsystem), call its open/toggle UFunction, bind to a hotkey (F8). It already has Unit / PlayerData / Battle / Flag editors and a Vision info panel.
* Then a dedicated "FFR Mod Menu" (UE4SS Lua + ImGui, or a UMG `WBP_` built in an editor project): list custom Visions, grant and level them, swap skins, toggle cheats, reload data tables.

## Phase D: custom Vision content
* Stats/moveset: author a small JSON per unit (`mods/units/<name>.json`); a generator script writes rows into the tables above (skills into `SKILL_DATA` / `SKILL_EFFECT_DATA` / `COMMAND_SKILL_DATA`, passives into `PASSIVE_SKILL_DATA`, limit bursts). Use the FFBE data in `S:\FFBE JP Data Export` as the numeric source.
* Sprites (the hard part): FFBE cgg/cgs sheets -> SpriteStudio 6 project -> import with the SS6 UE plugin in an **Unreal 5.6 editor project** (needs UE 5.6 + the SpriteStudio6 plugin from its GitHub) -> cook -> add the cooked `Ss6Project` + textures to the mod folder -> `build_mod.py`. Until then new Visions can reuse existing in-game sprites (palette-swap the `_tex` atlas for a quick visual difference).
* Skill visuals: reuse existing LevelSequences by pointing `DT_SkillAsset` rows at them.

## Phase E: skins for the main cast (Demon Rain, Dracu Lasswell)
* Rain already has a second battle form `Chara/Unit/unit0010/unit0011`. Study how `UNIT_ASSET_DATA` / `DT_MetamorphoseItem` select it. A skin = extra `UNIT_ASSET_DATA` row + swapped atlas textures, toggled from the mod menu (runtime) or by overriding the row (data).

## Open questions to answer with the CXX dump
1. Exact field names/types of `UNIT_PARAMETER`, `VISION_ITEM_DATA`, `UNIT_ASSET_DATA` (ids are likely integers keyed separately from the Japanese row names).
2. How the save game stores owned Visions (`SaveData_UnitParameter`, `InitPlayableUnitSaveData`) so a granted custom Vision persists.
3. Whether `CPP_DebugMenuSubsystem` refuses to open in Shipping (look for an `IsEnabled` gate).
