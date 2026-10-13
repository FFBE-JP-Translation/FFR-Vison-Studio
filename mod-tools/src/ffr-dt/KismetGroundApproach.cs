using Newtonsoft.Json.Linq;
using UAssetAPI;
using UAssetAPI.UnrealTypes;
using UAssetAPI.Unversioned;
using UAssetAPI.ExportTypes;
using UAssetAPI.Kismet.Bytecode;
using UAssetAPI.Kismet.Bytecode.Expressions;

public static partial class KismetTools
{
    const string GroundApproachEvent = "NativeGroundApproach";
    static void ValidateGroundApproach(JObject set)
    {
        var offset = set["NativeGroundApproach_Offset"] as JObject;
        if (set.Count != 5 || set.Value<string>("EventType") != GroundApproachEvent
            || set["NativeGroundApproach_UnitId"]?.Type != JTokenType.Integer
            || set.Value<long>("NativeGroundApproach_UnitId") is <= 0 or > int.MaxValue
            || set["NativeGroundApproach_Frame"]?.Type != JTokenType.Integer
            || set.Value<long>("NativeGroundApproach_Frame") is < 1 or > 3600
            || set["NativeGroundApproach_PartName"]?.Type != JTokenType.String
            || string.IsNullOrWhiteSpace(set.Value<string>("NativeGroundApproach_PartName"))
            || set.Value<string>("NativeGroundApproach_PartName")!.Length > 128
            || offset == null || offset.Count != 3
            || new[] { "x", "y", "z" }.Any(k => offset[k]?.Type is not (JTokenType.Integer or JTokenType.Float)
                || !double.IsFinite(offset.Value<double>(k))) || offset.Value<double>("z") != 0)
            throw new InvalidDataException("NativeGroundApproach requires one positive vision ID, 1-3600 frames, target part and finite horizontal-only offset");
    }

