using Newtonsoft.Json.Linq;
using UAssetAPI;
using UAssetAPI.UnrealTypes;
using UAssetAPI.ExportTypes;
using UAssetAPI.FieldTypes;
using UAssetAPI.Kismet.Bytecode;
using UAssetAPI.Kismet.Bytecode.Expressions;

public static partial class KismetTools
{
    const string ResonanceVisibilityEvent = "NativeResonanceVisibility";
    const string ResonanceVisibilityPrefix = "FFBE_ResonanceVisibility_";

    static void ValidateResonanceVisibility(JObject set)
    {
        if (set.Count != (set.ContainsKey("NativeResonanceVisibility_HideAura") ? 4 : 3)
            || (set.ContainsKey("NativeResonanceVisibility_HideAura") && set["NativeResonanceVisibility_HideAura"]?.Type != JTokenType.Boolean) || set.Value<string>("EventType") != ResonanceVisibilityEvent
            || set["NativeResonanceVisibility_UnitId"]?.Type != JTokenType.Integer
            || set.Value<long>("NativeResonanceVisibility_UnitId") is <= 0 or > int.MaxValue
            || set["NativeResonanceVisibility_Restore"]?.Type != JTokenType.Boolean)
            throw new InvalidDataException("NativeResonanceVisibility requires a positive host vision ID and boolean Restore");
    }

