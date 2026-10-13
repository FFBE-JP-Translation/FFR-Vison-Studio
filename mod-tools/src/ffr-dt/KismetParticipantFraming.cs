using Newtonsoft.Json.Linq;
using UAssetAPI;
using UAssetAPI.UnrealTypes;
using UAssetAPI.Unversioned;
using UAssetAPI.ExportTypes;
using UAssetAPI.FieldTypes;
using UAssetAPI.Kismet.Bytecode;
using UAssetAPI.Kismet.Bytecode.Expressions;

public static partial class KismetTools
{
    const string FramingPrefix = "FFBE_Framing_";
    static readonly string[] FramingNumbers = { "CenterX", "CenterY", "HeightFraction", "MaxFocalLength" };

    static void ValidateParticipantFraming(JObject set)
    {
        if (set.Count != 8 || set.Value<string>("EventType") != ParticipantCameraEvent
            || set["NativeParticipantCamera_UnitId"]?.Type != JTokenType.Integer
            || set.Value<long>("NativeParticipantCamera_UnitId") is <= 0 or > int.MaxValue
            || set["NativeParticipantCamera_Frame"]?.Type != JTokenType.Integer
            || set.Value<long>("NativeParticipantCamera_Frame") is < 1 or > 120
            || set["NativeParticipantCamera_Shot"]?.Type != JTokenType.String
            || set.Value<string>("NativeParticipantCamera_Shot") is not ("caster" or "targets"))
            throw new InvalidDataException("NativeParticipantCamera framing requires a selected vision, caster/targets shot and native duration");
        foreach (var key in FramingNumbers) {
            var token = set["NativeParticipantCamera_" + key];
            var n = token?.Value<double>() ?? double.NaN;
            var (low, high) = key switch {
                "HeightFraction" => (.1, .75), "MaxFocalLength" => (8d, 80d), _ => (.15, .85)
            };
            if (token?.Type is not (JTokenType.Float or JTokenType.Integer) || !double.IsFinite(n) || n < low || n > high)
                throw new InvalidDataException("NativeParticipantCamera invalid framing parameter " + key);
        }
        // Leave a five-percent safety edge around the entire requested height.
        if (set.Value<double>("NativeParticipantCamera_HeightFraction") / 2 >
            Math.Min(set.Value<double>("NativeParticipantCamera_CenterY") - .05, .95 - set.Value<double>("NativeParticipantCamera_CenterY")))
            throw new InvalidDataException("NativeParticipantCamera requested height crosses the viewport safety edge");
    }

