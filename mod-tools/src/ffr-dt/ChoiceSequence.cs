using UAssetAPI;
using UAssetAPI.ExportTypes;
using UAssetAPI.Kismet.Bytecode;
using UAssetAPI.Kismet.Bytecode.Expressions;
using UAssetAPI.UnrealTypes;
using UAssetAPI.Unversioned;

// Keep the native free-talk bindings and timeline in their binary representation.
// A full JSON round trip discards UE5 UniversalObjectLocator private fields.
static class ChoiceSequence
{
    public static int Build(List<string> args, Usmap? mappings)
    {
        // make-choice-sequence <free-talk.uasset> <out.uasset> <new-package> <tag>
        const string oldPackage = "/Game/Sequencer/Event/FreeTalk/SEQ_CcommonFreeTalk";
        var newName = Path.GetFileName(args[3]);
        Patch.ClonePackage(args[1], args[2], oldPackage, args[3],
            new() { ("SEQ_CcommonFreeTalk", newName) }, mappings);
        var asset = new UAsset(args[2], EngineVersion.VER_UE5_6, mappings);
        FPackageIndex Import(string name, string kind, FPackageIndex outer)
        {
            var found = asset.Imports.FindIndex(i => i.ObjectName.ToString() == name && i.OuterIndex == outer);
            if (found >= 0) return FPackageIndex.FromImport(found);
            asset.Imports.Add(new Import("/Script/CoreUObject", kind, outer, name, false, asset));
            return FPackageIndex.FromImport(asset.Imports.Count - 1);
        }
        var director = FPackageIndex.FromImport(asset.Imports.FindIndex(i => i.ObjectName.ToString() == "CPP_TalkEventSequenceDirector"));
        if (!director.IsImport()) throw new InvalidDataException("Missing native talk director");
        var open = Import("OpenChoiceDialog", "Object", director);
        var wait = Import("DialogWait", "Object", director);
        var tags = Import("/Script/GameplayTags", "Package", new FPackageIndex(0));
        var tag = Import("GameplayTag", "Object", tags);
        void Replace(string name, FPackageIndex target, int size, params KismetExpression[] parameters)
        {
            var fn = asset.Exports.OfType<FunctionExport>().Single(x => x.ObjectName.ToString() == name);
            fn.ScriptBytecode = new KismetExpression[] {
                new EX_FinalFunction { StackNode = target, Parameters = parameters },
                new EX_Return { ReturnExpression = new EX_Nothing() }, new EX_EndOfScript()
            };
            fn.ScriptBytecodeSize = size;
            fn.CreateBeforeSerializationDependencies.Add(target);
            if (parameters.Length > 0) fn.CreateBeforeSerializationDependencies.Add(tag);
        }
        Replace("TalkPlay_Event", open, 40, new EX_StructConst {
            Struct = tag, StructSize = 12,
            Value = new KismetExpression[] { new EX_NameConst { Value = FName.FromString(asset, args[4]) } }
        });
        Replace("TalkWait_Event", wait, 13);
        asset.Write(args[2]);
        var check = new UAsset(args[2], EngineVersion.VER_UE5_6, mappings);
        foreach (var (name, size) in new[] { ("TalkPlay_Event", 40), ("TalkWait_Event", 13) })
        {
            var fn = check.Exports.OfType<FunctionExport>().Single(x => x.ObjectName.ToString() == name);
            if (fn.ScriptBytecodeSize != size || fn.ScriptBytecode.Length != 3 || fn.ScriptBytecode[0] is not EX_FinalFunction)
                throw new InvalidDataException($"Choice function did not round trip: {name}");
        }
        Console.WriteLine($"Choice sequence written: {args[2]}");
        return 0;
    }
}
