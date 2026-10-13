"""Record native stat entry points for the pinned demo, without loading it."""
import json
from pathlib import Path
import struct
import capstone
import pefile

ROOT = Path(__file__).resolve().parents[2]
game = Path('T:/SteamLibrary/steamapps/common/FINAL FANTASY RESONANCE DEMO/FFRS/Binaries/Win64/FFRS-Win64-Shipping.exe')
pe = pefile.PE(str(game), fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
binary = game.read_bytes()
decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
report = {}
for name in ('GetUnitId',):
    offset = binary.find(name.encode() + b'\0')
    pointer = struct.pack('<Q', base + pe.get_rva_from_offset(offset))
    offset = -1
    entries = []
    while (offset := binary.find(pointer, offset + 1)) != -1:
        target, = struct.unpack_from('<Q', binary, offset + 8)
        if base < target < base + 0x6000000:
            entries.append({'address': hex(target), 'instructions': [
                f'{i.mnemonic} {i.op_str}' for i in decoder.disasm(pe.get_data(target-base, 64), target)]})
    report[name] = entries
report['equipmentBonus'] = {'rva': '0x522e0f0', 'prologue': pe.get_data(0x522e0f0, 20).hex()}
path = ROOT / 'build/vision-cards/native-bindings.json'
path.write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
