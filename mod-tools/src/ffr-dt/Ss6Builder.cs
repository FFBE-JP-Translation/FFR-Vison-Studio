using System.Buffers.Binary;
using System.Text;
using Newtonsoft.Json.Linq;
using UAssetAPI;
using UAssetAPI.UnrealTypes;
using UAssetAPI.Unversioned;
using UAssetAPI.ExportTypes;
using UAssetAPI.PropertyTypes.Objects;
using UAssetAPI.PropertyTypes.Structs;

// Builds cooked SpriteStudio6 project + texture assets for FINAL FANTASY RESONANCE by cloning a donor asset and
// rewriting its content from a spec produced by tools/ffbe2ss6/build_sprites.py.
//
//   ffr-dt make-ss6     <donor.uasset> <spec.json> <out.uasset> <oldPkg> <newPkg> [old=new ...]
//   ffr-dt make-texture <donor.uasset> <payload.bin> <width> <height> <out.uasset> <oldPkg> <newPkg> [old=new ...]
//
// The SS6 plugin serializes every keyframe value payload after the property block (USs6Project::Serialize ->
// FSsAnimePack/FSsAnimation/FSsPartAnime/FSsAttribute/FSsKeyframe::Serialize -> FSsValue::Serialize), so the
// export's Extras are regenerated here in the same order (see extracted/ss6plugin/SsValue.cpp).
static class Ss6Builder
{
    static PropertyData F(List<PropertyData> l, string n) => l.FirstOrDefault(p => p.Name.ToString() == n) ?? throw new Exception($"property '{n}' not found (have {string.Join(",", l.Select(p => p.Name.ToString()))})");
    static StructPropertyData S(List<PropertyData> l, string n) => (StructPropertyData)F(l, n);
    static ArrayPropertyData A(List<PropertyData> l, string n) => (ArrayPropertyData)F(l, n);

    static void SetVec2(PropertyData p, float x, float y)
    {
        if (p is Vector2fPropertyData v) { v.Value = new FVector2f(x, y); return; }
        if (p is StructPropertyData s && s.Value.Count == 1 && s.Value[0] is Vector2fPropertyData v2) { v2.Value = new FVector2f(x, y); return; }
        if (p is StructPropertyData s2)
        {
            foreach (var c in s2.Value) { if (c is FloatPropertyData f) { if (c.Name.ToString() == "X") f.Value = x; else if (c.Name.ToString() == "Y") f.Value = y; } }
            return;
        }
        throw new Exception($"cannot set vector2 on {p.GetType().Name} '{p.Name}'");
    }

    static void Rename(UAsset asset, string oldPkg, string newPkg, List<(string, string)> renames)
    {
        var all = new List<(string, string)> { (oldPkg, newPkg) }; all.AddRange(renames);
        var names = asset.GetNameMapIndexList();
        for (int i = 0; i < names.Count; i++)
        {
            var s = names[i].Value; var s2 = s;
            foreach (var (a, b) in all) s2 = s2.Replace(a, b);
            if (s2 != s) asset.SetNameReference(i, new FString(s2));
        }
        if (asset.FolderName != null) { var f = asset.FolderName.Value; foreach (var (a, b) in all) f = f.Replace(a, b); asset.FolderName = new FString(f); }
    }

    static List<(string, string)> ParseRenames(IEnumerable<string> args) => args.Select(x => x.Split('=', 2)).Where(a => a.Length == 2).Select(a => (a[0], a[1])).ToList();

    static void SetNames(UAsset asset, ArrayPropertyData array, IEnumerable<string> names)
    {
        var template = (NamePropertyData)array.Value[0];
        array.Value = names.Select((name, index) =>
        {
            var item = (NamePropertyData)template.Clone();
            item.Name = FName.FromString(asset, index.ToString());
            item.Value = FName.FromString(asset, name);
            return (PropertyData)item;
        }).ToArray();
    }

