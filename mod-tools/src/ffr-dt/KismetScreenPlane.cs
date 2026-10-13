using Newtonsoft.Json.Linq;
using UAssetAPI;
using UAssetAPI.UnrealTypes;
using UAssetAPI.ExportTypes;
using UAssetAPI.FieldTypes;
using UAssetAPI.Kismet.Bytecode;
using UAssetAPI.Kismet.Bytecode.Expressions;

public static partial class KismetTools
{
    const string ScreenPlaneEvent = "NativeScreenPlane";
    const string ScreenPrefix = "FFBE_Screen_";
    static readonly string[] ScreenNumbers = { "SourceWidth", "SourceHeight", "RuntimeScale", "OverscanX", "OverscanY", "FrontDepth", "RearMargin" };

    static void ValidateScreenPlane(JObject set)
    {
        if (set.Count != 10 + (set.ContainsKey("NativeScreenPlane_Cover") ? 1 : 0) + (set.ContainsKey("NativeScreenPlane_VisionUnitId") ? 1 : 0) + (set.ContainsKey("NativeScreenPlane_ViewportRise") ? 1 : 0)
            || (set.ContainsKey("NativeScreenPlane_ViewportRise") &&
                (set["NativeScreenPlane_ViewportRise"]?.Type is not (JTokenType.Integer or JTokenType.Float)
                 || !double.IsFinite(set.Value<double>("NativeScreenPlane_ViewportRise"))
                 || set.Value<double>("NativeScreenPlane_ViewportRise") is < -.5 or > .5))
            || (set.ContainsKey("NativeScreenPlane_VisionUnitId") &&
                (set["NativeScreenPlane_VisionUnitId"]?.Type != JTokenType.Integer
                 || set.Value<long>("NativeScreenPlane_VisionUnitId") is <= 0 or > int.MaxValue))
            || (set.ContainsKey("NativeScreenPlane_Cover") && set["NativeScreenPlane_Cover"]?.Type != JTokenType.Boolean)
            || set.Value<string>("EventType") != ScreenPlaneEvent
            || set["NativeScreenPlane_Id"]?.Type != JTokenType.String
            || set.Value<string>("NativeScreenPlane_Id") is not { Length: > 0 and <= 128 } id
            || id.Any(c => !(char.IsAsciiLetterOrDigit(c) || c == '_'))
            || set["NativeScreenPlane_IsRear"]?.Type != JTokenType.Boolean)
            throw new InvalidDataException("NativeScreenPlane requires one sprite ID, rear flag and seven projection parameters");
        foreach (var key in ScreenNumbers) {
            var value = set["NativeScreenPlane_" + key];
            var n = value?.Value<double>() ?? double.NaN;
            var (lo, hi) = key switch {
                "SourceWidth" or "SourceHeight" => (1d, 8192d),
                "RuntimeScale" => (.01, 100d),
                "OverscanX" or "OverscanY" => (1d, 2d),
                _ => (1d, 10000d)
            };
            if (value?.Type is not (JTokenType.Integer or JTokenType.Float) || !double.IsFinite(n) || n < lo || n > hi)
                throw new InvalidDataException("NativeScreenPlane invalid projection parameter " + key);
        }
    }

