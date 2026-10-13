import re, struct, sys, os, mmap
G = r"S:\Program Files (x86)\Steam\steamapps\common\FINAL FANTASY RESONANCE DEMO"
EXE = os.path.join(G, r"FFRS\Binaries\Win64\FFRS-Win64-Shipping.exe")
PAK = os.path.join(G, r"FFRS\Content\Paks\FFRS-Windows.pak")
UTOC = os.path.join(G, r"FFRS\Content\Paks\FFRS-Windows.utoc")
GUTOC = os.path.join(G, r"FFRS\Content\Paks\global.utoc")

print("=== UE version (UTF-16 + ASCII scan) ===")
with open(EXE, "rb") as f:
    mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    pats = [rb"\+\+UE[45]\+Release-[0-9]+\.[0-9]+", rb"[45]\.[0-9]+\.[0-9]+-[0-9]+\+\+\+UE[45]\+Release-[0-9.]+"]
    found=set()
    for p in pats:
        for m in re.finditer(p, mm): found.add(("ascii", m.group().decode()))
        p16 = b"".join(bytes([c,0]) if c not in b"+*.[]()\-" else b"\\"+bytes([c])+b"\x00" for c in b"") # placeholder
    # UTF-16LE search
    for p in [rb"\+\x00\+\x00U\x00E\x00[45]\x00\+\x00R\x00e\x00l\x00e\x00a\x00s\x00e\x00-\x00([0-9]\x00)+\.\x00([0-9]\x00)+"]:
        for m in re.finditer(p, mm): found.add(("utf16", m.group().decode("utf-16-le")))
    for x in sorted(found): print(x)
    # also look for "5.x.y" near "UnrealEngine"
    for m in re.finditer(rb"UE5\.[0-9]", mm):
        s = mm[m.start()-10:m.end()+10]; print("ctx:", s)
        break
    mm.close()

print("\n=== PAK footer ===")
sz = os.path.getsize(PAK)
with open(PAK,"rb") as f:
    f.seek(sz-4096); tail=f.read()
# Find magic 0x5A6F12E1 (little-endian bytes E1 12 6F 5A)
idx = tail.rfind(b"\xE1\x12\x6F\x5A")
print("pak size:", sz, "magic idx from end:", len(tail)-idx if idx>=0 else None)
if idx>=0:
    # v8+ footer: [EncryptionKeyGuid(16)][bEncryptedIndex(1)][Magic(4)][Version(4)][IndexOffset(8)][IndexSize(8)][IndexHash(20)]...
    enc = tail[idx-1]
    guid = tail[idx-17:idx-1]
    ver, = struct.unpack("<I", tail[idx+4:idx+8])
    ioff, isz = struct.unpack("<qq", tail[idx+8:idx+24])
    print("pak version:", ver, "encrypted index:", enc, "key guid:", guid.hex(), "index off/size:", ioff, isz)
    # compression methods after hash for v8+
    cm = tail[idx+44:idx+44+32*5]
    names=[cm[i*32:(i+1)*32].split(b"\x00")[0].decode(errors="replace") for i in range(5)]
    print("compression methods:", [n for n in names if n])

print("\n=== UTOC headers ===")
for p in (UTOC, GUTOC):
    with open(p,"rb") as f: h=f.read(144)
    magic=h[:16]; ver=h[16]; res=h[17:20]
    hdrsize, entrycount, cbcount, cbentsize, cmcount, cmnamelen, cmblocksize = struct.unpack("<IIIIIII", h[20:48])
    dirsz, partcount = struct.unpack("<II", h[48:56])
    cid = h[56:68]  # FIoContainerId? actually 8 bytes container id then guid 16
    print(os.path.basename(p), "magic:", magic, "version:", ver)
    print("  hdrsize",hdrsize,"tocEntries",entrycount,"chunkBlocks",cbcount,"blockEntrySize",cbentsize,"compMethods",cmcount,"cmNameLen",cmnamelen,"blockSize",cmblocksize)
    print("  dirIndexSize",dirsz,"partitions",partcount)
    # container flags at offset 80..? For v3+: ContainerId(8)@56, EncryptionKeyGuid(16)@64, ContainerFlags(1)@80
    cont_id = h[56:64].hex(); keyguid=h[64:80].hex(); flags=h[80]
    print("  containerId",cont_id,"encKeyGuid",keyguid,"flags",flags, "(1=Compressed,2=Encrypted,4=Signed,8=Indexed)")
    names=[]
    with open(p,"rb") as f:
        f.seek(hdrsize + entrycount*12 + entrycount*10 + cbcount*cbentsize)
        # compression method names come after ChunkIds, ChunkOffsets, ChunkBlocks
        blob=f.read(cmcount*cmnamelen)
        for i in range(cmcount): names.append(blob[i*cmnamelen:(i+1)*cmnamelen].split(b"\x00")[0].decode(errors="replace"))
    print("  compression:", names)