    static KismetExpression[] GroundApproachCode(UAsset asset, Usmap m, FunctionExport fn, EX_StructConst template,
        int unitId, int frames, string part, FVector offset, out List<FPackageIndex> dependencies)
    {
        var refs = new List<FPackageIndex>();
        FPackageIndex Import(string package, string name, string kind, FPackageIndex outer) {
            var found = asset.Imports.FindIndex(i => i.ObjectName.ToString() == name && i.OuterIndex.Index == outer.Index);
            if (found < 0) { asset.Imports.Add(new Import(package, kind, outer, name, false, asset)); found = asset.Imports.Count - 1; }
            var index = FPackageIndex.FromImport(found);
            if (refs.All(r => r.Index != index.Index)) refs.Add(index);
            return index;
        }
        FPackageIndex Package(string n) => Import("/Script/CoreUObject", n, "Package", new FPackageIndex(0));
        FPackageIndex Class(string p, string n) => Import("/Script/CoreUObject", n, "Class", Package(p));
        FPackageIndex Function(string p, string c, string n) => Import("/Script/CoreUObject", n, "Object", Class(p, c));
        var getter = Function("/Script/mucha", "CPP_BFL_Battle", AuraGetter);
        var valid = Function("/Script/Engine", "KismetSystemLibrary", "IsValid");
        var validIndex = Function("/Script/Engine", "KismetArrayLibrary", "Array_IsValidIndex");
        var location = Function("/Script/Engine", "Actor", "K2_GetActorLocation");
        var socketLocation = Function("/Script/Engine", "SceneComponent", "GetSocketLocation");
        var socketExists = Function("/Script/Engine", "SceneComponent", "DoesSocketExist");
        var add = Function("/Script/Engine", "KismetMathLibrary", "Add_VectorVector");
        var subtract = Function("/Script/Engine", "KismetMathLibrary", "Subtract_VectorVector");
        var multiply = Function("/Script/Engine", "KismetMathLibrary", "Multiply_VectorVector");
        var eventClass = Class("/Script/mucha", "CPP_BtlSequencerEvent");
        var unitClass = Class("/Script/mucha", "CPP_Unit");
        var parameter = StageEventParameter(asset, fn);
        KismetPropertyPointer Property(FPackageIndex owner, params string[] path) => new(new FFieldPath {
            Path = path.Select(n => FName.FromString(asset, n)).ToArray(), ResolvedOwner = owner });
        EX_CallMath Call(FPackageIndex f, params KismetExpression[] args) => new() { StackNode = f, Parameters = args };
        KismetExpression Event() => new EX_LocalVariable { Variable = Property(parameter.owner, parameter.name) };
        KismetExpression Unit() => Call(getter, new EX_IntConst { Value = unitId }, new EX_False());
        EX_Context_FailSilent Context(KismetExpression obj, KismetExpression rhs, KismetPropertyPointer result) => new() {
            ObjectExpression = obj, ContextExpression = rhs, RValuePointer = result, PropertyType = 0,
            Offset = checked((uint)AuraBytes(asset, new[] { rhs }).size) };
        KismetExpression Member(KismetExpression obj, FPackageIndex cls, string n) => Context(obj,
            new EX_InstanceVariable { Variable = Property(cls, n) }, Property(cls, n));
        KismetExpression Targets() => Member(Event(), eventClass, "m_TargetUnitList");
        KismetExpression Target() => new EX_ArrayGetByRef { ArrayVariable = Targets(), ArrayIndex = new EX_IntZero() };
        KismetExpression Sprite() => Member(Target(), unitClass, "m_pSsPlayerComponent");
        KismetExpression Invoke(KismetExpression obj, FPackageIndex f, params KismetExpression[] args) => Context(obj,
            new EX_FinalFunction { StackNode = f, Parameters = args }, Property(f, "ReturnValue"));
        KismetExpression Part() => new EX_NameConst { Value = FName.FromString(asset, part) };
        var props = SchemaProps(m, "BTL_SEQUENCE_PARAMETER");
        if (StructName(asset, template.Struct) != "BTL_SEQUENCE_PARAMETER" || template.Value.Length != props.Count)
            throw new InvalidDataException("NativeGroundApproach requires complete native battle-event schema");
        int Index(string n) => props.FindIndex(p => p.Name == n) is var i && i >= 0 ? i : throw new InvalidDataException("Missing movement schema field " + n);
        var offsetIndex = Index("Unit_MoveToTarget_AddLocation");
        var sc = new EX_StructConst { Struct = template.Struct, StructSize = template.StructSize,
            Value = template.Value.Select((e, i) => i == offsetIndex
                ? new EX_VectorConst { Value = new FVector(0, 0, 0) } : ZeroStageConstant(asset, e)).ToArray() };
        SetPath(asset, m, sc, "EventType", "UnitMoveToTarget");
        SetPath(asset, m, sc, "Unit_MoveToTarget_Frame", frames);
        SetPath(asset, m, sc, "Unit_MoveToTarget_PartName", part);
        SetPath(asset, m, sc, "Unit_MoveToTarget_EasingType", "EaseOut");
        SetPath(asset, m, sc, "Unit_MoveToTarget_EasingBlendExp", 1.5);
        SetPath(asset, m, sc, "Unit_MoveToTarget_EasingSteps", 2);
        SetPath(asset, m, sc, "Unit_MoveToTarget_IsDisableOffset", true);
        SetPath(asset, m, sc, "Unit_MoveToTarget_IsVisionUnit", true);
        // Native move uses the named target socket plus its offset. Preserve
        // the source-translated horizontal offset, replace only the endpoint Z
        // with the vision's current actor Z, and leave trajectory height zero.
        sc.Value[offsetIndex] = Call(add, new EX_VectorConst { Value = offset },
            Call(multiply, Call(subtract, Invoke(Unit(), location), Invoke(Sprite(), socketLocation, Part())),
                new EX_VectorConst { Value = new FVector(0, 0, 1) }));
        var code = new KismetExpression[] {
            new EX_JumpIfNot { BooleanExpression = Call(valid, Event()) },
            new EX_JumpIfNot { BooleanExpression = Call(valid, Unit()) },
            new EX_JumpIfNot { BooleanExpression = Call(validIndex, Targets(), new EX_IntZero()) },
            new EX_JumpIfNot { BooleanExpression = Call(valid, Target()) },
            new EX_JumpIfNot { BooleanExpression = Call(valid, Sprite()) },
            new EX_JumpIfNot { BooleanExpression = Invoke(Sprite(), socketExists, Part()) },
            new EX_LocalVirtualFunction { VirtualFunctionName = FName.FromString(asset, "SeqBattleEvent"), Parameters = new KismetExpression[] { Event(), sc } },
            new EX_Return { ReturnExpression = new EX_Nothing() }, new EX_EndOfScript()
        };
        var end = checked((uint)AuraBytes(asset, code.Take(7)).size);
        foreach (var guard in code.OfType<EX_JumpIfNot>()) guard.CodeOffset = end;
        dependencies = refs;
        return code;
    }

