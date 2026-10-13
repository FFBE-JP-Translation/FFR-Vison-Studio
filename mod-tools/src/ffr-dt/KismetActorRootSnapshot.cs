using Newtonsoft.Json.Linq;
using UAssetAPI;
using UAssetAPI.UnrealTypes;
using UAssetAPI.ExportTypes;
using UAssetAPI.FieldTypes;
using UAssetAPI.Kismet.Bytecode;
using UAssetAPI.Kismet.Bytecode.Expressions;

public static partial class KismetTools
{
    const string RootSnapshotEvent = "NativeActorRootSnapshot";
    const string RootPrefix = "FFBE_Root_";

    static void ValidateRootSnapshot(JObject set)
    {
        if (set.Count != 5 + (set.ContainsKey("NativeActorRootSnapshot_TargetIndex") ? 1 : 0)
                + (set.ContainsKey("NativeActorRootSnapshot_HeightFraction") ? 1 : 0)
                + (set.ContainsKey("NativeActorRootSnapshot_SortLayer") ? 1 : 0)
                + (set.ContainsKey("NativeActorRootSnapshot_PreservePlacement") ? 1 : 0)
            || (set.ContainsKey("NativeActorRootSnapshot_PreservePlacement") &&
                (set["NativeActorRootSnapshot_PreservePlacement"]?.Type != JTokenType.Boolean
                 || !set.ContainsKey("NativeActorRootSnapshot_SortLayer") || set.ContainsKey("NativeActorRootSnapshot_HeightFraction")))
            || (set.ContainsKey("NativeActorRootSnapshot_HeightFraction") &&
                (set["NativeActorRootSnapshot_HeightFraction"]?.Type is not (JTokenType.Integer or JTokenType.Float)
                 || !double.IsFinite(set.Value<double>("NativeActorRootSnapshot_HeightFraction"))
                 || set.Value<double>("NativeActorRootSnapshot_HeightFraction") is < 0 or > 1))
            || (set.ContainsKey("NativeActorRootSnapshot_SortLayer") &&
                (set["NativeActorRootSnapshot_SortLayer"]?.Type != JTokenType.Integer
                 || set.Value<int>("NativeActorRootSnapshot_SortLayer") is not (-1 or -2)))
            || (set.ContainsKey("NativeActorRootSnapshot_TargetIndex") &&
                (set["NativeActorRootSnapshot_TargetIndex"]?.Type != JTokenType.Integer
                 || set.Value<int>("NativeActorRootSnapshot_TargetIndex") is < 0 or > 15
                 || !set.Value<bool>("NativeActorRootSnapshot_IsTarget")))
            || set.Value<string>("EventType") != RootSnapshotEvent
            || set["NativeActorRootSnapshot_Id"]?.Type != JTokenType.String
            || set.Value<string>("NativeActorRootSnapshot_Id") is not { Length: > 0 and <= 128 } id
            || id.Any(c => !(char.IsAsciiLetterOrDigit(c) || c == '_'))
            || set["NativeActorRootSnapshot_UnitId"]?.Type != JTokenType.Integer
            || set.Value<long>("NativeActorRootSnapshot_UnitId") is <= 0 or > int.MaxValue
            || set["NativeActorRootSnapshot_IsTarget"]?.Type != JTokenType.Boolean
            || set["NativeActorRootSnapshot_Depth"]?.Type is not (JTokenType.Integer or JTokenType.Float)
            || !double.IsFinite(set.Value<double>("NativeActorRootSnapshot_Depth"))
            || Math.Abs(set.Value<double>("NativeActorRootSnapshot_Depth")) > 1000)
            throw new InvalidDataException("NativeActorRootSnapshot requires one sprite ID, host vision ID, target flag and finite layer depth");
    }

