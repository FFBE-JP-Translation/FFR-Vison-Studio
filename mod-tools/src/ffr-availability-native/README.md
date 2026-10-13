# FFR availability native bridge

This is the compiled native transport for the converter's Lua availability engine. The staged package is **disabled and configured for observation**. Source abilities with cooldowns, limited uses or charges remain held for playable export until native owner, turn and logical-cast bindings are verified in battles.

The DLL intercepts the direct native skill-job guard at game RVA `0x4f44800` using MinHook. It calls the original guard first and returns its original result for unmanaged commands. In enforcement mode, a configured command also needs a successful Lua authorization; native false always remains false. The hook returns to FFR's existing accept/cancel branch before the skill execution body. No game files or saves are modified by building or staging.

Supported binary fingerprints:

- FFR demo executable: `e06401cdf4e64d55f652043bdd2012267d5529a00c3dbc36ee4365e0ce49caad`.
- UE4SS `24b126628ea99671e592cd76048655b2313d7c19`, saved build v3.0.1 Beta: `7082324aa440169fc992c02812a10f5c68a975d83f95273134c1c7ccddbe4b2d`.

UE4SS is checked before constructing its public mod class. Attach checks both files and the loaded guard's original prologue, resolves the RVA against the loaded executable base, and rejects an already modified prologue. The bridge is built with the release DLL C runtime. The resulting DLL's 28 UE4SS imports are checked against the exact saved DLL's export table.

## Build and stage

From the FFR repository root:

```powershell
python -X utf8 -B src/ffr-availability-native/bootstrap.py
python -X utf8 -B src/ffr-availability-native/build.py
python -X utf8 -B src/ffr-availability-native/stage.py
```

The first command downloads three hash-pinned public source archives to `build/tooling`. Later builds use those cached archives offline. The build driver uses the installed Visual Studio 2022 CMake path, configures a Win64 release build, runs the standalone tests, verifies the imports and records source/runtime/DLL fingerprints in `build/abilities/native-bridge-validation.json`. Staging rejects stale builds and creates `build/abilities/runtime-native/FFRAvailabilityRuntime`, with no `enabled.txt` and no installer side effects.

The original public `CppUserModBase` header transitively includes unused GUI/private Unreal headers. Bootstrap removes that GUI include using forward declarations and spells its nonvirtual callback alias as the same function pointer type. Its fields, virtual methods and order remain unchanged; reversing the two substitutions must reproduce the original header. A compile-time check verifies the public class size, and the generated SDK manifest records both header hashes. No private Unreal source is fetched or reconstructed.

The native query transport now lives in the runtime DLL. `FFRAvailabilityNativeAttachQuery(enforce, commaSeparatedActiveSkillIds)` binds up to 512 distinct IDs in FFR's active category (`100000..999999`). Empty enforcement, invalid categories, malformed lists and repeated attachment are rejected. The disposable fixture no longer implements or registers a query hook. Its Lua helper exercises the production API, rejects seven invalid calls and duplicate attachment, and records `transport=runtime` before verifying actual available/exhausted queries. The earlier explicit-ID fixture matrix is preserved under `build/abilities/native-query-fixture-baseline-20260911`; its DLL is historical evidence.

## Native/Lua interface

UE4SS calls the C++ `on_lua_start` lifecycle before executing `main.lua`, and creates the hook coroutine lazily. The C++ method registers the attach API. After defining its callback and installing reflected observers, `main.lua` calls `FFRAvailabilityNativeInit`, which schedules attachment through `ExecuteInGameThread`. Attach binds the actual calling Lua coroutine, records that thread, and refuses managed callbacks from a different thread. The default entry calls `FFRAvailabilityNativeAttach(false, "")`, observing all native guard calls. It logs job, actor and root-job addresses; the skill ID; object index; action/target counts; and the original native result. The observer stops invoking Lua after 20,000 observations and reports that limit. Reflected battle/turn/command/skill observations share the log, including native actor/parameter addresses for identity correlation.

`native_host.bind(engine, nativeSkillToCommand, resolveContext)` connects configured native IDs to the canonical `availability.lua` engine. Its callback passes a resolved battle/owner/cast/selection identity to `authorize`. The resolver is required: raw pointers and object indices are metadata, not proof of logical cast identity. Missing identities, native rejection, exhausted resources, duplicate/cancelled casts and wrong selections deny authorization. A disposable ordinary Rain fixture now verifies the binder in FFR; a general production lifecycle/loadout resolver remains incomplete.

The C++ API can enforce an explicit set of up to 512 IDs once the lifecycle binder exists. Unmanaged IDs keep native behavior. Callback exceptions, missing callbacks, wrong-thread calls and reentrant authorization deny configured commands. Enforcement has no lifetime observation-count cap; the canonical engine bounds state per owner and battle.

