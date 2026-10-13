# Vision cards

Vision cards have their own **VISION CARD** heading and blue equipment slot directly below Visions for every character. The heading uses the native section widget, and equipment-panel text is reduced by one point. Each equipped copy adds only its six flat stats at the card's maximum level. Card passives and level progression are not enabled. The existing Vision and accessory slots keep their normal behavior.

Open the new row to browse owned cards in a fixed three-column, nine-card page. Empty cells retain their size, including when only one card is owned. Only the highlighted card animates, when animation exists. Use the D-pad to select, A to equip and B to return; keyboard equivalents are arrows, Enter and Escape. Select **Remove card**, illustrated with the supplied `download.png`, to clear the slot. An inventory copy can be equipped by one character at a time.

The selector uses the native game font and has no X/Y details action or tooltip. The existing character **Skill Details** screen now includes a **VISION CARD** section below the skill list: the equipped card animates beside its maximum level and six flat stats. Native skill navigation and Back remain available, and the section follows the displayed character, including empty card slots.

## Mitra merchant

A new NPC to the accessory merchant's left carries the tilted FFBE card back inside the native overhead bubble. The actor is at X=134, Y=3734, Z=298.443; increasing X would put it behind the stall. Ten cards cost 1 gil each, with unlimited purchases:

- Azure Successor
- Memories of Akstar
- Shimmering Hoarfrost
- Meeting with a Girl
- Dragon Tear
- Vacation, All I Ever Wanted
- Hero of Grandshelt
- To the Uncharted Future!
- Battle with Marilith
- In Order to Change the World

## Vision Studio

Run `tools/devui/start_studio.ps1` in the repository, then select **VISION CARDS**. **Import all** imports the configured FFBE metadata and artwork. Source folders can be changed in the tab. Grid images stay static; the selected card animates in the right-hand preview. The library supports search, maximum-level stats and import progress.

The initial import contains 350 cards: 276 with animation and 74 still cards. English GL metadata takes precedence for shared JP/GL card IDs. The importer also supports JP-only cards. Source maximum levels are retained, including levels 1, 2 and 10.

Animations retain their complete source timeline and match the full-card still's framing instead of showing the small vignette stage. OpenCV matches distributed scene landmarks to recover each card's camera (274 use 2x pixel scaling; two use 3x); matching background patches handles heavy glow. `framing.json` beside each animation records the result. The card frame is composited after the scene transform, and game playback uses elapsed real time rather than assuming every timer callback arrives on schedule. The Python engine requires OpenCV as well as Pillow and NumPy; its launcher includes OpenCV for packaging.

Blank GL titles fall back to JP titles. `tools/vision_card_names.json` provides local English translations for titles without English source names, including **BLOODY ESCAPE: Escape from Hell** (354000101). These are display translations, not claims of official GL localization. The original title remains in `sourceName`; later genuine English source titles take precedence.

Card metadata, artwork and the persistent native item-ID registry live in `data/vision_cards`. Keep this folder in place: this local game build references its artwork by absolute path. Importing refreshes the Studio library; adding future cards to the game's item tables also requires the package/export steps below.

## Local build and installation

The native adapter is pinned to the current demo executable and bundled UE4SS version. It adds card stats to the common equipment-stat calculation using a native cache. Save data stores the selected card separately for each unit in reserved gimmick map 771300, splitting the source card ID into two exactly representable 16-bit values. Stable inventory item IDs are allocated in 12200–12999 and retained across imports.

The demo classifies equipment by numeric ID even when the item table says `EquipmentType=None`. The adapter therefore excludes registered card IDs from native equipment classification, accessory inventory/catalog lists and the shop's "equip now" list. Both native equipment setters reject cards. These guards leave ordinary accessories unchanged and preserve existing purchased item IDs.

On loading a save, cards mistakenly equipped as accessories by the earlier build are detached through the unit-level unequip operation, which updates both save data and live stats. The first available card moves into that character's empty card slot; other copies remain in inventory. Existing card selections and ordinary equipment are retained. This repair is safe to run repeatedly and follows the game's normal save operation.

