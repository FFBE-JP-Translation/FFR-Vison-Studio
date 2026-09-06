# FFR Vision Studio (Windows app)

The native front of the studio: a Flutter desktop app that downloads and supervises the Python/.NET engine
(`FFR Vision Studio Engine.exe`, fetched from the project's host on first start) and drives its Easy mode natively.
This repository is the app on its own: it needs nothing else on disk to build, and at runtime it talks only to the
engine over localhost and to the host over HTTPS. Design: `DESIGN.md` and `lib/design/DIRECTION.md`. The engine's
source, the pack builder and the project notes live in a separate project repository, which is not published yet.

## Build

```
flutter pub get
flutter analyze
flutter test
flutter build windows --release            # a developer build (version 1.0.0, build 0)
```

A developer build is enough to work on the app: it talks to the live host exactly like a release does. A numbered
build stamps the version into the exe and into the app's own version check:

```
flutter build windows --release --build-name 1.0.0 --build-number <n> \
  --dart-define=APP_VERSION=1.0.0 --dart-define=APP_BUILD=<n>
```

`.github/workflows/windows.yml` runs analyze, test and that build on every push (build 0) and attaches the Release
folder as an artifact; a numbered build is a manual run ("Run workflow" with the build number). The zips people
download are assembled by the packaging run in the project repository, which passes the same flags and ships the
exe next to the engine and the data packs.

## Layout

- `lib/main.dart` window, single-instance lock, header, engine-down banner
- `lib/state/app_state.dart` boot (downloads, offline start, update notice), engine supervision, units, build, restore
- `lib/services/` engine process, downloader (resume + checksum), engine API client, game folder detection, paths
- `lib/design/` the guide's tokens (`Guide`, day and night editions), parts, wordmark, motion viewer, choice
- `lib/screens/` setup, home (spread), unit page and its four steps, add-unit, copy-a-vision, about, build status
- `windows/runner/Runner.rc` exe metadata; `windows/runner/resources/app_icon.ico` Rain's face

## Developing without touching your real install

Start the built exe with `LOCALAPPDATA` pointed at a scratch folder: the app keeps everything (engine, packs, units, logs)
under `<LOCALAPPDATA>\FFR Vision Studio`. `FFR_STUDIO_HOST` points it at another host tree (a local copy served on
127.0.0.1, for instance); it defaults to the live host, which is all a developer build needs.

## Files

`CHANGELOG.md` (by build), `LICENSE` (MIT for the code; the game's art and data are Square Enix's and excluded),
`CONTRIBUTING.md`, `.github/workflows/windows.yml` (analyze, test, build, artifact on every push).
