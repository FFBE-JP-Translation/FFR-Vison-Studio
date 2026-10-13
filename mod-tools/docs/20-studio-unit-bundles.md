# Builds 13–14: LB names, metadata and unit downloads

Build 14 was deployed on 2026-09-08 after local checks and public asset
verification. See [the deployment record](../deployment/README.md).

## Local Studio

Run `Studio Local.cmd` in the repository root. It starts the packaged build 14
with a temporary localhost asset server. Its separate workspace is
`build/build14/local-home/FFR Vision Studio`. It copies reusable game preparation
from the normal Studio installation, starts with an empty test mod, and retains
that test workspace between runs. Closing Studio also stops the asset server.
The regular Studio installation and installed game mods are unchanged by launch.
Units imported through this private launcher receive Raegen Blast for faster
resonance testing, as requested. Public import defaults do not grant it.

The launcher checks the staged app archive and extracts its matching executable
under `build/build14/studio/<app-hash>/`. Each build uses its own app copy; a
Studio left open from an earlier build does not block the next build. Use the
launcher to select the local asset host. Opening Flutter's shared Release exe
directly uses the public host and may still be an older build.

## Build 14: cached previews and Brave Shift

Startup downloads all 3,806 idle WebPs as one content-addressed ZIP. Browsing a
unit or changing Look reads its idle from the local `idles/` folder. It makes no
unit-bundle or individual-idle requests. A missing preview shows a placeholder
and still permits importing the unit.

Add unit downloads the selected `.ffr` and its shared sound dependencies. A
Brave Shift also downloads its base when necessary for borrowed victory/down
animations. The dialog shows the current stage, bytes and percentage, disables
selection changes while importing, and opens the editor only after preparation
succeeds. Failure leaves the chosen form and custom name available for retry.

Reported missing options were 2B -Neo Vision- (`401013807` / `401013817`) and
Sora (KHIII) (`340000107` / `340000117`). Their hosted sprites and shift mappings
already existed. The older engine rebuilt its catalog from installed sprites:
a base-only installation could omit the undownloaded shift before pairing the
two records. The shipped compact catalog now wins over that old partial cache.
The picker also merges catalog form/shift metadata into partial detail records
and gives the Look selector a full row so Brave Shift labels are readable.

Build 14 checks: 17 Flutter tests, clean Flutter analysis, seven focused Python
tests, and four packaged-engine imports (both units, base and Brave Shift).
`build/build14/bundle-smoke-results.json` records their LB names, hit frames,
sound counts and generated schedules. These are import/presentation checks;
the user still tests the resulting mod in the game. Existing audit gaps remain:
2B's two forms and Sora's shift currently have only the common charging cue;
Sora's base keeps its supported sounds while omitting unsupported cue 175.

## English resonance names

Three Terra translation batches filled 371 missing Japanese LB names. The
runtime lookup in `tools/devui/lb_names.json` covers 3,376 exact LB ID/name pairs
and 1,635 unique Japanese names. Official GL and English-patch names take
precedence over the editorial translations. Twenty-one Japanese names have
different English renderings across IDs, so they require the exact ID/name pair.

`lb_names.english_name(lb_id, source_name)` is used by the LB resolver and unit
catalog. New imports use the resolved English name. Changing an LB variant also
updates its automatic name; editing the name switches that unit to a custom name.
Existing custom names are preserved.

Reproduce the lookup with the local FFBE source dumps installed:

```powershell
$env:PYTHONUTF8='1'
python -B tools/build_lb_translation_inventory.py --merge-runtime
```

Tracked editorial maps and their uncertainty notes are under
`docs/translations/lb_names_batch1.json` through `lb_names_batch3.json`.

## Download contract

Startup obtains one icon ZIP, one idle ZIP and one small common pack, along
with the engine, game data and compact catalog. Pack checksums determine whether a download is
needed, including when icons change within the same numbered build.

Selecting a look displays its cached idle WebP. Clicking Add unit downloads a
`.ffr` archive while keeping that preview visible. The archive is an ordinary ZIP
containing:

- `sprites/<form>/`: atlas, composition data and animation timelines;
- `unit_records/<unit>.json`: translated display data, stats, skills and raw source rows;
- `lb_profiles/<form>.json`: all available regional LB variants, raw mechanics,
  movement, application frames, sound cues and unresolved-data reasons;
- `audio/lb/<form>.json`: supported recording descriptions and omitted-cue reasons;
- `ability_icons/`: icons referenced by the unit's skill list.

Archives extract under `engine/data/ffbe`. Their completion marker is written
after metadata, required sprites, sound downloads and engine indexing succeed.
A failed or incomplete download can be retried. Concurrent requests share one
download, and downloads are serialized so their 429 retries also wait their turn.
The selection is fixed during Add unit; browsing alone never queues asset work.

Sound recordings remain individual `.hca` files under `ffbe/audio/<sha256>.hca`.
Units share recordings by checksum. `audio/System.json` and the common opening
recording arrive in the startup common ZIP. The existing native audio adapter
still builds the game's ACB banks; packaging does not transcode the recordings.

