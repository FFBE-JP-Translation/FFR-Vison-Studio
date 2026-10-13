# Contributing

Thanks for looking at the studio. A few things that keep it easy to work on.

## What this repository is

The Windows app and its mod tools. The app downloads the engine (Python + .NET tools packaged as
`FFR Vision Studio Engine.exe`) and game data packs on first start, then talks to the engine over localhost.
The engine and builders are maintained as source in [`mod-tools/`](mod-tools/README.md), including Vision Cards,
units, extra party members, custom battles, ability conversion and the native runtime hooks.

## Setup

```
flutter pub get
flutter analyze
flutter test
flutter build windows --release
```

Run the built exe with these environment variables to keep your real install untouched:

- `LOCALAPPDATA` pointed at a scratch folder (the app keeps everything under `<LOCALAPPDATA>\FFR Vision Studio`)
- `FFR_STUDIO_HOST` pointed at a local copy of the host tree if you have one (defaults to the live host)

Neither is required: a developer build talks to the live host, which is all you need to work on the app.

For engine or mod changes, follow [`mod-tools/README.md`](mod-tools/README.md) for Python dependencies, external
tools, source tests and the advanced build recipes. Run mod-tool commands from `mod-tools/` so their relative
paths resolve correctly. Game extraction, prepared data and native dependencies are required only for the
corresponding builders; keep generated assets, downloaded binaries and local settings out of commits.

## Design rules

The look is a strategy-guide spread; `DESIGN.md` and `lib/design/DIRECTION.md` describe it. In short:
colours come from `Guide` (both editions), pictures of the game sit in 2 px ink frames, sections open with a colour band, one
red button per screen changes the game, no rounded corners, no gradients, plain copy in the second person.

## Pull requests

- `flutter analyze` clean (infos about deprecated Material members are known), `flutter test` green.
- For mod-tool changes, run the checks in the mod-tools guide and report any game-data-dependent checks you could not run.
- For Flutter behavior changes, run the Windows app and check for runtime errors.
- One change per pull request, with a line in `CHANGELOG.md` under the unreleased build.
- Screenshots for anything visible.
