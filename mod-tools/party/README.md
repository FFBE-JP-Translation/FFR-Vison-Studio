# Extra party members and custom battles

The authored definitions are in `tools/private/make_party_mod.py` (Raegen and
Helena) and `tools/private/make_npc_battles.py` (the Mitra NPC and five encounters).
The `private` folder is a historical name; these sources are part of this repo.

Provide `raegen.webp` and `helena.webp` in this folder for the portrait inputs.
FFBE sprite/music inputs and the native game extraction are separate data.
See [the mod tools guide](../README.md) for prerequisites and staging commands.
The party installer can update saves, so review the staged package first and
use its `--keep-saves` option when only refreshing installed assets.