    // Direct component attachment bypasses the game's character billboard and
    // height hierarchy. Actor ownership and the existing finite destroy remain.
    // Each bounded timeline refresh recomputes FOV, viewport and rear support.
    static KismetExpression[] ScreenPlaneCode(UAsset asset, FunctionExport fn, JObject set,
        bool addLocals, out List<FPackageIndex> dependencies)
    {
        ValidateScreenPlane(set);
        if (addLocals) {
            var unused = new[] { "Cover", "VisionUnitId", "ViewportRise" }
                .Where(n => !set.ContainsKey("NativeScreenPlane_" + n)).Select(n => ScreenPrefix + n).ToHashSet();
            fn.LoadedProperties = fn.LoadedProperties.Where(p => !unused.Contains(p.Name.ToString())).ToArray();
        }
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
        FPackageIndex Math(string n) => Function("/Script/Engine", "KismetMathLibrary", n);
        var actorClass = Class("/Script/Engine", "Actor");
        var battleClass = Class("/Script/mucha", "CPP_BtlUnit");
        var eventClass = Class("/Script/mucha", "CPP_BtlSequencerEvent");
        var jobClass = Class("/Script/mucha", "CPP_BtlJob");
        var generated = Struct("/Script/mucha", "BTL_GENERATED_SPRITESTUDIO_ACTOR_INSTANCE");
        var playerClass = Class("/Script/SpriteStudio6", "SsPlayerComponent");
        var managerClass = Class("/Script/Engine", "PlayerCameraManager");
        var vector = Struct("/Script/CoreUObject", "Vector");
        var vector2 = Struct("/Script/CoreUObject", "Vector2D");
        var hitResult = Struct("/Script/Engine", "HitResult");
        var valid = Function("/Script/Engine", "KismetSystemLibrary", "IsValid");
        var validIndex = Function("/Script/Engine", "KismetArrayLibrary", "Array_IsValidIndex");
        var lastIndex = Function("/Script/Engine", "KismetArrayLibrary", "Array_LastIndex");
        var remove = Function("/Script/Engine", "KismetArrayLibrary", "Array_Remove");
        var enumerate = Function("/Script/Engine", "GameplayStatics", "GetAllActorsOfClass");
        var bounds = Function("/Script/Engine", "KismetSystemLibrary", "GetComponentBounds");
        var getCamera = Function("/Script/Engine", "GameplayStatics", "GetPlayerCameraManager");
        var getViewport = Function("/Script/UMG", "WidgetLayoutLibrary", "GetViewportSize");
        var getSs = Function("/Script/SpriteStudio6", "SsPlayerActor", "GetSsPlayer");
        var getFov = Function("/Script/Engine", "PlayerCameraManager", "GetFOVAngle");
        var getCameraLocation = Function("/Script/Engine", "PlayerCameraManager", "GetCameraLocation");
        var getCameraRotation = Function("/Script/Engine", "PlayerCameraManager", "GetCameraRotation");
        var attach = Function("/Script/Engine", "SceneComponent", "K2_AttachToComponent");
        var setAbsolute = Function("/Script/Engine", "SceneComponent", "SetAbsolute");
        var setTransform = Function("/Script/Engine", "SceneComponent", "K2_SetRelativeLocationAndRotation");
        var setScale = Function("/Script/Engine", "SceneComponent", "SetRelativeScale3D");
        var parameter = StageEventParameter(asset, fn);
        KismetPropertyPointer Property(FPackageIndex owner, params string[] path) => new(new FFieldPath {
            Path = path.Select(n => FName.FromString(asset, n)).ToArray(), ResolvedOwner = owner });
        KismetPropertyPointer LocalProperty(string n) => Property(parameter.owner, ScreenPrefix + n);
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
        KismetExpression Entry() => new EX_ArrayGetByRef { ArrayVariable = Registry(), ArrayIndex = Local("Index") };
        KismetExpression EntryMember(string n) => new EX_StructMemberContext { StructExpression = Entry(), StructMemberExpression = Property(generated, n) };
        KismetExpression Component() => Invoke(EntryMember("ssActor"), getSs);
        KismetExpression Camera() => Call(getCamera, Event(), new EX_IntZero());
        KismetExpression CameraTransform() => Member(Camera(), managerClass, "TransformComponent");
        KismetExpression Number(double n) => new EX_DoubleConst { Value = n };
        KismetExpression Multiply(KismetExpression a, KismetExpression b) => Call(Math("Multiply_DoubleDouble"), a, b);
        KismetExpression Divide(KismetExpression a, KismetExpression b) => Call(Math("Divide_DoubleDouble"), a, b);
        KismetExpression Greater(KismetExpression a, KismetExpression b) => Call(Math("Greater_DoubleDouble"), a, b);
        KismetExpression Assign(string n, KismetExpression rhs) => new EX_Let { Value = LocalProperty(n), Variable = Local(n), Expression = rhs };
        void AddLocal(string n, FProperty property, string type, int size) {
            property.Name = FName.FromString(asset, ScreenPrefix + n); property.SerializedType = FName.FromString(asset, type);
            property.ArrayDim = EArrayDim.TArray; property.ElementSize = size; property.RepNotifyFunc = FName.FromString(asset, "None");
            var old = fn.LoadedProperties.SingleOrDefault(p => p.Name.ToString() == ScreenPrefix + n);
            if (old == null && addLocals) fn.LoadedProperties = fn.LoadedProperties.Append(property).ToArray();
            else if (old == null || old.GetType() != property.GetType() || old.SerializedType.ToString() != type || old.ElementSize != size || old.ArrayDim != EArrayDim.TArray || old.PropertyFlags != 0
                || old is FStructProperty sp && sp.Struct.Index != ((FStructProperty)property).Struct.Index)
                throw new InvalidDataException("Malformed NativeScreenPlane local " + n);
        }
        foreach (var n in ScreenNumbers.Concat(new[] { "Depth", "IsRear" })) AddLocal(n, new FGenericProperty(), "DoubleProperty", 8);
        if (set.ContainsKey("NativeScreenPlane_Cover")) AddLocal("Cover", new FGenericProperty(), "DoubleProperty", 8);
        if (set.ContainsKey("NativeScreenPlane_VisionUnitId")) AddLocal("VisionUnitId", new FGenericProperty(), "IntProperty", 4);
        if (set.ContainsKey("NativeScreenPlane_ViewportRise")) AddLocal("ViewportRise", new FGenericProperty(), "DoubleProperty", 8);
        AddLocal("Index", new FGenericProperty(), "IntProperty", 4);
        AddLocal("Viewport", new FStructProperty { Struct = vector2 }, "StructProperty", 16);
        AddLocal("Origin", new FStructProperty { Struct = vector }, "StructProperty", 24);
        AddLocal("Extent", new FStructProperty { Struct = vector }, "StructProperty", 24);
        AddLocal("Radius", new FGenericProperty(), "FloatProperty", 4);
        AddLocal("Sweep", new FStructProperty { Struct = hitResult }, "StructProperty", 256);
        var actors = new FArrayProperty { Inner = new FObjectProperty { Name = FName.FromString(asset, ScreenPrefix + "Actors"),
            SerializedType = FName.FromString(asset, "ObjectProperty"), ArrayDim = EArrayDim.TArray, ElementSize = 8,
            PropertyClass = actorClass, RepNotifyFunc = FName.FromString(asset, "None") } };
        AddLocal("Actors", actors, "ArrayProperty", 16);
        var localArray = (FArrayProperty)fn.LoadedProperties.Single(p => p.Name.ToString() == ScreenPrefix + "Actors");
        if (localArray.Inner is not FObjectProperty inner || inner.PropertyClass.Index != actorClass.Index || inner.ElementSize != 8 || inner.ArrayDim != EArrayDim.TArray)
            throw new InvalidDataException("Malformed NativeScreenPlane actor storage");
        if (addLocals) fn.FunctionFlags |= EFunctionFlags.FUNC_HasDefaults;
        if (!fn.FunctionFlags.HasFlag(EFunctionFlags.FUNC_HasDefaults)) throw new InvalidDataException("NativeScreenPlane requires initialized local storage");
        KismetExpression Viewport(string axis) => new EX_StructMemberContext { StructExpression = Local("Viewport"), StructMemberExpression = Property(vector2, axis) };
        KismetExpression UnitsPerPixel() => Call(Math("Conv_FloatToDouble"), Member(Component(), playerClass, "UUPerPixel"));
        KismetExpression Fov() => Call(Math("Conv_FloatToDouble"), Invoke(Camera(), getFov));
        KismetExpression Width() => Multiply(Multiply(Number(2), Local("Depth")), Call(Math("DegTan"), Divide(Fov(), Number(2))));
        KismetExpression AxisScale(string axis) => Divide(Multiply(axis == "X" ? Width() : Multiply(Width(), Divide(Viewport("Y"), Viewport("X"))), Local("Overscan" + axis)),
            Multiply(Multiply(Local(axis == "X" ? "SourceWidth" : "SourceHeight"), UnitsPerPixel()), Local("RuntimeScale")));
        var code = new List<KismetExpression>();
        var exits = new List<EX_JumpIfNot>();
        void Guard(KismetExpression condition, List<EX_JumpIfNot> targets) { var g = new EX_JumpIfNot { BooleanExpression = condition }; targets.Add(g); code.Add(g); }
        uint Position() => checked((uint)AuraBytes(asset, code).size);
        foreach (var n in ScreenNumbers) code.Add(Assign(n, Number(set.Value<double>("NativeScreenPlane_" + n))));
        var rear = set.Value<bool>("NativeScreenPlane_IsRear");
        code.Add(Assign("IsRear", Number(rear ? 1 : 0)));
        if (set.ContainsKey("NativeScreenPlane_Cover")) code.Add(Assign("Cover", Number(set.Value<bool>("NativeScreenPlane_Cover") ? 1 : 0)));
        if (set.ContainsKey("NativeScreenPlane_VisionUnitId")) code.Add(Assign("VisionUnitId", new EX_IntConst { Value = set.Value<int>("NativeScreenPlane_VisionUnitId") }));
        if (set.ContainsKey("NativeScreenPlane_ViewportRise")) code.Add(Assign("ViewportRise", Number(set.Value<double>("NativeScreenPlane_ViewportRise"))));
        Guard(Call(valid, Event()), exits); Guard(Call(valid, Job()), exits);
        Guard(Call(valid, Camera()), exits); Guard(Call(valid, CameraTransform()), exits);
        code.Add(Assign("Viewport", Call(getViewport, Event())));
        Guard(Greater(Viewport("X"), Number(0)), exits); Guard(Greater(Viewport("Y"), Number(0)), exits);
        Guard(Greater(Fov(), Number(.01)), exits); Guard(Call(Math("Less_DoubleDouble"), Fov(), Number(179)), exits);
        code.Add(Assign("Depth", Local("FrontDepth")));
        if (rear) {
            code.Add(Call(enumerate, Event(), new EX_ObjectConst { Value = battleClass }, Local("Actors")));
            var loop = Position(); var next = new List<EX_JumpIfNot>();
            var done = new EX_JumpIfNot { BooleanExpression = Call(validIndex, Local("Actors"), new EX_IntZero()) }; code.Add(done);
            KismetExpression Current() => new EX_ArrayGetByRef { ArrayVariable = Local("Actors"), ArrayIndex = Call(lastIndex, Local("Actors")) };
            KismetExpression Sprite() => Member(Current(), battleClass, "m_pSsPlayerComponent");
            Guard(Call(valid, Current()), next); Guard(Call(valid, Sprite()), next);
            code.Add(Call(bounds, Sprite(), Local("Origin"), Local("Extent"), Local("Radius")));
            KismetExpression Forward() => Call(Math("GetForwardVector"), Invoke(Camera(), getCameraRotation));
            var support = Call(Math("Add_DoubleDouble"), Call(Math("Dot_VectorVector"),
                    Call(Math("Subtract_VectorVector"), Local("Origin"), Invoke(Camera(), getCameraLocation)), Forward()),
                Call(Math("Dot_VectorVector"), Call(Math("Vector_GetAbs"), Forward()), Local("Extent")));
            code.Add(Assign("Depth", Call(Math("FMax"), Local("Depth"), Call(Math("Add_DoubleDouble"), support, Local("RearMargin")))));
            var skip = Position(); foreach (var g in next) g.CodeOffset = skip;
            code.Add(Call(remove, Local("Actors"), Call(lastIndex, Local("Actors")))); code.Add(new EX_Jump { CodeOffset = loop });
            done.CodeOffset = Position();
        }
        code.Add(Assign("Index", new EX_IntZero()));
        var registryLoop = Position();
        Guard(Call(validIndex, Registry(), Local("Index")), exits);
        var skipRegistry = new List<EX_JumpIfNot>();
        Guard(Call(Math("EqualEqual_NameName"), EntryMember("spriteStudioID"), new EX_NameConst { Value = FName.FromString(asset, set.Value<string>("NativeScreenPlane_Id")) }), skipRegistry);
        Guard(Call(valid, EntryMember("ssActor")), exits); Guard(Call(valid, Component()), exits);
        if (set.ContainsKey("NativeScreenPlane_VisionUnitId")) {
            var caster = Call(Function("/Script/mucha", "CPP_BFL_Battle", AuraGetter), Local("VisionUnitId"), new EX_False());
            var sprite = Member(caster, Class("/Script/mucha", "CPP_Unit"), "m_pSsPlayerComponent");
            var skipOrder = new List<EX_JumpIfNot>();
            Guard(Call(valid, caster), skipOrder); Guard(Call(valid, sprite), skipOrder);
            code.Add(Context(Component(), new EX_FinalFunction {
                StackNode = Function("/Script/Engine", "PrimitiveComponent", "SetTranslucentSortPriority"),
                Parameters = new KismetExpression[] { Call(Math("Subtract_IntInt"),
                    Member(sprite, Class("/Script/Engine", "PrimitiveComponent"), "TranslucencySortPriority"), new EX_IntConst { Value = rear ? 2 : 1 }) } }));
            foreach (var skip in skipOrder) skip.CodeOffset = Position();
        }
        Guard(Greater(UnitsPerPixel(), Number(.0001)), exits);
        Guard(Invoke(Component(), attach, CameraTransform(), new EX_NameConst { Value = FName.FromString(asset, "None") },
            new EX_ByteConst { Value = 2 }, new EX_ByteConst { Value = 2 }, new EX_ByteConst { Value = 2 }, new EX_False()), exits);
        code.Add(Context(Component(), new EX_FinalFunction { StackNode = setAbsolute,
            Parameters = new KismetExpression[] { new EX_False(), new EX_False(), new EX_False() } }));
        code.Add(Context(Component(), new EX_FinalFunction { StackNode = setTransform, Parameters = new KismetExpression[] {
            Call(Math("MakeVector"), Local("Depth"), Number(0), set.ContainsKey("NativeScreenPlane_ViewportRise")
                ? Multiply(Local("ViewportRise"), Multiply(Width(), Divide(Viewport("Y"), Viewport("X")))) : Number(0)), new EX_RotationConst { Value = new FRotator(0, 0, 0) },
            new EX_False(), Local("Sweep"), new EX_True() } }));
        // A uniform maximum fills the viewport and lets its edges crop the art.
        // Legacy assets retain their original independent-axis projection.
        KismetExpression FittedScale(string axis) => set.Value<bool>("NativeScreenPlane_Cover")
            ? Call(Math("FMax"), AxisScale("X"), AxisScale("Y")) : AxisScale(axis);
        code.Add(Context(Component(), new EX_FinalFunction { StackNode = setScale,
            Parameters = new[] { Call(Math("MakeVector"), Number(1), FittedScale("X"), FittedScale("Y")) } }));
        var finish = new EX_Jump(); code.Add(finish);
        var nextEntry = Position(); foreach (var g in skipRegistry) g.CodeOffset = nextEntry;
        code.Add(Assign("Index", Call(Math("Add_IntInt"), Local("Index"), new EX_IntConst { Value = 1 })));
        code.Add(new EX_Jump { CodeOffset = registryLoop });
        var end = Position(); finish.CodeOffset = end; foreach (var g in exits) g.CodeOffset = end;
        code.Add(new EX_Return { ReturnExpression = new EX_Nothing() }); code.Add(new EX_EndOfScript());
        dependencies = refs; return code.ToArray();
    }