    // SS6 1.6.20 GetSsPartsColorValue reads typed nested FSsValues. In the
    // unversioned compact header below only Type is nonzero; the three numeric
    // conversion caches remain zero. Int/Float/Color accessors read their own
    // payloads, so no implicit type conversion is required.
    static void WritePartsColor(BinaryWriter writer, UAsset asset, JToken value)
    {
        if (value is not JObject color) throw new InvalidDataException("PartsColor requires an object");
        if (color.Value<string>("target") != "Whole") throw new InvalidDataException("PartsColor currently supports target Whole only");
        var blend = color.Value<string>("blendType");
        int blendIndex = blend switch { "Mix" => 0, "Mul" => 1, "Add" => 2, "Sub" => 3, _ => throw new InvalidDataException("invalid PartsColor blendType") };
        if (color["rgba"] is not JArray rgba || rgba.Count != 4 || rgba.Any(v => v.Type != JTokenType.Integer || v.Value<long>() < 0 || v.Value<long>() > 255))
            throw new InvalidDataException("PartsColor rgba requires four integer bytes");
        float rate = color.Value<float?>("rate") ?? 1f;
        if (!float.IsFinite(rate) || rate < 0f || rate > 1f) throw new InvalidDataException("PartsColor rate must be between zero and one");
        void Header(string name, byte type)
        {
            FName.FromString(asset, name);
            writer.Write(asset.SearchNameReference(new FString(name)));
            writer.Write(0);
            writer.Write(new byte[] { 0x80, 0x09, 0x0e, type });
        }
        writer.Write(3);
        Header("target", 2); writer.Write(0); // SsColorBlendTarget::Whole
        Header("blendType", 2); writer.Write(blendIndex);
        Header("color", 5); writer.Write(2); // HashType
        Header("rgba", 8); // SsColor is SsTColor<uint32>: four UInt32 channels, NOT four bytes.
        foreach (var component in rgba) writer.Write(component.Value<uint>());
        Header("rate", 3); writer.Write(rate);
    }