Define `FFRAvailabilityOnNativeQuery(uniqueId, skillId, nativeAllowed, callerRva, selectionsAddress, option)` before attaching the query API through `ExecuteInGameThread`. The hook calls FFR's complete query at RVA `0x4f439d0` once with all original arguments, then invokes Lua only for managed active skills. Items retain native behavior even when their numeric ID matches a managed skill. Return a boolean; errors, missing callbacks and non-boolean values deny managed queries in enforcement mode. The selection address and native unique ID require a host resolver and must not be treated as logical cast/owner tokens. Query callbacks should use canonical `query`, which does not consume uses. The execution and query hooks share a recursion guard. Query observation mode preserves native results and limits callbacks to 20,000; enforcement continues beyond that limit. The default staged entry does not attach query enforcement.

An installed hook pins its DLL for the process lifetime. Lua/C++ mod stop invalidates the callback; managed enforcement remains closed and observer mode retains native results. Restart the game to rebind or remove this transport. Controlled detour removal exists for the standalone test host only and requires no concurrent native callers. The production plugin does not free a trampoline underneath an active game job.

## Validation and remaining work

The standalone executable passes **134 checks**: 49 execution checks and 85 query checks. It covers native snapshots, fingerprints, real MinHook trampolines, every forwarded query argument, multiple managed IDs, item/unmanaged preservation, category and capacity boundaries, wrong threads, callback failure/stop, recursion within and between hooks, observer limits and original-function restoration. It embeds Lua 5.4.7 and exercises the canonical engine and execution host, including 20,001 non-consuming availability queries followed by a real use and an exhausted query. It does not load UE4SS or the game. The separate emulator replay executes the real FFR guard/caller bytes with documented service fixtures.

Live startup validation confirms one native attachment, all 13 reflected registrations, and successful travel into `/Game/Debug/BattleTest/DBG_BattleTest`. The debug roster starts empty: six friendly slots and eight enemy slots, with unit IDs `-1`. These startup runs did not start combat. `build/abilities/native-startup-validation.json` records their exact DLL, logs, cleanup and original-save checks; `verify_observation.py` excludes subsequent combat attempts.

Separate protected stock-combat runs now create Rain and a Goblin, select Rain's ordinary attack through the live command view model, observe native player/enemy guards, and reach Rain's next turn. One player selection produces one native guard and four reflected skill-start notifications sharing one payload. The reflected actor address matches the native guard's actor, and the Goblin's HP falls while both units survive. `build/abilities/native-combat-validation.json` records the verified traces, hashes, saved-file checks and cleanup. These observations establish the ordinary stock command path only. They do not execute a converted ability, establish a complete lifecycle/loadout resolver, or validate repeats, multicast, dual wield, menu availability and resource costs. No converter holds are released.

The additional fixture observer resolves `m_pVisionOwner` or `m_pOwnerBtlUnit` on each turn event and reads the equipping actor's `GetActionCountInBattle()`. For both ordinary actors, the pre-hook sees `0` on the first turn and `1` on the second; later unit samples see the incremented value. The trace verifier checks consecutive counters, stable actor/parameter identity, and that every observed native guard belongs to the actor whose turn was last reported. This timing must be accounted for when supplying the availability engine's one-based owner-turn ordinal. The equipped-Vision fixture below verifies its grant path; extra actions and other special turn paths still require separate cases.

The first converted-ability combat case also passes: source `JP_2024/magic/10020` (Cure), materialized as temporary skill `1900010`, loads with the converter's 4 MP cost, recovery magnitude 62, one hit and private sequence. After a stock attack and enemy turns, the command view model casts Cure on Rain. One native guard and four reflected skill-start notifications precede a verified HP increase from 255 to 322 and MP decrease from 43 to 39. `build/abilities/native-converted-cure-validation.json` records the source/profile/package hashes, target and actor correlation, healing and cost. This validates one ordinary converted healing command; it does not validate the held availability gates or all converted mechanics.

Fire (`JP_2024/magic/20010`) now passes the production command converter. Initial disposable casts and a timing control established the missing resistance phase evidence; the latest fixture requires the accepted production profile. One native cast deals damage, charges 4 MP, adds exactly 4 LB points to Rain, and places effect `190001000` on the Goblin with Rain as its source. The enemy becomes weak to fire, while Rain's resistance and the enemy's resources stay unchanged. The source-wide command audit gains 11,146 imports with no losses. Recovery and general before-damage resistance bindings remain held.

The expiry fixture casts Fire once, then selects stock Defend (`400010`) on subsequent Rain turns. It reads the effect's life, the enemy's resistance, both actor counters and the shared battle turn through the enemy AI's native `GetTurnNum` accessor (`0x144f52720`, manager field `+0x200`). The accepted production cast in run `20260910_220546_077` retains the effect for five shared battle turns and removes it at turn 6, restoring neutral fire resistance. Rain and the Goblin remain alive. Individual action opportunities are a different counter; an earlier diagnostic caught lifetime changes while the other actor's turn began. `build/abilities/native-fire-expiry-validation.json` checks the clock, decrement sequence, removal, all native player guards and cleanup.

