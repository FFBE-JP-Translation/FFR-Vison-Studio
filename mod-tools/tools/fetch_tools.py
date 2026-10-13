import json, urllib.request, os, sys, re
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(OUT, exist_ok=True)
def gh(url):
    req=urllib.request.Request(url, headers={"User-Agent":"ffr-mod-tools"})
    return json.load(urllib.request.urlopen(req, timeout=60))
def dl(url, name):
    dst=os.path.join(OUT,name)
    if os.path.exists(dst) and os.path.getsize(dst)>0: print("exists", name); return dst
    req=urllib.request.Request(url, headers={"User-Agent":"ffr-mod-tools"})
    with urllib.request.urlopen(req, timeout=600) as r, open(dst,"wb") as f:
        while True:
            b=r.read(1<<20)
            if not b: break
            f.write(b)
    print("downloaded", name, os.path.getsize(dst)); return dst
targets = [
  ("trumank/retoc", None, r"retoc.*x86_64-pc-windows-msvc\.zip$"),
  ("trumank/repak", None, r"repak_cli-x86_64-pc-windows-msvc\.zip$"),
  ("4sval/FModel", None, r"^FModel\.zip$"),
  ("atenfyr/UAssetGUI", "v1.1.0", r"^UAssetGUI\.exe$"),
  ("atenfyr/UAssetAPI", None, r"^UAssetAPI.*\.zip$"),
]
for repo, tag, pat in targets:
    rels = gh(f"https://api.github.com/repos/{repo}/releases?per_page=10")
    rels = [r for r in rels if (tag is None and not r["prerelease"]) or r["tag_name"]==tag]
    got=False
    for r in rels:
        for a in r["assets"]:
            if re.search(pat, a["name"]):
                print(repo, r["tag_name"], "->", a["name"]); dl(a["browser_download_url"], a["name"]); got=True; break
        if got: break
    if not got: print("NO MATCH", repo, [a["name"] for r in rels[:2] for a in r["assets"]])
# UE4SS: list all recent releases/tags to pick a 5.6-capable build
print("\n=== UE4SS releases ===")
for r in gh("https://api.github.com/repos/UE4SS-RE/RE-UE4SS/releases?per_page=15"):
    print(" ", r["tag_name"], "pre" if r["prerelease"] else "", r["published_at"], [a["name"] for a in r["assets"]][:6])
print("=== UE4SS tags ===")
print([t["name"] for t in gh("https://api.github.com/repos/UE4SS-RE/RE-UE4SS/tags?per_page=20")])
