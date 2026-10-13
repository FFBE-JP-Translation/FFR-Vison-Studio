using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UAssetAPI;
using UAssetAPI.UnrealTypes;
using UAssetAPI.Unversioned;
using UAssetAPI.ExportTypes;
using UAssetAPI.PropertyTypes.Objects;
using UAssetAPI.PropertyTypes.Structs;

// ffr-dt: read/write FINAL FANTASY RESONANCE data tables (legacy .uasset produced by retoc to-legacy)
//   ffr-dt info     <asset.uasset> [--usmap p]            summary
//   ffr-dt rows     <asset.uasset> <out.json> [--usmap p]  clean JSON: { rowName: {field: value} }  (DataTable / StringTable)
//   ffr-dt tojson   <asset.uasset> <out.json> [--usmap p]  full UAssetAPI JSON (lossless)
//   ffr-dt fromjson <in.json> <out.uasset> [--usmap p]     write asset back from full JSON
static class Program
{
    static int Main(string[] args)
    {
        // Invalid input and deliberate corrupt-asset checks are CLI failures,
        // not unhandled CLR crashes (which launch Windows Error Reporting).
        try { return Run(args); }
        catch (Exception error) {
            Console.Error.WriteLine($"ffr-dt: {error.GetType().Name}: {error.Message}");
            if (error is not (InvalidDataException or IOException or ArgumentException or JsonException))
                Console.Error.WriteLine(error.StackTrace);
            return 1;
        }
    }

    static int Run(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        if (args.Length < 2) { Console.Error.WriteLine("usage: ffr-dt info|rows|tojson|fromjson <in> [out] [--usmap path]"); return 2; }
        string? usmapPath = null; var pos = new List<string>(); var schemas = new List<string>();
        for (int i = 0; i < args.Length; i++)
        {
            if (args[i] == "--usmap" && i + 1 < args.Length) { usmapPath = args[++i]; continue; }
            if (args[i] == "--schema" && i + 1 < args.Length) { schemas.Add(args[++i]); continue; }
            pos.Add(args[i]);
        }
        Usmap? mappings = usmapPath != null ? new Usmap(usmapPath) : null;
        var ver = EngineVersion.VER_UE5_6;
        // Cooked map instances need their Blueprint's fields in addition to the
        // native usmap. Reading a class registers its schema in this shared map.
        foreach (var schema in schemas)
        {
            if (mappings == null) throw new ArgumentException("--schema requires --usmap");
            _ = new UAsset(schema, ver, mappings);
        }
        switch (pos[0])
        {
            case "info":
            {
                var asset = new UAsset(pos[1], ver, mappings);
                Console.WriteLine($"file: {pos[1]}");
                Console.WriteLine($"engine: {asset.GetEngineVersion()}  unversioned={asset.HasUnversionedProperties}");
                Console.WriteLine($"names={asset.GetNameMapIndexList().Count} imports={asset.Imports.Count} exports={asset.Exports.Count}");
                foreach (var e in asset.Exports)
                {
                    Console.WriteLine($"  export: {e.ObjectName} ({e.GetType().Name}) class={e.ClassIndex.ToImport(asset)?.ObjectName}");
                    if (e is DataTableExport dt)
                    {
                        Console.WriteLine($"    rows={dt.Table.Data.Count}");
                        int shown = 0;
                        foreach (var row in dt.Table.Data)
                        {
                            Console.WriteLine($"    row[{shown}] name={row.Name} struct={row.StructType} props={row.Value.Count}");
                            foreach (var p in row.Value.Take(60)) Console.WriteLine($"       {p.PropertyType} {p.Name} = {JsonConvert.SerializeObject(ToJson(p, asset))}");
                            if (++shown >= 2) break;
                        }
                    }
                    if (e is StringTableExport st) Console.WriteLine($"    stringtable ns={st.Table.TableNamespace} entries={st.Table.Count}");
                }
                Console.WriteLine($"verify roundtrip: {asset.VerifyBinaryEquality()}");
                return 0;
            }
            case "rows":
            {
                var asset = new UAsset(pos[1], ver, mappings);
                var root = new JObject();
                root["_asset"] = Path.GetFileNameWithoutExtension(pos[1]);
                foreach (var e in asset.Exports)
                {
                    if (e is DataTableExport dt)
                    {
                        root["_rowStruct"] = dt.Table.Data.Count > 0 ? dt.Table.Data[0].StructType?.ToString() : null;
                        var rows = new JObject();
                        foreach (var row in dt.Table.Data)
                        {
                            var o = new JObject();
                            foreach (var p in row.Value) o[p.Name.ToString()] = ToJson(p, asset);
                            rows[row.Name.ToString()] = o;
                        }
                        root["rows"] = rows;
                    }
                    else if (e is StringTableExport st)
                    {
                        root["_namespace"] = st.Table.TableNamespace?.ToString();
                        var rows = new JObject();
                        foreach (var kv in st.Table) rows[kv.Key.ToString()] = kv.Value.ToString();
                        root["rows"] = rows;
                    }
                }
                File.WriteAllText(pos[2], root.ToString(Formatting.Indented), new UTF8Encoding(false));
                Console.WriteLine($"wrote {pos[2]}  rows={(root["rows"] as JObject)?.Count}");
                return 0;
            }
            case "tojson":
            {
                var asset = new UAsset(pos[1], ver, mappings);
                File.WriteAllText(pos[2], asset.SerializeJson(Formatting.Indented), new UTF8Encoding(false));
                Console.WriteLine($"wrote {pos[2]}  exports={asset.Exports.Count}  roundtrip={asset.VerifyBinaryEquality()}");
                return 0;
            }
            case "fromjson":
            {
                var asset = UAsset.DeserializeJson(File.ReadAllText(pos[1]));
                if (mappings != null) asset.Mappings = mappings;
                asset.Write(pos[2]);
                Console.WriteLine($"wrote {pos[2]}");
                return 0;
            }
            case "patch":
                return Patch.Run(pos[1], mappings);
            case "seqdump":
            {
                // seqdump <sequence.uasset> <out.json> --usmap p : every director-blueprint event as {field: value} (non-default fields)
                var asset = new UAsset(pos[1], ver, mappings);
                var dump = KismetTools.Dump(asset, mappings ?? throw new Exception("--usmap required"), !pos.Contains("--all"));
                File.WriteAllText(pos[2], dump.ToString(Formatting.Indented), new UTF8Encoding(false));
                Console.WriteLine($"wrote {pos[2]} ({dump.Count} event functions)");
                return 0;
            }
            case "make-ss6":
                return Ss6Builder.MakeSs6(pos, mappings);
            case "make-choice-sequence":
                return ChoiceSequence.Build(pos, mappings);
            case "make-texture":
                return Ss6Builder.MakeTexture(pos, mappings);
            case "check-atom-bank":
            {
                try
                {
                    var asset = new UAsset(pos[1], ver, mappings);
                    var payload = AtomBankTools.Validate(asset);
                    Console.WriteLine($"Atom bank OK: {payload.Length} bytes, bulk offset {asset.DataResources[0].SerialOffset}");
                    return 0;
                }
                catch (InvalidDataException error)
                {
                    Console.Error.WriteLine(error.Message);
                    return 1;
                }
            }
            case "clone-package":
            {
                // clone-package <in.uasset> <out.uasset> <oldPackagePath> <newPackagePath> [old=new ...]
                var renames = pos.Skip(5).Select(x => x.Split('=', 2)).Select(a => (a[0], a[1])).ToList();
                Patch.ClonePackage(pos[1], pos[2], pos[3], pos[4], renames, mappings);
                return 0;
            }
            default: Console.Error.WriteLine("unknown command"); return 2;
        }
    }