The separate phase control changes only the first bundle to `BeforeDamageCalculation`. With matching magic stats, the original phase deals 43 damage and gains 4 LB, while the control deals 61 damage and gains 54 LB. Both charge 4 MP and leave the same weakness. The extra 50 LB points are observed, but their internal reward path is not traced. This comparison alone does not release general before-damage combinations. Native instruction replay covers AddElementResistance's phase iterator and Self/Group recipient selection on both actor sides. The production rule checks stock evidence for other element/category values; live battle coverage remains a representative Fire case, not every resistance configuration. Immutable copies of the binding evidence are under `build/abilities/native-hit-evidence/resistance-*-at-binding.json`.

## Temporary live observation

Three additional availability cases pass in actual protected battles. The forced-denial case (`20260910_225829_702`) returns false after FFR's original guard returns true: no Fire skill-start notification, MP cost, damage or weakness occurs, and stock Defend still executes. This native cancellation advances the actor's action opportunity, so execution denial alone is insufficient for ordinary command-menu behavior.

The stateful case (`20260910_231459_485`) uses the unchanged canonical Lua engine and native host with a synthetic one-use rule around the accepted production Fire body. The first selected cast commits the use, spends 4 MP and deals 42 damage. The second original native guard still allows Fire, but `authorize` returns `uses_exhausted`; it spends no additional MP and causes no extra damage. Four skill-start messages belong to the first logical cast only. The fixture correlates actual command-decision payloads, native root jobs and Rain's equipping actor across four owner turns.

That test exposed a direct native lifecycle path. FFR calls `HandleBeginBtl` at `0x14515c4c0` from the battle task at `0x144fc7e0a`, bypassing the reflected wrapper and Lua `RegisterHook`. The separate fixture DLL now observes this native function after always calling the original, checks the UI subsystem's `bDuringBattle` at `+0x80` changing from false to true, and starts the canonical engine before the first turn. Attachment pins the fixture DLL and checks both binary fingerprints and the exact prologue. That initial case covers one battle. The later death/revival, two-battle reset and late Vision grant cases below extend this evidence; a general production lifecycle/loadout adapter remains incomplete.

The query case (`20260910_231928_801`) also attaches the fixture to the shared native action-availability function at `0x144f439d0`. `CPP_VM_BtlCmd.CanActivateAction` calls it from `0x14515e0b4`. The original function runs first; all items and unmanaged IDs retain its result. For the single managed Fire command, canonical `query` is non-consuming and can only further restrict availability. The view model returns true before the first cast and false with `uses_exhausted` on Rain's next turn. The driver then selects stock Defend on that same second opportunity and reaches turn 3 with just one 4 MP charge and one damage application. This verifies the live view-model result, not a visual inspection of the rendered menu.

`native-denial-validation.json`, `native-limited-validation.json` and `native-limited-menu-validation.json` retain the traces and hashes under `build/abilities`. These gate rules and owner/selection resolution are explicitly fixture-only. The canonical staged runtime stays disabled in observation mode, and no source availability holds are released.

Two real FFBE source contracts now pass with their corresponding converted payloads. `GL_2024/ability/150300` (Fill LB, child `516017`) retains its one use, dual-wield control and multicast flag. In run `20260910_233027_348`, the self-target cast raises Rain's native gauge from 7 to 27, spends one use and no MP, and becomes unavailable on the next turn. This is the converter's documented capped 20% gauge adaptation; it does not fill the entire native gauge. Defend remains usable on that same turn. `native-source-availability-validation.json` verifies the original source and child, generated Lua contract, cooked tables, one native execution and the unchanged original export hold.

`JP_2022/ability/1007200` (child `1007201`) retains its five-turn cooldown and initial availability on turn 1. In run `20260910_233758_099`, native casts on owner turns 1 and 6 restore Rain from 316 and 161 HP respectively to the native maximum of 382. Query remains false on owner turns 2–5, then becomes false again on turn 7 as the second cast moves the deadline to turn 11. Five ordinary Defend commands use the intervening opportunities. `native-source-cooldown-validation.json` verifies both authorizations and the full deadline sequence. MP begins full and remains 43, so this case does not measure the separate MP-refill magnitude. The source's permission for dual-wield casts is retained but is not exercised by the ordinary fixture.

For these cases, the fixture builder saves the original held profile and availability plan, then derives a separate experimental payload by replacing each decoded wrapper with its immediate child reference. It checks that the payload's native mechanics, root costs and application frames exactly match the generated candidate plan. The original snapshot and nested held payload must still fail ordinary export. `source_contract.lua` is generated from the original decoded rule, and the native fixture loads that contract instead of the synthetic Fire rule. The runner refuses a source payload unless both execution and query bindings are explicitly selected. These are native evidence for two source records; general lifecycle/loadout and additional cast forms remain unfinished.