    // Compute one bounded snapshot from real sprite bounds in the current camera
    // basis. The caller refreshes caster snapshots between finite native blends.
    // Target framing scans the complete selected list, never all battle actors.
    static KismetExpression[] ParticipantFramingCode(UAsset asset, Usmap m, FunctionExport fn,
        EX_StructConst template, JObject set, bool addLocals, out List<FPackageIndex> dependencies)
    {
        ValidateParticipantFraming(set);
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
        FPackageIndex MathFn(string n) => Function("/Script/Engine", "KismetMathLibrary", n);
        var eventClass = Class("/Script/mucha", "CPP_BtlSequencerEvent");
        var unitClass = Class("/Script/mucha", "CPP_Unit");
        var cineClass = Class("/Script/CinematicCamera", "CineCameraComponent");
        var filmback = Struct("/Script/CinematicCamera", "CameraFilmbackSettings");
        var lensSettings = Struct("/Script/CinematicCamera", "CameraLensSettings");
        var vector = Struct("/Script/CoreUObject", "Vector");
        var vector2 = Struct("/Script/CoreUObject", "Vector2D");
        var rotator = Struct("/Script/CoreUObject", "Rotator");
        var valid = Function("/Script/Engine", "KismetSystemLibrary", "IsValid");
        var validIndex = Function("/Script/Engine", "KismetArrayLibrary", "Array_IsValidIndex");
        var getter = Function("/Script/mucha", "CPP_BFL_Battle", AuraGetter);
        var bounds = Function("/Script/Engine", "KismetSystemLibrary", "GetComponentBounds");
        var getCine = Function("/Script/CinematicCamera", "CineCameraActor", "GetCineCameraComponent");
        var getViewport = Function("/Script/UMG", "WidgetLayoutLibrary", "GetViewportSize");
        var getLocation = Function("/Script/Engine", "SceneComponent", "K2_GetComponentLocation");
        var getRotation = Function("/Script/Engine", "SceneComponent", "K2_GetComponentRotation");
        var actorLocation = Function("/Script/Engine", "Actor", "K2_GetActorLocation");
        var parameter = StageEventParameter(asset, fn);
        KismetPropertyPointer Property(FPackageIndex owner, params string[] path) => new(new FFieldPath {
            Path = path.Select(n => FName.FromString(asset, n)).ToArray(), ResolvedOwner = owner });
        KismetPropertyPointer LocalProperty(string n) => Property(parameter.owner, FramingPrefix + n);
        KismetExpression Local(string n) => new EX_LocalVariable { Variable = LocalProperty(n) };
        EX_CallMath Call(FPackageIndex f, params KismetExpression[] args) => new() { StackNode = f, Parameters = args };
        EX_Context_FailSilent Context(KismetExpression obj, KismetExpression rhs, KismetPropertyPointer? result = null) =>
            new() { ObjectExpression = obj, ContextExpression = rhs, RValuePointer = result ?? Property(new FPackageIndex(0)),
                PropertyType = 0, Offset = checked((uint)AuraBytes(asset, new[] { rhs }).size) };
        KismetExpression Invoke(KismetExpression obj, FPackageIndex f, params KismetExpression[] args) =>
            Context(obj, new EX_FinalFunction { StackNode = f, Parameters = args }, Property(f, "ReturnValue"));
        KismetExpression Member(KismetExpression obj, FPackageIndex cls, string n) =>
            Context(obj, new EX_InstanceVariable { Variable = Property(cls, n) }, Property(cls, n));
        KismetExpression StructMember(KismetExpression value, FPackageIndex type, string name) =>
            new EX_StructMemberContext { StructExpression = value, StructMemberExpression = Property(type, name) };
        KismetExpression Event() => new EX_LocalVariable { Variable = Property(parameter.owner, parameter.name) };
        KismetExpression Camera() => Member(Event(), eventClass, "m_pCamera");
        KismetExpression Cine() => Invoke(Camera(), getCine);
        KismetExpression Targets() => Member(Event(), eventClass, "m_TargetUnitList");
        var targetsShot = set.Value<string>("NativeParticipantCamera_Shot") == "targets";
        KismetExpression Unit() => targetsShot
            ? new EX_ArrayGetByRef { ArrayVariable = Targets(), ArrayIndex = Local("Index") }
            : Call(getter, Local("UnitId"), new EX_False());
        KismetExpression Sprite() => Member(Unit(), unitClass, "m_pSsPlayerComponent");
        KismetExpression Number(double n) => new EX_DoubleConst { Value = n };
        KismetExpression Op(string name, params KismetExpression[] args) => Call(MathFn(name), args);
        KismetExpression Add(KismetExpression a, KismetExpression b) => Op("Add_DoubleDouble", a, b);
        KismetExpression Sub(KismetExpression a, KismetExpression b) => Op("Subtract_DoubleDouble", a, b);
        KismetExpression Mul(KismetExpression a, KismetExpression b) => Op("Multiply_DoubleDouble", a, b);
        KismetExpression Div(KismetExpression a, KismetExpression b) => Op("Divide_DoubleDouble", a, b);
        KismetExpression Dot(KismetExpression a, KismetExpression b) => Op("Dot_VectorVector", a, b);
        KismetExpression Assign(string n, KismetExpression rhs) => new EX_Let { Value = LocalProperty(n), Variable = Local(n), Expression = rhs };
        void AddLocal(string n, FProperty property, string type, int size) {
            property.Name = FName.FromString(asset, FramingPrefix + n); property.SerializedType = FName.FromString(asset, type);
            property.ArrayDim = EArrayDim.TArray; property.ElementSize = size; property.RepNotifyFunc = FName.FromString(asset, "None");
            var old = fn.LoadedProperties.SingleOrDefault(p => p.Name.ToString() == FramingPrefix + n);
            if (old == null && addLocals) fn.LoadedProperties = fn.LoadedProperties.Append(property).ToArray();
            else if (old == null || old.GetType() != property.GetType() || old.SerializedType.ToString() != type || old.ElementSize != size
                || old.ArrayDim != EArrayDim.TArray || old.PropertyFlags != 0
                || old is FStructProperty sp && sp.Struct.Index != ((FStructProperty)property).Struct.Index)
                throw new InvalidDataException("Malformed NativeParticipantCamera framing local " + n);
        }
        foreach (var n in new[] { "UnitId", "Frame", "Shot", "Index", "Count" }) AddLocal(n, new FGenericProperty(), "IntProperty", 4);
        foreach (var n in FramingNumbers.Concat(new[] { "Aspect", "Sensor", "MinLens", "MaxLens", "Lens", "Depth", "Width", "CenterDepth", "R", "U", "F",
                     "MinR", "MaxR", "MinU", "MaxU", "MinF", "MaxF" })) AddLocal(n, new FGenericProperty(), "DoubleProperty", 8);
        foreach (var n in new[] { "Origin", "Extent", "CameraLocation", "Forward", "Right", "Up" })
            AddLocal(n, new FStructProperty { Struct = vector }, "StructProperty", 24);
        AddLocal("CameraRotation", new FStructProperty { Struct = rotator }, "StructProperty", 24);
        AddLocal("Viewport", new FStructProperty { Struct = vector2 }, "StructProperty", 16);
        AddLocal("Radius", new FGenericProperty(), "FloatProperty", 4);
        if (addLocals) fn.FunctionFlags |= EFunctionFlags.FUNC_HasDefaults;
        if (!fn.FunctionFlags.HasFlag(EFunctionFlags.FUNC_HasDefaults)) throw new InvalidDataException("NativeParticipantCamera requires initialized framing locals");
        var code = new List<KismetExpression> {
            Assign("UnitId", new EX_IntConst { Value = set.Value<int>("NativeParticipantCamera_UnitId") }),
            Assign("Frame", new EX_IntConst { Value = set.Value<int>("NativeParticipantCamera_Frame") }),
            Assign("Shot", new EX_IntConst { Value = targetsShot ? 1 : 0 }) };
        foreach (var n in FramingNumbers) code.Add(Assign(n, Number(set.Value<double>("NativeParticipantCamera_" + n))));
        var exits = new List<EX_JumpIfNot>();
        void Guard(KismetExpression condition, List<EX_JumpIfNot> destinations) {
            var guard = new EX_JumpIfNot { BooleanExpression = condition }; destinations.Add(guard); code.Add(guard);
        }
        void Positive(KismetExpression expression) => Guard(Op("Greater_DoubleDouble", expression, Number(.0001)), exits);
        uint Position() => checked((uint)AuraBytes(asset, code).size);
        Guard(Call(valid, Event()), exits); Guard(Call(valid, Camera()), exits); Guard(Call(valid, Cine()), exits);
        code.Add(Assign("Viewport", Call(getViewport, Event())));
        Positive(StructMember(Local("Viewport"), vector2, "X")); Positive(StructMember(Local("Viewport"), vector2, "Y"));
        code.Add(Assign("Aspect", Div(StructMember(Local("Viewport"), vector2, "X"), StructMember(Local("Viewport"), vector2, "Y"))));
        code.Add(Assign("Sensor", Op("Conv_FloatToDouble", StructMember(Member(Cine(), cineClass, "Filmback"), filmback, "SensorWidth"))));
        Positive(Local("Sensor"));
        code.Add(Assign("MinLens", Op("FMax", Number(8), Op("Conv_FloatToDouble", StructMember(Member(Cine(), cineClass, "LensSettings"), lensSettings, "MinFocalLength")))));
        code.Add(Assign("MaxLens", Op("FMin", Local("MaxFocalLength"), Op("Conv_FloatToDouble", StructMember(Member(Cine(), cineClass, "LensSettings"), lensSettings, "MaxFocalLength")))));
        Guard(Op("GreaterEqual_DoubleDouble", Local("MaxLens"), Local("MinLens")), exits);
        code.Add(Assign("CameraLocation", Invoke(Cine(), getLocation))); code.Add(Assign("CameraRotation", Invoke(Cine(), getRotation)));
        foreach (var axis in new[] { "Forward", "Right", "Up" }) code.Add(Assign(axis, Op("Get" + axis + "Vector", Local("CameraRotation"))));
        foreach (var axis in new[] { "R", "U", "F" }) {
            code.Add(Assign("Min" + axis, Number(1e12))); code.Add(Assign("Max" + axis, Number(-1e12)));
        }
        code.Add(Assign("Index", new EX_IntZero())); code.Add(Assign("Count", new EX_IntZero()));
        var loop = Position(); EX_JumpIfNot? done = null;
        if (targetsShot) { done = new EX_JumpIfNot { BooleanExpression = Call(validIndex, Targets(), Local("Index")) }; code.Add(done); }
        var skips = new List<EX_JumpIfNot>();
        Guard(Call(valid, Unit()), skips); Guard(Call(valid, Sprite()), skips);
        code.Add(Call(bounds, Sprite(), Local("Origin"), Local("Extent"), Local("Radius")));
        foreach (var (axis, direction) in new[] { ("R", "Right"), ("U", "Up"), ("F", "Forward") }) {
            var center = Dot(Local("Origin"), Local(direction));
            var support = Dot(Local("Extent"), Op("Vector_GetAbs", Local(direction)));
            code.Add(Assign("Min" + axis, Op("FMin", Local("Min" + axis), Sub(center, support))));
            code.Add(Assign("Max" + axis, Op("FMax", Local("Max" + axis), Add(center, support))));
        }
        code.Add(Assign("Count", Op("Add_IntInt", Local("Count"), new EX_IntConst { Value = 1 })));
        foreach (var skip in skips) skip.CodeOffset = Position();
        if (targetsShot) {
            code.Add(Assign("Index", Op("Add_IntInt", Local("Index"), new EX_IntConst { Value = 1 })));
            code.Add(new EX_Jump { CodeOffset = loop }); done!.CodeOffset = Position();
        }
        Guard(Op("Greater_IntInt", Local("Count"), new EX_IntZero()), exits);
        Positive(Sub(Local("MaxU"), Local("MinU")));
        // Fit the union at its nearest depth, with a five-percent horizontal
        // safety edge. HeightFraction deliberately leaves large vertical room.
        var horizontalFraction = Mul(Number(2), Op("FMin", Sub(Local("CenterX"), Number(.05)), Sub(Number(.95), Local("CenterX"))));
        code.Add(Assign("Width", Op("FMax", Div(Sub(Local("MaxR"), Local("MinR")), horizontalFraction),
            Div(Mul(Sub(Local("MaxU"), Local("MinU")), Local("Aspect")), Local("HeightFraction")))));
        Positive(Local("Width"));
        code.Add(Assign("Depth", Op("FMax", Number(100), Sub(Local("MinF"), Dot(Local("CameraLocation"), Local("Forward"))))));
        // An exceptionally large target widens the lens first, then moves the
        // camera back if the native lens minimum is reached. No target is dropped.
        code.Add(Assign("Lens", Op("FMax", Local("MinLens"), Op("FMin", Local("MaxLens"), Div(Mul(Local("Sensor"), Local("Depth")), Local("Width"))))));
        code.Add(Assign("Depth", Op("FMax", Local("Depth"), Div(Mul(Local("Width"), Local("Lens")), Local("Sensor")))));
        code.Add(Assign("CenterDepth", Add(Local("Depth"), Mul(Sub(Local("MaxF"), Local("MinF")), Number(.5)))));
        code.Add(Assign("Width", Div(Mul(Local("Sensor"), Local("CenterDepth")), Local("Lens"))));
        code.Add(Assign("R", Sub(Mul(Add(Local("MinR"), Local("MaxR")), Number(.5)), Mul(Sub(Local("CenterX"), Number(.5)), Local("Width")))));
        code.Add(Assign("U", Sub(Mul(Add(Local("MinU"), Local("MaxU")), Number(.5)), Mul(Sub(Number(.5), Local("CenterY")), Div(Local("Width"), Local("Aspect"))))));
        code.Add(Assign("F", Sub(Local("MinF"), Local("Depth"))));
        var desiredLocation = Op("Add_VectorVector", Op("Add_VectorVector", Op("Multiply_VectorFloat", Local("Right"), Local("R")),
            Op("Multiply_VectorFloat", Local("Up"), Local("U"))), Op("Multiply_VectorFloat", Local("Forward"), Local("F")));
        // Native view-location addresses the camera actor. Compensate any local
        // CineCameraComponent translation instead of assuming it is zero.
        desiredLocation = Op("Add_VectorVector", desiredLocation, Op("Subtract_VectorVector", Invoke(Camera(), actorLocation), Local("CameraLocation")));
        var props = SchemaProps(m, "BTL_SEQUENCE_PARAMETER");
        if (StructName(asset, template.Struct) != "BTL_SEQUENCE_PARAMETER" || template.Value.Length != props.Count)
            throw new InvalidDataException("NativeParticipantCamera requires the complete native battle-event schema");
        int Index(string name) => props.FindIndex(p => p.Name == name) is var i && i >= 0 ? i : throw new InvalidDataException("Missing framing schema " + name);
        EX_StructConst EventStruct(string type, string prefix) {
            var sc = new EX_StructConst { Struct = template.Struct, StructSize = template.StructSize,
                Value = template.Value.Select((e, i) => i == Index("Camera_SetViewLocation_Location")
                    ? new EX_VectorConst { Value = new FVector(0, 0, 0) }
                    : i == Index("Camera_SetZoomInOut_Value") ? new EX_FloatConst { Value = 0 }
                    : ZeroStageConstant(asset, e)).ToArray() };
            SetPath(asset, m, sc, "EventType", type); SetPath(asset, m, sc, prefix + "_Frame", set.Value<int>("NativeParticipantCamera_Frame"));
            SetPath(asset, m, sc, prefix + "_EasingType", "EaseInOut"); SetPath(asset, m, sc, prefix + "_EasingBlendExp", 2.0);
            SetPath(asset, m, sc, prefix + "_EasingSteps", 1); return sc;
        }
        var pan = EventStruct("CameraSetViewLocation", "Camera_SetViewLocation");
        pan.Value[Index("Camera_SetViewLocation_Location")] = desiredLocation;
        SetPath(asset, m, pan, "Camera_SetViewLocation_RelativeLocation", false);
        var zoom = EventStruct("CameraSetZoomInOut", "Camera_SetZoomInOut");
        zoom.Value[Index("Camera_SetZoomInOut_Value")] = Op("Conv_DoubleToFloat", Local("Lens"));
        SetPath(asset, m, zoom, "Camera_SetZoomInOut_RelativeValue", false);
        foreach (var sc in new[] { pan, zoom }) code.Add(new EX_LocalVirtualFunction {
            VirtualFunctionName = FName.FromString(asset, "SeqBattleEvent"), Parameters = new KismetExpression[] { Event(), sc } });
        var end = Position(); foreach (var guard in exits) guard.CodeOffset = end;
        code.Add(new EX_Return { ReturnExpression = new EX_Nothing() }); code.Add(new EX_EndOfScript());
        dependencies = refs; return code.ToArray();
    }