    // Only state actually changed by this scope is tagged. Aura owner tags let
    // cleanup find the components independently of a later unit registry or
    // target selection. Scene bHiddenInGame is separate from authored bVisible.
    static KismetExpression[] ResonanceVisibilityCode(UAsset asset, FunctionExport fn, JObject set,
        bool addLocals, out List<FPackageIndex> dependencies)
    {
        ValidateResonanceVisibility(set);
        int unitId = set.Value<int>("NativeResonanceVisibility_UnitId");
        bool restore = set.Value<bool>("NativeResonanceVisibility_Restore");
        bool explicitAura = set.ContainsKey("NativeResonanceVisibility_HideAura");
        bool hideAura = set.Value<bool?>("NativeResonanceVisibility_HideAura") ?? true;
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
        FPackageIndex Array(string n) => Function("/Script/Engine", "KismetArrayLibrary", n);
        FPackageIndex Math(string n) => Function("/Script/Engine", "KismetMathLibrary", n);
        var actorClass = Class("/Script/Engine", "Actor");
        var componentClass = Class("/Script/Engine", "ActorComponent");
        var sceneClass = Class("/Script/Engine", "SceneComponent");
        var niagaraClass = Class("/Script/Niagara", "NiagaraComponent");
        var battleClass = Class("/Script/mucha", "CPP_BtlUnit");
        var eventClass = Class("/Script/mucha", "CPP_BtlSequencerEvent");
        var entryStruct = Import("/Script/CoreUObject", "SsNiagaraData", "ScriptStruct", Package("/Script/mucha"));
        var expectedAura = Import("/Script/Niagara", AuraAssetName, "NiagaraSystem", Package(AuraAssetPackage));
        var getter = Function("/Script/mucha", "CPP_BFL_Battle", AuraGetter);
        var valid = Function("/Script/Engine", "KismetSystemLibrary", "IsValid");
        var enumerate = Function("/Script/Engine", "GameplayStatics", "GetAllActorsOfClass");
        var enumerateTagged = Function("/Script/Engine", "GameplayStatics", "GetAllActorsWithTag");
        var getAsset = Function("/Script/Niagara", "NiagaraComponent", "GetAsset");
        var getOwner = Function("/Script/Engine", "ActorComponent", "GetOwner");
        var getComponents = Function("/Script/Engine", "Actor", "GetComponentsByTag");
        var setActorHidden = Function("/Script/Engine", "Actor", "SetActorHiddenInGame");
        var setComponentHidden = Function("/Script/Engine", "SceneComponent", "SetHiddenInGame");
        var parameter = StageEventParameter(asset, fn);
        KismetPropertyPointer Property(FPackageIndex owner, params string[] path) => new(new FFieldPath {
            Path = path.Select(n => FName.FromString(asset, n)).ToArray(), ResolvedOwner = owner });
        KismetPropertyPointer LocalProperty(string n) => Property(parameter.owner, ResonanceVisibilityPrefix + n);
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
        KismetExpression Vision() => Call(getter, Local("UnitId"), new EX_False());
        KismetExpression Targets() => Member(Event(), eventClass, "m_TargetUnitList");
        KismetExpression Current() => new EX_ArrayGetByRef { ArrayVariable = Local("Actors"), ArrayIndex = Call(Array("Array_LastIndex"), Local("Actors")) };
        KismetExpression Registry() => Member(Current(), battleClass, "m_SsNiagaraDatas");
        KismetExpression RegistryComponent() => new EX_StructMemberContext {
            StructExpression = new EX_ArrayGetByRef { ArrayVariable = Registry(), ArrayIndex = Local("Index") },
            StructMemberExpression = Property(entryStruct, "NiagaraComponent") };
        KismetExpression TaggedComponent() => new EX_ArrayGetByRef { ArrayVariable = Local("Components"), ArrayIndex = Call(Array("Array_LastIndex"), Local("Components")) };
        KismetExpression Tags(KismetExpression obj) => Member(obj, actorClass, "Tags");
        KismetExpression ComponentTags(KismetExpression obj) => Member(obj, componentClass, "ComponentTags");
        KismetExpression Tag(string purpose) => new EX_NameConst { Value = FName.FromString(asset, "FFBE_Resonance" + purpose + "_" + unitId) };
        KismetExpression Assign(string n, KismetExpression rhs) => new EX_Let { Value = LocalProperty(n), Variable = Local(n), Expression = rhs };
        void AddLocal(string n, FProperty property, string type, int size) {
            property.Name = FName.FromString(asset, ResonanceVisibilityPrefix + n); property.SerializedType = FName.FromString(asset, type);
            property.ArrayDim = EArrayDim.TArray; property.ElementSize = size; property.RepNotifyFunc = FName.FromString(asset, "None");
            var old = fn.LoadedProperties.SingleOrDefault(p => p.Name.ToString() == ResonanceVisibilityPrefix + n);
            if (old == null && addLocals) fn.LoadedProperties = fn.LoadedProperties.Append(property).ToArray();
            else if (old == null || old.GetType() != property.GetType() || old.SerializedType.ToString() != type || old.ElementSize != size || old.ArrayDim != EArrayDim.TArray || old.PropertyFlags != 0)
                throw new InvalidDataException("Malformed NativeResonanceVisibility local " + n);
        }
        void AddArray(string n, FPackageIndex cls) {
            AddLocal(n, new FArrayProperty { Inner = new FObjectProperty { Name = FName.FromString(asset, ResonanceVisibilityPrefix + n),
                SerializedType = FName.FromString(asset, "ObjectProperty"), ArrayDim = EArrayDim.TArray, ElementSize = 8,
                PropertyClass = cls, RepNotifyFunc = FName.FromString(asset, "None") } }, "ArrayProperty", 16);
            var value = (FArrayProperty)fn.LoadedProperties.Single(p => p.Name.ToString() == ResonanceVisibilityPrefix + n);
            if (value.Inner is not FObjectProperty inner || inner.PropertyClass.Index != cls.Index || inner.ElementSize != 8 || inner.ArrayDim != EArrayDim.TArray || inner.PropertyFlags != 0)
                throw new InvalidDataException("Malformed NativeResonanceVisibility array " + n);
        }
        AddLocal("UnitId", new FGenericProperty(), "IntProperty", 4);
        AddLocal("Restore", new FGenericProperty(), "IntProperty", 4);
        AddLocal("Index", new FGenericProperty(), "IntProperty", 4);
        // A function may be reused after an explicit aura choice. Remove the
        // version marker when rewriting the legacy contract, so readback does
        // not mistake the next instruction for the optional fourth setting.
        if (addLocals && !explicitAura)
            fn.LoadedProperties = fn.LoadedProperties.Where(p => p.Name.ToString() != ResonanceVisibilityPrefix + "HideAura").ToArray();
        if (explicitAura) AddLocal("HideAura", new FGenericProperty(), "IntProperty", 4);
        AddArray("Actors", actorClass); AddArray("Components", componentClass);
        if (addLocals) fn.FunctionFlags |= EFunctionFlags.FUNC_HasDefaults;
        if (!fn.FunctionFlags.HasFlag(EFunctionFlags.FUNC_HasDefaults)) throw new InvalidDataException("NativeResonanceVisibility requires initialized local storage");
        var code = new List<KismetExpression> { Assign("UnitId", new EX_IntConst { Value = unitId }),
            Assign("Restore", new EX_IntConst { Value = restore ? 1 : 0 }) };
        if (explicitAura) code.Add(Assign("HideAura", new EX_IntConst { Value = hideAura ? 1 : 0 }));
        var exits = new List<EX_JumpIfNot>();
        uint Position() => checked((uint)AuraBytes(asset, code).size);
        void Guard(KismetExpression condition, List<EX_JumpIfNot> jumps) { var g = new EX_JumpIfNot { BooleanExpression = condition }; jumps.Add(g); code.Add(g); }
        void Resolve(List<EX_JumpIfNot> jumps) { var at = Position(); foreach (var g in jumps) g.CodeOffset = at; }
        void Pop(string n) => code.Add(Call(Array("Array_Remove"), Local(n), Call(Array("Array_LastIndex"), Local(n))));
        Guard(Call(valid, Event()), exits);
        if (!restore) {
            Guard(Call(valid, Vision()), exits);
            code.Add(Call(enumerate, Event(), new EX_ObjectConst { Value = battleClass }, Local("Actors")));
            var actorLoop = Position(); Guard(Call(Array("Array_IsValidIndex"), Local("Actors"), new EX_IntZero()), exits);
            var nextActor = new List<EX_JumpIfNot>(); Guard(Call(valid, Current()), nextActor);
            if (hideAura) {
            code.Add(Assign("Index", new EX_IntZero()));
            var auraLoop = Position(); var auraDone = new List<EX_JumpIfNot>(); var nextAura = new List<EX_JumpIfNot>();
            Guard(Call(Array("Array_IsValidIndex"), Registry(), Local("Index")), auraDone);
            Guard(Call(valid, RegistryComponent()), nextAura);
            Guard(Call(Math("EqualEqual_ObjectObject"), Invoke(RegistryComponent(), getAsset), new EX_ObjectConst { Value = expectedAura }), nextAura);
            Guard(Call(Math("Not_PreBool"), Member(RegistryComponent(), sceneClass, "bHiddenInGame")), nextAura);
            Guard(Call(valid, Invoke(RegistryComponent(), getOwner)), nextAura);
            code.Add(Call(Array("Array_AddUnique"), ComponentTags(RegistryComponent()), Tag("Aura")));
            code.Add(Call(Array("Array_AddUnique"), Tags(Invoke(RegistryComponent(), getOwner)), Tag("AuraOwner")));
            code.Add(Invoke(RegistryComponent(), setComponentHidden, new EX_True(), new EX_False()));
            Resolve(nextAura);
            code.Add(Assign("Index", Call(Math("Add_IntInt"), Local("Index"), new EX_IntConst { Value = 1 })));
            code.Add(new EX_Jump { CodeOffset = auraLoop }); Resolve(auraDone);
            }
            Guard(Call(Math("NotEqual_ObjectObject"), Current(), Vision()), nextActor);
            Guard(Call(Math("Not_PreBool"), Call(Array("Array_Contains"), Targets(), Current())), nextActor);
            Guard(Call(Math("Not_PreBool"), Member(Current(), actorClass, "bHidden")), nextActor);
            code.Add(Call(Array("Array_AddUnique"), Tags(Current()), Tag("Hidden")));
            code.Add(Invoke(Current(), setActorHidden, new EX_True()));
            Resolve(nextActor); Pop("Actors"); code.Add(new EX_Jump { CodeOffset = actorLoop });
        } else {
            code.Add(Call(enumerateTagged, Event(), Tag("Hidden"), Local("Actors")));
            var actorLoop = Position(); var actorsDone = new List<EX_JumpIfNot>(); var nextActor = new List<EX_JumpIfNot>();
            Guard(Call(Array("Array_IsValidIndex"), Local("Actors"), new EX_IntZero()), actorsDone);
            Guard(Call(valid, Current()), nextActor);
            code.Add(Invoke(Current(), setActorHidden, new EX_False()));
            code.Add(Call(Array("Array_RemoveItem"), Tags(Current()), Tag("Hidden")));
            Resolve(nextActor); Pop("Actors"); code.Add(new EX_Jump { CodeOffset = actorLoop }); Resolve(actorsDone);
            code.Add(Call(enumerateTagged, Event(), Tag("AuraOwner"), Local("Actors")));
            var ownerLoop = Position(); Guard(Call(Array("Array_IsValidIndex"), Local("Actors"), new EX_IntZero()), exits);
            var nextOwner = new List<EX_JumpIfNot>(); Guard(Call(valid, Current()), nextOwner);
            code.Add(Assign("Components", Invoke(Current(), getComponents, new EX_ObjectConst { Value = niagaraClass }, Tag("Aura"))));
            var componentLoop = Position(); var componentsDone = new List<EX_JumpIfNot>(); var nextComponent = new List<EX_JumpIfNot>();
            Guard(Call(Array("Array_IsValidIndex"), Local("Components"), new EX_IntZero()), componentsDone);
            Guard(Call(valid, TaggedComponent()), nextComponent);
            code.Add(Invoke(TaggedComponent(), setComponentHidden, new EX_False(), new EX_False()));
            code.Add(Call(Array("Array_RemoveItem"), ComponentTags(TaggedComponent()), Tag("Aura")));
            Resolve(nextComponent); Pop("Components"); code.Add(new EX_Jump { CodeOffset = componentLoop }); Resolve(componentsDone);
            code.Add(Call(Array("Array_RemoveItem"), Tags(Current()), Tag("AuraOwner")));
            Resolve(nextOwner); Pop("Actors"); code.Add(new EX_Jump { CodeOffset = ownerLoop });
        }
        Resolve(exits); code.Add(new EX_Return { ReturnExpression = new EX_Nothing() }); code.Add(new EX_EndOfScript());
        dependencies = refs; return code.ToArray();
    }