    static int SetScreenPlane(UAsset asset, JObject op, JObject set)
    {
        ValidateScreenPlane(set);
        var selected = op.Value<string>("export");
        var matches = asset.Exports.OfType<FunctionExport>().Where(f => !string.IsNullOrEmpty(selected) && selected != "*"
            && (f.ObjectName.ToString() == selected || (asset.Exports.IndexOf(f) + 1).ToString() == selected)).ToArray();
        if (op["match"] != null || matches.Length != 1) throw new InvalidDataException("NativeScreenPlane requires one explicit donor function");
        var fn = matches[0];
        if (!fn.ScriptBytecode.SelectMany(Walk).OfType<EX_StructConst>().Any(sc => StructName(asset, sc.Struct) == "BTL_SEQUENCE_PARAMETER")
            && !fn.LoadedProperties.Any(p => p.Name.ToString() == ScreenPrefix + "SourceWidth"))
            throw new InvalidDataException("NativeScreenPlane requires a native battle-event donor");
        fn.ScriptBytecode = ScreenPlaneCode(asset, fn, set, true, out var dependencies);
        fn.ScriptBytecodeSize = AuraBytes(asset, fn.ScriptBytecode).size;
        fn.CreateBeforeSerializationDependencies ??= new List<FPackageIndex>();
        foreach (var d in dependencies) if (fn.CreateBeforeSerializationDependencies.All(v => v.Index != d.Index)) fn.CreateBeforeSerializationDependencies.Add(d);
        return 1;
    }

