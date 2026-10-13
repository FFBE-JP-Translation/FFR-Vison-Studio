using Newtonsoft.Json.Linq;
using UAssetAPI;
using UAssetAPI.UnrealTypes;
using UAssetAPI.Unversioned;
using UAssetAPI.ExportTypes;
using UAssetAPI.Kismet.Bytecode;
using UAssetAPI.Kismet.Bytecode.Expressions;

// Battle sequences (Sequencer/Battle/**/SEQ_Battle_*) drive everything through director-blueprint functions whose body is one
// EX_StructConst of FBTL_SEQUENCE_PARAMETER (event type + every parameter). This maps those constants to field names via the
// usmap schema so they can be dumped ("seqdump") and edited in place (patch "bytecode" ops).
public static partial class KismetTools
{
    // The ambient blue vision aura is registry[0], NOT m_pAuraEffect (magic aura).
    // Resolve one selected vision and guard its actual native AuraOnly asset.
    const string AuraEvent = "NativeAuraVisibility";
    const string AuraGetter = "GetBattleUnitByUnitIdWithVision";
    const string AuraAssetPackage = "/Game/Effect/04_BTL/VisionAura/NS_EF_BTL_VisionAura_AuraOnly";
    const string AuraAssetName = "NS_EF_BTL_VisionAura_AuraOnly";

    static bool IsCall(UAsset asset, EX_FinalFunction call, string package, string owner, string name)
    {
        if (!call.StackNode.IsImport()) return false;
        var fn = call.StackNode.ToImport(asset);
        if (fn.ObjectName.ToString() != name || !fn.OuterIndex.IsImport()) return false;
        var cls = fn.OuterIndex.ToImport(asset);
        return cls.ObjectName.ToString() == owner && cls.OuterIndex.IsImport()
            && cls.OuterIndex.ToImport(asset).ObjectName.ToString() == package;
    }

    static bool IsAuraGetter(UAsset asset, EX_FinalFunction call) =>
        IsCall(asset, call, "/Script/mucha", "CPP_BFL_Battle", AuraGetter);

    static bool IsLegacyAura(UAsset asset, EX_FinalFunction call) =>
        IsCall(asset, call, "/Script/mucha", "CPP_DBG_BFL_Battle", "DBG_SetVisibilityUnitAuraEffect");

    static (byte[] bytes, int size) AuraBytes(UAsset asset, IEnumerable<KismetExpression> code)
    {
        using var stream = new MemoryStream();
        using var writer = new AssetBinaryWriter(stream, System.Text.Encoding.UTF8, true, asset);
        // WriteExpression returns the VM memory length, not serialized file length.
        var size = code.Sum(e => ExpressionSerializer.WriteExpression(e, writer));
        writer.Flush();
        return (stream.ToArray(), size);
    }

    static KismetExpression[] AuraCode(UAsset asset, int unitId, bool visible, out List<FPackageIndex> dependencies)
    {
        var refs = new List<FPackageIndex>();
        FPackageIndex Import(string package, string name, string kind, FPackageIndex outer)
        {
            var found = asset.Imports.FindIndex(i => i.ObjectName.ToString() == name && i.OuterIndex.Index == outer.Index);
            if (found < 0)
            {
                asset.Imports.Add(new Import(package, kind, outer, name, false, asset));
                found = asset.Imports.Count - 1;
            }
            var index = FPackageIndex.FromImport(found);
            if (refs.All(r => r.Index != index.Index)) refs.Add(index);
            return index;
        }
        FPackageIndex Package(string name) => Import("/Script/CoreUObject", name, "Package", new FPackageIndex(0));
        FPackageIndex Class(string package, string name) => Import("/Script/CoreUObject", name, "Class", Package(package));
        FPackageIndex Function(string package, string owner, string name) =>
            Import("/Script/CoreUObject", name, "Object", Class(package, owner));
        var getter = Function("/Script/mucha", "CPP_BFL_Battle", AuraGetter);
        var valid = Function("/Script/Engine", "KismetSystemLibrary", "IsValid");
        var validIndex = Function("/Script/Engine", "KismetArrayLibrary", "Array_IsValidIndex");
        var equal = Function("/Script/Engine", "KismetMathLibrary", "EqualEqual_ObjectObject");
        var getAsset = Function("/Script/Niagara", "NiagaraComponent", "GetAsset");
        var setVisibility = Function("/Script/Engine", "SceneComponent", "SetVisibility");
        var unitClass = Class("/Script/mucha", "CPP_BtlUnit");
        var entryStruct = Import("/Script/CoreUObject", "SsNiagaraData", "ScriptStruct", Package("/Script/mucha"));
        var expectedAsset = Import("/Script/Niagara", AuraAssetName, "NiagaraSystem", Package(AuraAssetPackage));
        KismetPropertyPointer Property(FPackageIndex owner, params string[] path) =>
            new(new FFieldPath { Path = path.Select(n => FName.FromString(asset, n)).ToArray(), ResolvedOwner = owner });
        KismetPropertyPointer ArrayProperty() => Property(unitClass, "m_SsNiagaraDatas");
        EX_CallMath Call(FPackageIndex function, params KismetExpression[] args) =>
            new() { StackNode = function, Parameters = args };
        KismetExpression Unit() => Call(getter, new EX_IntConst { Value = unitId }, new EX_False());
        EX_Context_FailSilent Context(KismetExpression obj, KismetExpression expression, KismetPropertyPointer? result = null) =>
            new() { ObjectExpression = obj, ContextExpression = expression,
                Offset = checked((uint)AuraBytes(asset, new[] { expression }).size),
                RValuePointer = result ?? Property(new FPackageIndex(0)), PropertyType = 0 };
        KismetExpression Registry() => Context(Unit(), new EX_InstanceVariable { Variable = ArrayProperty() }, ArrayProperty());
        KismetExpression Component() => new EX_StructMemberContext {
            StructMemberExpression = Property(entryStruct, "NiagaraComponent"),
            StructExpression = new EX_ArrayGetByRef { ArrayVariable = Registry(), ArrayIndex = new EX_IntZero() }
        };
        var code = new KismetExpression[] {
            new EX_JumpIfNot { BooleanExpression = Call(valid, Unit()) },
            new EX_JumpIfNot { BooleanExpression = Call(validIndex, Registry(), new EX_IntZero()) },
            new EX_JumpIfNot { BooleanExpression = Call(valid, Component()) },
            new EX_JumpIfNot { BooleanExpression = Call(equal,
                Context(Component(), new EX_FinalFunction { StackNode = getAsset, Parameters = Array.Empty<KismetExpression>() },
                    Property(getAsset, "ReturnValue")), new EX_ObjectConst { Value = expectedAsset }) },
            Context(Component(), new EX_FinalFunction { StackNode = setVisibility, Parameters = new KismetExpression[] {
                visible ? new EX_True() : new EX_False(), new EX_True() } }),
            new EX_Return { ReturnExpression = new EX_Nothing() }, new EX_EndOfScript()
        };
        // Jump offsets are absolute VM offsets. Context skips are only RHS size.
        var end = checked((uint)AuraBytes(asset, code.Take(5)).size);
        foreach (var guard in code.OfType<EX_JumpIfNot>()) guard.CodeOffset = end;
        dependencies = refs;
        return code;
    }