    // ------------------------------------------------------------------ make-ss6
    public static int MakeSs6(List<string> pos, Usmap? mappings)
    {
        var donor = pos[1]; var specPath = pos[2]; var outPath = pos[3]; var oldPkg = pos[4]; var newPkg = pos[5];
        var spec = JObject.Parse(File.ReadAllText(specPath, Encoding.UTF8));
        float runtimeScale = 1f;
        if (spec["runtimeScale"] is JToken scaleValue)
        {
            if (scaleValue.Type != JTokenType.Integer && scaleValue.Type != JTokenType.Float)
                throw new InvalidDataException("runtimeScale must be a finite positive number");
            runtimeScale = scaleValue.Value<float>();
            if (!float.IsFinite(runtimeScale) || runtimeScale <= 0f)
                throw new InvalidDataException("runtimeScale must be a finite positive number");
        }
        float viewportStretchX = 1f, viewportCenterX = 0f;
        if (spec["runtimeViewport"] is JToken viewportValue)
        {
            if (viewportValue is not JObject viewport || viewport["stretchX"] is not JToken stretchValue
                || (stretchValue.Type != JTokenType.Integer && stretchValue.Type != JTokenType.Float))
                throw new InvalidDataException("runtimeViewport.stretchX must be a finite positive number");
            viewportStretchX = stretchValue.Value<float>();
            if (!float.IsFinite(viewportStretchX) || viewportStretchX <= 0f)
                throw new InvalidDataException("runtimeViewport.stretchX must be a finite positive number");
            if (viewport["center"] is not JArray center || center.Count != 2
                || center.Any(v => (v.Type != JTokenType.Integer && v.Type != JTokenType.Float) || !float.IsFinite(v.Value<float>())))
                throw new InvalidDataException("runtimeViewport.center requires two finite coordinates");
            viewportCenterX = center[0].Value<float>();
        }
        // Root coordinates stay in the spec's SS6 units. A horizontal viewport
        // fit is applied after the scalar host size, around the authored center.
        float viewportOffsetX = (runtimeScale * viewportCenterX) * (1f - viewportStretchX);
        float viewportScaleX = runtimeScale * viewportStretchX;
        if (!float.IsFinite(viewportOffsetX) || !float.IsFinite(viewportScaleX) || viewportScaleX <= 0f)
            throw new InvalidDataException("runtimeViewport produced a non-finite or non-positive root transform");
        var asset = new UAsset(donor, EngineVersion.VER_UE5_6, mappings);
        Rename(asset, oldPkg, newPkg, ParseRenames(pos.Skip(6)));
        var ex = asset.Exports.OfType<NormalExport>().First();
        var data = ex.Data;

        // ---- cellmaps ----
        // Older specs describe one atlas at the top level. Paged specs retain
        // those fields for compatibility and put every atlas in cellmaps.
        var mapSpecs = spec["cellmaps"] as JArray ?? new JArray(spec.DeepClone());
        if (mapSpecs.Count == 0) throw new InvalidDataException("cellmaps must contain at least one map");
        var mapArray = A(data, "CellmapList");
        var mapTemplate = (StructPropertyData)mapArray.Value[0];
        var cellTemplate = (StructPropertyData)A(mapTemplate.Value, "Cells").Value[0];
        var newMaps = new List<PropertyData>();
        var mapNames = new List<string>();
        var cellMaps = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        for (int mapIndex = 0; mapIndex < mapSpecs.Count; mapIndex++)
        {
            var mapSpec = (JObject)mapSpecs[mapIndex]!;
            var cm = (StructPropertyData)mapTemplate.Clone();
            var suffix = mapIndex == 0 ? "" : $"_{mapIndex}";
            var mapName = mapSpec.Value<string>("cellmapName") ?? ((NamePropertyData)F(mapTemplate.Value, "CellMapName")).Value.ToString() + suffix;
            var fileName = mapName + ".ssce";
            if (mapNames.Contains(fileName, StringComparer.OrdinalIgnoreCase)) throw new InvalidDataException($"duplicate cellmap name '{mapName}'");
            mapNames.Add(fileName);
            foreach (var field in new[] { "Filename", "FileName", "CellMapNameEx" })
                if (cm.Value.FirstOrDefault(p => p.Name.ToString() == field) is NamePropertyData np) np.Value = FName.FromString(asset, fileName);
            ((NamePropertyData)F(cm.Value, "CellMapName")).Value = FName.FromString(asset, mapName);
            ((StrPropertyData)F(cm.Value, "ImagePath")).Value = new FString(mapSpec.Value<string>("imagePath") ?? "");
            ((ObjectPropertyData)F(cm.Value, "Texture")).Value = Patch.FindOrAddImport(asset, newPkg + "_tex" + suffix);
            var W = mapSpec["pixelSize"]![0]!.Value<float>(); var H = mapSpec["pixelSize"]![1]!.Value<float>();
            if (!float.IsFinite(W) || !float.IsFinite(H) || W <= 0 || H <= 0) throw new InvalidDataException($"cellmap '{mapName}' has invalid pixelSize");
            SetVec2(F(cm.Value, "PixelSize"), W, H);
            var newCells = new List<PropertyData>();
            foreach (var c in mapSpec["cells"] as JArray ?? new JArray())
            {
                var cellName = c.Value<string>("name")!;
                if (string.IsNullOrWhiteSpace(cellName) || !cellMaps.TryAdd(cellName, mapIndex)) throw new InvalidDataException($"cell names must be globally unique: '{cellName}'");
                var s = (StructPropertyData)cellTemplate.Clone();
                ((NamePropertyData)F(s.Value, "CellName")).Value = FName.FromString(asset, cellName);
                SetVec2(F(s.Value, "Pos"), c["pos"]![0]!.Value<float>(), c["pos"]![1]!.Value<float>());
                SetVec2(F(s.Value, "Size"), c["size"]![0]!.Value<float>(), c["size"]![1]!.Value<float>());
                SetVec2(F(s.Value, "Pivot"), c["pivot"]![0]!.Value<float>(), c["pivot"]![1]!.Value<float>());
                if (s.Value.FirstOrDefault(p => p.Name.ToString() == "ParentSize") is PropertyData parentSize) SetVec2(parentSize, W, H);
                foreach (var n in new[] { "Rotated", "IsMesh" }) if (s.Value.FirstOrDefault(p => p.Name.ToString() == n) is BoolPropertyData b) b.Value = false;
                foreach (var n in new[] { "InnerPoint", "OuterPoint", "MeshPointList", "MeshTriList" }) if (s.Value.FirstOrDefault(p => p.Name.ToString() == n) is ArrayPropertyData arr) arr.Value = Array.Empty<PropertyData>();
                newCells.Add(s);
            }
            A(cm.Value, "Cells").Value = newCells.ToArray();
            newMaps.Add(cm);
        }
        mapArray.Value = newMaps.ToArray();
        SetNames(asset, A(data, "CellmapNames"), mapNames);

        // ---- animations ----
        var pack = (StructPropertyData)A(data, "AnimeList").Value[0];
        SetNames(asset, A(pack.Value, "CellmapNames"), mapNames);
        if (spec.Value<string>("animePackName") is string packName)
        {
            ((NamePropertyData)F(pack.Value, "AnimePackName")).Value = FName.FromString(asset, packName);
            SetNames(asset, A(data, "AnimepackNames"), new[] { packName + ".ssae" });
        }
        // ---- model (optional): "model": {"parts": [{"name": "fx_0", "parent": 0, "type": "Normal", "blend": "Add", "inherit": "Parent"}, ...]}
        // rebuilds the part list (index 0 must be the root Null part) so effect projects can have their own layers and blend modes
        if (spec["model"] is JObject modelSpec && modelSpec["parts"] is JArray partSpecs && partSpecs.Count > 0)
        {
            var partList = A(S(pack.Value, "Model").Value, "PartList");
            var donorParts = partList.Value.Cast<StructPropertyData>().ToList();
            StructPropertyData TemplateFor(string type) =>
                donorParts.FirstOrDefault(dp => ((EnumPropertyData)F(dp.Value, "Type")).Value.ToString().EndsWith(type)) ?? donorParts[0];
            var newParts = new List<PropertyData>();
            int idx = 0;
            foreach (var ps in partSpecs)
            {
                var type = ps.Value<string>("type") ?? (idx == 0 ? "Null" : "Normal");
                var np = (StructPropertyData)TemplateFor(type).Clone();
                ((NamePropertyData)F(np.Value, "PartName")).Value = FName.FromString(asset, ps.Value<string>("name")!);
                ((IntPropertyData)F(np.Value, "ArrayIndex")).Value = idx;
                ((IntPropertyData)F(np.Value, "ParentIndex")).Value = ps.Value<int?>("parent") ?? (idx == 0 ? -1 : 0);
                var tp = (EnumPropertyData)F(np.Value, "Type"); tp.Value = FName.FromString(asset, EnumLike2(tp.Value.ToString(), type));
                var bl = (EnumPropertyData)F(np.Value, "AlphaBlendType"); bl.Value = FName.FromString(asset, EnumLike2(bl.Value.ToString(), ps.Value<string>("blend") ?? "Mix"));
                var ih = (EnumPropertyData)F(np.Value, "InheritType"); ih.Value = FName.FromString(asset, EnumLike2(ih.Value.ToString(), ps.Value<string>("inherit") ?? (idx == 0 ? "Self" : "Parent")));
                newParts.Add(np); idx++;
            }
            partList.Value = newParts.ToArray();
            Console.WriteLine($"make-ss6: model rebuilt with {newParts.Count} parts");
        }
        // Optional host size adapter. Keep source cells and child geometry
        // untouched; SS6 parent inheritance applies this one scale at playback.
        string? runtimeRoot = null;
        if (runtimeScale != 1f || viewportStretchX != 1f)
        {
            var roots = A(S(pack.Value, "Model").Value, "PartList").Value.Cast<StructPropertyData>()
                .Where(p => ((IntPropertyData)F(p.Value, "ParentIndex")).Value == -1).ToList();
            if (roots.Count != 1) throw new InvalidDataException("runtimeScale requires one model root part");
            runtimeRoot = ((NamePropertyData)F(roots[0].Value, "PartName")).Value.ToString();
            var animations = (spec["animations"] as JArray ?? new JArray()).ToList();
            bool HasRootAxis(JToken animation, string axis)
            {
                var rootKeys = (animation["parts"] as JObject)?.Properties()
                    .FirstOrDefault(p => string.Equals(p.Name, runtimeRoot, StringComparison.OrdinalIgnoreCase))?.Value as JObject;
                return rootKeys?[axis] is JArray axisKeys && axisKeys.Count > 0;
            }
            var setups = animations.Where(a => a.Value<bool?>("isSetup") == true).ToList();
            if (setups.Count > 1) throw new InvalidDataException("runtimeScale requires at most one Setup animation");
            var actions = animations.Where(a => a.Value<bool?>("isSetup") != true).ToList();
            // SS6 initializes each frame from Setup, then applies action keys.
            // An absent action axis therefore inherits the explicit Setup key.
            var requiredAxes = viewportOffsetX != 0f ? new[] { "Sclx", "Scly", "Posx" } : new[] { "Sclx", "Scly" };
            foreach (var animation in actions.Count > 0 ? actions : setups)
                foreach (var axis in requiredAxes)
                    if (!HasRootAxis(animation, axis) && !setups.Any(a => HasRootAxis(a, axis)))
                        throw new InvalidDataException($"runtimeScale/runtimeViewport requires {runtimeRoot}.{axis} keys in animation '{animation.Value<string>("name")}' or Setup");
        }
        var anims = A(pack.Value, "AnimeList");
        var donorAnims = anims.Value.Cast<StructPropertyData>().ToList();
        var animTemplate = donorAnims.First(a => !((BoolPropertyData)F(a.Value, "IsSetup")).Value);
        StructPropertyData? partTemplate = null; var attrTemplates = new Dictionary<string, StructPropertyData>(); var keyTemplates = new Dictionary<string, StructPropertyData>();
        foreach (var a in donorAnims)
            foreach (var pa in A(a.Value, "PartAnimes").Value.Cast<StructPropertyData>())
            {
                partTemplate ??= pa;
                foreach (var at in A(pa.Value, "Attributes").Value.Cast<StructPropertyData>())
                {
                    var tag = ((EnumPropertyData)F(at.Value, "Tag")).Value.ToString(); var kind = tag.Contains("::") ? tag.Split("::")[1] : tag;
                    if (!attrTemplates.ContainsKey(kind)) attrTemplates[kind] = at;
                    var keys = A(at.Value, "Key").Value;
                    if (keys.Length > 0)
                    {
                        var vt = ((EnumPropertyData)F(((StructPropertyData)F(((StructPropertyData)keys[0]).Value, "Value")).Value, "Type")).Value.ToString();
                        var vk = vt.Contains("::") ? vt.Split("::")[1] : vt;
                        if (!keyTemplates.ContainsKey(vk)) keyTemplates[vk] = (StructPropertyData)keys[0];
                    }
                }
            }
        if (partTemplate == null || !keyTemplates.ContainsKey("HashType") || !keyTemplates.ContainsKey("FloatType")) throw new Exception("donor lacks templates (part / hash key / float key)");
        string EnumLike(string current, string wanted) => current.Contains("::") ? (wanted.Contains("::") ? wanted : current.Split("::")[0] + "::" + wanted) : (wanted.Contains("::") ? wanted.Split("::")[1] : wanted);

        var newAnims = new List<PropertyData>();
        var tail = new MemoryStream(); var bw = new BinaryWriter(tail);
        var nameMapId = FName.FromString(asset, "mapId"); var nameName = FName.FromString(asset, "name");
        int idxMapId = asset.SearchNameReference(new FString("mapId")); int idxName = asset.SearchNameReference(new FString("name"));
        int keyCount = 0;
        foreach (var an in spec["animations"] as JArray ?? new JArray())
        {
            var a = (StructPropertyData)animTemplate.Clone();
            ((NamePropertyData)F(a.Value, "AnimationName")).Value = FName.FromString(asset, an.Value<string>("name")!);
            ((BoolPropertyData)F(a.Value, "IsSetup")).Value = an.Value<bool?>("isSetup") ?? false;
            var st = S(a.Value, "Settings");
            // Effect specs preserve native draw order through part indices.
            // SS6 Z sorting reverses equal-Z indices; Priority keeps them in
            // ascending order. Older character specs retain the donor mode.
            if (an.Value<string>("sortMode") is string sortMode)
            {
                if (sortMode != "Priority" && sortMode != "Z") throw new InvalidDataException($"invalid animation sortMode '{sortMode}'");
                var sort = (EnumPropertyData)F(st.Value, "SortMode");
                sort.Value = FName.FromString(asset, EnumLike(sort.Value.ToString(), sortMode));
            }
            ((IntPropertyData)F(st.Value, "Fps")).Value = an.Value<int?>("fps") ?? 60;
            int fc = an.Value<int?>("frameCount") ?? 1;
            ((IntPropertyData)F(st.Value, "FrameCount")).Value = fc;
            ((IntPropertyData)F(st.Value, "StartFrame")).Value = 0;
            ((IntPropertyData)F(st.Value, "EndFrame")).Value = Math.Max(0, fc - 1);
            SetVec2(F(st.Value, "CanvasSize"), an["canvas"]![0]!.Value<float>(), an["canvas"]![1]!.Value<float>());
            SetVec2(F(st.Value, "Pivot"), an["pivot"]![0]!.Value<float>(), an["pivot"]![1]!.Value<float>());
            A(a.Value, "Labels").Value = Array.Empty<PropertyData>();
            var parts = new List<PropertyData>();
            foreach (var kv in an["parts"] as JObject ?? new JObject())
            {
                var pa = (StructPropertyData)partTemplate.Clone();
                ((NamePropertyData)F(pa.Value, "PartName")).Value = FName.FromString(asset, kv.Key);
                var attrs = new List<PropertyData>();
                foreach (var akv in (JObject)kv.Value!)
                {
                    var kind = akv.Key;
                    if (!attrTemplates.TryGetValue(kind, out var atTemplate)) atTemplate = attrTemplates["Posx"];
                    var at = (StructPropertyData)atTemplate.Clone();
                    var tagProp = (EnumPropertyData)F(at.Value, "Tag");
                    tagProp.Value = FName.FromString(asset, EnumLike(tagProp.Value.ToString(), kind));
                    var keys = new List<PropertyData>();
                    foreach (var k in (JArray)akv.Value!)
                    {
                        bool isCell = kind == "Cell";
                        bool isPartsColor = kind == "PartsColor";
                        bool isHash = isCell || isPartsColor;
                        var key = (StructPropertyData)keyTemplates[isHash ? "HashType" : "FloatType"].Clone();
                        ((IntPropertyData)F(key.Value, "Time")).Value = k[0]!.Value<int>();
                        var ip = (EnumPropertyData)F(key.Value, "IpType"); ip.Value = FName.FromString(asset, EnumLike(ip.Value.ToString(), "None"));
                        var val = S(key.Value, "Value");
                        var typeProp = (EnumPropertyData)F(val.Value, "Type");
                        typeProp.Value = FName.FromString(asset, EnumLike(typeProp.Value.ToString(), isHash ? "HashType" : "FloatType"));
                        var itmp = (IntPropertyData)F(val.Value, "Int_temp"); var ftmp = (FloatPropertyData)F(val.Value, "Float_temp"); var btmp = (BoolPropertyData)F(val.Value, "Bool_temp");
                        if (isPartsColor)
                        {
                            itmp.Value = 0; ftmp.Value = 0f; btmp.Value = false;
                            WritePartsColor(bw, asset, k[1]!);
                        }
                        else if (isCell)
                        {
                            itmp.Value = 0; ftmp.Value = 0f; btmp.Value = false;
                            var cellName = k[1]!.Value<string>()!;
                            if (!cellMaps.TryGetValue(cellName, out int mapIndex)) throw new InvalidDataException($"Cell key references unknown cell '{cellName}'");
                            // GetSsRefCell calls FSsValue::get<int>(). A FloatType
                            // returns the separately serialized Int_temp, which
                            // this compact header leaves zero: a float payload
                            // of 1 would still select map 0. Serialize IntType.
                            // tail: NumHash=2, [FName mapId][block][int32 map index], [FName name][block][FString]
                            bw.Write(2);
                            bw.Write(idxMapId); bw.Write(0); bw.Write(new byte[] { 0x80, 0x09, 0x0e, 0x02 }); bw.Write(mapIndex);
                            bw.Write(idxName); bw.Write(0); bw.Write(new byte[] { 0x80, 0x09, 0x0e, 0x01 });
                            var bytes = Encoding.ASCII.GetBytes(cellName); bw.Write(bytes.Length + 1); bw.Write(bytes); bw.Write((byte)0);
                        }
                        else
                        {
                            float v = k[1]!.Value<float>();
                            if (runtimeRoot != null && string.Equals(kv.Key, runtimeRoot, StringComparison.OrdinalIgnoreCase)
                                && (kind == "Sclx" || kind == "Scly" || (kind == "Posx" && viewportOffsetX != 0f)))
                            {
                                if (kind == "Posx") v += viewportOffsetX;
                                else
                                {
                                    v *= runtimeScale;
                                    if (kind == "Sclx") v *= viewportStretchX;
                                }
                                if (!float.IsFinite(v)) throw new InvalidDataException("runtimeScale/runtimeViewport produced a non-finite root transform key");
                            }
                            itmp.Value = (int)v; ftmp.Value = 0f;
                            btmp.Value = BitConverter.SingleToInt32Bits(v) > 0;   // plugin: Bool_temp = _Int > 0 (union int view of the float)
                            bw.Write(v);
                        }
                        keys.Add(key); keyCount++;
                    }
                    A(at.Value, "Key").Value = keys.ToArray();
                    attrs.Add(at);
                }
                A(pa.Value, "Attributes").Value = attrs.ToArray();
                parts.Add(pa);
            }
            A(a.Value, "PartAnimes").Value = parts.ToArray();
            newAnims.Add(a);
        }
        anims.Value = newAnims.ToArray();
        ex.Extras = tail.ToArray();
        Directory.CreateDirectory(Path.GetDirectoryName(outPath)!);
        asset.Write(outPath);
        var check = new UAsset(outPath, EngineVersion.VER_UE5_6, mappings);
        Console.WriteLine($"make-ss6: {outPath}  cellmaps={newMaps.Count} cells={cellMaps.Count} anims={newAnims.Count} keys={keyCount} tail={tail.Length}B  re-parse OK ({check.Exports.Count} exports)");
        return 0;
    }

