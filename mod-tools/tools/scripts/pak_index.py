import struct, os, sys, collections
G = r"S:\Program Files (x86)\Steam\steamapps\common\FINAL FANTASY RESONANCE DEMO"
PAK = os.path.join(G, r"FFRS\Content\Paks\FFRS-Windows.pak")
OUT = sys.argv[1]
sz=os.path.getsize(PAK)
with open(PAK,"rb") as f:
    f.seek(sz-4096); tail=f.read()
idx=tail.rfind(b"\xE1\x12\x6F\x5A")
ver,=struct.unpack("<I",tail[idx+4:idx+8]); ioff,isz=struct.unpack("<qq",tail[idx+8:idx+24])
with open(PAK,"rb") as f: f.seek(ioff); data=f.read(isz)
p=0
def fstr(p):
    n,=struct.unpack("<i",data[p:p+4]); p+=4
    if n<0: s=data[p:p+(-n)*2].decode("utf-16-le")[:-1]; p+=(-n)*2
    else: s=data[p:p+n].decode("utf-8","replace")[:-1]; p+=n
    return s,p
mount,p=fstr(p)
count,=struct.unpack("<i",data[p:p+4]); p+=4
seed,=struct.unpack("<Q",data[p:p+8]); p+=8
hasPH,=struct.unpack("<i",data[p:p+4]); p+=4
if hasPH:
    ph_off,ph_size=struct.unpack("<qq",data[p:p+16]); p+=16; p+=20
hasFDI,=struct.unpack("<i",data[p:p+4]); p+=4
fdi_off,fdi_size=struct.unpack("<qq",data[p:p+16]); p+=16; p+=20
enc_size,=struct.unpack("<i",data[p:p+4]); p+=4
enc=data[p:p+enc_size]; p+=enc_size
print("pak version",ver,"mount",mount,"count",count,"hasPathHash",hasPH,"hasFDI",hasFDI)
with open(PAK,"rb") as f: f.seek(fdi_off); fdi=f.read(fdi_size)
data=fdi; p=0
ndirs,=struct.unpack("<i",data[p:p+4]); p+=4
entries=[]
for i in range(ndirs):
    dname,p=fstr(p)
    nfiles,=struct.unpack("<i",data[p:p+4]); p+=4
    for j in range(nfiles):
        fname,p=fstr(p)
        encidx,=struct.unpack("<i",data[p:p+4]); p+=4
        # decode size from encoded entry
        e=enc[encidx:encidx+32]
        flags,=struct.unpack("<I",e[0:4])
        off_32=(flags>>31)&1; usz_32=(flags>>30)&1; sz_32=(flags>>29)&1
        q=4
        if off_32: off,=struct.unpack("<I",e[q:q+4]); q+=4
        else: off,=struct.unpack("<Q",e[q:q+8]); q+=8
        if usz_32: usz,=struct.unpack("<I",e[q:q+4]); q+=4
        else: usz,=struct.unpack("<Q",e[q:q+8]); q+=8
        entries.append((mount+dname+fname, usz, (flags>>23)&0x3f))
with open(OUT,"w",encoding="utf-8") as o:
    for pth,usz,cm in entries: o.write(f"{usz}\t{cm}\t{pth}\n")
print("entries:",len(entries))
c=collections.Counter()
for pth,_,_ in entries:
    c[os.path.splitext(pth)[1]]+=1
print("by ext:",c.most_common(20))
c2=collections.Counter()
for pth,_,_ in entries:
    parts=pth.replace("../","").split("/"); c2["/".join(parts[:3])]+=1
for k,v in c2.most_common(40): print(f"{v:6d} {k}")
print("\n--- non-asset non-bulk samples ---")
for pth,usz,cm in entries:
    if not pth.endswith((".uasset",".ubulk",".uptnl",".umap",".uexp")): print(usz, pth)