Native learned ownership and independent per-actor uses pass in run `20260911_000028_658`. The fixture adds Fill LB to one empty level-1 learning slot for both Rain and Lasswell, preserving every other native learning field, and places the skill in their existing command category. Both `GetActiveSkillList` and `GetActiveSkillListWithVision` return the skill for each actor. Each casts once, gains 20 gauge points without MP cost, then receives its own `uses_exhausted` query result and executes stock Defend. The resolver chooses owners from actual native skill membership and stable actor/parameter identity; roster IDs do not select owners. Logical owner and cast tokens remain separate from native pointer values. `native-owned-source-validation.json` checks the cooked learning tables, both ownership lists, two independent balances, self targets, execution events and cleanup.

`SetUsableActiveSkill` changes a temporary allowed list; it does not add a skill to those ownership getters. The earlier direct-selection fixtures therefore do not establish learned ownership. The two-owner fixture never calls that setter or `RefreshCommandSkill`. Its bound scope remains stable equipping actors in one battle. The later loadout case covers late grants on stable actors, and the reset case covers a new battle generation. Replacement during a battle and additional cast forms still require native validation; no production availability holds are released.

Equipped Vision grants pass in run `20260911_002241_269`. Rain equips Amelia (`13017`), and Lasswell equips Lia (`13045`). One empty level-0 awakening entry in each Vision grants the same converted Fill LB. No ordinary learning table changes. The skill is absent from each actor's `GetActiveSkillList` and present in `GetActiveSkillListWithVision`; native equipment getters confirm the two Vision IDs throughout the observed turns. The converter's existing `equipperActionVisionSkills` binding executes both casts on the ordinary equipping actors, with actual self targets. Lasswell's gauge rises from 0 to 20 and Rain's from 8 to 28; each independently becomes unavailable and then Defends. `native-vision-source-validation.json` verifies every other mastery/general table field remains unchanged and retains the source, runtime, ownership and resource evidence. This does not test a manifested Vision sprite or a resonance cast.

The shipping `SetDebugBattleEntryData` wrapper calls an empty body (`0x1444aba70`, `ret 0`), so its level and equipment override fields do not initialize these actors. The Vision fixture uses `CPP_BFL_SaveDataInventory.AddInventory` and `CPP_BFL_SaveDataUnit.SetEquipmentId` on the fresh process's initial data before battle construction. It checks the eight initial roster entries, empty Vision inventory and equipment getters. It does not load a gameplay save or call a save operation; the runner locks and hashes the five existing save files. The higher-level unit equipment API did not update these debug-world actors in earlier attempts. Failed setups are archived and excluded from positive evidence.

Death and revival preserve the spent source use in run `20260911_003551_820`. Both actors first cast Fill LB. On Rain's second opportunity, a private native Death control applies stock guaranteed instant-death effect `1357`; Rain reaches 0 HP, and native query denies his source command. Lasswell then uses a private native Raise control with stock full-revival effect `1367`, restoring Rain to 382 HP. Rain's third opportunity has the same actor, parameter and logical owner identity, with `used=1`; the source query remains `uses_exhausted`, and stock Defend executes. The two controls are zero-cost diagnostic clones of native Death (`220320`) and Raise (`210140`) with their own cooked sequences. They do not certify FFBE death/revival conversion or alter the source payload.

The fixture observes reflected `CPP_BtlDelEventUnit.OnExecuteUpdateDeadState` and rereads `IsDead()` on the equipping parameter. This event also fires without a life-state change. Every refresh updates canonical `set_alive` without restoring uses; only Rain's true→false→true transitions are treated as death/revival. These notifications can follow the visible HP change during the native sequence, so native availability rejection remains authoritative in that interval. `native-life-source-validation.json` checks repeated refreshes, native death/revival payloads, unchanged owner identity, consecutive turns, the spent balance, post-revival Defend and cleanup. The later reset case adds two Escape/end cycles, and the loadout case adds late grants on stable actors. Replacement during a battle, already-created job cancellation and other cast forms remain unbound.

Cancellation before command commitment passes in run `20260911_004138_272`. For each actor, `CPP_VM_BtlCmd.DecideActionKey` pushes Fill LB onto the live command stack, then `CancelCommand` removes it before target commitment. The stack returns from one entry to zero, and its current key returns from `1900010` to `-1`. After another observation tick, the actor remains on opportunity 1 with unchanged HP, MP and gauge; canonical query still reports `used=0` and available. No command-decision, execution-authorization or skill-start event occurs during cancellation. Each actor subsequently completes one source cast on that same opportunity, then exhausts its use and Defends. `native-cancel-source-validation.json` verifies both stack transitions, resources, event absence and final casts. This covers ordinary cancellation before native command decision; cancellation of an already-created job or multicast reservation remains unbound. The rendered menu has not been visually inspected.

