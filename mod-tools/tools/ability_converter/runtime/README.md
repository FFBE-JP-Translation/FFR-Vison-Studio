# Ability availability runtime

This directory contains an executable Lua state engine and an optional **observation-only** UE4SS probe. No FFR execution adapter is enabled. Cooldown and limited-use source records remain blocked for playable export, including the nested payloads in availability plans.

`availability.lua` has no UE4SS dependency and is tested directly in Lua 5.4 through Lupa. Commands have stable keys and one or more decoded gates. Each actor explicitly registers its loadout; an unregistered temporary vision is denied. All calls occur on battle/action/turn events, not ticks.

The host contract is:

1. Start a battle with a unique token and register each **equipping actor** with its granted command keys. An empty loadout is valid: track that actor's turns before a later grant. Never infer ownership from a temporary sprite's disappearance. The reflected `UCPP_BtlUnitParameter.m_pVisionOwner` is an actor pointer; the ordinary owner is `m_pOwnerBtlUnit`.
2. Supply consecutive owner-turn ordinals. This adapts FFBE's turn counts to the equipping actor's FFR turn opportunities. Duplicate/out-of-order turn messages do not decrement cooldowns. Ordinary native turns are verified by the disposable battle fixtures; special-turn paths still need validation.
3. Query with the existing native availability result. A native `false` always stays false. Querying never spends resources.
4. Reserve each logical cast with a unique token and a selection-group token. Reservations prevent concurrent selections from overspending uses/charges. Unique-multicast gates apply across pending and committed selections within that group.
5. Recheck native affordability/availability, then commit once at the authoritative cast boundary before effects. A successful commit spends every gate atomically. A replayed token never authorizes a second execution. Costs and effects must use this same boundary; a UI callback or hit notification alone cannot supply it. Dual-wield child/hit callbacks must retain the same logical cast identity when the source prohibits a second cast.
6. Cancel uncommitted casts, and finish selection groups after all their casts commit or cancel. A committed cast is not refunded because a later animation is cancelled. Death cancels reservations but preserves spent uses, charge balances and cooldown state. Revival does not reset them. Departure denies further actions. Battle end discards the battle state and stale callbacks cannot affect the next battle.
7. Refill only through an explicitly bound recharge event; non-rechargeable limits reject refill. No current FFBE refill adapter calls this method: Focused Rhythm remains its disclosed MP-cost replacement.
8. On a native loadout change, call `sync_loadout(battle, owner, commandKeys)` with the complete current set of managed commands. Validation is atomic. Removal cancels reservations for removed commands and preserves their cancelled tokens; retained commands keep their reservations. Uses, charges, cooldown deadlines, shared gate balances and group history remain attached to the actor for the whole battle. Re-granting a command or granting an alias does not replenish a shared balance. Initial cooldown eligibility remains anchored to observed owner opportunities, including opportunities before the grant. All 4,713 candidate contracts exercise late grants and removal/regrant in Lua. A native fixture verifies one limited-use command on two stable actors, reading Vision-inclusive membership at query, turn, selection and execution boundaries. General equipment events and replacement actors still need binding.

`authorize(battle, owner, command, castToken, selectionGroup, nativeAllowed)` is the execution entry for the eventual host adapter. It commits an existing matching reservation, or reserves and commits a cast that arrives without prior selection. A mismatched command/group cannot consume another reservation. Native rejection cancels an existing reservation without spending a gate. Rejected attempts for registered commands also retain a bounded cancellation token when no selection occurred, so later callbacks cannot revive a cancelled job after cooldown, revival or native-state changes. Call `query` for display/selection checks; calling `authorize` consumes the logical attempt even when it is rejected. Only managed command IDs should enter this API. Native casts outside the configured command set remain the host's responsibility.

State storage is capped at 128 owners and 8,192 transaction tokens per owner/battle. Capacity exhaustion denies new actions. These state bounds do not establish engine frame-time performance; Unreal profiling remains outstanding.

## Generate and test

From the repository root:

```powershell
python -X utf8 -B tools/ability_import.py availability
python -X utf8 -B tools/ability_import.py availability GL_2024/ability/109000 --output build/abilities/beastslayer.jsonl
python -m pip install --target build/tooling/ability-runtime-tests -r tools/tests/requirements-ability-runtime.txt
python -X utf8 -B -m unittest discover -s tools/tests -p test_ability_availability.py
python -X utf8 -B tools/tests/verify_availability_plans.py
python -X utf8 -B build/abilities/replay_native_availability_boundary.py
python -X utf8 -B tools/ability_import.py availability-probe
```