    static int SetAuraVisibility(UAsset asset, JObject op, JObject set)
    {
        if (op["match"] != null || set.Count != 3 || set["NativeAura_IsVisible"]?.Type != JTokenType.Boolean
            || set["NativeAura_UnitId"]?.Type != JTokenType.Integer
            || set.Value<long>("NativeAura_UnitId") is <= 0 or > int.MaxValue)
            throw new InvalidDataException("NativeAuraVisibility requires a boolean and one positive NativeAura_UnitId");
        var selected = op.Value<string>("export");
        if (string.IsNullOrEmpty(selected) || selected == "*")
            throw new InvalidDataException("NativeAuraVisibility requires one explicit donor function");
        var matches = asset.Exports.Select((e, i) => (e, i)).Where(x => x.e is FunctionExport &&
            (x.e.ObjectName.ToString() == selected || (x.i + 1).ToString() == selected)).ToList();
        if (matches.Count != 1) throw new InvalidDataException("NativeAuraVisibility donor function is not unique");
        var fn = (FunctionExport)matches[0].e;
        var expressions = fn.ScriptBytecode?.SelectMany(Walk).ToArray() ?? Array.Empty<KismetExpression>();
        if (!expressions.OfType<EX_StructConst>().Any(sc => StructName(asset, sc.Struct) == "BTL_SEQUENCE_PARAMETER")
            && !expressions.OfType<EX_FinalFunction>().Any(c => IsLegacyAura(asset, c) || IsAuraGetter(asset, c)))
            throw new InvalidDataException("NativeAuraVisibility requires a battle-event donor body");
        fn.ScriptBytecode = AuraCode(asset, set.Value<int>("NativeAura_UnitId"), set.Value<bool>("NativeAura_IsVisible"), out var dependencies);
        fn.ScriptBytecodeSize = AuraBytes(asset, fn.ScriptBytecode).size;
        fn.CreateBeforeSerializationDependencies ??= new List<FPackageIndex>();
        foreach (var dependency in dependencies)
            if (fn.CreateBeforeSerializationDependencies.All(d => d.Index != dependency.Index)) fn.CreateBeforeSerializationDependencies.Add(dependency);
        Console.WriteLine($"  ~ native vision aura {fn.ObjectName}: unit={set["NativeAura_UnitId"]}, visible={set["NativeAura_IsVisible"]}");
        return 1;
    }

    static JObject? ReadAura(UAsset asset, FunctionExport fn)
    {
        var expressions = fn.ScriptBytecode.SelectMany(Walk).ToArray();
        var getters = expressions.OfType<EX_FinalFunction>().Where(c => IsAuraGetter(asset, c)).ToArray();
        if (getters.Length == 0) return null;
        // A guarded adapter is recognizable by its four leading guards and its
        // one SceneComponent setter. Never reinterpret ordinary native functions.
        var setters = expressions.OfType<EX_FinalFunction>().Where(c =>
            IsCall(asset, c, "/Script/Engine", "SceneComponent", "SetVisibility")).ToArray();
        if (setters.Length == 0) return null;
        if (getters.Any(g => g.Parameters.Length != 2 || g.Parameters[0] is not EX_IntConst || g.Parameters[1] is not EX_False)
            || setters.Length != 1 || setters[0].Parameters.Length != 2
            || setters[0].Parameters[0] is not (EX_True or EX_False) || setters[0].Parameters[1] is not EX_True)
            throw new InvalidDataException("Malformed native vision aura function body");
        var unitId = ((EX_IntConst)getters[0].Parameters[0]).Value;
        if (unitId <= 0 || getters.Any(g => ((EX_IntConst)g.Parameters[0]).Value != unitId))
            throw new InvalidDataException("Native vision aura has inconsistent unit IDs");
        var visible = setters[0].Parameters[0] is EX_True;
        var importsBefore = asset.Imports.Count;
        var expected = AuraCode(asset, unitId, visible, out _);
        var actualBytes = AuraBytes(asset, fn.ScriptBytecode);
        var expectedBytes = AuraBytes(asset, expected);
        if (importsBefore != asset.Imports.Count || fn.ScriptBytecodeSize != expectedBytes.size
            || actualBytes.size != expectedBytes.size || !actualBytes.bytes.SequenceEqual(expectedBytes.bytes))
            throw new InvalidDataException($"Malformed native vision aura guards, field paths, offsets or asset identity (imports {importsBefore}/{asset.Imports.Count}, VM {fn.ScriptBytecodeSize}/{actualBytes.size}/{expectedBytes.size}, bytes {actualBytes.bytes.Length}/{expectedBytes.bytes.Length}, first difference {Enumerable.Range(0, Math.Min(actualBytes.bytes.Length, expectedBytes.bytes.Length)).FirstOrDefault(i => actualBytes.bytes[i] != expectedBytes.bytes[i], -1)})");
        return new JObject { ["EventType"] = AuraEvent, ["NativeAura_UnitId"] = unitId, ["NativeAura_IsVisible"] = visible };
    }


    const string StageCameraEvent = "NativeStageCamera";

    // Native CameraSetLookAtTarget(-1) adds its offset to the selected target's
    // actor root. Compute the offset from the staged vision at execution time,
    // then keep the game's own interpolation state and camera reset path.
    static KismetExpression ZeroStageConstant(UAsset asset, KismetExpression e) => e switch {
        EX_IntConst => new EX_IntConst { Value = 0 },
        EX_ByteConst => new EX_ByteConst { Value = 0 },
        EX_IntConstByte => new EX_IntConstByte { Value = 0 },
        EX_FloatConst => new EX_FloatConst { Value = 0 },
        EX_DoubleConst => new EX_DoubleConst { Value = 0 },
        EX_True or EX_False => new EX_False(),
        EX_VectorConst => new EX_VectorConst { Value = new FVector(0, 0, 0) },
        EX_RotationConst => new EX_RotationConst { Value = new FRotator(0, 0, 0) },
        EX_NameConst => new EX_NameConst { Value = FName.FromString(asset, "None") },
        EX_StringConst or EX_UnicodeStringConst => new EX_StringConst { Value = "" },
        EX_NoObject or EX_ObjectConst => new EX_NoObject(),
        EX_SoftObjectConst => new EX_SoftObjectConst { Value = new EX_StringConst { Value = "None" } },
        EX_ArrayConst a => new EX_ArrayConst { InnerProperty = a.InnerProperty, Elements = Array.Empty<KismetExpression>() },
        EX_StructConst sc => new EX_StructConst { Struct = sc.Struct, StructSize = sc.StructSize,
            Value = sc.Value.Select(v => ZeroStageConstant(asset, v)).ToArray() },
        _ => throw new InvalidDataException($"NativeStageCamera unexpected parameter expression {e.GetType().Name}")
    };

    static (FPackageIndex owner, string name) StageEventParameter(UAsset asset, FunctionExport fn)
    {
        var parameters = fn.LoadedProperties?.OfType<UAssetAPI.FieldTypes.FObjectProperty>().Where(p =>
            p.PropertyClass.IsImport() && p.PropertyClass.ToImport(asset).ObjectName.ToString() == "CPP_BtlSequencerEvent").ToArray();
        if (parameters == null || parameters.Length != 1)
            throw new InvalidDataException("NativeStageCamera requires one bound CPP_BtlSequencerEvent parameter");
        return (FPackageIndex.FromExport(asset.Exports.IndexOf(fn)), parameters[0].Name.ToString());
    }