Battle end and fresh use limits pass in run `20260911_010611_730`. Two native battles run in the same process. Rain and Lasswell each cast Fill LB once in each battle, gain 20 gauge points for no MP, exhaust their independent use and Defend. Native Escape ends each battle. Paired pre/post observations of `CPP_UI_BattleSubsystem.HandleEndBtl` verify `bDuringBattle` changing from true to false before calling canonical `end_battle`. The host clears owner, selection and payload records; the next native begin creates a new battle token and registers fresh owners with `used=0`. Six explicit canonical queries using ended-battle identities reject with `stale_battle`, including after the second battle begins. `native-reset-source-validation.json` checks all four casts, both native end transitions, fresh balances, consecutive owner opportunities, targets, resources, table grants and cleanup. Native enforcement forwards only managed skill `1900010` to Lua; Escape retains its original native behavior and is correlated through command and skill-start events.

The repeatable arena uses `CPP_DBG_BFL_BattleTest.BegineBattleInBattleTest`. Its missing field state is supplied before return: an empty native `CPP_LevelBundle` and a `CPP_Level` wrapping the loaded Plain-stage lighting stream. The fixture DLL reads the lighting collector's current key at `+0x90`; Lua registers the wrapper under that key through the reflected map. No end function is skipped or overridden. All combat actors disappear after each end, and the second battle constructs fresh actors. Stock control run `20260911_005924_738` independently verifies two Escape/end cycles. This is a supplied debug field scaffold, not certification of normal field travel, wins, losses, mid-battle replacement or every lifecycle route. Earlier missing-field crashes and a source-driver stall remain failed evidence.

Late native Vision grants and removal/regrant pass in run `20260911_012708_835`. Both actors begin without equipped Visions. The host registers empty managed loadouts on the first native owner opportunity and keeps their clocks advancing. Each Defends on opportunity 1. On opportunity 2, `CPP_BFL_Unit.SetEquipmentId` equips Amelia or Lia, and `GetActiveSkillListWithVision` gains Fill LB. The same equipping actor and parameter now synchronize their managed membership and cast once for 20 gauge points at zero MP. On opportunity 3, `UnequipmentId` removes the command, then re-equipping restores membership while retaining its spent use. Query remains `uses_exhausted`, and Defend still works. The ordinary skill getter never contains the Vision-granted command.

The native equipment API chooses between field and battle parameters using `CPP_BFL_Map.IsDuringEncount` (`0x14505b340`), which reads the current map manager's byte at `+0x2fc`. The debug arena leaves that flag unset even while the battle UI is active; earlier equipment attempts updated only a separate field parameter. The separate fixture helper verifies the game thread, native current map identity, initial flag and active battle UI before supplying that missing flag, matching the normal encounter startup write at `0x14504b73d`. It then verifies that `GetPlayableUnitParameterObj` resolves to the exact battle parameter before invoking the full native equipment API. This scaffold belongs only to the disposable diagnostic DLL, not the production runtime.

`verify_loadout_observation.py` checks the held source and cooked grants, two initially unowned actors, six membership changes, two native authorizations, four Defend commands, unchanged MP, gauge increases and stable native/logical identities. It rejects the two earlier failed grant attempts. This covers one limited-use source and two stable actors through native equipment APIs; normal field equipment UI, replacement actors and pending-job cancellation remain outside the case. The canonical `sync_loadout` operation separately preserves charges, cooldown deadlines, aliases and cancelled reservations in the Lua tests. All 4,713 candidate contracts replay late grants and removal/regrant with unchanged gate balances.

```powershell
python -X utf8 -B src/ffr-availability-native/fixture/build_ability.py --case limited --owned-source --vision-source
./src/ffr-availability-native/observe.ps1 -Seconds 110 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility -LimitedConverted -MenuLimited -SourceAvailability -OwnedSource -VisionSource -LoadoutSource
python -X utf8 -B src/ffr-availability-native/verify_loadout_observation.py 20260911_012708_835
```

Add `--loadout-run` with the actual run ID to the combined verifier below, alongside fresh runs for the other modes when the canonical Lua runtime changes. Loadout mode requires Vision ownership and cannot combine with death/revival, cancellation or battle-return modes.

```powershell
# Requires the accepted after-damage Fire fixture built below.
./src/ffr-availability-native/observe.ps1 -Seconds 65 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility -DenyConverted
python -X utf8 -B src/ffr-availability-native/verify_denial_observation.py 20260911_013522_299
./src/ffr-availability-native/observe.ps1 -Seconds 65 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility -LimitedConverted
python -X utf8 -B src/ffr-availability-native/verify_limited_observation.py 20260911_013635_021
./src/ffr-availability-native/observe.ps1 -Seconds 65 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility -LimitedConverted -MenuLimited
python -X utf8 -B src/ffr-availability-native/verify_limited_observation.py 20260911_013713_295 --menu
```

Use each new run's actual ID when repeating these cases. The runner archives the original observer entry and verifies the exact temporary fixture overlay. Semantic verifiers reject the other run modes. Every passed run verifies unchanged original saves and existing content packages and removes its temporary installation.