    static JToken ToJson(PropertyData p, UAsset asset)
    {
        switch (p)
        {
            case StructPropertyData s:
            {
                var o = new JObject();
                foreach (var c in s.Value) o[c.Name.ToString()] = ToJson(c, asset);
                return o;
            }
            case ArrayPropertyData a: return new JArray(a.Value.Select(x => ToJson(x, asset)));
            case MapPropertyData m:
            {
                var o = new JObject();
                foreach (var kv in m.Value) o[ToJson(kv.Key, asset).ToString()] = ToJson(kv.Value, asset);
                return o;
            }
            case TextPropertyData t:
            {
                var o = new JObject();
                if (t.TableId != null && !t.TableId.IsDummy) { o["table"] = t.TableId.ToString(); o["key"] = t.Value?.ToString(); return o; }
                if (t.Namespace != null && t.Namespace.Value != null) o["ns"] = t.Namespace.ToString();
                if (t.Value != null && t.Value.Value != null) o["key"] = t.Value.ToString();
                if (t.CultureInvariantString != null && t.CultureInvariantString.Value != null) o["text"] = t.CultureInvariantString.ToString();
                if (o.Count == 0) return "";
                if (o.Count == 1 && o["text"] != null) return o["text"]!;
                return o;
            }
            case EnumPropertyData en: return en.Value?.ToString() ?? "";
            case BytePropertyData b: return b.ByteType == BytePropertyType.FName ? (b.EnumValue?.ToString() ?? "") : (JToken)b.Value;
            case NamePropertyData n: return n.Value?.ToString() ?? "";
            case StrPropertyData str: return str.Value?.ToString() ?? "";
            case SoftObjectPropertyData so:
            {
                var pkg = so.Value.AssetPath.PackageName?.ToString() ?? "";
                var sub = so.Value.SubPathString?.ToString();
                return string.IsNullOrEmpty(sub) ? pkg : pkg + ":" + sub;
            }
            case ObjectPropertyData op:
            {
                if (op.Value.IsNull()) return JValue.CreateNull();
                if (op.Value.IsImport()) return op.Value.ToImport(asset).ObjectName.ToString();
                return "export:" + op.Value.Index;
            }
            case BoolPropertyData bp: return bp.Value;
            case IntPropertyData ip: return ip.Value;
            case Int64PropertyData i64: return i64.Value;
            case UInt32PropertyData u32: return u32.Value;
            case FloatPropertyData fp: return fp.Value;
            case DoublePropertyData dp: return dp.Value;
            case VectorPropertyData v: return new JObject { ["x"] = v.Value.X, ["y"] = v.Value.Y, ["z"] = v.Value.Z };
            case Vector4PropertyData v: return new JObject { ["X"] = v.Value.X, ["Y"] = v.Value.Y, ["Z"] = v.Value.Z, ["W"] = v.Value.W };
            case Vector4fPropertyData v: return new JObject { ["X"] = v.Value.X, ["Y"] = v.Value.Y, ["Z"] = v.Value.Z, ["W"] = v.Value.W };
            case GameplayTagContainerPropertyData g: return new JArray(g.Value.Select(x => x.ToString()));
            default:
            {
                try { var raw = p.RawValue; if (raw == null) return JValue.CreateNull(); if (raw is string || raw is ValueType) return JToken.FromObject(raw); return raw.ToString() ?? ""; } catch { return p.ToString(); }
            }
        }
    }
}