    static int SetResonanceVisibility(UAsset asset, JObject op, JObject set)
    {
        ValidateResonanceVisibility(set);
        var selected = op.Value<string>("export");
        var matches = asset.Exports.OfType<FunctionExport>().Where(f => !string.IsNullOrEmpty(selected) && selected != "*"
            && (f.ObjectName.ToString() == selected || (asset.Exports.IndexOf(f) + 1).ToString() == selected)).ToArray();
        if (op["match"] != null || matches.Length != 1) throw new InvalidDataException("NativeResonanceVisibility requires one explicit donor function");
        var fn = matches[0];
        if (!fn.ScriptBytecode.SelectMany(Walk).OfType<EX_StructConst>().Any(sc => StructName(asset, sc.Struct) == "BTL_SEQUENCE_PARAMETER")
            && !fn.LoadedProperties.Any(p => p.Name.ToString() == ResonanceVisibilityPrefix + "UnitId"))
            throw new InvalidDataException("NativeResonanceVisibility requires a native battle-event donor");
        fn.ScriptBytecode = ResonanceVisibilityCode(asset, fn, set, true, out var dependencies);
        fn.ScriptBytecodeSize = AuraBytes(asset, fn.ScriptBytecode).size;
        fn.CreateBeforeSerializationDependencies ??= new List<FPackageIndex>();
        foreach (var d in dependencies) if (fn.CreateBeforeSerializationDependencies.All(v => v.Index != d.Index)) fn.CreateBeforeSerializationDependencies.Add(d);
        return 1;
    }

