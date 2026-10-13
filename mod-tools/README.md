# Vision Studio mod tools

This is the editable source of the engine and game mods, alongside the Flutter
app in the same repository. It includes the current local implementation,
including features that have not been packaged into a public engine release.
Use this folder as the working directory for the commands below. The relative
`tools/`, `src/`, `data/` and `build/` layout keeps the tools independent of the
old development workspace.

## Find a feature

| Feature | Source |
| --- | --- |
| Vision and unit generation | [`tools/make_vision_mod.py`](tools/make_vision_mod.py), [`tools/build_mod.py`](tools/build_mod.py) |
| Unit imports and custom sprite uploads | [`tools/devui/vision_import.py`](tools/devui/vision_import.py), [`tools/devui/custom_units.py`](tools/devui/custom_units.py) |
| Vision Card catalog, stats, artwork and package | [`tools/vision_cards.py`](tools/vision_cards.py), [`tools/make_vision_card_mod.py`](tools/make_vision_card_mod.py) |
| Card equipment, menu and battle runtime | [`src/ffr-vision-cards/`](src/ffr-vision-cards), [`tools/export_vision_card_runtime.py`](tools/export_vision_card_runtime.py), [`tools/install_vision_cards.py`](tools/install_vision_cards.py) |
| Extra party members and save records | [`tools/private/make_party_mod.py`](tools/private/make_party_mod.py), [`tools/private/ffr_party_save.py`](tools/private/ffr_party_save.py) |
| Custom battles, NPC, boss sprites and music | [`tools/private/make_npc_battles.py`](tools/private/make_npc_battles.py), [`tools/private/npc_assets.py`](tools/private/npc_assets.py), [`tools/private/battle_music.py`](tools/private/battle_music.py) |
| Ability mechanics and reviewed conversion rules | [`tools/ability_converter/`](tools/ability_converter), [`data/ability_converter/reviewed-rules.json`](data/ability_converter/reviewed-rules.json) |
| Native ability availability bridge | [`src/ffr-availability-native/`](src/ffr-availability-native) |
| Animation, effects, audio and camera conversion | [`tools/ffbe2ss6/`](tools/ffbe2ss6), [`tools/ffbe_effects/`](tools/ffbe_effects), `tools/ffbe_*.py` |
| .NET tables, textures and sequence editing | [`src/ffr-dt/`](src/ffr-dt) |
| Independent cooked-output export and validation | [`src/ffr-export/`](src/ffr-export) |
| Local engine API and advanced React editor | [`tools/devui/server.py`](tools/devui/server.py), [`tools/devui/web/src/`](tools/devui/web/src) |
| Engine and data-pack packaging | [`tools/release/`](tools/release) |

`private` is a historical folder name. Its builders and helpers are now ordinary
source in this repo. Party and battle definitions are currently the fixed demo
addons in those builders; source inclusion does not add a new editor screen.
`SOURCE.json` records the original source import. Work on these files here.

## Check the source