```powershell
python -X utf8 -B src/ffr-availability-native/fixture/build_ability.py --case limited
./src/ffr-availability-native/observe.ps1 -Seconds 65 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility -LimitedConverted -MenuLimited -SourceAvailability
python -X utf8 -B src/ffr-availability-native/verify_source_observation.py 20260911_013756_172
python -X utf8 -B src/ffr-availability-native/fixture/build_ability.py --case cooldown
./src/ffr-availability-native/observe.ps1 -Seconds 100 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility -LimitedConverted -MenuLimited -SourceAvailability
python -X utf8 -B src/ffr-availability-native/verify_cooldown_observation.py 20260911_013839_072
python -X utf8 -B src/ffr-availability-native/fixture/build_ability.py --case limited --owned-source
./src/ffr-availability-native/observe.ps1 -Seconds 75 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility -LimitedConverted -MenuLimited -SourceAvailability -OwnedSource
python -X utf8 -B src/ffr-availability-native/verify_owned_observation.py 20260911_013954_782
python -X utf8 -B src/ffr-availability-native/fixture/build_ability.py --case limited --owned-source --vision-source
./src/ffr-availability-native/observe.ps1 -Seconds 75 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility -LimitedConverted -MenuLimited -SourceAvailability -OwnedSource -VisionSource
python -X utf8 -B src/ffr-availability-native/verify_owned_observation.py 20260911_014253_874 --vision
python -X utf8 -B src/ffr-availability-native/fixture/build_ability.py --case limited --owned-source --life-source
./src/ffr-availability-native/observe.ps1 -Seconds 90 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility -LimitedConverted -MenuLimited -SourceAvailability -OwnedSource -LifeSource
python -X utf8 -B src/ffr-availability-native/verify_life_observation.py 20260911_014342_186
python -X utf8 -B src/ffr-availability-native/fixture/build_ability.py --case limited --owned-source
./src/ffr-availability-native/observe.ps1 -Seconds 75 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility -LimitedConverted -MenuLimited -SourceAvailability -OwnedSource -CancelSource
python -X utf8 -B src/ffr-availability-native/verify_owned_observation.py 20260911_014035_312 --cancel
./src/ffr-availability-native/observe.ps1 -Seconds 120 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility -LimitedConverted -MenuLimited -SourceAvailability -OwnedSource -ResetSource
python -X utf8 -B src/ffr-availability-native/verify_reset_observation.py 20260911_014119_799
./src/ffr-availability-native/observe.ps1 -Seconds 100 -OpenBattleTest -ProtectedSaveTest -StartBattle -BattleReturn
python -X utf8 -B src/ffr-availability-native/verify_return_observation.py 20260911_005924_738
python -X utf8 -B src/ffr-availability-native/verify_gate_observations.py 20260911_013522_299 20260911_013635_021 20260911_013713_295 --source-run 20260911_013756_172 --cooldown-run 20260911_013839_072 --owned-run 20260911_013954_782 --vision-run 20260911_014253_874 --life-run 20260911_014342_186 --cancel-run 20260911_014035_312 --reset-run 20260911_014119_799 --loadout-run 20260911_012708_835
```

The combined verifier rechecks eleven cases and 110 wrong-case rejections when `--loadout-run` is included. Its report is `build/abilities/native-availability-validation.json`. Use the actual new IDs for repeated runs; the earlier IDs above document historical runs. The aggregate requires every stateful case to match the current canonical runtime and host hashes. After a source build, rebuild `--case fire` before running Fire or synthetic gate tests.

```powershell
./src/ffr-availability-native/observe.ps1 -Seconds 25 -OpenBattleTest -ProtectedSaveTest
python -X utf8 -B src/ffr-availability-native/verify_observation.py
```

The runner refuses an existing UE4SS installation or running FFR process, verifies binaries and staged files, installs the observer plus a bounded diagnostic companion, and launches the owned process hidden with offscreen rendering. It uses the demo's real Steam app ID for direct launch. Startup ignores the map URL, so the companion calls the native `CPP_DBG_BFL_BattleTest.OpenBattleTestLevel` function after boot; that function clears the current map task before travel. The startup command above reads test settings and widget functions without importing a main save or executing a combat command.

The separate `fixture` project supports combat diagnostics:

```powershell
python -X utf8 -B src/ffr-availability-native/fixture/build.py
./src/ffr-availability-native/observe.ps1 -Seconds 55 -OpenBattleTest -ProtectedSaveTest -StartBattle
python -X utf8 -B src/ffr-availability-native/verify_combat_observation.py 20260910_204826_579 20260910_205013_860 20260910_205153_361
```

This opt-in run creates transient Rain and Goblin rosters and requests one native encounter on stock stage 5 (Plain). The shipping build replaces the requested stage with the battle-level manager's current stage, which starts at `-1` in the debug world. The helper registers the stage, stores the native current-stage field, and requests the registered assets through FFR's own loader. It checks exact game and UE4SS fingerprints, the manager type, initial stage, game thread and native function prologues. In ordinary observation mode its DLL installs no combat hooks; limited-use modes explicitly request the native lifecycle observer and optional query hook described above. The DLL is separate from the staged converter runtime, is installed only for this protected run, and is retained with its build manifest and hashes as diagnostic evidence. The Lua driver selects stock attack 401010 and observes equipping-actor turn counters. The runner stops its owned process when Rain reaches a second turn, or on timeout. Pass completed run IDs to the verifier; crashes, stale or altered runtime files, read failures, missing guard/owner correlation and save changes fail verification.