The host index retains `forms` with the previous sprite ZIP URLs for old clients.
Builds 13 and newer read `unitBundles`. The complete datamine and whole SE bank are no
longer required on a fresh client's machine.

This snapshot contains 1,295 units, 3,806 `.ffr` bundles, 3,806 idle previews and
647 staged recording files. Median bundle size is about 182 KiB; median idle
preview is 12 KiB. Startup icons are 3.4 MiB, the compact catalog is about 1 MiB,
and the charging-sound pack is 10.5 KiB, excluding engine and game data. Build 14
adds roughly 68 MiB of idle previews to the first startup. Unchanged previews
are reused; adding or replacing an idle changes the pack hash and downloads it
again. Releases without preview changes do not trigger that download.

## Categories

Search supports multiple category filters together with a name or ID query.
All selected filters must match. Source tags include series, roles, elements and
named groups; older units also expose their source game. All catalog units have
at least one filter, with 143 filter values used in this snapshot.

Labels come from the local GL category text table and the live JP category/game
tables, with remaining JP labels translated in `unit_categories.json`. Game IDs
and category IDs are separate numbering schemes after the original FF titles;
`ffbe_categories.py` keeps those mappings explicit.

## Metadata coverage and remaining audit work

The preparation pass recorded 8,106 regional/form/variant cases: 7,603 have
application frames, 6,794 have sound cues, and 111 lack resolved source data.
Some cases intentionally represent a regional fallback or a form with no LB.
These counts are metadata coverage, not a claim of complete mechanics or effects.

Compatibility resonances now retain known LB frames and sounds while keeping
generic damage mechanics. Source frames remain in the bundle even if FFR's
30-hit limit requires a representative 30-event fallback. LBs without frames
retain the existing generic timing. Negative FFBE cue frames receive pre-roll,
preserving their timing relative to LB1 and damage events.

Thirty referenced audio cue IDs are still unsupported or absent. They include
stereo/HFR recordings, layered/weighted sequences, track command 2001 and missing
cue 893. Supported cues and the common charge still play. Sylvie currently has
only the common charge because matching attack-sound metadata is unavailable.
Particle effects and the remaining mechanics adapters stay on the resonance audit.

Evidence under `build/build13`:

- `assets/metadata-coverage.json`: every metadata case and audio omission;
- `presentation-check.json`: schedule validation for resolved cases;
- `bundle-smoke-results.json`: seven units loaded through the packaged engine;
- `host/`: staged complete host tree; `deploy/`: site archives.

Checks covered archive CRCs/hashes and required members for all 3,806 forms;
shared recording references; separate-data resolution without master/datamine
tables; native audio bank byte equality; and seven packaged imports: Agnès, 2B,
Raegen -Ultimate Summon-, Sylvie, Rena, Ultimate Power Rain and Eiko. In-game
listening, spacing and visual effects still need the user's test.

## Rebuild and publish

```powershell
python -B tools/release/unit_assets.py --out build/build13/assets
python -B tools/release/build_release.py --skip-web --skip-dotnet --skip-pyinstaller
python -B tools/release/build_host_pack.py 1.0.0 --build 14 --min-app 1.0.0.14 --build-app --out build/build14/host --unit-assets build/build13/assets
```

The skip flags reuse previously built engine runtimes and native tools. A clean
checkout must build those dependencies first. Unchanged unit records can be
reused across numbered app builds. If the Flutter Release exe is running, copy
the app source without `.git`, `.dart_tool`, `build` or platform `ephemeral` folders into an isolated folder
and pass `--app-source <folder>` to compile there.

The builder distributes `.ffr` files and individual idle previews into unit-site
archives. Production uses eight provisioned sites, `units1.luminest.io` through
`units8.luminest.io`. Some further site requests did not finish provisioning, so
the final two sites combine the remaining builder archives. The configured MCP
accepts these larger uploads. Stage this routing and preserve old downloads with:

```powershell
python -B tools/release/stage_production.py --build-dir build/build14 --previous 1.0.0.12 --unit-sites 8
```

Use the resulting `build/build14/production` site archives and updated host index.
Do not publish the builder's original twelve-site index. Build 15 reused the
published unit, sound, idle and legacy sprite assets. For the next release,
use `--previous 1.0.0.15`; its engine and FFBE archives are retained in `deployment`.
Preserve the published legacy sprite index and archive bytes when their contents
are unchanged; rebuilding a ZIP can change its checksum without changing sprites.

The live `idle.luminest.io` site contains `previews/idles-<hash>.zip`. The default
idle host can be changed with `--idle-host`. Retain the existing seven sprite
sites for older clients. Publish unit, idle and engine assets first. Stage the
FFBE assets while retaining its previous manifest/index/page, verify all public
objects with `tools/release/verify_host.py`, then promote the final FFBE archive.
Build 14 verified all 4,459 public objects before promotion. Never replace a live
site with an archive that omits still-advertised downloads.
