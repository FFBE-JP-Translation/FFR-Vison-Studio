#!/usr/bin/env python
"""ss6_summary.py - compact summary of a SpriteStudio6 project exported by ffr-export (json command).

usage: python tools/ss6_summary.py <ss6project.json> [out.json]
Prints animation packs, animations (name/fps/frames/canvas), the part tree and the cell map (cell names, sizes),
and writes the same as JSON when an output path is given.
"""
import json, sys, collections

def main():
    j = json.load(open(sys.argv[1], encoding="utf-8"))
    p = j["Properties"]
    out = {"version": p.get("Version"), "settings": p.get("Settings"), "cellmaps": [], "animepacks": []}
    for cm in p.get("CellmapList", []):
        cells = cm.get("Cells", [])
        out["cellmaps"].append({
            "name": cm.get("CellMapName"), "image": cm.get("ImagePath"), "pixelSize": cm.get("PixelSize"),
            "cellCount": len(cells),
            "cells": [{"name": c.get("CellName"), "pos": c.get("Pos"), "size": c.get("Size"), "pivot": c.get("Pivot"), "rotated": c.get("Rotated")} for c in cells]})
    for ap in p.get("AnimeList", []):
        model = ap.get("Model", {})
        parts = [{"name": pt.get("PartName"), "index": pt.get("ArrayIndex"), "parent": pt.get("ParentIndex"), "type": pt.get("Type"), "blend": pt.get("AlphaBlendType")} for pt in model.get("PartList", [])]
        anims = []
        for an in ap.get("AnimeList", []):
            st = an.get("Settings", {})
            part_anims = an.get("PartAnimes", []) or an.get("partAnimes", [])
            # count keyframes per attribute to show which channels each animation uses
            attrs = collections.Counter()
            for pa in part_anims:
                for att in pa.get("Attributes", []):
                    attrs[att.get("Tag") or att.get("tag") or "?"] += len(att.get("Keys", []) or [])
            anims.append({"name": an.get("AnimationName"), "fps": st.get("Fps"), "frames": st.get("FrameCount"), "canvas": st.get("CanvasSize"),
                          "pivot": st.get("Pivot"), "sortMode": st.get("SortMode"), "partsAnimated": len(part_anims),
                          "keyframesByAttribute": dict(attrs.most_common(12)), "labels": [l.get("Name") or l.get("name") for l in (an.get("Labels") or [])]})
        out["animepacks"].append({"name": ap.get("AnimePackName"), "cellmaps": ap.get("CellmapNames"), "parts": parts, "animations": anims})
    # print
    print(f"SS6 version {out['version']}")
    for cm in out["cellmaps"]:
        print(f"cellmap {cm['name']} image={cm['image']} size={cm['pixelSize']} cells={cm['cellCount']}")
        sizes = collections.Counter((int(c['size']['X']), int(c['size']['Y'])) for c in cm["cells"] if c.get("size"))
        print("  most common cell sizes:", sizes.most_common(8))
        print("  cell names sample:", [c["name"] for c in cm["cells"][:12]], "...")
    for ap in out["animepacks"]:
        print(f"animepack {ap['name']}: {len(ap['parts'])} parts, {len(ap['animations'])} animations")
        print("  parts:", ", ".join(f"{pt['name']}({pt['type'].split('::')[-1]},parent={pt['parent']})" for pt in ap["parts"]))
        for an in ap["animations"]:
            print(f"  anim {an['name']:<24} fps={an['fps']} frames={an['frames']:<5} canvas={an['canvas']} parts={an['partsAnimated']} keys={an['keyframesByAttribute']} labels={an['labels']}")
    if len(sys.argv) > 2:
        json.dump(out, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("wrote", sys.argv[2])

if __name__ == "__main__":
    main()