    static JObject? ReadParticipantFraming(UAsset asset, Usmap m, FunctionExport fn)
    {
        if (!fn.LoadedProperties.Any(p => p.Name.ToString() == FramingPrefix + "Shot")) return null;
        var assignments = fn.ScriptBytecode.Take(7).OfType<EX_Let>().ToArray();
        if (assignments.Length != 7 || assignments[0].Expression is not EX_IntConst unit
            || assignments[1].Expression is not EX_IntConst frames || assignments[2].Expression is not EX_IntConst shot || shot.Value is not (0 or 1))
            throw new InvalidDataException("Malformed NativeParticipantCamera framing settings");
        var set = new JObject { ["EventType"] = ParticipantCameraEvent, ["NativeParticipantCamera_UnitId"] = unit.Value,
            ["NativeParticipantCamera_Frame"] = frames.Value, ["NativeParticipantCamera_Shot"] = shot.Value == 0 ? "caster" : "targets" };
        for (var i = 0; i < FramingNumbers.Length; i++) {
            if (assignments[i + 3].Expression is not EX_DoubleConst number) throw new InvalidDataException("Malformed NativeParticipantCamera framing number");
            set["NativeParticipantCamera_" + FramingNumbers[i]] = number.Value;
        }
        var calls = fn.ScriptBytecode.OfType<EX_LocalVirtualFunction>().Where(c => c.VirtualFunctionName.ToString() == "SeqBattleEvent").ToArray();
        if (calls.Length != 2 || calls[0].Parameters.Length != 2 || calls[0].Parameters[1] is not EX_StructConst template)
            throw new InvalidDataException("Malformed NativeParticipantCamera pan/zoom binding");
        var before = asset.Imports.Count;
        var expected = ParticipantFramingCode(asset, m, fn, template, set, false, out _);
        var a = AuraBytes(asset, fn.ScriptBytecode); var b = AuraBytes(asset, expected);
        if (asset.Imports.Count != before || fn.ScriptBytecodeSize != b.size || a.size != b.size || !a.bytes.SequenceEqual(b.bytes))
            throw new InvalidDataException("Malformed NativeParticipantCamera framing guards, target union, projection, native camera binding or VM offsets");
        return set;
    }
}
