using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UAssetAPI;
using UAssetAPI.UnrealTypes;
using UAssetAPI.Unversioned;
using UAssetAPI.ExportTypes;
using UAssetAPI.PropertyTypes.Objects;
using UAssetAPI.PropertyTypes.Structs;

// patch file format (JSON):
// {
//   "legacyRoot": "S:/Projects/ffr/extracted/legacy",     base folder holding FFRS/Content/... legacy assets
//   "outRoot":    "S:/Projects/ffr/build/mymod",           patched/cloned assets are written here (same relative paths)
//   "tables": [
//     { "asset": "FFRS/Content/Datatable/Unit/DT_UnitParameter",
//       "add": [ { "row": "NewRowName", "cloneFrom": "ExistingRowName", "set": { "ID": 13201, "Name": "Esther", "roles": ["eUnitRole::Attacker"], ... } } ],
//       "set": [ { "row": "ExistingRowName", "set": { "ItemList[4].ItemId": 13201 } } ],
//       "remove": [ "RowName" ] }
//   ],
//   "clones": [ { "from": "FFRS/Content/Chara/menu/summon13125/summon13125", "to": "FFRS/Content/Chara/menu/summon13201/summon13201",
//                 "rename": [ ["summon13125", "summon13201"] ] } ]
// }
// Values: numbers, bools, strings (Str/Name/Enum/Text-literal/SoftObject path), objects (struct fields or {"table":..,"key":..} for FText),
// arrays (array property; elements cloned from the first existing element or created from the array type).
static class Patch
{
    public static int Run(string patchPath, Usmap? mappings)
    {
        var patch = JObject.Parse(File.ReadAllText(patchPath, Encoding.UTF8));
        var legacyRoot = patch.Value<string>("legacyRoot")!; var outRoot = patch.Value<string>("outRoot")!;
        var ver = EngineVersion.VER_UE5_6;
        int changed = 0;
        foreach (var t in patch["tables"] as JArray ?? new JArray())
        {
            var rel = t.Value<string>("asset")!;
            var src = Path.Combine(legacyRoot, rel + ".uasset");
            var asset = new UAsset(src, ver, mappings);
            var dt = asset.Exports.OfType<DataTableExport>().FirstOrDefault() ?? throw new Exception($"{rel}: no DataTable export");
            var rows = dt.Table.Data;
            foreach (var add in t["add"] as JArray ?? new JArray())
            {
                var name = add.Value<string>("row")!; var from = add.Value<string>("cloneFrom")!;
                var template = rows.FirstOrDefault(r => r.Name.ToString() == from) ?? throw new Exception($"{rel}: cloneFrom row '{from}' not found");
                var existing = rows.FirstOrDefault(r => r.Name.ToString() == name);
                if (existing != null) rows.Remove(existing);
                var row = (StructPropertyData)DeepClone(template);
                row.Name = FName.FromString(asset, name);
                ApplyObject(asset, row.Value, add["set"] as JObject ?? new JObject());
                rows.Add(row); changed++;
                Console.WriteLine($"  + {rel}: added row '{name}' (clone of '{from}')");
            }
            foreach (var set in t["set"] as JArray ?? new JArray())
            {
                var name = set.Value<string>("row")!;
                var row = rows.FirstOrDefault(r => r.Name.ToString() == name) ?? throw new Exception($"{rel}: row '{name}' not found");
                ApplyObject(asset, row.Value, set["set"] as JObject ?? new JObject()); changed++;
                Console.WriteLine($"  ~ {rel}: set row '{name}'");
            }
            foreach (var rem in t["remove"] as JArray ?? new JArray())
            {
                var name = rem.Value<string>()!; rows.RemoveAll(r => r.Name.ToString() == name); changed++;
            }
            var dst = Path.Combine(outRoot, rel + ".uasset"); Directory.CreateDirectory(Path.GetDirectoryName(dst)!);
            asset.Write(dst);
            // re-read to make sure it still parses
            var check = new UAsset(dst, ver, mappings);
            var n = check.Exports.OfType<DataTableExport>().First().Table.Data.Count;
            Console.WriteLine($"  = wrote {dst} ({n} rows, re-parse OK)");
        }
        foreach (var seq in patch["sequenceData"] as JArray ?? new JArray())
        {
            // Overlay authored channels and cooked entity fields on a binary-read
            // shell. UAssetAPI JSON loses private UniversalObjectLocator state;
            // keeping the original director binding avoids corrupting that state.
            var rel = seq.Value<string>("asset")!;
            var asset = new UAsset(Path.Combine(legacyRoot, rel + ".uasset"), ver, mappings);
            var authored = UAsset.DeserializeJson(File.ReadAllText(seq.Value<string>("json")!));
            var originalCount = asset.Exports.Count;
            if (authored.Exports.Count < originalCount) throw new InvalidDataException("Sequence exports cannot be removed");
            var fields = new Dictionary<string, string[]>
            {
                ["LevelSequence"] = new[] { "Signature" },
                ["MovieScene"] = new[] { "ObjectBindings", "PlaybackRange", "Signature" },
                ["MovieSceneEventTrack"] = new[] { "Sections", "EvaluationFieldGuid", "Signature" },
                ["MovieSceneEventTriggerSection"] = new[] { "EventChannel", "Signature" },
                ["MovieSceneCompiledData"] = new[] { "EntityComponentField", "CompiledSignature" },
            };
            // Preserve name indices used by deserialized FNames.
            foreach (var name in authored.GetNameMapIndexList()) FName.FromString(asset, name.Value);
            for (int i = 0; i < originalCount; i++)
            {
                var original = asset.Exports[i]; var edited = authored.Exports[i];
                if (original.ObjectName.ToString() != edited.ObjectName.ToString() || original.ClassIndex.Index != edited.ClassIndex.Index)
                    throw new Exception($"Sequence export #{i + 1} identity changed");
                if (original is not NormalExport dst || edited is not NormalExport src || !original.ClassIndex.IsImport()) continue;
                var kind = original.ClassIndex.ToImport(asset).ObjectName.ToString();
                if (!fields.TryGetValue(kind, out var allowed)) continue;
                foreach (var name in allowed)
                {
                    int index = dst.Data.FindIndex(p => p.Name.ToString() == name);
                    if (index < 0) continue;
                    dst.Data[index] = src.Data.First(p => p.Name.ToString() == name);
                }
            }
            // Extend only the existing director's bound event entries. All
            // original binary-read exports, especially the private locator
            // binding, remain intact; JSON is never used as the whole shell.
            for (int i = originalCount; i < authored.Exports.Count; i++)
            {
                if (authored.Exports[i] is not FunctionExport fn || fn.OuterIndex.Index is <= 0
                    || fn.OuterIndex.Index > originalCount || asset.Exports[fn.OuterIndex.Index-1] is not ClassExport director
                    || authored.Exports[fn.OuterIndex.Index-1] is not ClassExport authoredDirector
                    || !fn.ObjectName.ToString().StartsWith("FFBE_AuthoredEvent_")
                    || !authoredDirector.Children.Any(c => c.Index == i+1)
                    || !authoredDirector.FuncMap.Any(p => p.Key.ToString() == fn.ObjectName.ToString() && p.Value.Index == i+1)
                    || fn.LoadedProperties.Length != 1 || fn.LoadedProperties[0] is not UAssetAPI.FieldTypes.FObjectProperty parameter
                    || !parameter.PropertyClass.IsImport()
                    || parameter.PropertyClass.ToImport(authored).ObjectName.ToString() != "CPP_BtlSequencerEvent")
                    throw new InvalidDataException("Sequence growth requires a registered, bound director event function");
                if (director.FuncMap.Any(p => p.Key.ToString() == fn.ObjectName.ToString()))
                    throw new InvalidDataException("Sequence event function name collision");
                fn.Asset = asset;
                fn.ObjectName = FName.FromString(asset, fn.ObjectName.ToString());
                asset.Exports.Add(fn);
                var index = FPackageIndex.FromExport(i);
                director.Children = director.Children.Append(index).ToArray();
                director.FuncMap.Add(FName.FromString(asset, fn.ObjectName.ToString()), index);
                director.CreateBeforeSerializationDependencies ??= new List<FPackageIndex>();
                director.CreateBeforeSerializationDependencies.Add(index);
            }
            var path = Path.Combine(outRoot, rel + ".uasset");
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            asset.Write(path);
            _ = new UAsset(path, ver, mappings);
            Console.WriteLine($"  = wrote {path} (authored sequence data, re-parse OK)");
            changed++;
        }
        foreach (var fr in patch["frames"] as JArray ?? new JArray())
        {
            // { "asset": rel, "after": ticks, "delta": ticks } -> every frame number / range bound at or after `after` moves by `delta`
            // (event key times, section ranges, playback range, marked frames, compiled evaluation fields); sub-section offsets stay.
            // Used to stretch a cloned battle sequence so a longer LB motion is not cut off by the next motion key.
            // With cut:true, delete [after + delta, after) and close that gap instead (delta must be negative).
            var rel = fr.Value<string>("asset")!;
            var asset = new UAsset(Path.Combine(legacyRoot, rel + ".uasset"), ver, mappings);
            int after = fr.Value<int>("after"), delta = fr.Value<int>("delta"), n = 0;
            if (fr.Value<bool>("cut"))
            {
                if (delta >= 0) throw new ArgumentException("A timeline cut needs a negative delta");
                n = CutSequence(asset, checked(after + delta), after);
            }
            else
                foreach (var ex in asset.Exports.OfType<NormalExport>()) n += ShiftFrames(ex.Data, after, delta);
            var dst = Path.Combine(outRoot, rel + ".uasset"); Directory.CreateDirectory(Path.GetDirectoryName(dst)!);
            asset.Write(dst);
            var check = new UAsset(dst, ver, mappings);
            Console.WriteLine($"  = wrote {dst} ({n} frame values >= {after} shifted by {delta}, re-parse OK, {check.Exports.Count} exports)");
            changed++;
        }
        foreach (var rt in patch["retime"] as JArray ?? new JArray())
        {
            // { "asset": rel, "function": "<event function export name>", "time": ticks } -> moves that one event key (the key whose
            // MovieSceneEvent.Ptrs.Function is the export) to the tick, keeping the channel's keys sorted; the sequence gets a new Signature
            var rel = rt.Value<string>("asset")!;
            var asset = new UAsset(Path.Combine(legacyRoot, rel + ".uasset"), ver, mappings);
            var fn = rt.Value<string>("function")!; int time = rt.Value<int>("time"); int n = 0;
            foreach (var ex in asset.Exports.OfType<NormalExport>())
            {
                var ch = ex.Data.FirstOrDefault(p => p.Name.ToString() == "EventChannel") as StructPropertyData;
                if (ch == null) continue;
                var times = ch.Value.FirstOrDefault(p => p.Name.ToString() == "KeyTimes") as ArrayPropertyData;
                var values = ch.Value.FirstOrDefault(p => p.Name.ToString() == "KeyValues") as ArrayPropertyData;
                if (times == null || values == null || times.Value.Length != values.Value.Length) continue;
                var pairs = new List<(int t, PropertyData tp, PropertyData vp)>();
                for (int i = 0; i < times.Value.Length; i++)
                {
                    int t = FrameOf(times.Value[i]);
                    if (FunctionName(asset, values.Value[i]) == fn) { t = time; SetFrame(times.Value[i], time); n++; }
                    pairs.Add((t, times.Value[i], values.Value[i]));
                }
                if (n == 0) continue;
                var sorted = pairs.OrderBy(x => x.t).ToList();
                times.Value = sorted.Select(x => x.tp).ToArray(); values.Value = sorted.Select(x => x.vp).ToArray();
                foreach (var sig in ex.Data.OfType<GuidPropertyData>().Where(g => g.Name.ToString() == "Signature")) sig.Value = Guid.NewGuid();
            }
            foreach (var ex in asset.Exports.OfType<NormalExport>())
                if (ex.ObjectName.ToString() == Path.GetFileName(rel) || ex.Data.Any(p => p.Name.ToString() == "EvaluationField"))
                    foreach (var sig in ex.Data.OfType<GuidPropertyData>().Where(g => g.Name.ToString() == "Signature")) sig.Value = Guid.NewGuid();
            var dst = Path.Combine(outRoot, rel + ".uasset"); Directory.CreateDirectory(Path.GetDirectoryName(dst)!);
            asset.Write(dst);
            var check = new UAsset(dst, ver, mappings);
            Console.WriteLine($"  = wrote {dst} ({n} key(s) of {fn} moved to {time}, re-parse OK, {check.Exports.Count} exports)");
            if (n == 0) Console.WriteLine($"  ! {rel}: retime found no key bound to {fn}");
            changed++;
        }
        foreach (var o in patch["objects"] as JArray ?? new JArray())
        {
            // { "asset": rel, "export": optional name, "set": {...}, "mapAdd": { "PropName": { "key": value, ... } } }
            var rel = o.Value<string>("asset")!;
            var asset = new UAsset(Path.Combine(legacyRoot, rel + ".uasset"), ver, mappings);
            var exportName = o.Value<string>("export");
            var ex = asset.Exports.OfType<NormalExport>().FirstOrDefault(e => exportName == null || e.ObjectName.ToString() == exportName) ?? throw new Exception($"{rel}: export not found");
            if (o["set"] is JObject set) ApplyObject(asset, ex.Data, set);
            foreach (var kv in o["mapAdd"] as JObject ?? new JObject())
            {
                var m = ex.Data.FirstOrDefault(p => p.Name.ToString() == kv.Key) as MapPropertyData ?? throw new Exception($"{rel}: map property '{kv.Key}' not found");
                PropertyData? k0 = null, v0 = null;
                foreach (var entry in m.Value) { k0 = entry.Key; v0 = entry.Value; break; }
                if (k0 == null || v0 == null) throw new Exception($"{rel}: map '{kv.Key}' is empty, cannot clone an entry");
                foreach (var e in (JObject)kv.Value!)
                {
                    JToken keyTok = int.TryParse(e.Key, out var ki) ? new JValue(ki) : new JValue(e.Key);
                    PropertyData? existing = null;
                    foreach (var k in m.Value.Keys) { if (KeyString(k) == e.Key) { existing = k; break; } }
                    if (existing != null) { m.Value[existing] = Apply(asset, m.Value[existing], e.Value!); Console.WriteLine($"  ~ {rel}: {kv.Key}[{e.Key}] updated"); continue; }
                    var nk = Apply(asset, DeepClone(k0), keyTok);
                    var nv = Apply(asset, DeepClone(v0), e.Value!);
                    m.Value.Add(nk, nv);
                    Console.WriteLine($"  + {rel}: {kv.Key}[{e.Key}] added");
                }
            }
            var dst = Path.Combine(outRoot, rel + ".uasset"); Directory.CreateDirectory(Path.GetDirectoryName(dst)!);
            asset.Write(dst);
            var check = new UAsset(dst, ver, mappings);
            Console.WriteLine($"  = wrote {dst} (re-parse OK, {check.Exports.Count} exports)");
            changed++;
        }
        foreach (var b in patch["bytecode"] as JArray ?? new JArray())
        {
            // { "asset": rel, "export": name | "*", "match": {field: value}, "set": {field: value} } -> edits the director-blueprint
            // event constants of a battle sequence in place (see KismetTools)
            var rel = b.Value<string>("asset")!;
            var asset = new UAsset(Path.Combine(legacyRoot, rel + ".uasset"), ver, mappings);
            var n = KismetTools.Edit(asset, mappings ?? throw new Exception("bytecode ops need --usmap"), (JObject)b);
            if (n == 0) Console.WriteLine($"  ! {rel}: bytecode op matched no event function");
            var dst = Path.Combine(outRoot, rel + ".uasset"); Directory.CreateDirectory(Path.GetDirectoryName(dst)!);
            asset.Write(dst);
            var check = new UAsset(dst, ver, mappings);
            Console.WriteLine($"  = wrote {dst} ({n} event functions edited, re-parse OK, {check.Exports.Count} exports)");
            changed++;
        }
        foreach (var c in patch["clones"] as JArray ?? new JArray())
        {
            var from = c.Value<string>("from")!; var to = c.Value<string>("to")!;
            var renames = (c["rename"] as JArray ?? new JArray()).Select(p => ((string)p[0]!, (string)p[1]!)).ToList();
            ClonePackage(Path.Combine(legacyRoot, from + ".uasset"), Path.Combine(outRoot, to + ".uasset"), "/Game/" + from.Replace("FFRS/Content/", ""), "/Game/" + to.Replace("FFRS/Content/", ""), renames, mappings);
            changed++;
        }
        foreach (var bank in patch["atomBanks"] as JArray ?? new JArray())
        {
            var from = bank.Value<string>("from")!; var to = bank.Value<string>("to")!;
            var dst = Path.Combine(outRoot, to + ".uasset");
            var acb = File.ReadAllBytes(bank.Value<string>("acb")!);
            if (acb.Length < 8 || Encoding.ASCII.GetString(acb, 0, 4) != "@UTF" ||
                System.Buffers.Binary.BinaryPrimitives.ReadUInt32BigEndian(acb.AsSpan(4, 4)) + 8L != acb.Length)
                throw new Exception("Invalid self-contained ACB payload");
            var hash = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(acb));
            if (!hash.Equals(bank.Value<string>("sha256"), StringComparison.OrdinalIgnoreCase))
                throw new Exception("FFBE sound bank changed after cue lookup");
            ClonePackage(Path.Combine(legacyRoot, from + ".uasset"), dst,
                "/Game/" + from.Replace("FFRS/Content/", ""), "/Game/" + to.Replace("FFRS/Content/", ""),
                new() { (Path.GetFileName(from), Path.GetFileName(to)) }, mappings);
            var asset = new UAsset(dst, ver, mappings);
            var ex = asset.Exports.OfType<NormalExport>().Single();
            AtomBankTools.Validate(asset);
            // The zero prefix selects DataResources[0]. Both the raw payload
            // and its loading metadata must change when replacing the bank.
            ex.Extras = new byte[checked(acb.Length + 4)];
            acb.CopyTo(ex.Extras, 4);
            var resource = asset.DataResources[0];
            resource.SerialSize = resource.RawSize = acb.Length;
            asset.DataResources[0] = resource;
            bool appendCues = bank.Value<bool?>("appendCues") == true;
            var settings = new JObject { ["CueSheetName"] = Path.GetFileName(to) };
            if (!appendCues) settings["NumSlots"] = 0;
            ApplyObject(asset, ex.Data, settings);
            var infos = (ArrayPropertyData)ex.Data.Single(p => p.Name.ToString() == "CueInfos");
            var template = (StructPropertyData)infos.Value[0];
            var newInfos = ((JArray)bank["cues"]!).Select(c =>
            {
                var info = (StructPropertyData)DeepClone(template);
                ApplyObject(asset, info.Value, new JObject
                {
                    ["ID"] = c["id"], ["Name"] = c["name"], ["UserData"] = "",
                    ["CategoryNames"] = new JArray(), ["AisacControlNames"] = new JArray(),
                    ["bLooping"] = c.Value<long>("durationMs") == uint.MaxValue,
                    ["bIsParameterPalletAssigned"] = false,
                });
                var duration = (StructPropertyData)info.Value.Single(p => p.Name.ToString() == "Duration");
                ((TimespanPropertyData)duration.Value[0]).Value = TimeSpan.FromMilliseconds(c.Value<long>("durationMs"));
                return (PropertyData)info;
            }).ToArray();
            if (appendCues)
            {
                foreach (var field in new[] { "ID", "Name" })
                {
                    string Key(PropertyData p) => ((StructPropertyData)p).Value.Single(v => v.Name.ToString() == field) switch
                    {
                        IntPropertyData id => id.Value.ToString(),
                        StrPropertyData name => name.Value.ToString(),
                        _ => throw new InvalidDataException($"Unexpected Atom cue {field} type")
                    };
                    var existing = infos.Value.Select(Key).ToHashSet();
                    if (newInfos.Select(Key).Any(existing.Contains))
                        throw new InvalidDataException($"Appended Atom cue {field} collides with a native cue");
                }
                infos.Value = infos.Value.Concat(newInfos).ToArray();
            }
            else infos.Value = newInfos;
            for (int i = 0; i < infos.Value.Length; i++) infos.Value[i].Name = FName.FromString(asset, i.ToString());
            asset.Write(dst);
            var check = new UAsset(dst, ver, mappings);
            // CueInfos has a different serialized length from the donor. The
            // resource offset is export-relative; measure it after serialization.
            var written = check.Exports.OfType<NormalExport>().Single();
            resource = check.DataResources[0];
            resource.SerialOffset = written.SerialSize - written.Extras.Length + 4;
            check.DataResources[0] = resource;
            check.Write(dst);
            check = new UAsset(dst, ver, mappings);
            if (!AtomBankTools.Validate(check).SequenceEqual(acb)) throw new Exception("Atom bank payload did not round-trip");
            Console.WriteLine($"  = wrote {dst} (FFBE ACB and {infos.Value.Length} cue records, bulk bounds and payload verified)");
            changed++;
        }
        Console.WriteLine($"patch done: {changed} operations");
        return 0;
    }

    public static void ClonePackage(string src, string dst, string oldPkg, string newPkg, List<(string, string)> renames, Usmap? mappings)
    {
        var asset = new UAsset(src, EngineVersion.VER_UE5_6, mappings);
        var all = new List<(string, string)> { (oldPkg, newPkg) }; all.AddRange(renames);
        int renamed = 0;
        var names = asset.GetNameMapIndexList();
        for (int i = 0; i < names.Count; i++)
        {
            var s = names[i].Value; var s2 = s;
            foreach (var (a, b) in all) s2 = s2.Replace(a, b);
            if (s2 != s) { asset.SetNameReference(i, new FString(s2)); renamed++; }
        }
        if (asset.FolderName != null)
        {
            var f = asset.FolderName.Value; foreach (var (a, b) in all) f = f.Replace(a, b); asset.FolderName = new FString(f);
        }
        Directory.CreateDirectory(Path.GetDirectoryName(dst)!);
        asset.Write(dst);
        Console.WriteLine($"  * cloned {Path.GetFileName(src)} -> {dst} (package {newPkg}, {renamed} names rewritten)");
    }

    static int FrameOf(PropertyData p)
    {
        if (p is FrameNumberPropertyData f) return f.Value.Value;
        if (p is StructPropertyData st) foreach (var c in st.Value) { var v = FrameOf(c); if (v != int.MinValue) return v; }
        return int.MinValue;
    }
    static void SetFrame(PropertyData p, int t)
    {
        if (p is FrameNumberPropertyData f) { f.Value = new FFrameNumber(t); return; }
        if (p is StructPropertyData st) foreach (var c in st.Value) SetFrame(c, t);
    }
    static string? FunctionName(UAsset asset, PropertyData keyValue)
    {
        // MovieSceneEvent { Ptrs: MovieSceneEventPtrs { Function: ObjectProperty -> export } }
        if (keyValue is not StructPropertyData ev) return null;
        var ptrs = ev.Value.FirstOrDefault(p => p.Name.ToString() == "Ptrs") as StructPropertyData;
        var fn = ptrs?.Value.FirstOrDefault(p => p.Name.ToString() == "Function") as ObjectPropertyData;
        if (fn == null || !fn.Value.IsExport()) return null;
        return fn.Value.ToExport(asset).ObjectName.ToString();
    }

    static readonly HashSet<string> FrameSkip = new() { "StartFrameOffset", "EndFrameOffset", "FirstLoopStartFrameOffset", "DeltaFrame", "TickResolution", "DisplayRate" };

    // Delete [start, end), rather than just moving later keys across the keys that remain.
    // CriWare tracks cannot RemoveSectionAt at runtime: detach fully cut sections here,
    // and clip overlapping ranges before Unreal sees them.
    static int CutSequence(UAsset asset, int start, int end)
    {
        var removed = new HashSet<int>();
        for (int i = 0; i < asset.Exports.Count; i++)
        {
            if (asset.Exports[i] is not NormalExport ex) continue;
            var range = SectionRange(ex)?.Value;
            if (range == null) continue;
            var lo = range.Value.LowerBound; var hi = range.Value.UpperBound;
            if (lo.Type != ERangeBoundTypes.Open && hi.Type != ERangeBoundTypes.Open &&
                lo.Value.Value >= start && (hi.Value.Value < end ||
                (hi.Value.Value == end && hi.Type == ERangeBoundTypes.Exclusive)))
                removed.Add(i + 1);
        }
        int n = 0;
        for (int i = 0; i < asset.Exports.Count; i++)
        {
            if (asset.Exports[i] is not NormalExport ex || removed.Contains(i + 1)) continue;
            foreach (var sections in ex.Data.OfType<ArrayPropertyData>().Where(p => p.Name.ToString().EndsWith("Sections")))
            {
                var kept = sections.Value.Where(p => p is not ObjectPropertyData obj || !removed.Contains(obj.Value.Index)).ToArray();
                n += sections.Value.Length - kept.Length;
                sections.Value = kept;
            }
            foreach (var p in ex.Data) n += CutChannelKeys(p, start, end);
            n += ShiftFrames(ex.Data, end, start - end, start);
            // The cooked evaluation data describes the original timeline.
            var signature = ex.Data.FirstOrDefault(p => p.Name.ToString() == "Signature");
            if (signature is StructPropertyData wrapper) signature = wrapper.Value.FirstOrDefault();
            if (signature is GuidPropertyData guid) guid.Value = Guid.NewGuid();
        }
        return n;
    }

    static MovieSceneFrameRangePropertyData? SectionRange(NormalExport ex)
    {
        var p = ex.Data.FirstOrDefault(p => p.Name.ToString() == "SectionRange");
        while (p is StructPropertyData st && st.Value.Count == 1) p = st.Value[0];
        return p as MovieSceneFrameRangePropertyData;
    }

    static int CutChannelKeys(PropertyData p, int start, int end)
    {
        if (p is StructPropertyData st)
        {
            // Discrete events in the deleted interval must not fire. State curves
            // retain their keys at the splice, so the final state still takes effect.
            if (st.StructType?.ToString() == "MovieSceneEventChannel")
            {
                var times = st.Value.OfType<ArrayPropertyData>().FirstOrDefault(v => v.Name.ToString() is "KeyTimes" or "Times");
                var values = st.Value.OfType<ArrayPropertyData>().FirstOrDefault(v => v.Name.ToString() is "KeyValues" or "Values");
                if (times != null && values != null)
                {
                    if (times.Value.Length > values.Value.Length) throw new InvalidDataException("Sequence key has no value");
                    // Some cooked channels retain unkeyed values after the keyed entries.
                    var unkeyed = values.Value.Skip(times.Value.Length).ToArray();
                    var keep = Enumerable.Range(0, times.Value.Length).Where(i => FrameOf(times.Value[i]) < start || FrameOf(times.Value[i]) >= end).ToArray();
                    int removed = times.Value.Length - keep.Length;
                    times.Value = keep.Select(i => times.Value[i]).ToArray();
                    values.Value = keep.Select(i => values.Value[i]).Concat(unkeyed).ToArray();
                    return removed;
                }
            }
            return st.Value.Sum(v => CutChannelKeys(v, start, end));
        }
        if (p is ArrayPropertyData arr) return arr.Value.Sum(v => CutChannelKeys(v, start, end));
        if (p is MapPropertyData map) return map.Value.Values.Sum(v => CutChannelKeys(v, start, end));
        return 0;
    }

    static int ShiftFrames(IEnumerable<PropertyData> props, int after, int delta, int? cutStart = null)
    {
        int n = 0;
        foreach (var p in props) n += ShiftFrame(p, after, delta, cutStart);
        return n;
    }

    static int ShiftFrame(PropertyData p, int after, int delta, int? cutStart = null)
    {
        var name = p.Name?.ToString() ?? "";
        if (FrameSkip.Contains(name)) return 0;
        int Move(int frame) => frame >= after ? checked(frame + delta) : cutStart.HasValue && frame > cutStart.Value ? cutStart.Value : frame;
        switch (p)
        {
            case FrameNumberPropertyData f:
                if (Move(f.Value.Value) != f.Value.Value) { f.Value = new FFrameNumber(Move(f.Value.Value)); return 1; }
                return 0;
            case MovieSceneFrameRangePropertyData r:
            {
                int n = 0; var rg = r.Value;
                if (rg.LowerBound.Type != ERangeBoundTypes.Open && Move(rg.LowerBound.Value.Value) != rg.LowerBound.Value.Value) { rg.LowerBound.Value = new FFrameNumber(Move(rg.LowerBound.Value.Value)); n++; }
                if (rg.UpperBound.Type != ERangeBoundTypes.Open && Move(rg.UpperBound.Value.Value) != rg.UpperBound.Value.Value) { rg.UpperBound.Value = new FFrameNumber(Move(rg.UpperBound.Value.Value)); n++; }
                r.Value = rg;
                return n;
            }
            case StructPropertyData st: return ShiftFrames(st.Value, after, delta, cutStart);
            case ArrayPropertyData arr: return ShiftFrames(arr.Value, after, delta, cutStart);
            case MapPropertyData m:
            {
                int n = 0;
                foreach (var v in m.Value.Values) n += ShiftFrame(v, after, delta, cutStart);
                return n;
            }
            default: return 0;
        }
    }

    static void ApplyObject(UAsset asset, List<PropertyData> props, JObject set)
    {
        foreach (var kv in set)
        {
            ApplyPath(asset, props, kv.Key, kv.Value!);
        }
    }

    // path like "ItemList[4].ItemId" or "Name"
    static void ApplyPath(UAsset asset, List<PropertyData> props, string path, JToken value)
    {
        var parts = path.Split('.', 2);
        var head = parts[0]; int? index = null;
        var br = head.IndexOf('[');
        if (br >= 0) { index = int.Parse(head[(br + 1)..^1]); head = head[..br]; }
        var prop = props.FirstOrDefault(p => p.Name.ToString() == head) ?? throw new Exception($"property '{head}' not found (have: {string.Join(", ", props.Select(p => p.Name.ToString()))})");
        if (index != null)
        {
            var arr = prop as ArrayPropertyData ?? throw new Exception($"'{head}' is not an array");
            if (index >= arr.Value.Length) throw new Exception($"'{head}[{index}]' out of range ({arr.Value.Length})");
            if (parts.Length == 2)
            {
                var elem = arr.Value[index.Value] as StructPropertyData ?? throw new Exception($"'{head}[{index}]' is not a struct");
                ApplyPath(asset, elem.Value, parts[1], value);
            }
            else arr.Value[index.Value] = Apply(asset, arr.Value[index.Value], value);
            return;
        }
        if (parts.Length == 2)
        {
            var st = prop as StructPropertyData ?? throw new Exception($"'{head}' is not a struct");
            ApplyPath(asset, st.Value, parts[1], value);
            return;
        }
        var i = props.IndexOf(prop);
        props[i] = Apply(asset, prop, value);
    }

    static PropertyData Apply(UAsset asset, PropertyData p, JToken v)
    {
        switch (p)
        {
            case IntPropertyData ip: ip.Value = v.Value<int>(); return ip;
            case Int64PropertyData i64: i64.Value = v.Value<long>(); return i64;
            case UInt32PropertyData u32: u32.Value = v.Value<uint>(); return u32;
            case FloatPropertyData fp: fp.Value = v.Value<float>(); return fp;
            case DoublePropertyData dp: dp.Value = v.Value<double>(); return dp;
            case BoolPropertyData bp: bp.Value = v.Value<bool>(); return bp;
            case EnumPropertyData en: en.Value = FName.FromString(asset, EnumForm(en.Value?.ToString(), v.Value<string>()!)); return en;
            case BytePropertyData b:
                if (b.ByteType == BytePropertyType.FName) b.EnumValue = FName.FromString(asset, EnumForm(b.EnumValue?.ToString(), v.Value<string>()!)); else b.Value = v.Value<byte>();
                return b;
            case NamePropertyData n:
                var name = v.Value<string>();
                n.Value = FName.FromString(asset, string.IsNullOrEmpty(name) ? "None" : name);
                return n;
            case StrPropertyData s: s.Value = new FString(v.Value<string>()!); return s;
            case TextPropertyData t:
                if (v.Type == JTokenType.Object && v["table"] != null)
                {
                    t.HistoryType = TextHistoryType.StringTableEntry;
                    t.TableId = FName.FromString(asset, v.Value<string>("table")!);
                    t.Value = new FString(v.Value<string>("key")!);
                    t.CultureInvariantString = null;
                }
                else
                {
                    var text = v.Type == JTokenType.Object ? (v.Value<string>("text") ?? v.Value<string>("en") ?? "") : v.Value<string>() ?? "";
                    t.HistoryType = TextHistoryType.None;
                    t.TableId = null; t.Namespace = null; t.Value = null;
                    t.CultureInvariantString = new FString(text);
                }
                return t;
            case SoftObjectPropertyData so:
                so.Value = ParseSoftPath(asset, v.Value<string>()!); return so;
            case SoftObjectPathPropertyData sop:
                sop.Value = ParseSoftPath(asset, v.Value<string>()!); return sop;
            case VectorPropertyData vec:
                vec.Value = new FVector(v.Value<double>("x"), v.Value<double>("y"), v.Value<double>("z")); return vec;
            case Vector4PropertyData v4:
                // This UAssetAPI build's four-argument constructor leaves zeroes.
                v4.Value = new FVector4 { X = Num(v, "X"), Y = Num(v, "Y"), Z = Num(v, "Z"), W = Num(v, "W") }; return v4;
            case Vector4fPropertyData v4f:
                v4f.Value = new FVector4f { X = Num(v, "X"), Y = Num(v, "Y"), Z = Num(v, "Z"), W = Num(v, "W") }; return v4f;
            case GuidPropertyData gp:
            {
                // "new" = a fresh GUID (used to invalidate a sequence's compiled data / a track's evaluation field)
                var gs = v.Value<string>() ?? "new";
                gp.Value = gs == "new" ? Guid.NewGuid() : Guid.Parse(gs); return gp;
            }
            case Vector2fPropertyData v2f:
                v2f.Value = new FVector2f(Num(v, "X"), Num(v, "Y")); return v2f;
            case Vector2DPropertyData v2d:
                v2d.Value = new FVector2D(Num(v, "X"), Num(v, "Y")); return v2d;
            case ObjectPropertyData op:
            {
                if (v.Type == JTokenType.Null) { op.Value = new FPackageIndex(0); return op; }   // null = no object
                // "/Game/Pkg/Name" -> existing or new import pair (package + object, class copied from a similar import)
                var path = v.Value<string>()!;
                var like = op.Value.IsImport() ? op.Value.ToImport(asset).ClassName.ToString() : "Texture2D";
                op.Value = FindOrAddImport(asset, path, like); return op;
            }
            case ArrayPropertyData arr:
            {
                var items = v as JArray ?? throw new Exception($"array '{p.Name}' needs a JSON array");
                if (items.Count == 0)
                {
                    arr.Value = Array.Empty<PropertyData>();
                    return arr;
                }
                var template = arr.Value.Length > 0 ? arr.Value[0] : MakeElement(asset, arr);
                var list = new List<PropertyData>();
                foreach (var item in items)
                {
                    var e = DeepClone(template);
                    list.Add(Apply(asset, e, item));
                }
                arr.Value = list.ToArray();
                return arr;
            }
            case StructPropertyData st:
            {
                if (v is JObject o)
                {
                    // vector-like struct wrapped in a struct (UAssetAPI: StructPropertyData whose single child is VectorPropertyData with same name)
                    if (st.Value.Count == 1 && st.Value[0] is VectorPropertyData && o["x"] != null) { st.Value[0] = Apply(asset, st.Value[0], v); return st; }
                    // same for 2D vectors (FDeprecateSlateVector2D / FVector2f, e.g. a brush's ImageSize): {"X":64,"Y":64}
                    if (st.Value.Count == 1 && st.Value[0] is not StructPropertyData && (o["X"] ?? o["x"]) != null && HasXY(st.Value[0])) { st.Value[0] = Apply(asset, st.Value[0], v); return st; }
                    ApplyObject(asset, st.Value, o);
                }
                else if (v.Type == JTokenType.String && st.Value.Count == 1 && st.Value[0] is GuidPropertyData) st.Value[0] = Apply(asset, st.Value[0], v);   // Guid struct wrapper
                else throw new Exception($"struct '{p.Name}' needs a JSON object");
                return st;
            }
            case MapPropertyData m:
            {
                var o = v as JObject ?? throw new Exception($"map '{p.Name}' needs a JSON object");
                foreach (var kv in o)
                {
                    PropertyData? key = null;
                    foreach (var k in m.Value.Keys) { if (KeyString(k) == kv.Key) { key = k; break; } }
                    if (key == null)
                    {
                        // Retain the cooked map's key/value types when extending
                        // sparse equipment stat maps. Empty maps have no schema
                        // template and remain explicitly unsupported.
                        var templateKey = m.Value.Keys.FirstOrDefault()
                            ?? throw new Exception($"map '{p.Name}': cannot add a key without a type template");
                        if (templateKey is not EnumPropertyData)
                            throw new Exception($"map '{p.Name}': adding keys is supported only for enum maps");
                        key = Apply(asset, DeepClone(templateKey), new JValue(kv.Key));
                        m.Value.Add(key, DeepClone(m.Value[templateKey]));
                    }
                    m.Value[key] = Apply(asset, m.Value[key], kv.Value!);
                }
                return m;
            }
            default:
                // any 2D vector flavour (Vector2 / Vector2f / Vector2D property data): {"X":..,"Y":..}
                if (v is JObject o2 && (o2["X"] ?? o2["x"]) != null && TrySetXY(p, Num(v, "X"), Num(v, "Y"))) return p;
                throw new Exception($"unsupported property type {p.GetType().Name} for '{p.Name}'");
        }
    }

    // find (or add) the import pair for "/Game/Pkg/Name"; class taken from an existing import with the same class as `like` (Texture2D by default)
    // class -> script package, for imports whose class the package does not reference yet
    static readonly Dictionary<string, string> KnownClassPackages = new()
    {
        ["Ss6Project"] = "/Script/SpriteStudio6", ["NiagaraSystem"] = "/Script/Niagara", ["Texture2D"] = "/Script/Engine", ["World"] = "/Script/Engine",
        ["MaterialInstanceConstant"] = "/Script/Engine", ["Material"] = "/Script/Engine", ["LevelSequence"] = "/Script/LevelSequence", ["SoundAtomCue"] = "/Script/CriWareRuntime",
        ["DataTable"] = "/Script/Engine", ["StringTable"] = "/Script/Engine", ["PaperSprite"] = "/Script/Paper2D",
    };

    public static FPackageIndex FindOrAddImport(UAsset asset, string path, string likeClass = "Texture2D")
    {
        var dot = path.IndexOf('.', path.LastIndexOf('/') + 1);
        var pkgName = dot >= 0 ? path[..dot] : path;
        var objName = dot >= 0 ? path[(dot + 1)..] : path[(path.LastIndexOf('/') + 1)..];
        for (int i = 0; i < asset.Imports.Count; i++)
        {
            var im = asset.Imports[i];
            if (im.ObjectName.ToString() == objName && im.OuterIndex.IsImport() && asset.Imports[-im.OuterIndex.Index - 1].ObjectName.ToString() == pkgName)
                return FPackageIndex.FromImport(i);
        }
        var template = asset.Imports.FirstOrDefault(im => im.ClassName.ToString() == likeClass);
        string classPackage, className;
        if (template != null) { classPackage = template.ClassPackage.ToString(); className = template.ClassName.ToString(); }
        else if (KnownClassPackages.TryGetValue(likeClass, out var kp)) { classPackage = kp; className = likeClass; }
        else throw new Exception($"no existing '{likeClass}' import to copy class info from (and it is not a known class)");
        var pkgTemplate = asset.Imports.First(im => im.ClassName.ToString() == "Package");
        var pkg = new Import(pkgTemplate.ClassPackage.ToString(), "Package", new FPackageIndex(0), pkgName, false, asset);
        asset.Imports.Add(pkg); int pkgIdx = asset.Imports.Count - 1;
        var obj = new Import(classPackage, className, FPackageIndex.FromImport(pkgIdx), objName, false, asset);
        asset.Imports.Add(obj); var idx = FPackageIndex.FromImport(asset.Imports.Count - 1);
        // cooked exports list the objects that must exist before they are serialized (CreateBeforeSerialization); add the new import there
        foreach (var ex in asset.Exports)
        {
            ex.CreateBeforeSerializationDependencies ??= new List<FPackageIndex>();
            if (!ex.CreateBeforeSerializationDependencies.Contains(idx)) ex.CreateBeforeSerializationDependencies.Add(idx);
        }
        Console.WriteLine($"  + import {pkgName} / {objName} ({className})");
        return idx;
    }

    // "/Game/Pkg/Name" | "/Game/Pkg/Name.Object" | "...:SubPath"  ->  FSoftObjectPath
    static float Num(JToken v, string key) => (v[key] ?? v[key.ToLowerInvariant()])?.Value<float>() ?? 0f;

    static System.Reflection.PropertyInfo? ValueProp(PropertyData p) => p.GetType().GetProperty("Value");
    static bool HasXY(PropertyData p)
    {
        var t = ValueProp(p)?.PropertyType; if (t == null || !t.IsValueType) return false;
        return (t.GetField("X") ?? (System.Reflection.MemberInfo?)t.GetProperty("X")) != null && (t.GetField("Y") ?? (System.Reflection.MemberInfo?)t.GetProperty("Y")) != null;
    }
    static bool TrySetXY(PropertyData p, float x, float y)
    {
        if (!HasXY(p)) return false;
        var vp = ValueProp(p)!; var t = vp.PropertyType;
        object boxed = vp.GetValue(p) ?? Activator.CreateInstance(t)!;
        void Set(string n, float val)
        {
            var f = t.GetField(n); if (f != null) { f.SetValue(boxed, Convert.ChangeType(val, f.FieldType)); return; }
            var pr = t.GetProperty(n)!; pr.SetValue(boxed, Convert.ChangeType(val, pr.PropertyType));
        }
        Set("X", x); Set("Y", y);
        vp.SetValue(p, boxed);
        return true;
    }

    // UAssetAPI's Clone() copies a struct's property list but shares array elements (and map entries) with the
    // original, so patching "animationAssetList[0].Ss6Project" on a cloned row also rewrote the donor row and every
    // earlier clone (all Lightning-based Visions ended up with the last clone's sprites). Clone the whole tree.
    static PropertyData DeepClone(PropertyData p)
    {
        var c = (PropertyData)p.Clone();
        switch (c)
        {
            case ArrayPropertyData a: a.Value = a.Value.Select(DeepClone).ToArray(); break;   // SetPropertyData derives from ArrayPropertyData
            case StructPropertyData st: st.Value = st.Value.Select(DeepClone).ToList(); break;
            case MapPropertyData m:
            {
                var nm = new TMap<PropertyData, PropertyData>();
                foreach (var kv in m.Value) nm.Add(DeepClone(kv.Key), DeepClone(kv.Value));
                m.Value = nm; break;
            }
        }
        return c;
    }

    static FSoftObjectPath ParseSoftPath(UAsset asset, string path)
    {
        if (string.IsNullOrEmpty(path) || path == "None") return new FSoftObjectPath(FName.FromString(asset, "None"), FName.FromString(asset, "None"), new FString(""));
        var sub = "";
        var colon = path.IndexOf(':'); if (colon >= 0) { sub = path[(colon + 1)..]; path = path[..colon]; }
        var lastSlash = path.LastIndexOf('/');
        var dot = path.IndexOf('.', lastSlash + 1);
        string pkg, assetName;
        if (dot >= 0) { pkg = path[..dot]; assetName = path[(dot + 1)..]; }
        else { pkg = path; assetName = path[(lastSlash + 1)..]; }
        return new FSoftObjectPath(FName.FromString(asset, pkg), FName.FromString(asset, assetName), new FString(sub));
    }

    // match the form the existing value uses: "eEnum::Value" (EnumProperty) or "Value" (byte-backed enum)
    static string EnumForm(string? current, string wanted)
    {
        current ??= "";
        if (current.Contains("::")) return wanted.Contains("::") ? wanted : current.Split("::")[0] + "::" + wanted;
        return wanted.Contains("::") ? wanted.Split("::")[1] : wanted;
    }

    static string KeyString(PropertyData k) => k switch
    {
        EnumPropertyData e => e.Value?.ToString() ?? "",
        NamePropertyData n => n.Value?.ToString() ?? "",
        IntPropertyData i => i.Value.ToString(),
        StrPropertyData s => s.Value?.ToString() ?? "",
        _ => k.ToString() ?? ""
    };

    static PropertyData MakeElement(UAsset asset, ArrayPropertyData arr)
    {
        var type = arr.ArrayType?.ToString() ?? "";
        var name = FName.FromString(asset, "0");
        return type switch
        {
            "IntProperty" => new IntPropertyData(name),
            "FloatProperty" => new FloatPropertyData(name),
            "BoolProperty" => new BoolPropertyData(name),
            "NameProperty" => new NamePropertyData(name),
            "StrProperty" => new StrPropertyData(name),
            "EnumProperty" => new EnumPropertyData(name),
            _ => throw new Exception($"cannot create elements for empty array of type '{type}' ('{arr.Name}'); clone from a row that has at least one element")
        };
    }
}