    // One dispatch-time world placement. The mechanical owner is never used as
    // the caster reference, and the component does not keep following the unit.
    static KismetExpression[] RootSnapshotCode(UAsset asset, FunctionExport fn, JObject set,
        bool addLocals, out List<FPackageIndex> dependencies)
    {
        ValidateRootSnapshot(set);
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
        FPackageIndex Struct(string p, string n) => Import("/Script/CoreUObject", n, "ScriptStruct", Package(p));
        FPackageIndex Function(string p, string c, string n) => Import("/Script/CoreUObject", n, "Object", Class(p, c));
        var eventClass = Class("/Script/mucha", "CPP_BtlSequencerEvent");
        var jobClass = Class("/Script/mucha", "CPP_BtlJob");
        var generated = Struct("/Script/mucha", "BTL_GENERATED_SPRITESTUDIO_ACTOR_INSTANCE");
        var hitResult = Struct("/Script/Engine", "HitResult");
        var valid = Function("/Script/Engine", "KismetSystemLibrary", "IsValid");
        var validIndex = Function("/Script/Engine", "KismetArrayLibrary", "Array_IsValidIndex");
        var getter = Function("/Script/mucha", "CPP_BFL_Battle", AuraGetter);
        var location = Function("/Script/Engine", "Actor", "K2_GetActorLocation");
        var getSs = Function("/Script/SpriteStudio6", "SsPlayerActor", "GetSsPlayer");
        var setAbsolute = Function("/Script/Engine", "SceneComponent", "SetAbsolute");
        var setLocation = Function("/Script/Engine", "SceneComponent", "K2_SetWorldLocation");
        var parameter = StageEventParameter(asset, fn);
        KismetPropertyPointer Property(FPackageIndex owner, params string[] path) => new(new FFieldPath {
            Path = path.Select(n => FName.FromString(asset, n)).ToArray(), ResolvedOwner = owner });
        KismetPropertyPointer LocalProperty(string n) => Property(parameter.owner, RootPrefix + n);
        KismetExpression Local(string n) => new EX_LocalVariable { Variable = LocalProperty(n) };
        EX_CallMath Call(FPackageIndex f, params KismetExpression[] args) => new() { StackNode = f, Parameters = args };
        EX_Context_FailSilent Context(KismetExpression obj, KismetExpression rhs, KismetPropertyPointer? result = null) =>
            new() { ObjectExpression = obj, ContextExpression = rhs, RValuePointer = result ?? Property(new FPackageIndex(0)),
                PropertyType = 0, Offset = checked((uint)AuraBytes(asset, new[] { rhs }).size) };
        KismetExpression Invoke(KismetExpression obj, FPackageIndex f, params KismetExpression[] args) =>
            Context(obj, new EX_FinalFunction { StackNode = f, Parameters = args }, Property(f, "ReturnValue"));
        KismetExpression Member(KismetExpression obj, FPackageIndex cls, string n) =>
            Context(obj, new EX_InstanceVariable { Variable = Property(cls, n) }, Property(cls, n));
        KismetExpression Event() => new EX_LocalVariable { Variable = Property(parameter.owner, parameter.name) };
        KismetExpression Job() => Member(Event(), eventClass, "m_pJob");
        KismetExpression Registry() => Member(Job(), jobClass, "m_GeneratedSpriteStudioDatas");
        KismetExpression Targets() => Member(Event(), eventClass, "m_TargetUnitList");
        var indexed = set.ContainsKey("NativeActorRootSnapshot_TargetIndex");
        var raised = set.ContainsKey("NativeActorRootSnapshot_HeightFraction");
        var ordered = set.ContainsKey("NativeActorRootSnapshot_SortLayer");
        var preserve = set.Value<bool>("NativeActorRootSnapshot_PreservePlacement");
        if (addLocals) {
            var unused = new[] { (!indexed, "TargetIndex"), (!raised, "HeightFraction"), (!raised, "Height"),
                (!ordered, "SortLayer"), (!set.ContainsKey("NativeActorRootSnapshot_PreservePlacement"), "PreservePlacement") }
                .Where(p => p.Item1).Select(p => RootPrefix + p.Item2).ToHashSet();
            fn.LoadedProperties = fn.LoadedProperties.Where(p => !unused.Contains(p.Name.ToString())).ToArray();
        }
        KismetExpression TargetIndex() => indexed ? Local("TargetIndex") : new EX_IntZero();
        KismetExpression Target() => new EX_ArrayGetByRef { ArrayVariable = Targets(), ArrayIndex = TargetIndex() };
        KismetExpression Unit() => set.Value<bool>("NativeActorRootSnapshot_IsTarget") ? Target() : Call(getter, Local("UnitId"), new EX_False());
        KismetExpression Entry() => new EX_ArrayGetByRef { ArrayVariable = Registry(), ArrayIndex = Local("Index") };
        KismetExpression EntryMember(string n) => new EX_StructMemberContext { StructExpression = Entry(), StructMemberExpression = Property(generated, n) };
        KismetExpression Component() => Invoke(EntryMember("ssActor"), getSs);
        KismetExpression Assign(string n, KismetExpression rhs) => new EX_Let { Value = LocalProperty(n), Variable = Local(n), Expression = rhs };
        void AddLocal(string n, FProperty property, string type, int size) {
            property.Name = FName.FromString(asset, RootPrefix + n); property.SerializedType = FName.FromString(asset, type);
            property.ArrayDim = EArrayDim.TArray; property.ElementSize = size; property.RepNotifyFunc = FName.FromString(asset, "None");
            var old = fn.LoadedProperties.SingleOrDefault(p => p.Name.ToString() == RootPrefix + n);
            if (old == null && addLocals) fn.LoadedProperties = fn.LoadedProperties.Append(property).ToArray();
            else if (old == null || old.GetType() != property.GetType() || old.SerializedType.ToString() != type || old.ElementSize != size || old.ArrayDim != EArrayDim.TArray || old.PropertyFlags != 0
                || old is FStructProperty sp && sp.Struct.Index != ((FStructProperty)property).Struct.Index)
                throw new InvalidDataException("Malformed NativeActorRootSnapshot local " + n);
        }
        AddLocal("UnitId", new FGenericProperty(), "IntProperty", 4);
        AddLocal("IsTarget", new FGenericProperty(), "IntProperty", 4);
        AddLocal("Depth", new FGenericProperty(), "DoubleProperty", 8);
        AddLocal("Index", new FGenericProperty(), "IntProperty", 4);
        if (indexed) AddLocal("TargetIndex", new FGenericProperty(), "IntProperty", 4);
        if (raised) {
            AddLocal("HeightFraction", new FGenericProperty(), "DoubleProperty", 8);
            AddLocal("Height", new FGenericProperty(), "DoubleProperty", 8);
        }
        if (ordered) AddLocal("SortLayer", new FGenericProperty(), "IntProperty", 4);
        if (set.ContainsKey("NativeActorRootSnapshot_PreservePlacement")) AddLocal("PreservePlacement", new FGenericProperty(), "IntProperty", 4);
        AddLocal("Sweep", new FStructProperty { Struct = hitResult }, "StructProperty", 256);
        if (addLocals) fn.FunctionFlags |= EFunctionFlags.FUNC_HasDefaults;
        if (!fn.FunctionFlags.HasFlag(EFunctionFlags.FUNC_HasDefaults)) throw new InvalidDataException("NativeActorRootSnapshot requires initialized local storage");
        var code = new List<KismetExpression> {
            Assign("UnitId", new EX_IntConst { Value = set.Value<int>("NativeActorRootSnapshot_UnitId") }),
            Assign("IsTarget", new EX_IntConst { Value = set.Value<bool>("NativeActorRootSnapshot_IsTarget") ? 1 : 0 }),
            Assign("Depth", new EX_DoubleConst { Value = set.Value<double>("NativeActorRootSnapshot_Depth") }) };
        if (indexed) code.Add(Assign("TargetIndex", new EX_IntConst { Value = set.Value<int>("NativeActorRootSnapshot_TargetIndex") }));
        if (raised) code.Add(Assign("HeightFraction", new EX_DoubleConst { Value = set.Value<double>("NativeActorRootSnapshot_HeightFraction") }));
        if (ordered) code.Add(Assign("SortLayer", new EX_IntConst { Value = set.Value<int>("NativeActorRootSnapshot_SortLayer") }));
        if (set.ContainsKey("NativeActorRootSnapshot_PreservePlacement")) code.Add(Assign("PreservePlacement", new EX_IntConst { Value = preserve ? 1 : 0 }));
        var exits = new List<EX_JumpIfNot>();
        void Guard(KismetExpression condition, List<EX_JumpIfNot> list) { var g = new EX_JumpIfNot { BooleanExpression = condition }; list.Add(g); code.Add(g); }
        uint Position() => checked((uint)AuraBytes(asset, code).size);
        Guard(Call(valid, Event()), exits); Guard(Call(valid, Job()), exits);
        if (!indexed) {
            if (set.Value<bool>("NativeActorRootSnapshot_IsTarget")) Guard(Call(validIndex, Targets(), TargetIndex()), exits);
            Guard(Call(valid, Unit()), exits);
        }
        code.Add(Assign("Index", new EX_IntZero()));
        var loop = Position(); Guard(Call(validIndex, Registry(), Local("Index")), exits);
        var mismatch = new List<EX_JumpIfNot>();
        Guard(Call(Function("/Script/Engine", "KismetMathLibrary", "EqualEqual_NameName"), EntryMember("spriteStudioID"),
            new EX_NameConst { Value = FName.FromString(asset, set.Value<string>("NativeActorRootSnapshot_Id")) }), mismatch);
        Guard(Call(valid, EntryMember("ssActor")), exits); Guard(Call(valid, Component()), exits);
        // Bounded per-target instances are invisible when that target does not exist.
        var absent = new List<EX_JumpIfNot>();
        if (indexed) { Guard(Call(validIndex, Targets(), TargetIndex()), absent); Guard(Call(valid, Unit()), absent); }
        if (ordered) {
            var caster = Call(getter, Local("UnitId"), new EX_False());
            var sprite = Member(caster, Class("/Script/mucha", "CPP_Unit"), "m_pSsPlayerComponent");
            var skips = new List<EX_JumpIfNot>();
            Guard(Call(valid, caster), skips); Guard(Call(valid, sprite), skips);
            code.Add(Context(Component(), new EX_FinalFunction {
                StackNode = Function("/Script/Engine", "PrimitiveComponent", "SetTranslucentSortPriority"),
                Parameters = new KismetExpression[] { Call(Function("/Script/Engine", "KismetMathLibrary", "Add_IntInt"),
                    Member(sprite, Class("/Script/Engine", "PrimitiveComponent"), "TranslucencySortPriority"), Local("SortLayer")) } }));
            foreach (var skip in skips) skip.CodeOffset = Position();
        }
        if (raised) {
            var unitClass = Class("/Script/mucha", "CPP_Unit");
            var sprite = Member(Unit(), unitClass, "m_pSsPlayerComponent");
            var capsule = Member(Unit(), unitClass, "m_pRootCapsuleComponent");
            var mathClass = "/Script/Engine";
            FPackageIndex Math(string name) => Function(mathClass, "KismetMathLibrary", name);
            code.Add(Assign("Height", new EX_DoubleConst { Value = 0 }));
            var noCapsule = new List<EX_JumpIfNot>(); Guard(Call(valid, capsule), noCapsule);
            code.Add(Assign("Height", Call(Math("Multiply_DoubleDouble"), new EX_DoubleConst { Value = 2 },
                Call(Math("Conv_FloatToDouble"), Invoke(capsule, Function("/Script/Engine", "CapsuleComponent", "GetScaledCapsuleHalfHeight"))))));
            foreach (var skip in noCapsule) skip.CodeOffset = Position();
            var noHead = new List<EX_JumpIfNot>(); Guard(Call(valid, sprite), noHead);
            var headName = new EX_NameConst { Value = FName.FromString(asset, "NULL_Head") };
            Guard(Invoke(sprite, Function("/Script/Engine", "SceneComponent", "DoesSocketExist"), headName), noHead);
            var delta = Call(Math("Subtract_VectorVector"), Invoke(sprite, Function("/Script/Engine", "SceneComponent", "GetSocketLocation"), headName), Invoke(Unit(), location));
            code.Add(Assign("Height", Call(Math("FMax"), new EX_DoubleConst { Value = 0 },
                Call(Math("Dot_VectorVector"), delta, new EX_VectorConst { Value = new FVector(0, 0, 1) }))));
            foreach (var skip in noHead) skip.CodeOffset = Position();
        }
        if (!preserve) {
        code.Add(Context(Component(), new EX_FinalFunction { StackNode = setAbsolute,
            Parameters = new KismetExpression[] { new EX_True(), new EX_False(), new EX_False() } }));
        var position = Call(Function("/Script/Engine", "KismetMathLibrary", "Add_VectorVector"), Invoke(Unit(), location),
            Call(Function("/Script/Engine", "KismetMathLibrary", "MakeVector"), Local("Depth"), new EX_DoubleConst { Value = 0 },
                raised ? Call(Function("/Script/Engine", "KismetMathLibrary", "Multiply_DoubleDouble"), Local("Height"), Local("HeightFraction")) : new EX_DoubleConst { Value = 0 }));
        code.Add(Context(Component(), new EX_FinalFunction { StackNode = setLocation,
            Parameters = new KismetExpression[] { position, new EX_False(), Local("Sweep"), new EX_True() } }));
        }
        var finish = new EX_Jump(); code.Add(finish);
        EX_Jump? hiddenFinish = null;
        if (indexed) {
            var hide = Position(); foreach (var g in absent) g.CodeOffset = hide;
            code.Add(Context(Component(), new EX_FinalFunction {
                StackNode = Function("/Script/Engine", "SceneComponent", "SetVisibility"),
                Parameters = new KismetExpression[] { new EX_False(), new EX_True() } }));
            code.Add(Context(Component(), new EX_FinalFunction {
                StackNode = Function("/Script/Engine", "ActorComponent", "SetComponentTickEnabled"),
                Parameters = new KismetExpression[] { new EX_False() } }));
            hiddenFinish = new EX_Jump(); code.Add(hiddenFinish);
        }
        var next = Position(); foreach (var g in mismatch) g.CodeOffset = next;
        code.Add(Assign("Index", Call(Function("/Script/Engine", "KismetMathLibrary", "Add_IntInt"), Local("Index"), new EX_IntConst { Value = 1 })));
        code.Add(new EX_Jump { CodeOffset = loop });
        var end = Position(); finish.CodeOffset = end; if (hiddenFinish != null) hiddenFinish.CodeOffset = end; foreach (var g in exits) g.CodeOffset = end;
        code.Add(new EX_Return { ReturnExpression = new EX_Nothing() }); code.Add(new EX_EndOfScript());
        dependencies = refs; return code.ToArray();
    }