    static int SetGroundApproach(UAsset asset, Usmap m, JObject op, JObject set)
    {
        ValidateGroundApproach(set);
        var selected = op.Value<string>("export");
        var matches = asset.Exports.OfType<FunctionExport>().Where(f => op["match"] == null && !string.IsNullOrEmpty(selected) && selected != "*"
            && (f.ObjectName.ToString() == selected || (asset.Exports.IndexOf(f)+1).ToString() == selected)).ToArray();
        if (matches.Length != 1) throw new InvalidDataException("NativeGroundApproach requires one explicit donor function");
        var fn = matches[0];
        var call = fn.ScriptBytecode?.OfType<EX_LocalVirtualFunction>().SingleOrDefault(c => c.VirtualFunctionName.ToString() == "SeqBattleEvent");
        if (call?.Parameters.Length != 2 || call.Parameters[0] is not EX_LocalVariable || call.Parameters[1] is not EX_StructConst template)
            throw new InvalidDataException("NativeGroundApproach requires the native battle-event binding");
        var v = (JObject)set["NativeGroundApproach_Offset"]!;
        fn.ScriptBytecode = GroundApproachCode(asset, m, fn, template, set.Value<int>("NativeGroundApproach_UnitId"),
            set.Value<int>("NativeGroundApproach_Frame"), set.Value<string>("NativeGroundApproach_PartName")!,
            new FVector(v.Value<double>("x"), v.Value<double>("y"), 0), out var dependencies);
        fn.ScriptBytecodeSize = AuraBytes(asset, fn.ScriptBytecode).size;
        fn.CreateBeforeSerializationDependencies ??= new List<FPackageIndex>();
        foreach (var dependency in dependencies)
            if (fn.CreateBeforeSerializationDependencies.All(d => d.Index != dependency.Index)) fn.CreateBeforeSerializationDependencies.Add(dependency);
        return 1;
    }

    static JObject? ReadGroundApproach(UAsset asset, Usmap m, FunctionExport fn)
    {
        var expressions = fn.ScriptBytecode.SelectMany(Walk).ToArray();
        var sockets = expressions.OfType<EX_FinalFunction>().Where(c => IsCall(asset, c, "/Script/Engine", "SceneComponent", "GetSocketLocation")).ToArray();
        var getters = expressions.OfType<EX_FinalFunction>().Where(c => IsAuraGetter(asset, c)).ToArray();
        var calls = fn.ScriptBytecode.OfType<EX_LocalVirtualFunction>().Where(c => c.VirtualFunctionName.ToString() == "SeqBattleEvent").ToArray();
        if (sockets.Length == 0 || getters.Length == 0 || calls.Length == 0) return null;
        if (sockets.Length != 1 || sockets[0].Parameters.Length != 1 || sockets[0].Parameters[0] is not EX_NameConst part
            || calls.Length != 1 || calls[0].Parameters.Length != 2 || calls[0].Parameters[1] is not EX_StructConst sc
            || getters.Any(g => g.Parameters.Length != 2 || g.Parameters[0] is not EX_IntConst || g.Parameters[1] is not EX_False))
            throw new InvalidDataException("Malformed NativeGroundApproach target socket or binding");
        var unitId = ((EX_IntConst)getters[0].Parameters[0]).Value;
        var adds = expressions.OfType<EX_FinalFunction>().Where(c => IsCall(asset, c, "/Script/Engine", "KismetMathLibrary", "Add_VectorVector")).ToArray();
        if (getters.Any(g => ((EX_IntConst)g.Parameters[0]).Value != unitId) || adds.Length != 1 || adds[0].Parameters.Length != 2
            || adds[0].Parameters[0] is not EX_VectorConst offset)
            throw new InvalidDataException("Malformed NativeGroundApproach selected vision or offset");
        var props = SchemaProps(m, "BTL_SEQUENCE_PARAMETER");
        if (sc.Value[props.FindIndex(p => p.Name == "Unit_MoveToTarget_Frame")] is not EX_IntConst frames)
            throw new InvalidDataException("Malformed NativeGroundApproach duration");
        var result = new JObject { ["EventType"] = GroundApproachEvent, ["NativeGroundApproach_UnitId"] = unitId,
            ["NativeGroundApproach_Frame"] = frames.Value, ["NativeGroundApproach_PartName"] = part.Value.ToString(),
            ["NativeGroundApproach_Offset"] = new JObject { ["x"] = offset.Value.X, ["y"] = offset.Value.Y, ["z"] = offset.Value.Z } };
        ValidateGroundApproach(result);
        var before = asset.Imports.Count;
        var expected = GroundApproachCode(asset, m, fn, sc, unitId, frames.Value, part.Value.ToString(), offset.Value, out _);
        var actualBytes = AuraBytes(asset, fn.ScriptBytecode); var expectedBytes = AuraBytes(asset, expected);
        if (asset.Imports.Count != before || fn.ScriptBytecodeSize != expectedBytes.size || actualBytes.size != expectedBytes.size
            || !actualBytes.bytes.SequenceEqual(expectedBytes.bytes))
            throw new InvalidDataException("Malformed NativeGroundApproach guards, height compensation, target binding or VM offsets");
        return result;
    }
}