Availability planning opens the completed `source-index.sqlite` **read-only**. It emits `availability-plans.jsonl` and `availability-plans.report.json`, containing decoded gates, original portable source snapshots, candidate mechanics, payload issues and the mandatory runtime binding hold. It emits no native rows. Non-self charge references are recorded as availability relationships, with shared-pool ownership still unresolved; they are never treated as recursive child casts.

## Native execution candidate

`src/ffr-availability-native` contains a compiled transport for this candidate, with a disabled observer package staged under `build/abilities/runtime-native/FFRAvailabilityRuntime`. Its 49 standalone C++ checks exercise real detours and the canonical Lua/native-host binder. Protected battle fixtures verify native execution/query gates, ordinary turns, learned and equipped Vision ownership, death/revival, selection cancellation, two battle-end/reset cycles and late Vision grants without restoring spent uses. The loadout fixture supplies the debug map's missing encounter flag before native equipment APIs can resolve the battle actors. These are bounded diagnostics; general production lifecycle and cast coverage remain incomplete. Lua initiates attachment after its script loads, since UE4SS invokes the C++ lifecycle before that point. See that directory's README for build, staging, protected observation and interface details.

The installed demo has a direct native guard at `0x144f44800`, called from the skill-job execution path at `0x144f62cbb`. Its caller branches to cancellation on false and reaches the execution body at `0x144f62cd3` on true. The reflected `CanUnitActivateSkill` query has a separate body. Its cost helper at `0x144f57880` is shared with the guard, but the guard can skip that helper for some contexts; the helper alone cannot enforce a universal cast restriction.

The native W Action diagnostic observes a single command decision containing a wrapper and two child commands, followed by three distinct jobs with self-referencing root pointers. Native partial selection reserves MP and refunds it on cancellation or final dispatch; each executed child then pays its own cost. A shared selection must therefore be correlated with the command-decision batch. Root-job identity alone is insufficient. The observation does not yet bind production multicast, automatic repeats or dual wield. Current diagnostic skill IDs use the native active range; earlier high-ID traces remain historical direct-execution evidence.

An isolated replay executes the full guard and its caller's accept/cancel branch. It covers 25 native configurations, 50 selected/unselected Lua mediation cases and 11 runtime rejection cases. Services, cancellation implementation and logical owner/cast mapping are fixtures; successful execution stops before costs and effects. The generated contracts separately exercise `authorize` in the actual Lua 5.4 engine. This establishes the candidate boundary and runtime interface independently of the native battle fixtures. Complete hook coverage and repeat/dual-wield identities remain unbound. See `build/abilities/native-hit-evidence/availability-boundary.md` and its replay JSON for exact scope and binary fingerprints.

## Optional battle observation

The probe command stages `runtime-probe/FFRAvailabilityProbe` beneath the conversion output. It does not modify the game or create `enabled.txt`. If an operator chooses to collect a trace, copy that staged directory into the game's `ue4ss/Mods/FFRAvailabilityProbe`, enable it using UE4SS's existing mod-loading configuration, and restart the game. Keep the current restricted abilities out of playable loadouts during this observation.

The probe logs lines prefixed `[FFRAvailabilityProbe]` to `UE4SS.log`. It observes reflected battle/turn/death/result handlers, command decisions, mimic/repeat stacking, skill-start message/Libra handlers and the two native availability queries. It never returns an override, changes native exclusions, charges resources or writes a save. The owner lookup is read-only and emits an error when it cannot resolve the actor. Hook registrations, read failures and trace truncation are visible in the log. There are no periodic object scans; the battle function-library object is cached and revalidated when used.

Collect manual, repeat, auto, cancelled-selection, death/revival, escape and second-battle cases with stock/previously supported commands. Compare command decisions with both skill-start observations, their payload identities, the owner-turn stream and query observations. Empty query coverage, missing handlers, reused payload objects or inconsistent actor identities remain failures to establish an authoritative execution gate. These observations cannot prove that every native C++ call passes through reflection, nor do they turn the held availability plans into playable skills.

The probe bounds query observations to 2,048 per battle and total observations to 20,000 per load. It records saturation instead of silently treating a truncated trace as complete. It remains a development instrument; disable/remove this optional mod after collecting the required trace.

Sources: the repository's reflected `extracted/CXXHeaderDump/mucha.hpp`, the local Solaris active-effect formatter, and UE4SS's official documentation for [RegisterHook](https://github.com/UE4SS-RE/RE-UE4SS/blob/main/docs/lua-api/global-functions/registerhook.md), [RemoteUnrealParam](https://docs.ue4ss.com/lua-api/classes/remoteunrealparam.html), [TArray](https://docs.ue4ss.com/lua-api/classes/tarray.html) and [UObject](https://docs.ue4ss.com/lua-api/classes/uobject.html). Registration success is only evidence that a reflected function is hookable.