The custom row relays native button events to its equipment menu so directional focus and Confirm agree. Closing or equipping restores the native input target and navigation entries; it does not leave the stock equipment picker active underneath the card window.

Adapter 0.3.0 also gates the two native details handlers while the selector is open. Those global shortcuts bypass the widget-level input flags; merely deleting the selector's X/Y handler left a native details screen opening underneath it. The gate is cleared on close and Lua shutdown, preserving normal details behavior everywhere else.

The UI uses `LoopInGameThreadWithDelay`; delayed probe actions also stay on the game thread. This avoids the shared Lua-state races seen when an async timer queued work while the UI was rebuilding card widgets.

From the repository, with the game closed:

```powershell
python -X utf8 tools/vision_cards.py
python -X utf8 tools/export_vision_card_runtime.py build/vision-cards/runtime/FFRVisionCards
python -X utf8 tools/make_vision_card_mod.py --game 'T:/SteamLibrary/steamapps/common/FINAL FANTASY RESONANCE DEMO'
python -X utf8 tools/install_vision_cards.py --game 'T:/SteamLibrary/steamapps/common/FINAL FANTASY RESONANCE DEMO'
```

Build the native DLL with `src/ffr-vision-cards/CMakeLists.txt` when changing its C++ source. The installer copies the latest Lua source and native DLL, preserves other enabled UE4SS mods, verifies copied hashes and records backups in `build/vision-cards/installed.json`. The card package is `zzzzzz_VisionCards_7_P`; its priority preserves the existing party and battle merchant additions. Subsequent Studio vision installs rebuild this retained card addon along with those additions.

To disable this feature, close the game, set `FFRVisionCards : 0` in its UE4SS `Mods/mods.txt`, and move the three `zzzzzz_VisionCards_7_P` package files out of the game's mods folder. The installation record identifies every copied file and any original backup.

## Verification

The isolated game check loads the current mod stack and Mitra, verifies all six stat bonuses and their removal, purchases a card for exactly 1 gil, checks native inventory lookup and the new merchant, and captures the grid and details views. Existing save files are locked against writes and their hashes checked afterward.

The accessory regression additionally checks all 350 card classifications, sorted and unsorted accessory inventory lists, the accessory catalog, both equipment setters, the card/ordinary-accessory shop prompt distinction, purchased-copy preservation and legacy assignment repair without doubled stats. Menu checks select the character through the game's Confirm handler, navigate Down/Up to and from the card row, Confirm through that same handler, equip, close and reopen while checking that accessories remain unchanged. The previous direct row-click check did not cover this full input path; it has been replaced. The completion marker now waits until these checks finish, followed by a 12-second error check.

The complete regression passed in `probe-20260916-085500`, including a save with cards in both accessory slots and an existing independent card selection. `build/vision-cards/classification-regression.json` records the tested source/DLL hashes. That verified build was installed with backups and copy verification.

The revised selector/details regression passed in `probe-20260916-194236`: fixed sparse grid, supplied remove artwork, native font, suppression of both details shortcuts during selection, equip/close/reopen, native skill-category navigation, and switching to a character with no card. The maximum-stat and accessory-preservation checks remain included. Animation checks verify Azure Successor's framing against a stable landmark and preserve its 24-second source timeline; all 276 animated cards have matched framing.

The actual Windows Flutter app loaded all 350 cards with zero captured runtime errors. The card widget tests, Python card/addon tests, Flutter analysis and release build also passed. Native controller navigation events were exercised; a physical Xbox controller was not used by the automated check.

The September 16 revision also verifies that the card seller projects to the left of the accessory seller and that a swept player approach is unobstructed. A dedicated test camera captures both merchants and their overhead bubbles. Font compaction uses an iterative widget walk to avoid overflowing the scripting bridge on deeply nested native menus; native load/click callbacks queue work for the UI update rather than modifying the engine inside the callback.

Isolated tests disable Unreal messaging and Steam networking. The temporary executable paths had each caused a fresh Windows Firewall prompt; the corrected test has zero UDP endpoints and zero TCP listeners. The installed Steam game already has its own allow rules, so this fix does not change global firewall settings or add unnecessary rules.
