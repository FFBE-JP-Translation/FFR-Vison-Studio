"""Inspect pinned native item classification and shop/native-navigation functions."""
import json, struct
from pathlib import Path
import pefile, capstone
game=Path('T:/SteamLibrary/steamapps/common/FINAL FANTASY RESONANCE DEMO/FFRS/Binaries/Win64/FFRS-Win64-Shipping.exe')
pe=pefile.PE(str(game),fast_load=True);base=pe.OPTIONAL_HEADER.ImageBase;binary=game.read_bytes()
decoder=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64)
names=['GetEquipmentTypeById','GetSelectEquipItemList','GetInventoryItemIdListByEquipType','GetAllEquipIdListByType','GetEquipmentId','SetEquipmentId','UnequipmentId','GetItemTypeById','SetFocusedIndex','HandleInputDecide','HandleInputDirection','MakeInputActionValueOfType']
report={}
for name in names:
    start=0;entries=[];seen=set()
    while (offset:=binary.find(name.encode()+b'\0',start))>=0:
        start=offset+1;pointer=struct.pack('<Q',base+pe.get_rva_from_offset(offset));ref=-1
        while (ref:=binary.find(pointer,ref+1))>=0:
            target,=struct.unpack_from('<Q',binary,ref+8)
            if not base<target<base+0x8000000 or target in seen:continue
            seen.add(target)
            instructions=[]
            for ins in decoder.disasm(pe.get_data(target-base,650),target):
                instructions.append(f'{ins.address-base:x}: {ins.mnemonic} {ins.op_str}')
                if ins.mnemonic=='ret':break
            entries.append({'rva':hex(target-base),'asm':instructions})
    report[name]=entries
out=Path('build/vision-cards/classification-bindings.json');out.write_text(json.dumps(report,indent=2))
functions={0x51cd340:224,0x51cd420:240}
assembly=[]
for rva,size in functions.items():
    assembly.append(f'\nNative {rva:x} prologue {pe.get_data(rva,20).hex()}')
    for ins in decoder.disasm(pe.get_data(rva,size),base+rva):
        assembly.append(f'{ins.address-base:x}: {ins.mnemonic} {ins.op_str}')
Path('build/vision-cards/classification-asm.txt').write_text('\n'.join(assembly))
print(out)
