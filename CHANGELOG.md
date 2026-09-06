# Changelog

FFR Vision Studio, the Windows app. The product is 1.0.0 while the first release is being finished; every packaging run is a
build (`1.0.0.<build>` in file names, the manifest and the app's own version check). Engine changes are listed when the app
needs them.

## 1.0.0 build 7 — 2026-09-06

- The host answered with 429 (too many requests) and 404s once many people used the app at the same time. The add-unit
  dialog fetched one icon per row and one per look straight from the host, and the host only had one icon per unit.
  The icons are now one pack (every look, about 4 MB) downloaded once at setup and read from disk; the pickers make no
  host requests at all.
- Downloads back off on 429 and 5xx (honouring Retry-After) instead of failing at once; a missing file still fails fast.
- A pack that did not change between builds keeps its earlier version: this build reuses the build 6 engine (76 MB) and
  data, so updating downloads the app and the icons only.
- Update now: the helper is started through `cmd /c start`, the one route that outlives the closing app (the build 6
  helper never ran).

## 1.0.0 build 6 — 2026-09-06

- Limit-burst, magic and victory previews for Super Limit Break, Overdrive and every newer unit: the engine now finds
  `unit_limit_atk_cgs` next to `unit_limitatk_cgs` (both spellings of the archives).
- Brave Shift and Super Limit Break pairs are one unit with two looks ("7★ · Brave Shift", "7★ · Super Limit Break").
  A shifted look borrows its victory and down motions from the base form, in the viewer and in the mod.
- 53 units that exist only in the live JP client (Rain & Lasswell and others) are in the picker, with their sprites hosted.
- "Studio moves" in the Abilities library: Raegen Blast (staggers every enemy, no damage) can be granted like any ability.
- Unit page header: Back on the left, "Play like a vision the game has" and "Remove" on the right; the left column is
  the entry only.
- "Update now": the app downloads the new build, verifies it, stages it and restarts itself through a small PowerShell
  helper (started via `cmd /c start`, the one launch route that outlives the closing app); the download page remains the
  fallback, and read-only app folders are sent there.
- Developer environment (the script lives in the project repository): build a numbered pack, serve it locally, start the
  app from a scratch app-data folder.

## 1.0.0 build 5 — 2026-09-06

- Sprite packs downloaded after the engine started were invisible to it (cached folder scan): units lost their sprites and
  the build crashed on the missing sheet. The downloaded root is now checked live, the index rebuild rescans, and a build
  first heals units whose sprite copy is missing.
- Crashing tool scripts no longer show a message box: the traceback goes to `logs/engine-errors.log` and the process exits
  with code 1. Every build's console is saved as `logs/build-<stamp>.log`.
- Setup and build consoles are selectable and have a Copy button.

## 1.0.0 build 4 — 2026-09-05

- Release audit worked through: version and build number stamped into the exe and shown in the header, About page,
  offline start on installed packs, engine-exit watch with restart, close guard during builds, update notice, engine log
  files with "Logs folder" buttons, resumable downloads, sprite pack completion marker, single instance, safe unzip,
  minimum window 960×600, framed choices instead of radios, unit tests.
- Resonance step: the three animations that play the unit's limit burst come first with a description each; the owner
  cinematics are marked; a warning when the unit's motion is longer than the animation's window; caption-lines picker;
  Brave Exvius limit-burst hint; collapsible timeline. The auto-stretch measures from the first LB1 key.

## 1.0.3 (renumbered as build 3) — 2026-09-05

- All 3,800 Brave Exvius sprite forms hosted on sprite shards; every unit's face icon on the site; the add-unit dialog
  downloads a unit's pack when it is picked and shows its motions with arrows; rarity reads 1★..7★, NV, NV+.
- "Play like a vision the game has" copies a game vision's kit, stats, type, roles and Resonance numbers.
- Night edition toggle. Exe renamed `FFR Vision Studio.exe`.

## 1.0.1 (build 1) — 2026-09-05

- Install backups and "Restore the original game". Rain's face as the app icon and in the wordmark. Download page with the
  two game logos.

## 1.0.0 — 2026-09-05

- First native release: two-page spread, four Easy-mode steps with drag-and-drop tiers, build and install, first-run
  downloads of the engine and data packs, game folder detection.
