"""ss6_tail.py - decode the custom-serialized keyframe payload tail of a cooked Ss6Project (UAssetAPI JSON dump)"""
import json, base64, struct, sys
TYPES=["Unkown","StringType","IntType","FloatType","BooleanType","HashType","ArrayType","Point2Type","ColorType"]
def find(props,name):
    for p in props:
        if p.get("Name")==name: return p
def decode(path, want_anim=None):
    j=json.load(open(path,encoding="utf-8-sig")); names=j["NameMap"]; ex=j["Exports"][0]; ext=base64.b64decode(ex["Extras"])
    pos=[0]
    def rd(n): b=ext[pos[0]:pos[0]+n]; pos[0]+=n; return b
    def fstr():
        n,=struct.unpack("<i",rd(4))
        if n<0: return rd(-n*2).decode("utf-16-le")[:-1]
        return rd(n).decode()[:-1] if n>0 else ""
    def value(t):
        if t=="FloatType": return struct.unpack("<f",rd(4))[0]
        if t=="IntType": return struct.unpack("<i",rd(4))[0]
        if t=="BooleanType": return rd(1)[0]
        if t=="StringType": return fstr()
        if t=="Point2Type": return struct.unpack("<ff",rd(8))
        if t=="ColorType": return struct.unpack("<4f",rd(16))
        if t=="HashType":
            n,=struct.unpack("<i",rd(4)); out={}
            for _ in range(n):
                ki,kn=struct.unpack("<ii",rd(8)); key=names[ki]; fr=struct.unpack("<H",rd(2))[0]; vn=fr>>9; hz=bool(fr&0x80); mask=rd((vn+7)//8) if hz else b""
                present=[i for i in range(vn) if not hz or not (mask[i//8]>>(i%8))&1]; vals={}
                for i in present:
                    if i==0: vals["Type"]=rd(1)[0]
                    elif i==1: vals["Int"]=struct.unpack("<i",rd(4))[0]
                    elif i==2: vals["Float"]=struct.unpack("<f",rd(4))[0]
                    elif i==3: vals["Bool"]=rd(1)[0]
                out[key]=value(TYPES[vals.get("Type",0)])
            return out
        if t=="ArrayType":
            n,=struct.unpack("<i",rd(4)); return [None]*n
        raise Exception(t)
    result={}
    for ap in find(ex["Data"],"AnimeList")["Value"]:
        for a in find(ap["Value"],"AnimeList")["Value"]:
            an=find(a["Value"],"AnimationName")["Value"]
            for pa in find(a["Value"],"PartAnimes")["Value"]:
                pn=find(pa["Value"],"PartName")["Value"]
                for at in find(pa["Value"],"Attributes")["Value"]:
                    tag=find(at["Value"],"Tag")["Value"]
                    for k in find(at["Value"],"Key")["Value"]:
                        vt=find(find(k["Value"],"Value")["Value"],"Type")["Value"]; v=value(vt.split("::")[-1])
                        if want_anim is None or an==want_anim: result.setdefault((an,pn,tag),[]).append((find(k["Value"],"Time")["Value"],v))
    return pos[0], len(ext), result
if __name__=="__main__":
    consumed,total,res=decode(sys.argv[1], sys.argv[2] if len(sys.argv)>2 else None)
    print(f"tail consumed {consumed} of {total} -> {'OK' if consumed==total else 'MISMATCH'}")
    for k,v in list(res.items())[:12]: print("  ", k, v[:4])
