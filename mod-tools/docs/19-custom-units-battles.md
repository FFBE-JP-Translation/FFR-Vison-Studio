# Custom units and private battles

## Confirmed baseline

On 2026-09-07 the user confirmed the four-choice Mitra NPC, FFBE enemies,
battle background, music and return to the field work. `a9557e5` fixed the
return sequence and music playback settings; `e9fb3aa` restored normal music
volume, also confirmed in-game. This is a private prototype, outside Studio.

The encounter list, source track names, monster IDs and NPC location are in
[party/Battles.md](../party/Battles.md). The prototype gives opponents 200 HP,
weak Firaga/Thundaga/Blizzaga/Dystopia, no rewards and guaranteed escape for
resonance testing. Those are test settings, not a future balancing policy.

## Native battle music

Use `tools/private/battle_music.py` and `battle_hca.py` as the working reference.
The four source tracks are unencrypted HCA 2 with two independently encoded
channels, no joint stereo and no high-frequency reconstruction. This narrow
layout can be promoted to HCA 3 while keeping the spectral frames intact.
The adapter applies FFR's cipher type 56, reads the installed game's key from
the extracted `DefaultEngine.ini`, uses the host AWB subkey and ID width,
masks the header tags and updates checksums. Unsupported layouts fail;
changing the version bytes alone is not a general HCA conversion method.

Playback settings matter as well as the recording:

- Clone FFR's embedded looping waveform profile. Set `Streaming=0`,
  `EncodeType=2`, `NumChannels=2` and a valid `MemoryAwbId`; both streaming
  ID and port are `65535`. Preserve exact sample counts and loop metadata.
- Use the native `BGM_PP_BATTLE1` sequence commands and native synthesis
  commands. Normal custom cue gain is **0.13**, matching that battle cue.
- Append the custom cues to `BGM_PP`, because the game's `PlayBGM` lookup
  uses its main BGM sheet. Rebase all new cue, sequence, track, synth, command
  and waveform references. Preserve original cues, embedded recordings,
  streaming metadata, bus names and the game's BGM volume controls.
- Verify both standalone HCA and bank playback with independent decoding:
  PCM must match the source sample-for-sample and loops must be unchanged.
  Verify the packed asset still contains the exact authored ACB.

The ADX attempt decoded acceptably offline but sounded distorted in FFR.
Reducing gain did not cure it. The first HCA replacement was silent; the
working update also corrected embedded-wave settings, copied native playback
commands and used an audible gain. Those changes were tested together, so
the contribution of each individual setting is not isolated. Preserve the
confirmed combination when extending this prototype. Offline decoding alone
does not establish that a new codec or playback graph works in the game.

## Arena and return from battle

`battleStage=5` selects the plains arena, but assigning that table value alone
produced a battle with no background. Mitra's persistent world must also
register both stage entries from `CDT_BtlStageAsset_Demo.battleLevelList`:

- `/Game/Map/Btl/00Com/00Com_60/LT/Btl_00Com_60_01_LT`
- `/Game/Map/Btl/00Com/00Com_60/BG/Btl_00Com_60_BG0`

`npc_assets.add_battle_streaming` adds them as `LevelStreamingDynamic`
exports and appends their references to the UWorld streaming list and load
dependencies. Preserve existing level references. New cooked FNames must be
inside `NamesReferencedFromExportDataCount`; a legacy round trip alone did
not catch an earlier IoStore startup crash caused by that prefix.

All four groups route victory, escape and defeat to `Private_Battles_Return`.
A data-only return row left the screen black. The working return uses
`/Game/Sequencer/Event/Gimmick/Majipot/SEQ_Gim_EV_Majipot_Escape`: its native
timeline executes the event header, fade-in, fade wait and footer. The return
row has `encountGroupId=-1`, restores the party and restores map BGM. Keep
story flags, progression, rewards and save operations empty for repeatable tests.

The choice dialog is authored by `src/ffr-dt/ChoiceSequence.cs` from the
native free-talk sequence. It keeps native bindings and modifies the choice
calls in bytecode. A full JSON rebuild can lose UE5 UniversalObjectLocator
private fields; preserve the native binary representation when cloning it.

## Adding future units

Enemy prototypes in `make_npc_battles.py` combine FFBE sprites with native
unit parameters, AI, battle assets, design parameters and encounter groups.
Each referenced skill needs a sequence actually present in the demo; a row
in the full-game table does not prove its sequence is shipped. The four
opening spells in the prototype are verified native sequence donors.

The party prototype in `make_party_mod.py` occupies unused Jake (1007) and
Sakura (1008) slots. This is not a general party expansion mechanism. See
[party/README.md](../party/README.md) for save restrictions and backups.
Party units need native playable parameters, commands, growth-table references,
portraits, sprites and equipment compatibility so they can equip visions.
Persistent FFBE aura cells are removed separately from attack effects. Basic
attacks map the FFBE `atk` frames across native windup, strike and recovery;
attack ordering uses the native Attack `SortId`.

Select voices independently of graphics and stat donors. `UNITS.voiceRow`
copies the donor's `DT_UnitParameter.BattleVoiceLabel`. Raegen uses Rain
(`CHR0010`); Helena now selects regular Fina (`CHR0030`), whose demo voice
bank is `VO_BTL_CHR0030`. Dark Fina's label is `CHR0060`, a different voice.
Helena's voice change is structurally verified and awaits a separate listening
test. No new voice recordings are required. Future unfamiliar voice donors
must have their cue bank checked for availability in the target game.

## Rebuild and verify

Build in dependency order: **Studio visions → PrivateParty → PrivateBattles**.
The latter two ship shared tables, so an old higher-priority NPC package can
mask a new party change. The party builder excludes prior party/NPC packages;
the NPC builder reads the newly installed party. `party/Rebuild Party.cmd`
performs that sequence with `--keep-saves`.

Before installing, check that the game is closed and the input mod hashes have
not changed. Back up replaced packages. The builders verify unrelated rows,
growth references, party priority, attack order and selected voice labels.
`tools/tests/test_private_battles.py` checks encounter returns, scheduled native
fades, arena registration, audio graphs, PCM equality and packed music bytes.
The timestamped `build/party-members` and `build/npc-battles` verification
reports distinguish structural checks from actual user gameplay confirmation.
Re-test new source layouts and units in-game before adding them to Studio.