    static int SetRootSnapshot(UAsset asset, JObject op, JObject set)
    {
        ValidateRootSnapshot(set);
        var selected = op.Value<string>("export");
        var matches = asset.Exports.OfType<FunctionExport>().Where(f => !string.IsNullOrEmpty(selected) && selected != "*"
            && (f.ObjectName.ToString() == selected || (asset.Exports.IndexOf(f) + 1).ToString() == selected)).ToArray();
        if (op["match"] != null || matches.Length != 1) throw new InvalidDataException("NativeActorRootSnapshot requires one explicit donor function");
        var fn = matches[0];
        if (!fn.ScriptBytecode.SelectMany(Walk).OfType<EX_StructConst>().Any(sc => StructName(asset, sc.Struct) == "BTL_SEQUENCE_PARAMETER")
            && !fn.LoadedProperties.Any(p => p.Name.ToString() == RootPrefix + "UnitId"))
            throw new InvalidDataException("NativeActorRootSnapshot requires a native battle-event donor");
        fn.ScriptBytecode = RootSnapshotCode(asset, fn, set, true, out var dependencies);
        fn.ScriptBytecodeSize = AuraBytes(asset, fn.ScriptBytecode).size;
        fn.CreateBeforeSerializationDependencies ??= new List<FPackageIndex>();
        foreach (var d in dependencies) if (fn.CreateBeforeSerializationDependencies.All(v => v.Index != d.Index)) fn.CreateBeforeSerializationDependencies.Add(d);
        return 1;
    }