    static JObject? ReadScreenPlane(UAsset asset, FunctionExport fn)
    {
        if (!fn.LoadedProperties.Any(p => p.Name.ToString() == ScreenPrefix + "SourceWidth")) return null;
        var set = new JObject { ["EventType"] = ScreenPlaneEvent };
        var assignments = fn.ScriptBytecode.Take(8).OfType<EX_Let>().ToArray();
        if (assignments.Length != 8) throw new InvalidDataException("Malformed NativeScreenPlane projection settings");
        for (var i = 0; i < 8; i++) {
            var key = i < 7 ? ScreenNumbers[i] : "IsRear";
            if (assignments[i].Expression is not EX_DoubleConst value) throw new InvalidDataException("Malformed NativeScreenPlane numeric setting");
            if (i < 7) set["NativeScreenPlane_" + key] = value.Value;
            else { if (value.Value != 0 && value.Value != 1) throw new InvalidDataException("Malformed NativeScreenPlane rear flag"); set["NativeScreenPlane_IsRear"] = value.Value == 1; }
        }
        if (fn.LoadedProperties.Any(p => p.Name.ToString() == ScreenPrefix + "Cover")) {
            if (fn.ScriptBytecode.ElementAtOrDefault(8) is not EX_Let cover || cover.Expression is not EX_DoubleConst value || (value.Value != 0 && value.Value != 1))
                throw new InvalidDataException("Malformed NativeScreenPlane cover flag");
            set["NativeScreenPlane_Cover"] = value.Value == 1;
        }
        if (fn.LoadedProperties.Any(p => p.Name.ToString() == ScreenPrefix + "VisionUnitId")) {
            var index = set.ContainsKey("NativeScreenPlane_Cover") ? 9 : 8;
            if (fn.ScriptBytecode.ElementAtOrDefault(index) is not EX_Let unit || unit.Expression is not EX_IntConst value)
                throw new InvalidDataException("Malformed NativeScreenPlane vision ID");
            set["NativeScreenPlane_VisionUnitId"] = value.Value;
        }
        if (fn.LoadedProperties.Any(p => p.Name.ToString() == ScreenPrefix + "ViewportRise")) {
            var index = 8 + (set.ContainsKey("NativeScreenPlane_Cover") ? 1 : 0) + (set.ContainsKey("NativeScreenPlane_VisionUnitId") ? 1 : 0);
            if (fn.ScriptBytecode.ElementAtOrDefault(index) is not EX_Let rise || rise.Expression is not EX_DoubleConst value)
                throw new InvalidDataException("Malformed NativeScreenPlane viewport rise");
            set["NativeScreenPlane_ViewportRise"] = value.Value;
        }
        var names = fn.ScriptBytecode.SelectMany(Walk).OfType<EX_FinalFunction>().Where(c => IsCall(asset, c, "/Script/Engine", "KismetMathLibrary", "EqualEqual_NameName")).ToArray();
        if (names.Length != 1 || names[0].Parameters.Length != 2 || names[0].Parameters[1] is not EX_NameConst id)
            throw new InvalidDataException("Malformed NativeScreenPlane sprite identity");
        set["NativeScreenPlane_Id"] = id.Value.ToString();
        var before = asset.Imports.Count;
        var expected = ScreenPlaneCode(asset, fn, set, false, out _);
        var a = AuraBytes(asset, fn.ScriptBytecode); var b = AuraBytes(asset, expected);
        if (before != asset.Imports.Count || fn.ScriptBytecodeSize != b.size || a.size != b.size || !a.bytes.SequenceEqual(b.bytes))
            throw new InvalidDataException("Malformed NativeScreenPlane guards, camera projection, actor bounds, component attachment or VM offsets");
        return set;
    }
}
