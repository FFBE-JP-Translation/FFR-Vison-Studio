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
    const string FocusPrefix = "FFBE_Focus_";
    static readonly string[] FocusNumbers = { "CenterX", "CenterY", "HeightFraction", "ZoomFactor" };

    static void ValidateParticipantFocus(JObject set)
    {
        if (set.Count != (set.Value<string>("NativeParticipantCamera_Shot") == "destination" ? 10 : 8) || set.Value<string>("EventType") != ParticipantCameraEvent
            || set["NativeParticipantCamera_UnitId"]?.Type != JTokenType.Integer
            || set.Value<long>("NativeParticipantCamera_UnitId") is <= 0 or > int.MaxValue
            || set["NativeParticipantCamera_Frame"]?.Type != JTokenType.Integer
            || set.Value<long>("NativeParticipantCamera_Frame") is < 1 or > 120
            || set["NativeParticipantCamera_Shot"]?.Type != JTokenType.String
            || set.Value<string>("NativeParticipantCamera_Shot") is not ("caster" or "targets" or "participants" or "destination" or "targets_fit" or "targets_pan" or "targets_zoom" or "participants_pan" or "participants_zoom"))
            throw new InvalidDataException("NativeParticipantCamera focus requires a selected vision, caster/targets shot and native duration");
        foreach (var key in FocusNumbers) {
            var token = set["NativeParticipantCamera_" + key];
            var n = token?.Value<double>() ?? double.NaN;
            var (low, high) = key switch {
                "HeightFraction" => (.1, .75), "ZoomFactor" => (.5, 3d), _ => (.15, .85)
            };
            if (token?.Type is not (JTokenType.Float or JTokenType.Integer) || !double.IsFinite(n) || n < low || n > high)
                throw new InvalidDataException("NativeParticipantCamera invalid focus parameter " + key);
        }
        if (set.Value<string>("NativeParticipantCamera_Shot") == "destination") {
            if (set["NativeParticipantCamera_DestinationOffset"] is not JObject offset || offset.Count != 3
                || new[] { "x", "y", "z" }.Any(k => offset[k]?.Type is not (JTokenType.Integer or JTokenType.Float)
                    || !double.IsFinite(offset.Value<double>(k)) || Math.Abs(offset.Value<double>(k)) > 10000)
                || offset.Value<double>("z") != 0
                || set.Value<string>("NativeParticipantCamera_DestinationPart") is not { Length: > 0 and <= 128 })
                throw new InvalidDataException("Destination focus requires a finite ground offset and target socket");
        }
        // Leave a five-percent safety edge around the entire requested height.
        if (set.Value<double>("NativeParticipantCamera_HeightFraction") / 2 >
            Math.Min(set.Value<double>("NativeParticipantCamera_CenterY") - .05, .95 - set.Value<double>("NativeParticipantCamera_CenterY")))
            throw new InvalidDataException("NativeParticipantCamera requested height crosses the viewport safety edge");
    }

    // Versioned focus adapter: native body landmarks and the default camera
    // basis replace SpriteStudio's padded animation/culling canvas. The caller
    // refreshes caster snapshots between finite native blends. Target focus
    // scans the complete selected list. The staged target handoff trucks in
    // the camera plane; legacy focus shots keep their original rotation logic.
    static KismetExpression[] ParticipantFocusCode(UAsset asset, Usmap m, FunctionExport fn,
        EX_StructConst template, JObject set, bool addLocals, out List<FPackageIndex> dependencies)
    {
        ValidateParticipantFocus(set);
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
        var socketLocation = Function("/Script/Engine", "SceneComponent", "GetSocketLocation");
        var socketExists = Function("/Script/Engine", "SceneComponent", "DoesSocketExist");
        var capsuleRadius = Function("/Script/Engine", "CapsuleComponent", "GetScaledCapsuleRadius");
        var capsuleHeight = Function("/Script/Engine", "CapsuleComponent", "GetScaledCapsuleHalfHeight");
        var defaultTransform = Function("/Script/mucha", "CPP_BtlCamera", "GetDefaultCameraTransform");
        var defaultLens = Function("/Script/mucha", "CPP_BtlCamera", "GetDefaultCurrentFocalLength");
        var getCine = Function("/Script/CinematicCamera", "CineCameraActor", "GetCineCameraComponent");
        var getViewport = Function("/Script/UMG", "WidgetLayoutLibrary", "GetViewportSize");
        var actorLocation = Function("/Script/Engine", "Actor", "K2_GetActorLocation");
        var parameter = StageEventParameter(asset, fn);
        KismetPropertyPointer Property(FPackageIndex owner, params string[] path) => new(new FFieldPath {
            Path = path.Select(n => FName.FromString(asset, n)).ToArray(), ResolvedOwner = owner });
        KismetPropertyPointer LocalProperty(string n) => Property(parameter.owner, FocusPrefix + n);
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
        var shotName = set.Value<string>("NativeParticipantCamera_Shot");
        var participantsShot = shotName is "participants" or "participants_pan" or "participants_zoom";
        var destinationShot = shotName == "destination";
        var panOnly = shotName is "targets_pan" or "participants_pan";
        var zoomOnly = shotName is "targets_zoom" or "participants_zoom";
        var stagedTarget = panOnly || zoomOnly;
        var fitSingleTarget = shotName == "targets_fit" || stagedTarget;
        var targetsShot = shotName == "targets" || participantsShot || fitSingleTarget;
        var measureCaster = false;
        KismetExpression Unit() => targetsShot && !measureCaster
            ? new EX_ArrayGetByRef { ArrayVariable = Targets(), ArrayIndex = Local("Index") }
            : Call(getter, Local("UnitId"), new EX_False());
        KismetExpression Sprite() => Member(Unit(), unitClass, "m_pSsPlayerComponent");
        KismetExpression Capsule() => Member(Unit(), unitClass, "m_pRootCapsuleComponent");
        KismetExpression FirstTarget() => new EX_ArrayGetByRef { ArrayVariable = Targets(), ArrayIndex = new EX_IntZero() };
        KismetExpression HeadName() => new EX_NameConst { Value = FName.FromString(asset, "NULL_Head") };
        KismetExpression Number(double n) => new EX_DoubleConst { Value = n };
        KismetExpression Op(string name, params KismetExpression[] args) => Call(MathFn(name), args);
        KismetExpression Add(KismetExpression a, KismetExpression b) => Op("Add_DoubleDouble", a, b);
        KismetExpression Sub(KismetExpression a, KismetExpression b) => Op("Subtract_DoubleDouble", a, b);
        KismetExpression Mul(KismetExpression a, KismetExpression b) => Op("Multiply_DoubleDouble", a, b);
        KismetExpression Div(KismetExpression a, KismetExpression b) => Op("Divide_DoubleDouble", a, b);
        KismetExpression Dot(KismetExpression a, KismetExpression b) => Op("Dot_VectorVector", a, b);
        KismetExpression Assign(string n, KismetExpression rhs) => new EX_Let { Value = LocalProperty(n), Variable = Local(n), Expression = rhs };
        void AddLocal(string n, FProperty property, string type, int size) {
            property.Name = FName.FromString(asset, FocusPrefix + n); property.SerializedType = FName.FromString(asset, type);
            property.ArrayDim = EArrayDim.TArray; property.ElementSize = size; property.RepNotifyFunc = FName.FromString(asset, "None");
            var old = fn.LoadedProperties.SingleOrDefault(p => p.Name.ToString() == FocusPrefix + n);
            if (old == null && addLocals) fn.LoadedProperties = fn.LoadedProperties.Append(property).ToArray();
            else if (old == null || old.GetType() != property.GetType() || old.SerializedType.ToString() != type || old.ElementSize != size
                || old.ArrayDim != EArrayDim.TArray || old.PropertyFlags != 0
                || old is FStructProperty sp && sp.Struct.Index != ((FStructProperty)property).Struct.Index)
                throw new InvalidDataException("Malformed NativeParticipantCamera focus local " + n);
        }
        foreach (var n in new[] { "UnitId", "Frame", "Shot", "Index", "Count" }) AddLocal(n, new FGenericProperty(), "IntProperty", 4);
        foreach (var n in FocusNumbers.Concat(new[] { "Aspect", "Sensor", "MinLens", "MaxLens", "DefaultLens", "Lens", "Depth", "Width", "Radius", "Height", "R", "U", "F",
                     "MinR", "MaxR", "MinU", "MaxU", "MinF", "MaxF" })) AddLocal(n, new FGenericProperty(), "DoubleProperty", 8);
        foreach (var n in new[] { "Origin", "Feet", "Head", "CameraLocation", "CameraScale", "Forward", "Right", "Up" })
            AddLocal(n, new FStructProperty { Struct = vector }, "StructProperty", 24);
        AddLocal("CameraRotation", new FStructProperty { Struct = rotator }, "StructProperty", 24);
        AddLocal("Viewport", new FStructProperty { Struct = vector2 }, "StructProperty", 16);
        if (destinationShot) {
            AddLocal("DestinationOffset", new FStructProperty { Struct = vector }, "StructProperty", 24);
            AddLocal("DestinationPart", new FGenericProperty(), "NameProperty", 8);
        }
        if (addLocals) fn.FunctionFlags |= EFunctionFlags.FUNC_HasDefaults;
        if (!fn.FunctionFlags.HasFlag(EFunctionFlags.FUNC_HasDefaults)) throw new InvalidDataException("NativeParticipantCamera requires initialized focus locals");
        var code = new List<KismetExpression> {
            Assign("UnitId", new EX_IntConst { Value = set.Value<int>("NativeParticipantCamera_UnitId") }),
            Assign("Frame", new EX_IntConst { Value = set.Value<int>("NativeParticipantCamera_Frame") }),
            Assign("Shot", new EX_IntConst { Value = panOnly ? (participantsShot ? 7 : 5) : zoomOnly ? (participantsShot ? 8 : 6) : participantsShot ? 2 : destinationShot ? 3 : fitSingleTarget ? 4 : targetsShot ? 1 : 0 }) };
        foreach (var n in FocusNumbers) code.Add(Assign(n, Number(set.Value<double>("NativeParticipantCamera_" + n))));
        if (destinationShot) {
            var offset = (JObject)set["NativeParticipantCamera_DestinationOffset"]!;
            code.Add(Assign("DestinationOffset", new EX_VectorConst { Value = new FVector(offset.Value<double>("x"), offset.Value<double>("y"), 0) }));
            code.Add(Assign("DestinationPart", new EX_NameConst { Value = FName.FromString(asset, set.Value<string>("NativeParticipantCamera_DestinationPart")!) }));
        }
        var exits = new List<EX_JumpIfNot>();
        void Guard(KismetExpression condition, List<EX_JumpIfNot> destinations) {
            var guard = new EX_JumpIfNot { BooleanExpression = condition }; destinations.Add(guard); code.Add(guard);
        }
        void Positive(KismetExpression expression) => Guard(Op("Greater_DoubleDouble", expression, Number(.0001)), exits);
        uint Position() => checked((uint)AuraBytes(asset, code).size);
        Guard(Call(valid, Event()), exits); Guard(Call(valid, Camera()), exits); Guard(Call(valid, Cine()), exits);
        Guard(Call(validIndex, Targets(), new EX_IntZero()), exits); Guard(Call(valid, FirstTarget()), exits);
        code.Add(Assign("Viewport", Call(getViewport, Event())));
        Positive(StructMember(Local("Viewport"), vector2, "X")); Positive(StructMember(Local("Viewport"), vector2, "Y"));
        code.Add(Assign("Aspect", Div(StructMember(Local("Viewport"), vector2, "X"), StructMember(Local("Viewport"), vector2, "Y"))));
        code.Add(Assign("Sensor", Op("Conv_FloatToDouble", StructMember(Member(Cine(), cineClass, "Filmback"), filmback, "SensorWidth"))));
        Positive(Local("Sensor"));
        code.Add(Assign("MinLens", Op("FMax", Number(8), Op("Conv_FloatToDouble", StructMember(Member(Cine(), cineClass, "LensSettings"), lensSettings, "MinFocalLength")))));
        code.Add(Assign("MaxLens", Op("Conv_FloatToDouble", StructMember(Member(Cine(), cineClass, "LensSettings"), lensSettings, "MaxFocalLength"))));
        code.Add(Assign("DefaultLens", Op("Conv_FloatToDouble", Invoke(Camera(), defaultLens))));
        Positive(Local("DefaultLens"));
        Guard(Op("GreaterEqual_DoubleDouble", Local("MaxLens"), Local("MinLens")), exits);
        code.Add(Op("BreakTransform", Invoke(Camera(), defaultTransform), Local("CameraLocation"), Local("CameraRotation"), Local("CameraScale")));
        // The active native camera's default transform may report an origin
        // translation. Fit against its live world position, not that snapshot.
        // Caster shots retain the accepted step-one behavior.
        if (fitSingleTarget) code.Add(Assign("CameraLocation", Invoke(Camera(), actorLocation)));
        if (stagedTarget) code.Add(Assign("CameraRotation", Invoke(Cine(),
            Function("/Script/Engine", "SceneComponent", "K2_GetComponentRotation"))));
        foreach (var axis in new[] { "Forward", "Right", "Up" }) code.Add(Assign(axis, Op("Get" + axis + "Vector", Local("CameraRotation"))));
        foreach (var axis in new[] { "R", "U", "F" }) {
            code.Add(Assign("Min" + axis, Number(1e12))); code.Add(Assign("Max" + axis, Number(-1e12)));
        }
        code.Add(Assign("Index", new EX_IntZero())); code.Add(Assign("Count", new EX_IntZero()));
        void MeasureBody() {
        var skips = new List<EX_JumpIfNot>();
        Guard(Call(valid, Unit()), skips); Guard(Call(valid, Sprite()), skips);
        code.Add(Assign("Feet", Invoke(Unit(), actorLocation)));
        code.Add(Assign("Head", Local("Feet")));
        code.Add(Assign("Radius", Number(0)));
        var noCapsule = new EX_JumpIfNot { BooleanExpression = Call(valid, Capsule()) }; code.Add(noCapsule);
        code.Add(Assign("Radius", Op("Conv_FloatToDouble", Invoke(Capsule(), capsuleRadius))));
        code.Add(Assign("Head", Op("Add_VectorVector", Local("Feet"), Op("MakeVector", Number(0), Number(0),
            Mul(Number(2), Op("Conv_FloatToDouble", Invoke(Capsule(), capsuleHeight)))))));
        noCapsule.CodeOffset = Position();
        var noHead = new EX_JumpIfNot { BooleanExpression = Invoke(Sprite(), socketExists, HeadName()) }; code.Add(noHead);
        code.Add(Assign("Head", Invoke(Sprite(), socketLocation, HeadName())));
        noHead.CodeOffset = Position();
        if (destinationShot) {
            var targetSprite = Member(FirstTarget(), unitClass, "m_pSsPlayerComponent");
            Guard(Call(valid, targetSprite), skips);
            Guard(Invoke(targetSprite, socketExists, Local("DestinationPart")), skips);
            // Same socket, translated XY and ground Z as NativeGroundApproach.
            var endpoint = Op("Add_VectorVector", Invoke(targetSprite, socketLocation, Local("DestinationPart")), Local("DestinationOffset"));
            var delta = Op("Multiply_VectorVector", Op("Subtract_VectorVector", endpoint, Local("Feet")),
                Op("MakeVector", Number(1), Number(1), Number(0)));
            code.Add(Assign("Origin", delta));
            code.Add(Assign("Feet", Op("Add_VectorVector", Local("Feet"), Local("Origin"))));
            code.Add(Assign("Head", Op("Add_VectorVector", Local("Head"), Local("Origin"))));
        }
        code.Add(Assign("Height", Op("VSize", Op("Subtract_VectorVector", Local("Head"), Local("Feet")))));
        code.Add(Assign("Origin", Op("Multiply_VectorFloat", Op("Add_VectorVector", Local("Head"), Local("Feet")), Number(.5))));
        // Capsule width is a collision proxy. Where a unit has no meaningful
        // capsule, a quarter of native head-to-feet height is an explicit body
        // width approximation, never the source animation/effect canvas.
        code.Add(Assign("Radius", Op("FMax", Local("Radius"), Mul(Local("Height"), Number(.25)))));
        foreach (var (axis, direction) in new[] { ("R", "Right"), ("U", "Up"), ("F", "Forward") }) {
            var foot = Dot(Local("Feet"), Local(direction)); var head = Dot(Local("Head"), Local(direction));
            var support = axis == "R" ? Local("Radius") : Mul(Local("Height"), Number(.05));
            code.Add(Assign("Min" + axis, Op("FMin", Local("Min" + axis), Sub(Op("FMin", foot, head), support))));
            code.Add(Assign("Max" + axis, Op("FMax", Local("Max" + axis), Add(Op("FMax", foot, head), support))));
        }
        code.Add(Assign("Count", Op("Add_IntInt", Local("Count"), new EX_IntConst { Value = 1 })));
        foreach (var skip in skips) skip.CodeOffset = Position();
        }
        if (participantsShot) { measureCaster = true; MeasureBody(); measureCaster = false; }
        var loop = Position(); EX_JumpIfNot? done = null;
        if (targetsShot) { done = new EX_JumpIfNot { BooleanExpression = Call(validIndex, Targets(), Local("Index")) }; code.Add(done); }
        MeasureBody();
        if (targetsShot) {
            code.Add(Assign("Index", Op("Add_IntInt", Local("Index"), new EX_IntConst { Value = 1 })));
            code.Add(new EX_Jump { CodeOffset = loop }); done!.CodeOffset = Position();
        }
        Guard(Op("Greater_IntInt", Local("Count"), new EX_IntZero()), exits);
        // Lens units are actual focal millimetres. Always reference the native
        // default, never the in-flight lens or previous camera displacement.
        code.Add(Assign("Lens", Op("FMax", Local("MinLens"), Op("FMin", Local("MaxLens"),
            Mul(Local("DefaultLens"), Local("ZoomFactor"))))));
        code.Add(Assign("Depth", Op("FMax", Number(100), Sub(Local("MinF"), Dot(Local("CameraLocation"), Local("Forward"))))));
        // The target-stage shot fits even one large enemy. Legacy shots retain
        // their fixed single-body lens; the accepted caster shot is unchanged.
        var single = new EX_JumpIfNot { BooleanExpression = Op("Greater_IntInt", Local("Count"), new EX_IntConst { Value = fitSingleTarget ? 0 : 1 }) }; code.Add(single);
        var horizontalFraction = Mul(Number(2), Op("FMin", Sub(Local("CenterX"), Number(.05)), Sub(Number(.95), Local("CenterX"))));
        code.Add(Assign("Width", Op("FMax", Number(1), Op("FMax", Div(Sub(Local("MaxR"), Local("MinR")), horizontalFraction),
            Div(Mul(Sub(Local("MaxU"), Local("MinU")), Local("Aspect")), Local("HeightFraction"))))));
        code.Add(Assign("Lens", Op("FMax", Local("MinLens"), Op("FMin", Local("Lens"),
            Div(Mul(Local("Sensor"), Local("Depth")), Local("Width"))))));
        single.CodeOffset = Position();
        // The staged target shot must never widen the lens from the cast shot.
        // Its pan uses this final composition without changing focal length;
        // the following zoom changes only focal length, not camera rotation.
        // Keeping a stationary caster is more important than the old minimum
        // target zoom: fit the union even when caster and enemies are far apart.
        if (stagedTarget && !participantsShot) code.Add(Assign("Lens", Op("FMin", Local("MaxLens"), Op("FMax", Local("Lens"),
            Mul(Number(1.12), Op("Conv_FloatToDouble", Invoke(Camera(),
                Function("/Script/mucha", "CPP_BtlCamera", "GetCurrentFocalLength"))))))));
        code.Add(Assign("F", Mul(Add(Local("MinF"), Local("MaxF")), Number(.5))));
        code.Add(Assign("Depth", Op("FMax", Number(100), Sub(Local("F"), Dot(Local("CameraLocation"), Local("Forward"))))));
        code.Add(Assign("Width", Div(Mul(Local("Sensor"), Local("Depth")), Local("Lens"))));
        // Large targets use the available vertical space above the lower-left
        // anchor. Keep their feet clear of the screen bottom without tilting
        // upward or widening the lens during the handoff.
        if (stagedTarget) code.Add(Assign("CenterY", Op("FMax", Number(.3), Op("FMin", Local("CenterY"),
            Sub(Number(.96), Mul(Number(.5), Div(Mul(Sub(Local("MaxU"), Local("MinU")), Local("Aspect")), Local("Width"))))))));
        code.Add(Assign("R", Sub(Mul(Add(Local("MinR"), Local("MaxR")), Number(.5)), Mul(Sub(Local("CenterX"), Number(.5)), Local("Width")))));
        code.Add(Assign("U", Sub(Mul(Add(Local("MinU"), Local("MaxU")), Number(.5)), Mul(Sub(Number(.5), Local("CenterY")), Div(Local("Width"), Local("Aspect"))))));
        var aim = Op("Add_VectorVector", Op("Add_VectorVector", Op("Multiply_VectorFloat", Local("Right"), Local("R")),
            Op("Multiply_VectorFloat", Local("Up"), Local("U"))), Op("Multiply_VectorFloat", Local("Forward"), Local("F")));
        var lookOffset = Op("Subtract_VectorVector", aim, Invoke(FirstTarget(), actorLocation));
        var props = SchemaProps(m, "BTL_SEQUENCE_PARAMETER");
        if (StructName(asset, template.Struct) != "BTL_SEQUENCE_PARAMETER" || template.Value.Length != props.Count)
            throw new InvalidDataException("NativeParticipantCamera requires the complete native battle-event schema");
        int Index(string name) => props.FindIndex(p => p.Name == name) is var i && i >= 0 ? i : throw new InvalidDataException("Missing focus schema " + name);
        EX_StructConst EventStruct(string type, string prefix) {
            var sc = new EX_StructConst { Struct = template.Struct, StructSize = template.StructSize,
                Value = template.Value.Select((e, i) => i == Index("Camera_SetLookAtTarget_AddLocation")
                    || i == Index("Camera_SetViewLocation_Location")
                    ? new EX_VectorConst { Value = new FVector(0, 0, 0) }
                    : i == Index("Camera_SetZoomInOut_Value") ? new EX_FloatConst { Value = 0 }
                    : ZeroStageConstant(asset, e)).ToArray() };
            SetPath(asset, m, sc, "EventType", type); SetPath(asset, m, sc, prefix + "_Frame", set.Value<int>("NativeParticipantCamera_Frame"));
            SetPath(asset, m, sc, prefix + "_EasingType", "EaseInOut"); SetPath(asset, m, sc, prefix + "_EasingBlendExp", 2.0);
            SetPath(asset, m, sc, prefix + "_EasingSteps", 1); return sc;
        }
        var pan = EventStruct("CameraSetLookAtTarget", "Camera_SetLookAtTarget");
        pan.Value[Index("Camera_SetLookAtTarget_AddLocation")] = lookOffset;
        SetPath(asset, m, pan, "Camera_SetLookAtTarget_Id", -1);
        if (stagedTarget) {
            // Truck in the camera plane toward the targets. Preserve the cast
            // view's pitch/yaw and depth; the separate zoom follows this move.
            pan = EventStruct("CameraSetViewLocation", "Camera_SetViewLocation");
            pan.Value[Index("Camera_SetViewLocation_Location")] = Op("Subtract_VectorVector", aim,
                Op("Multiply_VectorFloat", Local("Forward"), Local("Depth")));
            SetPath(asset, m, pan, "Camera_SetViewLocation_RelativeLocation", false);
        }
        var zoom = EventStruct("CameraSetZoomInOut", "Camera_SetZoomInOut");
        zoom.Value[Index("Camera_SetZoomInOut_Value")] = Op("Conv_DoubleToFloat", Local("Lens"));
        SetPath(asset, m, zoom, "Camera_SetZoomInOut_RelativeValue", false);
        foreach (var sc in panOnly ? new[] { pan } : zoomOnly ? new[] { zoom } : new[] { pan, zoom }) code.Add(new EX_LocalVirtualFunction {
            VirtualFunctionName = FName.FromString(asset, "SeqBattleEvent"), Parameters = new KismetExpression[] { Event(), sc } });
        var end = Position(); foreach (var guard in exits) guard.CodeOffset = end;
        code.Add(new EX_Return { ReturnExpression = new EX_Nothing() }); code.Add(new EX_EndOfScript());
        dependencies = refs; return code.ToArray();
    }

    static JObject? ReadParticipantFocus(UAsset asset, Usmap m, FunctionExport fn)
    {
        if (!fn.LoadedProperties.Any(p => p.Name.ToString() == FocusPrefix + "Shot")) return null;
        var assignments = fn.ScriptBytecode.Take(7).OfType<EX_Let>().ToArray();
        if (assignments.Length != 7 || assignments[0].Expression is not EX_IntConst unit
            || assignments[1].Expression is not EX_IntConst frames || assignments[2].Expression is not EX_IntConst shot || shot.Value is not (0 or 1 or 2 or 3 or 4 or 5 or 6 or 7 or 8))
            throw new InvalidDataException("Malformed NativeParticipantCamera focus settings");
        var set = new JObject { ["EventType"] = ParticipantCameraEvent, ["NativeParticipantCamera_UnitId"] = unit.Value,
            ["NativeParticipantCamera_Frame"] = frames.Value, ["NativeParticipantCamera_Shot"] = shot.Value switch { 0 => "caster", 1 => "targets", 2 => "participants", 3 => "destination", 4 => "targets_fit", 5 => "targets_pan", 6 => "targets_zoom", 7 => "participants_pan", _ => "participants_zoom" } };
        for (var i = 0; i < FocusNumbers.Length; i++) {
            if (assignments[i + 3].Expression is not EX_DoubleConst number) throw new InvalidDataException("Malformed NativeParticipantCamera focus number");
            set["NativeParticipantCamera_" + FocusNumbers[i]] = number.Value;
        }
        if (shot.Value == 3) {
            if (fn.ScriptBytecode[7] is not EX_Let pos || pos.Expression is not EX_VectorConst offset
                || fn.ScriptBytecode[8] is not EX_Let part || part.Expression is not EX_NameConst socket)
                throw new InvalidDataException("Malformed destination focus");
            set["NativeParticipantCamera_DestinationOffset"] = new JObject { ["x"] = offset.Value.X, ["y"] = offset.Value.Y, ["z"] = offset.Value.Z };
            set["NativeParticipantCamera_DestinationPart"] = socket.Value.ToString();
        }
        var calls = fn.ScriptBytecode.OfType<EX_LocalVirtualFunction>().Where(c => c.VirtualFunctionName.ToString() == "SeqBattleEvent").ToArray();
        if (calls.Length != (shot.Value is 5 or 6 or 7 or 8 ? 1 : 2) || calls[0].Parameters.Length != 2 || calls[0].Parameters[1] is not EX_StructConst template)
            throw new InvalidDataException("Malformed NativeParticipantCamera pan/zoom binding");
        var before = asset.Imports.Count;
        var expected = ParticipantFocusCode(asset, m, fn, template, set, false, out _);
        var a = AuraBytes(asset, fn.ScriptBytecode); var b = AuraBytes(asset, expected);
        if (asset.Imports.Count != before || fn.ScriptBytecodeSize != b.size || a.size != b.size || !a.bytes.SequenceEqual(b.bytes))
            throw new InvalidDataException("Malformed NativeParticipantCamera focus guards, target union, projection, native camera binding or VM offsets");
        return set;
    }
}