    static JObject? ReadRootSnapshot(UAsset asset, FunctionExport fn)
    {
        if (!fn.LoadedProperties.Any(p => p.Name.ToString() == RootPrefix + "UnitId")) return null;
        var assignments = fn.ScriptBytecode.Take(3).OfType<EX_Let>().ToArray();
        if (assignments.Length != 3 || assignments[0].Expression is not EX_IntConst unit
            || assignments[1].Expression is not EX_IntConst target || target.Value is not (0 or 1)
            || assignments[2].Expression is not EX_DoubleConst depth)
            throw new InvalidDataException("Malformed NativeActorRootSnapshot settings");
        var names = fn.ScriptBytecode.SelectMany(Walk).OfType<EX_FinalFunction>().Where(c => IsCall(asset, c, "/Script/Engine", "KismetMathLibrary", "EqualEqual_NameName")).ToArray();
        if (names.Length != 1 || names[0].Parameters.Length != 2 || names[0].Parameters[1] is not EX_NameConst id)
            throw new InvalidDataException("Malformed NativeActorRootSnapshot sprite identity");
        var set = new JObject { ["EventType"] = RootSnapshotEvent, ["NativeActorRootSnapshot_UnitId"] = unit.Value,
            ["NativeActorRootSnapshot_IsTarget"] = target.Value == 1, ["NativeActorRootSnapshot_Depth"] = depth.Value,
            ["NativeActorRootSnapshot_Id"] = id.Value.ToString() };
        if (fn.LoadedProperties.Any(p => p.Name.ToString() == RootPrefix + "TargetIndex")) {
            if (fn.ScriptBytecode.ElementAtOrDefault(3) is not EX_Let index || index.Expression is not EX_IntConst value)
                throw new InvalidDataException("Malformed NativeActorRootSnapshot target index");
            set["NativeActorRootSnapshot_TargetIndex"] = value.Value;
        }
        var optionalIndex = set.ContainsKey("NativeActorRootSnapshot_TargetIndex") ? 4 : 3;
        foreach (var name in new[] { "HeightFraction", "SortLayer", "PreservePlacement" }) {
            if (!fn.LoadedProperties.Any(p => p.Name.ToString() == RootPrefix + name)) continue;
            if (fn.ScriptBytecode.ElementAtOrDefault(optionalIndex++) is not EX_Let assignment)
                throw new InvalidDataException("Malformed NativeActorRootSnapshot " + name);
            if (name == "HeightFraction" && assignment.Expression is EX_DoubleConst fraction)
                set["NativeActorRootSnapshot_" + name] = fraction.Value;
            else if (name == "SortLayer" && assignment.Expression is EX_IntConst layer)
                set["NativeActorRootSnapshot_" + name] = layer.Value;
            else if (name == "PreservePlacement" && assignment.Expression is EX_IntConst preserve && preserve.Value is 0 or 1)
                set["NativeActorRootSnapshot_" + name] = preserve.Value == 1;
            else throw new InvalidDataException("Malformed NativeActorRootSnapshot " + name);
        }
        var before = asset.Imports.Count; var expected = RootSnapshotCode(asset, fn, set, false, out _);
        var a = AuraBytes(asset, fn.ScriptBytecode); var b = AuraBytes(asset, expected);
        if (before != asset.Imports.Count || fn.ScriptBytecodeSize != b.size || a.size != b.size || !a.bytes.SequenceEqual(b.bytes))
            throw new InvalidDataException("Malformed NativeActorRootSnapshot guards, selected actor, frozen placement or VM offsets");
        return set;
    }
}
