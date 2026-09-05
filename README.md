# FFR Vision Studio (Windows app)

The native front of the studio: a Flutter desktop app that downloads and supervises the Python/.NET engine
(`tools/devui`, packaged by `tools/release/build_release.py`) and drives its Easy mode natively. Design: `../../DESIGN.md`
and `lib/design/DIRECTION.md`. Plan and status: `../../docs/07-native-studio-plan.md`. Release audit: `../../docs/10-app-release-audit.md`.

## Build

```
flutter pub get
flutter analyze
flutter test
flutter build windows --release            # a developer build (version 1.0.0, build 0)
```

A release is built by the pack builder, which stamps the version into the exe and zips it with the packs:

```
python tools/release/build_release.py                          # the engine
python tools/release/build_host_pack.py 1.0.0 --build 4 --build-app --shard-hosts <list>
```

## Layout

- `lib/main.dart` window, single-instance lock, header, engine-down banner
- `lib/state/app_state.dart` boot (downloads, offline start, update notice), engine supervision, units, build, restore
- `lib/services/` engine process, downloader (resume + checksum), engine API client, game folder detection, paths
- `lib/design/` the guide's tokens (`Guide`, day and night editions), parts, wordmark, motion viewer, choice
- `lib/screens/` setup, home (spread), unit page and its four steps, add-unit, copy-a-vision, about, build status
- `windows/runner/Runner.rc` exe metadata; `windows/runner/resources/app_icon.ico` Rain's face

Test override: `FFR_STUDIO_HOST=http://127.0.0.1:8766/` with `python -m http.server 8766 --directory build/release/host`.