Python 3.12 is the supported interpreter. From `mod-tools/`:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python check_source.py
.venv\Scripts\python check_source.py --tests
```

The checks validate syntax, source dependencies and tests using synthetic data.
Tests that require a game extraction, real card artwork, or an already built mod
are separate integration checks under `tools/tests/`. They remain checked in.
The source checks run in `.github/workflows/mod-tools.yml`.

Build the advanced web editor separately with Node.js and npm:

```powershell
cd tools/devui/web
npm ci
npm run build
```

Return to `mod-tools/` before running engine commands. The Flutter app continues
to build from the repository root with its existing Flutter commands.

## Prepare external dependencies

Generated game data, extracted assets, installed third-party binaries, personal
rosters and compiled mod outputs are ignored. The sample roster at
`mods/EstherTsukiko/units.json` starts empty. Authored rules, source translations,
layout settings and small UI artwork references are checked in.

An installed Studio engine can supply the downloaded data and tool binaries:

```powershell
.venv\Scripts\python dev.py prepare --runtime "$env:LOCALAPPDATA/FFR Vision Studio/engine"
```

This copies missing dependency files into this source root without replacing
checked-in code or rules. If supplied, `bin/ffr-dt.exe` is a prebuilt dependency;
remove that local file when testing the .NET source build below, because
`ffrenv.py` prefers it. Preparing dependencies does not extract or install mods.

To build the .NET tools from source, install the .NET 8 and 10 SDKs. Place the
compatible UAssetAPI assembly in `tools/UAssetAPI/UAssetAPI.dll` (the original
dependency used by `ffr-dt`) and run:

```powershell
dotnet build src/ffr-dt -c Release
dotnet build src/ffr-export -c Release
```

When running `ffr-export` directly, set `FFR_PAKS` to the game's
`FFRS/Content/Paks` folder. Its exporter reads this variable independently of
the Python engine's `FFR_GAME`/`config.json` settings.

`tools/fetch_tools.py` downloads public retoc, repak, UAssetAPI and other tooling
archives to `tools/downloads/`; extract the required tools into their named
folders. Tool binaries and their upstream licenses remain separate dependencies.
No .NET or native build is claimed by the Python source checks.

The engine needs native mappings and game-side data from the Studio base pack.
The complete release also needs the prepared ability-kit database, reference
table dumps, FFBE tables, icons and converted media. These inputs can be supplied
from installed packs or generated by the checked-in extraction/conversion tools.
Source inclusion does not bundle those large datasets.

Optional offline HCA transcoding uses `cricodecs.hca`, located through
`FFBE_CRICODECS_PATH` by `tools/ffbe_effects/hca_transcode.py`. Supply that
separate codec dependency when performing source-audio conversion; the local
engine and source checks do not require it.

Configure `config.json` locally, or pass `FFR_GAME` to choose the game. For cards,
the `visionCards` configuration accepts `metadataRoot` (the folder with
`jp/vision_cards.json` and/or `gl/vision_cards.json`) and `assetRoots` (artwork/CPK
folders). Defaults use local `data/ffbe` and `data/vision_cards/source` folders.
FFBE conversion and older diagnostic scripts can require their own source paths;
see their arguments and docstrings before using them.

## Run and build from this checkout

Start the source engine on localhost:

```powershell
.venv\Scripts\python dev.py engine --port 8765
```

Then connect the Flutter app from another terminal at the repository root:

```powershell
$env:FFR_STUDIO_API = 'http://127.0.0.1:8765'
flutter run -d windows
```

Alternatively, `tools/devui/start_studio.ps1` builds the local app when needed,
starts this source engine and connects the desktop app. It uses the local
`.venv` when present. The engine can start without prepared game data and report
what is missing; producing a mod requires the dependencies described above.

After supplying game data and tool binaries, prepare the source workspace:

```powershell
.venv\Scripts\python tools/devui/setup.py --game '<game folder>'
```

Stage the mod outputs before installation:

```powershell
.venv\Scripts\python tools/make_vision_mod.py --no-install
.venv\Scripts\python tools/private/make_party_mod.py
.venv\Scripts\python tools/private/make_npc_battles.py
.venv\Scripts\python tools/make_vision_card_mod.py
```

The party builder also needs portrait files documented in [`party/README.md`](party/README.md),
and party/battle builders need local FFBE sprites/music. See
[`docs/19-custom-units-battles.md`](docs/19-custom-units-battles.md) and
[`docs/48-vision-cards.md`](docs/48-vision-cards.md) for their game-specific details.
Install switches are separate: the party installer can edit saves, while
`--keep-saves` refreshes its assets without changing those records.

Cards use the pinned UE4SS runtime identified by
`src/ffr-availability-native/bootstrap.py`. With Visual Studio 2022 C++ tools,
CMake, and that runtime under `tools/UE4SS/`, prepare and build the native hooks:

```powershell
.venv\Scripts\python src/ffr-availability-native/bootstrap.py
.venv\Scripts\python src/ffr-availability-native/build.py
.venv\Scripts\python src/ffr-vision-cards/build.py
.venv\Scripts\python tools/export_vision_card_runtime.py build/vision-cards/runtime/FFRVisionCards
```

The bootstrap checks pinned dependency hashes. Native builds create files under
`build/` and do not install them into the game. Full card installation remains
the separate `tools/install_vision_cards.py` command and its game-version checks.

Package the source engine with `python tools/release/build_release.py`, after
preparing its required release data and web editor. Its scripts and .NET tool
are built from this folder. `build_host_pack.py` finds the Flutter app in the
parent repository; `--app-source` can select another checkout. Publishing helpers
are included as source but are separate from the source checks and local builds.