The standalone debug world lacks the field-level and lighting state expected by the normal battle-return task. Earlier wins/losses crashed after emitting `battle_end`; an empty level bundle alone did not fix the missing lighting state. Those traces are retained as failed attempts. Ordinary fixtures stop during combat. The explicit `-BattleReturn` and `-ResetSource` modes supply the bounded field scaffold described above and verify two native Escape/end cycles. Debug-roster level overrides had no effect in this shipping build; combat uses the loaded native unit parameters.

## Temporary converted-ability test

Current fixtures use active skill **900010** (and lifecycle controls 900030/900050). Earlier traces used 1900010: the native category function identifies that number as a master skill, even though direct battle-table lookup can execute its active row. Historical verifiers retain the archived identity; those traces do not establish category-based mastery or menu compatibility. The converter now rejects such active/passive IDs. New Fire observations also check `GetSkillCategory(900010) == ActiveSkill` in the game.

```powershell
python -X utf8 -B src/ffr-availability-native/fixture/build_ability.py
./src/ffr-availability-native/observe.ps1 -Seconds 45 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility
python -X utf8 -B src/ffr-availability-native/verify_converted_observation.py 20260910_210706_835
```

The builder opens the existing source index read-only, runs the shared converter and command materializer, cooks new skill/asset/reaction rows and an authored sequence, verifies the cooked skill row, and packages them with `retoc`. It never installs. The source's reaction frame 90 is retained; the test uses native Rain's `magic_attack` in an explicit three-second animation window. This case makes no FFBE sprite or audiovisual fidelity claim.

The runner verifies the build inputs and all three package hashes, refuses existing files with the same names, and temporarily installs `zzzzzz_FFRConvertedAbilityProbe_100_P.{pak,ucas,utoc}`. The numeric patch version was needed for this fixture's skill table to win over the existing shared-table packages; earlier unversioned attempts returned the native missing-skill row and never cast. Cure temporarily overrides five shared native tables, including the skill general table, and adds one sequence. Existing package files remain intact and are checked after cleanup. The Lua driver checks the loaded row before battle, requests a transient usable-skill list, performs a baseline attack and then casts Cure on the injured caster. It stops observation after healing and the expected MP charge are observed. Inventory ownership and normal menu discovery are not established by this transient request. Pass the completed run ID to the converted-case verifier; the stock verifier deliberately rejects converted-case runs.

For the Fire experiment and its separate timing control:

```powershell
python -X utf8 -B src/ffr-availability-native/fixture/build_ability.py --case fire
./src/ffr-availability-native/observe.ps1 -Seconds 25 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility
python -X utf8 -B src/ffr-availability-native/verify_fire_observation.py 20260910_213314_931 20260910_214414_857
# Build/run this separately, then pass the actual new run IDs to the comparator.
python -X utf8 -B src/ffr-availability-native/fixture/build_ability.py --case fire --fire-phase before
./src/ffr-availability-native/observe.ps1 -Seconds 25 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility
python -X utf8 -B src/ffr-availability-native/verify_fire_phase_observation.py 20260910_214414_857 20260910_214344_265
```

Fire also overrides the skill-effect table (six shared tables total). Its source frame 80 is retained. The builder saves the accepted production profile, records any control-phase override separately, verifies cooked effect parameters as well as the skill row, and rejects inputs changed during cooking. It does not bypass the command converter for the normal after-damage case. The default build remains Cure; `--case fire` uses the converter's original after-damage timing, while `--fire-phase before` is only the comparison control. Each build has its own retained directory; the runner uses the most recent central fixture manifest.

To verify the production cast and its full native lifetime:

```powershell
python -X utf8 -B src/ffr-availability-native/fixture/build_ability.py --case fire
./src/ffr-availability-native/observe.ps1 -Seconds 80 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility -ConvertedExpiry
python -X utf8 -B src/ffr-availability-native/verify_fire_expiry_observation.py 20260910_220546_077
```

Use the actual new run ID when repeating the test. The verifier correlates five shared battle-turn transitions with lifetime 5 through 1, then effect removal and neutral resistance. It also verifies one Fire command and the separate native Defend commands, without claiming availability enforcement.

The automatic-repeat diagnostic grants temporary passive 90000 through Rain's learning table and the native mastery API. It clones passive 1414's spawn trigger with stock effect 1012 (`RepeatAction`). One explicit Fire selection then produces two distinct, self-rooted jobs and spends eight MP. It emits no `OnExecuteStackMimicRepeatCmd` event; that event cannot identify these repeats.

