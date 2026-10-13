import struct, os, sys, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools")); import ffrenv
G = sys.argv[2] if len(sys.argv) > 2 else ffrenv.game_root()          # usage: utoc_index.py <out.tsv> [<game folder>]
UTOC = os.path.join(G, r"FFRS\Content\Paks\FFRS-Windows.utoc")
OUT = sys.argv[1]
with open(UTOC,"rb") as f: data=f.read()
ver=data[16]
hdrsize, entrycount, cbcount, cbentsize, cmcount, cmnamelen, cmblocksize, dirsz, partcount = struct.unpack("<9I", data[20:56])
flags=data[80]; seeds, = struct.unpack("<I", data[84:88]); partsize,=struct.unpack("<Q",data[88:96]); nophash,=struct.unpack("<I",data[96:100])
print("version",ver,"entries",entrycount,"blocks",cbcount,"flags",flags,"seeds",seeds,"nophash",nophash,"partsize",partsize)
off=hdrsize
chunkids_off=off; off+=entrycount*12
offlen_off=off; off+=entrycount*10
if ver>=4: off+=seeds*4
if ver>=5: off+=nophash*4
blocks_off=off; off+=cbcount*cbentsize
cm_off=off; off+=cmcount*cmnamelen
print("compression:", [data[cm_off+i*cmnamelen:cm_off+(i+1)*cmnamelen].split(b"\0")[0].decode() for i in range(cmcount)])
if flags & 4:
    hs,=struct.unpack("<I",data[off:off+4]); off+=4+hs*2+cbcount*20
dir_off=off
# parse directory index
p=dir_off
def rd_fstring(p):
    n,=struct.unpack("<i",data[p:p+4]); p+=4
    if n<0:
        s=data[p:p+(-n)*2].decode("utf-16-le")[:-1]; p+=(-n)*2
    else:
        s=data[p:p+n].decode("utf-8",errors="replace")[:-1] if n>0 else ""; p+=n
    return s,p
mount,p=rd_fstring(p)
nd,=struct.unpack("<i",data[p:p+4]); p+=4
dirs=[struct.unpack("<IIII",data[p+i*16:p+(i+1)*16]) for i in range(nd)]; p+=nd*16
nf,=struct.unpack("<i",data[p:p+4]); p+=4
files=[struct.unpack("<III",data[p+i*12:p+(i+1)*12]) for i in range(nf)]; p+=nf*12
ns,=struct.unpack("<i",data[p:p+4]); p+=4
strs=[]
for i in range(ns):
    s,p=rd_fstring(p); strs.append(s)
print("mount:",mount,"dirs",nd,"files",nf,"strings",ns)
NONE=0xFFFFFFFF
# chunk offset/length for size info
def chunk_len(idx):
    b=data[offlen_off+idx*10:offlen_off+idx*10+10]
    # 5 bytes offset big-endian, 5 bytes length big-endian
    return int.from_bytes(b[5:10],"big")
paths=[]
def walk(d, prefix):
    while d!=NONE:
        name,first_child,next_sib,first_file=dirs[d]
        dname=strs[name] if name!=NONE else ""
        full=prefix+dname+"/" if dname else prefix
        fi=first_file
        while fi!=NONE:
            fname,nextf,userdata=files[fi]
            paths.append((full+strs[fname], userdata, chunk_len(userdata)))
            fi=nextf
        walk(first_child, full)
        d=next_sib
walk(0, mount)
with open(OUT,"w",encoding="utf-8") as o:
    for pth,ud,ln in paths: o.write(f"{ln}\t{pth}\n")
print("total paths:",len(paths))
# summary by top folders
c=collections.Counter()
for pth,_,_ in paths:
    parts=pth.split("/")
    c["/".join(parts[:3])]+=1
for k,v in c.most_common(60): print(f"{v:6d}  {k}")