    static string EnumLike2(string current, string wanted) => current.Contains("::") ? (wanted.Contains("::") ? wanted : current.Split("::")[0] + "::" + wanted) : (wanted.Contains("::") ? wanted.Split("::")[1] : wanted);

    // ------------------------------------------------------------------ make-texture
    public static int MakeTexture(List<string> pos, Usmap? mappings)
    {
        var donor = pos[1]; var payloadPath = pos[2]; int w = int.Parse(pos[3]); int h = int.Parse(pos[4]); var outPath = pos[5]; var oldPkg = pos[6]; var newPkg = pos[7];
        var payload = File.ReadAllBytes(payloadPath);
        var asset = new UAsset(donor, EngineVersion.VER_UE5_6, mappings);
        Rename(asset, oldPkg, newPkg, ParseRenames(pos.Skip(8)));
        var ex = asset.Exports.OfType<NormalExport>().First();
        var extras = ex.Extras; long propsLen = ex.SerialSize - extras.Length;
        if (asset.DataResources.Count != 1) throw new Exception($"donor texture has {asset.DataResources.Count} bulk data resources (mip chain); use a single-mip donor such as Cloud's summon13110_* textures");
        var dr = asset.DataResources[0];
        int payloadStart = (int)(dr.SerialOffset - propsLen); int oldLen = (int)dr.SerialSize;
        var header = extras[..payloadStart].ToArray(); var footer = extras[(payloadStart + oldLen)..].ToArray();
        // header: [strip flags 4][bCooked 4][FName PixelFormat 8][int32 ?][int64 SkipOffset @0x14] ... SizeX @0x2c, SizeY @0x30 ; footer: mip SizeX, SizeY
        BinaryPrimitives.WriteInt32LittleEndian(header.AsSpan(0x2c), w); BinaryPrimitives.WriteInt32LittleEndian(header.AsSpan(0x30), h);
        long skip = BinaryPrimitives.ReadInt64LittleEndian(header.AsSpan(0x14)); BinaryPrimitives.WriteInt64LittleEndian(header.AsSpan(0x14), skip + (payload.Length - oldLen));
        BinaryPrimitives.WriteInt32LittleEndian(footer.AsSpan(0), w); BinaryPrimitives.WriteInt32LittleEndian(footer.AsSpan(4), h);
        var combined = new byte[header.Length + payload.Length + footer.Length];
        header.CopyTo(combined, 0); payload.CopyTo(combined, header.Length); footer.CopyTo(combined, header.Length + payload.Length);
        ex.Extras = combined;
        dr.SerialSize = payload.Length; dr.RawSize = payload.Length;
        asset.DataResources[0] = dr;
        asset.BulkData = Array.Empty<byte>();   // donor's unreferenced trailing mip chain (retoc puts the zen bulk segment here)
        long expectedSkip = combined.Length - 0x1c; long writtenSkip = BinaryPrimitives.ReadInt64LittleEndian(header.AsSpan(0x14));
        if (expectedSkip != writtenSkip) Console.WriteLine($"  WARNING skip offset {writtenSkip} != expected {expectedSkip}");
        if (ex.Data.FirstOrDefault(p => p.Name.ToString() == "ImportedSize") is StructPropertyData isz)
        {
            if (isz.Value.Count == 1 && isz.Value[0] is IntPointPropertyData ipp) ipp.Value = new[] { w, h };
            else foreach (var c in isz.Value) if (c is IntPropertyData ip) { if (c.Name.ToString() == "X") ip.Value = w; else if (c.Name.ToString() == "Y") ip.Value = h; }
        }
        Directory.CreateDirectory(Path.GetDirectoryName(outPath)!);
        asset.Write(outPath);
        var check = new UAsset(outPath, EngineVersion.VER_UE5_6, mappings);
        var cex = check.Exports.OfType<NormalExport>().First();
        long newPropsLen = cex.SerialSize - cex.Extras.Length;
        if (newPropsLen != propsLen)
        {
            var cdr = check.DataResources[0]; cdr.SerialOffset = newPropsLen + payloadStart; check.DataResources[0] = cdr; check.Write(outPath);
            Console.WriteLine($"  (property block size changed {propsLen} -> {newPropsLen}; data resource offset fixed)");
        }
        Console.WriteLine($"make-texture: {outPath} {w}x{h} payload={payload.Length}B (was {oldLen}B) re-parse OK");
        return 0;
    }
}