```powershell
python -X utf8 -B src/ffr-availability-native/fixture/build_ability.py --case fire --repeat-command
./src/ffr-availability-native/observe.ps1 -Seconds 90 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility -RepeatCommand
# Build and run each control separately.
python -X utf8 -B src/ffr-availability-native/fixture/build_ability.py --case fire --repeat-command --repeat-control
./src/ffr-availability-native/observe.ps1 -Seconds 90 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility -RepeatCommand -RepeatControl
python -X utf8 -B src/ffr-availability-native/fixture/build_ability.py --case fire --repeat-command --repeat-suppressed
./src/ffr-availability-native/observe.ps1 -Seconds 90 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility -RepeatCommand -RepeatSuppressed
python -X utf8 -B src/ffr-availability-native/verify_repeat_suite.py REPEAT_RUN CONTROL_RUN SUPPRESSED_RUN
```

The absent-passive control casts once for four MP. The suppression control retains the learned, mastered, active repeat passive and appends only Fire to `DT_SkillGeneralData.nonRepeatSkillsIds`; it also casts once for four MP. Each verifies the native category, ownership, continuous effect, command decision, cast jobs, resources and unchanged stock rows. Single-cast controls observe through the next actor opportunity; the verifier separates the Fire resource sample from any later Goblin attack. The comparison requires matching current driver/builder inputs, rejects 69 wrong-mode combinations and rejects all five failed setup attempts. It establishes a native per-skill exclusion, not FFBE dual-wield identity, manual W Action behavior under that exclusion or a production availability binder. No availability holds are released. Restore `--case fire` after these controls.

The multi-command diagnostic selects stock W Action (400710) followed by two converted Fire commands:

```powershell
python -X utf8 -B src/ffr-availability-native/fixture/build_ability.py --case fire --multi-command
./src/ffr-availability-native/observe.ps1 -Seconds 105 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility -MultiCommand
# Repeat separately with -MultiCancel to cancel one partial selection first.
./src/ffr-availability-native/observe.ps1 -Seconds 105 -OpenBattleTest -ProtectedSaveTest -StartBattle -ConvertedAbility -MultiCommand -MultiCancel
python -X utf8 -B src/ffr-availability-native/verify_multicommand_suite.py NORMAL_RUN CANCEL_RUN
```

One native command decision contains the wrapper and both children. Execution creates three distinct jobs whose root pointers each point to themselves, so that pointer cannot identify the shared selection. Native selection temporarily reserves four MP after the first target, refunds it at final dispatch, and charges four MP per executed Fire. Cancelling the partial selection through three native back steps restores all resources without a cast or turn advance. The suite checks both traces and 46 wrong-mode rejections. New fixtures also grant Fire through the native mastery API, which ignored the previous out-of-range ID. Automatic repeats, dual wield and production availability grouping remain unbound; this diagnostic installs no availability enforcement.

During this work Steam relaunched a stale offscreen test using the exact arguments and output paths of the earlier `20260910_193232_247` attempt. The new runner refused to overlap it. The identified stale test process and its launcher were stopped; all tracked original file hashes still matched. `build/abilities/stale-test-relaunch-20260910.json` records the process identities and cleanup. This did not become a converted-test pass.

SQEX saves live under `%LOCALAPPDATA%/FFRS_DEMO`, outside Unreal's `-UserDir`. Both command-line and temporary PAK attempts left the live save title unchanged; `-TestSaveOverride` retains that diagnostic but is off by default. Protected test runs back up and hold all existing `.sav` files with read sharing only, preventing writes and deletion for the process lifetime. The runner checks original hashes and newly created files after exit. This protects existing files; it does not establish a separate save namespace or prevent creation of new filenames. Before these paths were located, the first successful boot rewrote `OptionSaveData.sav` and a Steam cache. All three gameplay slots still match their earlier Steam cache hashes. Later protected runs changed no tracked files. Earlier attempts through the debug widget created `BattleTestSaveData.sav`; after process exit, the runner archives that exact file into the evidence folder only when it did not exist before the run. The current encounter path does not call the widget's save method.

The runner enforces a bounded timeout because this shipping build did not exit on `-seconds`. After the owned process stops, it moves its temporary UE4SS directory into the run's evidence folder and removes only its matching proxy, app-ID file and optional config package. Existing game content packages remain in place. Restart is required between runs because the native detour is pinned for the process lifetime.

Public sources: [UE4SS C++ interface at the pinned revision](https://github.com/UE4SS-RE/RE-UE4SS/blob/24b126628ea99671e592cd76048655b2313d7c19/UE4SS/include/Mod/CppUserModBase.hpp), [UE4SS Lua API wrapper](https://github.com/UE4SS-RE/RE-UE4SS/blob/24b126628ea99671e592cd76048655b2313d7c19/deps/first/LuaMadeSimple/include/LuaMadeSimple/LuaMadeSimple.hpp), and [MinHook 1.3.4](https://github.com/TsudaKageyu/minhook/tree/v1.3.4). Their license notices accompany the staged package.