    static JObject? ReadResonanceVisibility(UAsset asset, FunctionExport fn)
    {
        if (!fn.LoadedProperties.Any(p => p.Name.ToString() == ResonanceVisibilityPrefix + "UnitId")) return null;
        var assignments = fn.ScriptBytecode.Take(2).OfType<EX_Let>().ToArray();
        if (assignments.Length != 2 || assignments[0].Expression is not EX_IntConst unit
            || assignments[1].Expression is not EX_IntConst restore || restore.Value is not (0 or 1))
            throw new InvalidDataException("Malformed NativeResonanceVisibility settings");
        var set = new JObject { ["EventType"] = ResonanceVisibilityEvent, ["NativeResonanceVisibility_UnitId"] = unit.Value,
            ["NativeResonanceVisibility_Restore"] = restore.Value == 1 };
        if (fn.LoadedProperties.Any(p => p.Name.ToString() == ResonanceVisibilityPrefix + "HideAura")) {
            if (fn.ScriptBytecode[2] is not EX_Let choice || choice.Expression is not EX_IntConst hide || hide.Value is not (0 or 1))
                throw new InvalidDataException("Malformed aura visibility choice");
            set["NativeResonanceVisibility_HideAura"] = hide.Value == 1;
        }
        var before = asset.Imports.Count; var expected = ResonanceVisibilityCode(asset, fn, set, false, out _);
        var a = AuraBytes(asset, fn.ScriptBytecode); var b = AuraBytes(asset, expected);
        if (before != asset.Imports.Count || fn.ScriptBytecodeSize != b.size || a.size != b.size || !a.bytes.SequenceEqual(b.bytes))
            throw new InvalidDataException("Malformed NativeResonanceVisibility selection, state markers, aura identity or VM offsets");
        return set;
    }
}
