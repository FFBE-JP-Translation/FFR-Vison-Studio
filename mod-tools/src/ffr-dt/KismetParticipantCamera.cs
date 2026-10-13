using Newtonsoft.Json.Linq;
using UAssetAPI;
using UAssetAPI.UnrealTypes;
using UAssetAPI.Unversioned;
using UAssetAPI.ExportTypes;
using UAssetAPI.Kismet.Bytecode;
using UAssetAPI.Kismet.Bytecode.Expressions;

public static partial class KismetTools
{
    const string ParticipantCameraEvent = "NativeParticipantCamera";

    static void ValidateParticipantCamera(JObject set)
    {
        if (set["NativeParticipantCamera_ZoomFactor"] != null) { ValidateParticipantFocus(set); return; }
        if (set["NativeParticipantCamera_Shot"] != null) { ValidateParticipantFraming(set); return; }
        if (set.Count != 3 || set.Value<string>("EventType") != ParticipantCameraEvent
            || set["NativeParticipantCamera_UnitId"]?.Type != JTokenType.Integer
            || set.Value<long>("NativeParticipantCamera_UnitId") is <= 0 or > int.MaxValue
            || set["NativeParticipantCamera_Frame"]?.Type != JTokenType.Integer
            || set.Value<long>("NativeParticipantCamera_Frame") is < 1 or > 120)
            throw new InvalidDataException("NativeParticipantCamera requires one positive vision ID and 1-120 native pan frames");
    }

    static int SetParticipantCamera(UAsset asset, Usmap m, JObject op, JObject set)
    {
        ValidateParticipantCamera(set);
        if (op["match"] != null) throw new InvalidDataException("NativeParticipantCamera requires one explicit donor function");
        var selected = op.Value<string>("export");
        var matches = asset.Exports.OfType<FunctionExport>().Where(f => !string.IsNullOrEmpty(selected) && selected != "*"
            && (f.ObjectName.ToString() == selected || (asset.Exports.IndexOf(f) + 1).ToString() == selected)).ToArray();
        if (matches.Length != 1) throw new InvalidDataException("NativeParticipantCamera requires one explicit donor function");
        var fn = matches[0];
        var calls = fn.ScriptBytecode?.OfType<EX_LocalVirtualFunction>().Where(c => c.VirtualFunctionName.ToString() == "SeqBattleEvent").ToArray();
        // A stock donor has one native event. A previously cooked, independently
        // validated participant camera has two (pan and focal interpolation).
        // Permit that exact upgrade path without accepting arbitrary wrappers.
        if (calls?.Length == 2 && ReadParticipantCamera(asset, m, fn) == null)
            throw new InvalidDataException("NativeParticipantCamera requires a validated existing camera binding");
        var call = calls?.Length is 1 or 2 ? calls[0] : null;
        if (call?.Parameters.Length != 2 || call.Parameters[0] is not EX_LocalVariable || call.Parameters[1] is not EX_StructConst template
            || StructName(asset, template.Struct) != "BTL_SEQUENCE_PARAMETER")
            throw new InvalidDataException("NativeParticipantCamera requires the native SeqBattleEvent donor binding");
        List<FPackageIndex> dependencies;
        fn.ScriptBytecode = set["NativeParticipantCamera_ZoomFactor"] != null
            ? ParticipantFocusCode(asset, m, fn, template, set, true, out dependencies)
            : set["NativeParticipantCamera_Shot"] != null
            ? ParticipantFramingCode(asset, m, fn, template, set, true, out dependencies)
            : StageCameraCode(asset, m, fn, template, set.Value<int>("NativeParticipantCamera_UnitId"),
                new FVector(0, 0, 0), out dependencies, set.Value<int>("NativeParticipantCamera_Frame"), "EaseInOut", participants: true);
        fn.ScriptBytecodeSize = AuraBytes(asset, fn.ScriptBytecode).size;
        fn.CreateBeforeSerializationDependencies ??= new List<FPackageIndex>();
        foreach (var dependency in dependencies)
            if (fn.CreateBeforeSerializationDependencies.All(d => d.Index != dependency.Index)) fn.CreateBeforeSerializationDependencies.Add(dependency);
        Console.WriteLine($"  ~ native participant camera {fn.ObjectName}: {set.Value<string>("NativeParticipantCamera_Shot") ?? "legacy midpoint"}");
        return 1;
    }

    static JObject? ReadParticipantCamera(UAsset asset, Usmap m, FunctionExport fn)
    {
        var focus = ReadParticipantFocus(asset, m, fn);
        if (focus != null) return focus;
        var framing = ReadParticipantFraming(asset, m, fn);
        if (framing != null) return framing;
        var expressions = fn.ScriptBytecode.SelectMany(Walk).ToArray();
        var multiply = expressions.OfType<EX_FinalFunction>().Where(c =>
            IsCall(asset, c, "/Script/Engine", "KismetMathLibrary", "Multiply_VectorFloat")).ToArray();
        if (multiply.Length == 0) return null;
        var calls = fn.ScriptBytecode.OfType<EX_LocalVirtualFunction>().Where(c => c.VirtualFunctionName.ToString() == "SeqBattleEvent").ToArray();
        var getters = expressions.OfType<EX_FinalFunction>().Where(c => IsAuraGetter(asset, c)).ToArray();
        // A native source function can legitimately contain vector math. Only
        // the selected-vision battle-event wrapper belongs to this adapter.
        if (getters.Length == 0 || calls.Length == 0) return null;
        if (multiply.Length != 1 || multiply[0].Parameters.Length != 2
            || multiply[0].Parameters[1] is not EX_DoubleConst scale || scale.Value != .5
            || calls.Length != 1 || calls[0].Parameters.Length != 2 || calls[0].Parameters[1] is not EX_StructConst sc
            || getters.Any(g => g.Parameters.Length != 2 || g.Parameters[0] is not EX_IntConst || g.Parameters[1] is not EX_False))
            throw new InvalidDataException("Malformed NativeParticipantCamera midpoint or native binding");
        var unitId = ((EX_IntConst)getters[0].Parameters[0]).Value;
        if (getters.Any(g => ((EX_IntConst)g.Parameters[0]).Value != unitId))
            throw new InvalidDataException("Malformed NativeParticipantCamera selected vision");
        var props = SchemaProps(m, "BTL_SEQUENCE_PARAMETER");
        var frameIndex = props.FindIndex(p => p.Name == "Camera_SetLookAtTarget_Frame");
        if (frameIndex < 0 || sc.Value[frameIndex] is not EX_IntConst frames)
            throw new InvalidDataException("Malformed NativeParticipantCamera duration");
        var result = new JObject { ["EventType"] = ParticipantCameraEvent,
            ["NativeParticipantCamera_UnitId"] = unitId, ["NativeParticipantCamera_Frame"] = frames.Value };
        ValidateParticipantCamera(result);
        var before = asset.Imports.Count;
        var expected = StageCameraCode(asset, m, fn, sc, unitId, new FVector(0, 0, 0), out _, frames.Value, "EaseInOut", participants: true);
        var actualBytes = AuraBytes(asset, fn.ScriptBytecode); var expectedBytes = AuraBytes(asset, expected);
        if (asset.Imports.Count != before || fn.ScriptBytecodeSize != expectedBytes.size || actualBytes.size != expectedBytes.size
            || !actualBytes.bytes.SequenceEqual(expectedBytes.bytes))
            throw new InvalidDataException("Malformed NativeParticipantCamera guards, midpoint coordinates, target binding or VM offsets");
        return result;
    }
}