    static KismetExpression[] StageCameraCode(UAsset asset, Usmap m, FunctionExport fn,
        EX_StructConst template, int unitId, FVector offset, out List<FPackageIndex> dependencies,
        int frames = 0, string easing = "Linear", bool participants = false)
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
        var add = Function("/Script/Engine", "KismetMathLibrary", "Add_VectorVector");
        var subtract = Function("/Script/Engine", "KismetMathLibrary", "Subtract_VectorVector");
        var eventClass = Class("/Script/mucha", "CPP_BtlSequencerEvent");
        var parameter = StageEventParameter(asset, fn);
        KismetPropertyPointer Property(FPackageIndex owner, params string[] path) =>
            new(new FFieldPath { Path = path.Select(n => FName.FromString(asset, n)).ToArray(), ResolvedOwner = owner });
        EX_CallMath Call(FPackageIndex f, params KismetExpression[] args) => new() { StackNode = f, Parameters = args };
        KismetExpression Event() => new EX_LocalVariable { Variable = Property(parameter.owner, parameter.name) };
        KismetExpression Unit() => Call(getter, new EX_IntConst { Value = unitId }, new EX_False());
        EX_Context_FailSilent Context(KismetExpression obj, KismetExpression rhs, KismetPropertyPointer result) =>
            new() { ObjectExpression = obj, ContextExpression = rhs, RValuePointer = result, PropertyType = 0,
                Offset = checked((uint)AuraBytes(asset, new[] { rhs }).size) };
        KismetExpression Member(string name) => Context(Event(), new EX_InstanceVariable { Variable = Property(eventClass, name) }, Property(eventClass, name));
        KismetExpression Targets() => Member("m_TargetUnitList");
        KismetExpression Target() => new EX_ArrayGetByRef { ArrayVariable = Targets(), ArrayIndex = new EX_IntZero() };
        KismetExpression Location(KismetExpression obj) => Context(obj,
            new EX_FinalFunction { StackNode = location, Parameters = Array.Empty<KismetExpression>() }, Property(location, "ReturnValue"));
        var props = SchemaProps(m, "BTL_SEQUENCE_PARAMETER");
        if (StructName(asset, template.Struct) != "BTL_SEQUENCE_PARAMETER" || template.Value.Length != props.Count)
            throw new InvalidDataException("NativeStageCamera requires complete native battle-event schema");
        int Index(string name) => props.FindIndex(p => p.Name == name) is var i && i >= 0 ? i : throw new InvalidDataException("Missing camera schema field " + name);
        var addIndex = Index("Camera_SetLookAtTarget_AddLocation");
        var sc = new EX_StructConst { Struct = template.Struct, StructSize = template.StructSize,
            Value = template.Value.Select((e, i) => i == addIndex ? new EX_VectorConst { Value = new FVector(0, 0, 0) } : ZeroStageConstant(asset, e)).ToArray() };
        SetPath(asset, m, sc, "EventType", "CameraSetLookAtTarget");
        SetPath(asset, m, sc, "Camera_SetLookAtTarget_Id", -1);
        if (frames > 0) {
            SetPath(asset, m, sc, "Camera_SetLookAtTarget_Frame", frames);
            SetPath(asset, m, sc, "Camera_SetLookAtTarget_EasingType", easing);
            SetPath(asset, m, sc, "Camera_SetLookAtTarget_EasingBlendExp", 2.0);
            SetPath(asset, m, sc, "Camera_SetLookAtTarget_EasingSteps", 1);
        }
        // CameraSetLookAtTarget(-1) adds this value to the selected target's
        // actor root. Half the root-to-root difference therefore addresses
        // their midpoint, in actual world space, without source-art offsets.
        sc.Value[addIndex] = participants
            ? Call(Function("/Script/Engine", "KismetMathLibrary", "Multiply_VectorFloat"),
                Call(subtract, Location(Unit()), Location(Target())), new EX_DoubleConst { Value = .5 })
            : Call(subtract, Call(add, Location(Unit()), new EX_VectorConst { Value = offset }), Location(Target()));
        var code = new KismetExpression[] {
            new EX_JumpIfNot { BooleanExpression = Call(valid, Event()) },
            new EX_JumpIfNot { BooleanExpression = Call(valid, Unit()) },
            new EX_JumpIfNot { BooleanExpression = Call(validIndex, Targets(), new EX_IntZero()) },
            new EX_JumpIfNot { BooleanExpression = Call(valid, Target()) },
            new EX_JumpIfNot { BooleanExpression = Call(valid, Member("m_pCamera")) },
            new EX_LocalVirtualFunction { VirtualFunctionName = FName.FromString(asset, "SeqBattleEvent"), Parameters = new KismetExpression[] { Event(), sc } },
            new EX_Return { ReturnExpression = new EX_Nothing() }, new EX_EndOfScript()
        };
        var end = checked((uint)AuraBytes(asset, code.Take(6)).size);
        foreach (var guard in code.OfType<EX_JumpIfNot>()) guard.CodeOffset = end;
        dependencies = refs;
        return code;
    }

    static int SetStageCamera(UAsset asset, Usmap m, JObject op, JObject set)
    {
        var v = set["NativeStageCamera_AddLocation"] as JObject;
        var hasPan = set["NativeStageCamera_Frame"] != null || set["NativeStageCamera_EasingType"] != null;
        if (op["match"] != null || set.Count != (hasPan ? 5 : 3) || set["NativeStageCamera_UnitId"]?.Type != JTokenType.Integer
            || set.Value<long>("NativeStageCamera_UnitId") is <= 0 or > int.MaxValue || v == null || v.Count != 3
            || new[] { "x", "y", "z" }.Any(k => v[k]?.Type is not (JTokenType.Float or JTokenType.Integer) || !double.IsFinite(v.Value<double>(k))))
            throw new InvalidDataException("NativeStageCamera requires a positive unit ID and finite {x,y,z} offset only");
        var frames = hasPan ? set.Value<int?>("NativeStageCamera_Frame") ?? -1 : 0;
        var easing = hasPan ? set.Value<string>("NativeStageCamera_EasingType") ?? "" : "Linear";
        if (hasPan && (set["NativeStageCamera_Frame"]?.Type != JTokenType.Integer || frames is < 1 or > 3600
            || easing is not ("Linear" or "EaseInOut" or "EaseOut" or "EaseIn")))
            throw new InvalidDataException("NativeStageCamera pan requires 1-3600 frames and a supported easing type");
        var selected = op.Value<string>("export");
        var matches = asset.Exports.OfType<FunctionExport>().Where(f => !string.IsNullOrEmpty(selected) && selected != "*"
            && (f.ObjectName.ToString() == selected || (asset.Exports.IndexOf(f) + 1).ToString() == selected)).ToArray();
        if (matches.Length != 1) throw new InvalidDataException("NativeStageCamera requires one explicit donor function");
        var fn = matches[0];
        var call = fn.ScriptBytecode?.OfType<EX_LocalVirtualFunction>().SingleOrDefault(c => c.VirtualFunctionName.ToString() == "SeqBattleEvent");
        if (call?.Parameters.Length != 2 || call.Parameters[0] is not EX_LocalVariable || call.Parameters[1] is not EX_StructConst template
            || StructName(asset, template.Struct) != "BTL_SEQUENCE_PARAMETER")
            throw new InvalidDataException("NativeStageCamera requires the native SeqBattleEvent donor binding");
        fn.ScriptBytecode = StageCameraCode(asset, m, fn, template, set.Value<int>("NativeStageCamera_UnitId"),
            new FVector(v.Value<double>("x"), v.Value<double>("y"), v.Value<double>("z")), out var dependencies, frames, easing);
        fn.ScriptBytecodeSize = AuraBytes(asset, fn.ScriptBytecode).size;
        fn.CreateBeforeSerializationDependencies ??= new List<FPackageIndex>();
        foreach (var dependency in dependencies)
            if (fn.CreateBeforeSerializationDependencies.All(d => d.Index != dependency.Index)) fn.CreateBeforeSerializationDependencies.Add(dependency);
        Console.WriteLine($"  ~ native stage camera {fn.ObjectName}: vision={set["NativeStageCamera_UnitId"]}, offset={v}");
        return 1;
    }

    static JObject? ReadStageCamera(UAsset asset, Usmap m, FunctionExport fn)
    {
        var expressions = fn.ScriptBytecode.SelectMany(Walk).ToArray();
        var getters = expressions.OfType<EX_FinalFunction>().Where(c => IsAuraGetter(asset, c)).ToArray();
        if (getters.Length == 0 || !expressions.OfType<EX_LocalVirtualFunction>().Any(c => c.VirtualFunctionName.ToString() == "SeqBattleEvent")) return null;
        var calls = fn.ScriptBytecode.OfType<EX_LocalVirtualFunction>().ToArray();
        if (calls.Length != 1 || calls[0].Parameters.Length != 2 || calls[0].Parameters[1] is not EX_StructConst sc
            || getters.Any(g => g.Parameters.Length != 2 || g.Parameters[0] is not EX_IntConst || g.Parameters[1] is not EX_False))
            throw new InvalidDataException("Malformed NativeStageCamera body");
        var unitId = ((EX_IntConst)getters[0].Parameters[0]).Value;
        var addCalls = expressions.OfType<EX_FinalFunction>().Where(c => IsCall(asset, c, "/Script/Engine", "KismetMathLibrary", "Add_VectorVector")).ToArray();
        if (unitId <= 0 || getters.Any(g => ((EX_IntConst)g.Parameters[0]).Value != unitId)
            || addCalls.Length != 1 || addCalls[0].Parameters.Length != 2 || addCalls[0].Parameters[1] is not EX_VectorConst v
            || !double.IsFinite(v.Value.X) || !double.IsFinite(v.Value.Y) || !double.IsFinite(v.Value.Z))
            throw new InvalidDataException("Malformed NativeStageCamera unit or offset");
        var props = SchemaProps(m, "BTL_SEQUENCE_PARAMETER");
        var frameIndex = props.FindIndex(p => p.Name == "Camera_SetLookAtTarget_Frame");
        var easingIndex = props.FindIndex(p => p.Name == "Camera_SetLookAtTarget_EasingType");
        if (sc.Value[frameIndex] is not EX_IntConst frameValue || frameValue.Value is < 0 or > 3600)
            throw new InvalidDataException("Malformed NativeStageCamera pan duration");
        var frames = frameValue.Value;
        var easing = frames > 0 ? ExprToJson(asset, m, sc.Value[easingIndex], props[easingIndex].PropertyData, false)?.Value<string>() ?? "" : "Linear";
        if (easing is not ("Linear" or "EaseInOut" or "EaseOut" or "EaseIn"))
            throw new InvalidDataException("Malformed NativeStageCamera pan easing");
        var before = asset.Imports.Count;
        var expected = StageCameraCode(asset, m, fn, sc, unitId, v.Value, out _, frames, easing);
        var actualBytes = AuraBytes(asset, fn.ScriptBytecode); var expectedBytes = AuraBytes(asset, expected);
        if (before != asset.Imports.Count || fn.ScriptBytecodeSize != expectedBytes.size || actualBytes.size != expectedBytes.size
            || !actualBytes.bytes.SequenceEqual(expectedBytes.bytes))
            throw new InvalidDataException("Malformed NativeStageCamera guards, target binding, native camera fields or VM offsets");
        var result = new JObject { ["EventType"] = StageCameraEvent, ["NativeStageCamera_UnitId"] = unitId,
            ["NativeStageCamera_AddLocation"] = new JObject { ["x"] = v.Value.X, ["y"] = v.Value.Y, ["z"] = v.Value.Z } };
        if (frames > 0) { result["NativeStageCamera_Frame"] = frames; result["NativeStageCamera_EasingType"] = easing; }
        return result;
    }

    const string StageVisibilityEvent = "NativeStageVisibility";
    const string StageActorsLocal = "FFBE_StageActors";
    const string StageHiddenTagPrefix = "FFBE_StageHidden_";

    // Actor-level hiding isolates the scene without the native FriendUnits
    // switch also disabling the acting vision. A scoped tag records only the
    // actors we hid; previously hidden actors are never revealed on cleanup.
    static KismetExpression[] StageVisibilityCode(UAsset asset, FunctionExport fn, int unitId,
        bool restore, bool addLocal, out List<FPackageIndex> dependencies)
    {
        var refs = new List<FPackageIndex>();
        FPackageIndex Import(string package, string name, string kind, FPackageIndex outer) {
            var i = asset.Imports.FindIndex(v => v.ObjectName.ToString() == name && v.OuterIndex.Index == outer.Index);
            if (i < 0) { asset.Imports.Add(new Import(package, kind, outer, name, false, asset)); i = asset.Imports.Count - 1; }
            var result = FPackageIndex.FromImport(i);
            if (refs.All(v => v.Index != result.Index)) refs.Add(result);
            return result;
        }
        FPackageIndex Package(string n) => Import("/Script/CoreUObject", n, "Package", new FPackageIndex(0));
        FPackageIndex Class(string p, string n) => Import("/Script/CoreUObject", n, "Class", Package(p));
        FPackageIndex Function(string p, string c, string n) => Import("/Script/CoreUObject", n, "Object", Class(p, c));
        var actorClass = Class("/Script/Engine", "Actor");
        var battleClass = Class("/Script/mucha", "CPP_BtlUnit");
        var eventClass = Class("/Script/mucha", "CPP_BtlSequencerEvent");
        var getter = Function("/Script/mucha", "CPP_BFL_Battle", AuraGetter);
        var valid = Function("/Script/Engine", "KismetSystemLibrary", "IsValid");
        var enumerate = Function("/Script/Engine", "GameplayStatics", "GetAllActorsOfClass");
        var validIndex = Function("/Script/Engine", "KismetArrayLibrary", "Array_IsValidIndex");
        var lastIndex = Function("/Script/Engine", "KismetArrayLibrary", "Array_LastIndex");
        var remove = Function("/Script/Engine", "KismetArrayLibrary", "Array_Remove");
        var add = Function("/Script/Engine", "KismetArrayLibrary", "Array_Add");
        var removeItem = Function("/Script/Engine", "KismetArrayLibrary", "Array_RemoveItem");
        var notEqual = Function("/Script/Engine", "KismetMathLibrary", "NotEqual_ObjectObject");
        var not = Function("/Script/Engine", "KismetMathLibrary", "Not_PreBool");
        var setHidden = Function("/Script/Engine", "Actor", "SetActorHiddenInGame");
        var hasTag = Function("/Script/Engine", "Actor", "ActorHasTag");
        var parameter = StageEventParameter(asset, fn);
        var local = fn.LoadedProperties.SingleOrDefault(p => p.Name.ToString() == StageActorsLocal);
        if (local == null && addLocal) {
            local = new UAssetAPI.FieldTypes.FArrayProperty {
                Name = FName.FromString(asset, StageActorsLocal), SerializedType = FName.FromString(asset, "ArrayProperty"),
                ArrayDim = UAssetAPI.FieldTypes.EArrayDim.TArray, ElementSize = 16,
                RepNotifyFunc = FName.FromString(asset, "None"),
                Inner = new UAssetAPI.FieldTypes.FObjectProperty {
                    Name = FName.FromString(asset, StageActorsLocal), SerializedType = FName.FromString(asset, "ObjectProperty"),
                    ArrayDim = UAssetAPI.FieldTypes.EArrayDim.TArray, ElementSize = 8,
                    PropertyClass = actorClass, RepNotifyFunc = FName.FromString(asset, "None") }
            };
            fn.LoadedProperties = fn.LoadedProperties.Append(local).ToArray();
        }
        if (addLocal) fn.FunctionFlags |= EFunctionFlags.FUNC_HasDefaults;
        if (local is not UAssetAPI.FieldTypes.FArrayProperty arr || arr.SerializedType.ToString() != "ArrayProperty"
            || arr.ElementSize != 16 || arr.ArrayDim != UAssetAPI.FieldTypes.EArrayDim.TArray || arr.PropertyFlags != 0
            || arr.Inner is not UAssetAPI.FieldTypes.FObjectProperty inner
            || inner.PropertyClass.Index != actorClass.Index || inner.ElementSize != 8 || inner.ArrayDim != UAssetAPI.FieldTypes.EArrayDim.TArray
            || !fn.FunctionFlags.HasFlag(EFunctionFlags.FUNC_HasDefaults))
            throw new InvalidDataException("Malformed NativeStageVisibility actor array local");
        KismetPropertyPointer Property(FPackageIndex owner, params string[] path) =>
            new(new FFieldPath { Path = path.Select(n => FName.FromString(asset, n)).ToArray(), ResolvedOwner = owner });
        EX_CallMath Call(FPackageIndex f, params KismetExpression[] args) => new() { StackNode = f, Parameters = args };
        EX_Context_FailSilent Context(KismetExpression obj, KismetExpression rhs, KismetPropertyPointer? result = null) =>
            new() { ObjectExpression = obj, ContextExpression = rhs, RValuePointer = result ?? Property(new FPackageIndex(0)),
                PropertyType = 0, Offset = checked((uint)AuraBytes(asset, new[] { rhs }).size) };
        KismetExpression Event() => new EX_LocalVariable { Variable = Property(parameter.owner, parameter.name) };
        KismetExpression Member(string n) => Context(Event(), new EX_InstanceVariable { Variable = Property(eventClass, n) }, Property(eventClass, n));
        KismetExpression Unit() => Call(getter, new EX_IntConst { Value = unitId }, new EX_False());
        KismetExpression Actors() => new EX_LocalVariable { Variable = Property(parameter.owner, StageActorsLocal) };
        KismetExpression Current() => new EX_ArrayGetByRef { ArrayVariable = Actors(), ArrayIndex = Call(lastIndex, Actors()) };
        KismetExpression Target() => new EX_ArrayGetByRef { ArrayVariable = Member("m_TargetUnitList"), ArrayIndex = new EX_IntZero() };
        KismetExpression Tags() => Context(Current(), new EX_InstanceVariable { Variable = Property(actorClass, "Tags") }, Property(actorClass, "Tags"));
        KismetExpression Tag() => new EX_NameConst { Value = FName.FromString(asset, StageHiddenTagPrefix + unitId) };
        KismetExpression Invoke(FPackageIndex f, params KismetExpression[] args) => Context(Current(), new EX_FinalFunction { StackNode = f, Parameters = args });
        var code = new List<KismetExpression>();
        var exitGuards = new List<EX_JumpIfNot>(); var nextGuards = new List<EX_JumpIfNot>();
        void Guard(KismetExpression condition, List<EX_JumpIfNot> guards) { var g = new EX_JumpIfNot { BooleanExpression = condition }; guards.Add(g); code.Add(g); }
        Guard(Call(valid, Event()), exitGuards);
        Guard(Call(valid, Member("m_pActionUnit")), exitGuards);
        if (!restore) {
            Guard(Call(valid, Unit()), exitGuards);
            Guard(Call(validIndex, Member("m_TargetUnitList"), new EX_IntZero()), exitGuards);
            Guard(Call(valid, Target()), exitGuards);
        }
        code.Add(Call(enumerate, Member("m_pActionUnit"), new EX_ObjectConst { Value = battleClass }, Actors()));
        var loop = checked((uint)AuraBytes(asset, code).size);
        Guard(Call(validIndex, Actors(), new EX_IntZero()), exitGuards);
        Guard(Call(valid, Current()), nextGuards);
        if (!restore) {
            Guard(Call(notEqual, Current(), Unit()), nextGuards);
            Guard(Call(notEqual, Current(), Target()), nextGuards);
            Guard(Call(not, Context(Current(), new EX_InstanceVariable { Variable = Property(actorClass, "bHidden") }, Property(actorClass, "bHidden"))), nextGuards);
            code.Add(Call(add, Tags(), Tag()));
            code.Add(Invoke(setHidden, new EX_True()));
        } else {
            Guard(Context(Current(), new EX_FinalFunction { StackNode = hasTag, Parameters = new[] { Tag() } }, Property(hasTag, "ReturnValue")), nextGuards);
            code.Add(Invoke(setHidden, new EX_False()));
            code.Add(Call(removeItem, Tags(), Tag()));
        }
        var next = checked((uint)AuraBytes(asset, code).size);
        code.Add(Call(remove, Actors(), Call(lastIndex, Actors())));
        code.Add(new EX_Jump { CodeOffset = loop });
        var end = checked((uint)AuraBytes(asset, code).size);
        foreach (var g in exitGuards) g.CodeOffset = end;
        foreach (var g in nextGuards) g.CodeOffset = next;
        code.Add(new EX_Return { ReturnExpression = new EX_Nothing() }); code.Add(new EX_EndOfScript());
        dependencies = refs; return code.ToArray();
    }

    static int SetStageVisibility(UAsset asset, JObject op, JObject set)
    {
        if (op["match"] != null || set.Count != 3 || set["NativeStageVisibility_UnitId"]?.Type != JTokenType.Integer
            || set.Value<long>("NativeStageVisibility_UnitId") is <= 0 or > int.MaxValue
            || set["NativeStageVisibility_Restore"]?.Type != JTokenType.Boolean)
            throw new InvalidDataException("NativeStageVisibility requires a positive vision ID and boolean Restore");
        var selected = op.Value<string>("export");
        var matches = asset.Exports.OfType<FunctionExport>().Where(f => !string.IsNullOrEmpty(selected) && selected != "*"
            && (f.ObjectName.ToString() == selected || (asset.Exports.IndexOf(f) + 1).ToString() == selected)).ToArray();
        if (matches.Length != 1) throw new InvalidDataException("NativeStageVisibility requires one explicit donor function");
        var fn = matches[0];
        if (!fn.ScriptBytecode.SelectMany(Walk).OfType<EX_StructConst>().Any(sc => StructName(asset, sc.Struct) == "BTL_SEQUENCE_PARAMETER")
            && !fn.ScriptBytecode.SelectMany(Walk).OfType<EX_FinalFunction>().Any(c => IsCall(asset, c, "/Script/Engine", "GameplayStatics", "GetAllActorsOfClass")))
            throw new InvalidDataException("NativeStageVisibility requires a battle-event donor body");
        fn.ScriptBytecode = StageVisibilityCode(asset, fn, set.Value<int>("NativeStageVisibility_UnitId"),
            set.Value<bool>("NativeStageVisibility_Restore"), true, out var dependencies);
        fn.ScriptBytecodeSize = AuraBytes(asset, fn.ScriptBytecode).size;
        fn.CreateBeforeSerializationDependencies ??= new List<FPackageIndex>();
        foreach (var dependency in dependencies)
            if (fn.CreateBeforeSerializationDependencies.All(d => d.Index != dependency.Index)) fn.CreateBeforeSerializationDependencies.Add(dependency);
        return 1;
    }

    static JObject? ReadStageVisibility(UAsset asset, FunctionExport fn)
    {
        if (!fn.LoadedProperties.Any(p => p.Name.ToString() == StageActorsLocal)) return null;
        var expressions = fn.ScriptBytecode.SelectMany(Walk).ToArray();
        var tags = expressions.OfType<EX_NameConst>().Select(n => n.Value.ToString()).Where(n => n.StartsWith(StageHiddenTagPrefix)).Distinct().ToArray();
        var setters = expressions.OfType<EX_FinalFunction>().Where(c => IsCall(asset, c, "/Script/Engine", "Actor", "SetActorHiddenInGame")).ToArray();
        if (tags.Length != 1 || !int.TryParse(tags[0][StageHiddenTagPrefix.Length..], out var unitId) || unitId <= 0
            || setters.Length != 1 || setters[0].Parameters.Length != 1 || setters[0].Parameters[0] is not (EX_True or EX_False))
            throw new InvalidDataException("Malformed NativeStageVisibility identity or setter");
        var restore = setters[0].Parameters[0] is EX_False; var before = asset.Imports.Count;
        var expected = StageVisibilityCode(asset, fn, unitId, restore, false, out _);
        var a = AuraBytes(asset, fn.ScriptBytecode); var b = AuraBytes(asset, expected);
        if (before != asset.Imports.Count || fn.ScriptBytecodeSize != b.size || a.size != b.size || !a.bytes.SequenceEqual(b.bytes))
            throw new InvalidDataException("Malformed NativeStageVisibility guards, actor selection, state markers or loop offsets");
        return new JObject { ["EventType"] = StageVisibilityEvent, ["NativeStageVisibility_UnitId"] = unitId,
            ["NativeStageVisibility_Restore"] = restore };
    }

    // ---------------------------------------------------------------- schema helpers
    static List<UsmapProperty> SchemaProps(Usmap m, string structName)
    {
        var list = new List<UsmapProperty>();
        if (!m.Schemas.TryGetValue(structName, out var schema)) return list;
        if (!string.IsNullOrEmpty(schema.SuperType)) list.AddRange(SchemaProps(m, schema.SuperType));
        var own = schema.Properties.Values.OrderBy(p => p.SchemaIndex).ToList();
        foreach (var p in own)
            for (int i = 0; i < Math.Max(1, (int)p.ArraySize); i++) list.Add(p);   // static arrays emit one constant per element
        return list;
    }

    // UsmapEnum's value container differs between UAssetAPI versions: read it reflectively (dictionary or list)
    static Dictionary<long, string> EnumValues(object usmapEnum)
    {
        var res = new Dictionary<long, string>();
        var t = usmapEnum.GetType();
        object? val = null;
        foreach (var n in new[] { "Values", "Names", "Entries" })
        {
            var f = t.GetField(n); if (f != null) { val = f.GetValue(usmapEnum); break; }
            var pr = t.GetProperty(n); if (pr != null) { val = pr.GetValue(usmapEnum); break; }
        }
        if (val is System.Collections.IDictionary dict) foreach (System.Collections.DictionaryEntry de in dict) res[Convert.ToInt64(de.Key)] = de.Value?.ToString() ?? "";
        else if (val is System.Collections.IEnumerable en) { long i = 0; foreach (var x in en) res[i++] = x?.ToString() ?? ""; }
        return res;
    }

    static Dictionary<long, string>? EnumOf(Usmap m, string enumName)
    {
        if (m.EnumMap == null) return null;
        foreach (System.Collections.DictionaryEntry de in (System.Collections.IDictionary)m.EnumMap)
            if (de.Key?.ToString() == enumName && de.Value != null) return EnumValues(de.Value);
        return null;
    }

    static string? EnumName(Usmap m, UsmapPropertyData? pd, int value)
    {
        var enumName = (pd as UsmapEnumData)?.Name;
        if (enumName == null) return null;
        var e = EnumOf(m, enumName);
        return e != null && e.TryGetValue(value, out var s) ? s : null;
    }

    static int EnumValue(Usmap m, UsmapPropertyData? pd, string name)
    {
        var enumName = (pd as UsmapEnumData)?.Name ?? throw new Exception($"'{name}': not an enum field");
        var e = EnumOf(m, enumName) ?? throw new Exception($"enum {enumName} not in usmap");
        foreach (var kv in e) if (kv.Value == name || kv.Value.EndsWith("::" + name) || name.EndsWith("::" + kv.Value)) return (int)kv.Key;
        throw new Exception($"enum {enumName} has no value '{name}'");
    }

    static string StructName(UAsset asset, FPackageIndex idx) =>
        idx.IsImport() ? idx.ToImport(asset).ObjectName.ToString() : idx.IsExport() ? idx.ToExport(asset).ObjectName.ToString() : "?";

    // ---------------------------------------------------------------- generic tree walk (reflection over expression fields)
    static IEnumerable<KismetExpression> Children(KismetExpression e)
    {
        foreach (var f in e.GetType().GetFields())
        {
            if (typeof(KismetExpression).IsAssignableFrom(f.FieldType)) { if (f.GetValue(e) is KismetExpression c) yield return c; }
            else if (f.FieldType == typeof(KismetExpression[])) { if (f.GetValue(e) is KismetExpression[] arr) foreach (var c in arr) if (c != null) yield return c; }
        }
        foreach (var p in e.GetType().GetProperties())
        {
            if (p.GetIndexParameters().Length > 0) continue;
            if (typeof(KismetExpression).IsAssignableFrom(p.PropertyType)) { if (p.GetValue(e) is KismetExpression c) yield return c; }
            else if (p.PropertyType == typeof(KismetExpression[])) { if (p.GetValue(e) is KismetExpression[] arr) foreach (var c in arr) if (c != null) yield return c; }
        }
    }

    static IEnumerable<KismetExpression> Walk(KismetExpression e)
    {
        yield return e;
        foreach (var c in Children(e)) foreach (var d in Walk(c)) yield return d;
    }

    // ---------------------------------------------------------------- dump
    public static JObject Dump(UAsset asset, Usmap m, bool skipDefaults = true)
    {
        var res = new JObject();
        for (int i = 0; i < asset.Exports.Count; i++)
        {
            if (asset.Exports[i] is not FunctionExport fn || fn.ScriptBytecode == null) continue;
            var screenPlane = ReadScreenPlane(asset, fn);
            if (screenPlane != null) { res[$"{i + 1}:{fn.ObjectName}"] = screenPlane; continue; }
            var rootSnapshot = ReadRootSnapshot(asset, fn);
            if (rootSnapshot != null) { res[$"{i + 1}:{fn.ObjectName}"] = rootSnapshot; continue; }
            var resonanceVisibility = ReadResonanceVisibility(asset, fn);
            if (resonanceVisibility != null) { res[$"{i + 1}:{fn.ObjectName}"] = resonanceVisibility; continue; }
            var stageVisibility = ReadStageVisibility(asset, fn);
            if (stageVisibility != null) { res[$"{i + 1}:{fn.ObjectName}"] = stageVisibility; continue; }
            var participantCamera = ReadParticipantCamera(asset, m, fn);
            if (participantCamera != null) { res[$"{i + 1}:{fn.ObjectName}"] = participantCamera; continue; }
            var groundApproach = ReadGroundApproach(asset, m, fn);
            if (groundApproach != null) { res[$"{i + 1}:{fn.ObjectName}"] = groundApproach; continue; }
            var stageCamera = ReadStageCamera(asset, m, fn);
            if (stageCamera != null) { res[$"{i + 1}:{fn.ObjectName}"] = stageCamera; continue; }
            var aura = ReadAura(asset, fn);
            if (aura != null)
            {
                res[$"{i + 1}:{fn.ObjectName}"] = aura;
                continue;
            }
            var consts = fn.ScriptBytecode.SelectMany(Walk).OfType<EX_StructConst>().Where(sc => sc.Struct.IsImport() || sc.Struct.IsExport()).ToList();
            // only top-level struct constants (nested ones are reached through their parent)
            var nested = new HashSet<KismetExpression>(consts.SelectMany(c => Children(c)).SelectMany(Walk));
            var tops = consts.Where(c => !nested.Contains(c)).ToList();
            if (tops.Count == 0) continue;
            var arr = new JArray();
            foreach (var sc in tops) arr.Add(StructToJson(asset, m, sc, skipDefaults));
            res[$"{i + 1}:{fn.ObjectName}"] = arr.Count == 1 ? arr[0] : arr;
        }
        return res;
    }

    static JToken StructToJson(UAsset asset, Usmap m, EX_StructConst sc, bool skipDefaults)
    {
        var name = StructName(asset, sc.Struct);
        var props = SchemaProps(m, name);
        var o = new JObject { ["$struct"] = name };
        if (props.Count != sc.Value.Length) o["$warning"] = $"schema has {props.Count} fields, constant has {sc.Value.Length} values";
        for (int i = 0; i < sc.Value.Length; i++)
        {
            var pname = i < props.Count ? props[i].Name : $"#{i}";
            var pd = i < props.Count ? props[i].PropertyData : null;
            var v = ExprToJson(asset, m, sc.Value[i], pd, skipDefaults);
            if (v == null) continue;
            if (skipDefaults && IsDefault(v) && pname != "EventType") continue;
            o[pname] = v;
        }
        return o;
    }

    static bool IsDefault(JToken v) => v.Type switch
    {
        JTokenType.Integer => (long)v == 0,
        JTokenType.Float => (double)v == 0,
        JTokenType.Boolean => !(bool)v,
        JTokenType.String => (string)v! == "" || (string)v! == "None",
        JTokenType.Null => true,
        JTokenType.Array => ((JArray)v).Count == 0,
        JTokenType.Object => ((JObject)v).Properties().All(p => p.Name == "$struct" || IsDefault(p.Value)),
        _ => false
    };

    static JToken? ExprToJson(UAsset asset, Usmap m, KismetExpression e, UsmapPropertyData? pd, bool skipDefaults)
    {
        switch (e)
        {
            case EX_StructConst sc: return StructToJson(asset, m, sc, skipDefaults);
            case EX_FloatConst f: return f.Value;
            case EX_DoubleConst d: return d.Value;
            case EX_IntConst n: return n.Value;
            case EX_Int64Const n64: return n64.Value;
            case EX_UInt64Const u64: return u64.Value;
            case EX_ByteConst b: return EnumName(m, pd, b.Value) ?? (JToken)b.Value;
            case EX_IntConstByte ib: return EnumName(m, pd, ib.Value) ?? (JToken)ib.Value;
            case EX_True: return true;
            case EX_False: return false;
            case EX_StringConst s: return s.Value;
            case EX_UnicodeStringConst us: return us.Value;
            case EX_NameConst nm: return nm.Value?.ToString() ?? "None";
            case EX_ObjectConst oc:
                if (oc.Value.IsImport()) { var imp = oc.Value.ToImport(asset); return "import:" + imp.ObjectName; }
                if (oc.Value.IsExport()) return "export:" + oc.Value.ToExport(asset).ObjectName;
                return null;
            case EX_NoObject: return null;
            case EX_Nothing: return null;
            case EX_VectorConst vc: return new JObject { ["x"] = vc.Value.X, ["y"] = vc.Value.Y, ["z"] = vc.Value.Z };
            case EX_RotationConst rc: return new JObject { ["pitch"] = rc.Value.Pitch, ["yaw"] = rc.Value.Yaw, ["roll"] = rc.Value.Roll };
            case EX_ArrayConst ac:
            {
                var inner = (pd as UsmapArrayData)?.InnerType;
                var arr = new JArray();
                foreach (var el in ac.Elements) { var v = ExprToJson(asset, m, el, inner, skipDefaults); arr.Add(v ?? JValue.CreateNull()); }
                return arr;
            }
            case EX_TextConst: return "<text>";
            case EX_SoftObjectConst so: return so.Value is EX_StringConst ss ? "soft:" + ss.Value : "<soft>";
            default: return "<" + e.GetType().Name + ">";
        }
    }

    // ---------------------------------------------------------------- edit
    // op: { "asset": rel, "export": "<function export name>" | "*", "match": { "Field": value }, "set": { "Field.Sub": value, ... } }
    // the function's top-level struct constant is edited; "match" selects functions whose constant has those values (dump form).
    public static int Edit(UAsset asset, Usmap m, JObject op)
    {
        var exportSel = op.Value<string>("export") ?? "*";
        var match = op["match"] as JObject;
        var set = op["set"] as JObject ?? new JObject();
        if (set.Value<string>("EventType") == StageCameraEvent) return SetStageCamera(asset, m, op, set);
        if (set.Value<string>("EventType") == ParticipantCameraEvent) return SetParticipantCamera(asset, m, op, set);
        if (set.Value<string>("EventType") == GroundApproachEvent) return SetGroundApproach(asset, m, op, set);
        if (set.Value<string>("EventType") == ScreenPlaneEvent) return SetScreenPlane(asset, op, set);
        if (set.Value<string>("EventType") == RootSnapshotEvent) return SetRootSnapshot(asset, op, set);
        if (set.Value<string>("EventType") == ResonanceVisibilityEvent) return SetResonanceVisibility(asset, op, set);
        if (set.Value<string>("EventType") == AuraEvent) return SetAuraVisibility(asset, op, set);
        if (set.Value<string>("EventType") == StageVisibilityEvent) return SetStageVisibility(asset, op, set);
        int edited = 0;
        for (int i = 0; i < asset.Exports.Count; i++)
        {
            if (asset.Exports[i] is not FunctionExport fn || fn.ScriptBytecode == null) continue;
            if (exportSel != "*" && fn.ObjectName.ToString() != exportSel && (i + 1).ToString() != exportSel) continue;
            var consts = fn.ScriptBytecode.SelectMany(Walk).OfType<EX_StructConst>().ToList();
            var nested = new HashSet<KismetExpression>(consts.SelectMany(c => Children(c)).SelectMany(Walk));
            foreach (var sc in consts.Where(c => !nested.Contains(c)))
            {
                if (match != null)
                {
                    var dump = (JObject)StructToJson(asset, m, sc, false);
                    bool ok = true;
                    foreach (var kv in match)
                    {
                        var cur = dump.SelectToken(kv.Key);
                        if (cur == null) { ok = false; break; }
                        if (JToken.DeepEquals(cur, kv.Value)) continue;
                        // dump form vs. friendly form: "import:NS_EF_X" / "soft:/Game/.../X.X" match "NS_EF_X"
                        string a = cur.ToString(), b = kv.Value!.ToString();
                        string Strip(string x) { var i = x.IndexOf(':'); x = i >= 0 && i < 8 ? x[(i + 1)..] : x; var j = Math.Max(x.LastIndexOf('/'), x.LastIndexOf('.')); return j >= 0 ? x[(j + 1)..] : x; }
                        if (a == b || Strip(a) == Strip(b) || a.EndsWith(b)) continue;
                        ok = false; break;
                    }
                    if (!ok) continue;
                }
                int delta = 0;
                foreach (var kv in set) delta += SetPath(asset, m, sc, kv.Key, kv.Value!);
                fn.ScriptBytecodeSize += delta;   // BytecodeBufferSize = in-memory size, the loader stops exactly there
                edited++;
                Console.WriteLine($"  ~ bytecode {fn.ObjectName} (#{i + 1}): {string.Join(", ", set.Properties().Select(p => p.Name))}{(delta != 0 ? $" (size {delta:+#;-#;0})" : "")}");
            }
        }
        return edited;
    }

    // returns the in-memory size delta
    static int SetPath(UAsset asset, Usmap m, EX_StructConst sc, string path, JToken value)
    {
        var parts = path.Split('.', 2);
        var head = parts[0]; int? index = null;
        var br = head.IndexOf('[');
        if (br >= 0) { index = int.Parse(head[(br + 1)..^1]); head = head[..br]; }
        var props = SchemaProps(m, StructName(asset, sc.Struct));
        var fi = props.FindIndex(p => p.Name == head);
        if (fi < 0 || fi >= sc.Value.Length) throw new Exception($"field '{head}' not found in {StructName(asset, sc.Struct)} (have: {string.Join(", ", props.Select(p => p.Name).Take(40))} ...)");
        var pd = props[fi].PropertyData;
        if (index != null)
        {
            var ac = sc.Value[fi] as EX_ArrayConst ?? throw new Exception($"'{head}' is not an array constant");
            if (index >= ac.Elements.Length) throw new Exception($"'{head}[{index}]' out of range ({ac.Elements.Length})");
            var inner = (pd as UsmapArrayData)?.InnerType;
            if (parts.Length == 2)
            {
                var child = ac.Elements[index.Value] as EX_StructConst ?? throw new Exception($"'{head}[{index}]' is not a struct");
                return SetPath(asset, m, child, parts[1], value);
            }
            var (ne, d) = Replace(asset, m, ac.Elements[index.Value], inner, value);
            ac.Elements[index.Value] = ne; return d;
        }
        if (parts.Length == 2)
        {
            var child = sc.Value[fi] as EX_StructConst ?? throw new Exception($"'{head}' is not a struct constant");
            return SetPath(asset, m, child, parts[1], value);
        }
        var (nexpr, delta) = Replace(asset, m, sc.Value[fi], pd, value);
        sc.Value[fi] = nexpr; return delta;
    }

    static int MemSize(KismetExpression e) => e switch
    {
        EX_StringConst s => 1 + (s.Value?.Length ?? 0) + 1,
        EX_UnicodeStringConst u => 1 + 2 * ((u.Value?.Length ?? 0) + 1),
        EX_ObjectConst => 1 + 8,
        EX_NoObject => 1,
        EX_True => 1, EX_False => 1, EX_Nothing => 1,
        EX_FloatConst => 5, EX_IntConst => 5, EX_ByteConst => 2, EX_IntConstByte => 2, EX_DoubleConst => 9,
        _ => throw new Exception($"cannot size {e.GetType().Name}")
    };

    static (KismetExpression, int) Replace(UAsset asset, Usmap m, KismetExpression cur, UsmapPropertyData? pd, JToken v)
    {
        KismetExpression ne;
        switch (cur)
        {
            case EX_FloatConst f: f.Value = v.Value<float>(); return (f, 0);
            case EX_DoubleConst d: d.Value = v.Value<double>(); return (d, 0);
            case EX_IntConst n: n.Value = v.Value<int>(); return (n, 0);
            case EX_ByteConst b: b.Value = (byte)(v.Type == JTokenType.String ? EnumValue(m, pd, v.Value<string>()!) : v.Value<int>()); return (b, 0);
            case EX_IntConstByte ib: ib.Value = (byte)(v.Type == JTokenType.String ? EnumValue(m, pd, v.Value<string>()!) : v.Value<int>()); return (ib, 0);
            case EX_StringConst or EX_UnicodeStringConst:
            {
                var s = v.Value<string>() ?? "";
                ne = s.All(c => c < 128) ? new EX_StringConst { Value = s } : new EX_UnicodeStringConst { Value = s };
                return (ne, MemSize(ne) - MemSize(cur));
            }
            case EX_SoftObjectConst soft:
            {
                // The VM expects the soft-object opcode followed by its string
                // expression. Preserve the wrapper and account for string growth.
                if (v.Type != JTokenType.String || soft.Value is not (EX_StringConst or EX_UnicodeStringConst))
                    throw new Exception("soft object field requires a path string");
                var path = v.Value<string>()!;
                if (path.StartsWith("soft:", StringComparison.Ordinal)) path = path[5..];
                var (value, delta) = Replace(asset, m, soft.Value, null, new JValue(path));
                soft.Value = value;
                return (soft, delta);
            }
            case EX_NameConst nm: nm.Value = FName.FromString(asset, v.Value<string>()!); return (nm, 0);
            case EX_VectorConst vc:
            {
                var o = v as JObject ?? throw new Exception("vector field needs {x,y,z}");
                vc.Value = new FVector(o.Value<double?>("x") ?? vc.Value.X, o.Value<double?>("y") ?? vc.Value.Y, o.Value<double?>("z") ?? vc.Value.Z); return (vc, 0);
            }
            case EX_True or EX_False:
                ne = v.Value<bool>() ? new EX_True() : new EX_False(); return (ne, 0);
            case EX_ObjectConst or EX_NoObject:
            {
                if (v.Type == JTokenType.Null) { ne = new EX_NoObject(); return (ne, MemSize(ne) - MemSize(cur)); }
                string path; string? cls = null;
                if (v is JObject vo) { path = vo.Value<string>("path")!; cls = vo.Value<string>("class"); }
                else path = v.Value<string>()!;
                if (cls == null && cur is EX_ObjectConst oc && oc.Value.IsImport()) cls = oc.Value.ToImport(asset).ClassName.ToString();
                var idx = Patch.FindOrAddImport(asset, path, cls ?? "NiagaraSystem");
                ne = new EX_ObjectConst { Value = idx }; return (ne, MemSize(ne) - MemSize(cur));
            }
            case EX_StructConst sc:
            {
                var o = v as JObject ?? throw new Exception("struct field needs an object");
                int delta = 0; foreach (var kv in o) delta += SetPath(asset, m, sc, kv.Key, kv.Value!);
                return (sc, delta);
            }
            default: throw new Exception($"cannot set a {cur.GetType().Name}");
        }
    }
}
