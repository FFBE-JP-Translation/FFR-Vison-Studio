using System.Text;
using CUE4Parse.Compression;
using CUE4Parse.Encryption.Aes;
using CUE4Parse.FileProvider;
using CUE4Parse.MappingsProvider;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse_Conversion;
using CUE4Parse_Conversion.Options;
using CUE4Parse.UE4.Assets.Exports;
using CUE4Parse.UE4.Assets.Exports.Texture;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.UE4.Versions;
using CUE4Parse_Conversion.Textures;
using Newtonsoft.Json;

// ffr-export: read game assets straight from the IoStore containers with CUE4Parse.
//   ffr-export list   <substring>                       list matching files
//   ffr-export json   <objectPath> <out.json>           dump any UObject (Ss6Project, DataTable, ...) as JSON
//   ffr-export tex    <objectPath> <out.png>            decode a Texture2D to PNG
//   ffr-export vision <id> <outDir>                     textures + Ss6Project JSON for /Game/Chara/summon/summon<id> and menu
// objectPath examples: /Game/Chara/summon/summon13110/summon13110_tex   (no extension)
static class Program
{
    const string PAKS = @"S:\Program Files (x86)\Steam\steamapps\common\FINAL FANTASY RESONANCE DEMO\FFRS\Content\Paks";
    static readonly string ROOT = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", ".."));

    static int Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        if (args.Length < 2) { Console.Error.WriteLine("usage: ffr-export list|json|tex|vision ..."); return 2; }
        var usmap = Path.Combine(ROOT, "extracted", "Mappings.usmap");
        var oodleDir = Path.Combine(ROOT, "tools", "oodle"); Directory.CreateDirectory(oodleDir);
        var oodlePath = Path.Combine(oodleDir, OodleHelper.OODLE_NAME_CURRENT);
        string? oodleRef = oodlePath;
        if (!File.Exists(oodlePath)) OodleHelper.DownloadOodleDll(ref oodleRef);
        OodleHelper.Initialize(oodleRef ?? oodlePath);

        var paksDir = Environment.GetEnvironmentVariable("FFR_PAKS") ?? PAKS;   // FFR_PAKS=<dir with global.utoc + containers> to test a mod container offline
        var provider = new DefaultFileProvider(paksDir, SearchOption.AllDirectories, new VersionContainer(EGame.GAME_UE5_6));
        provider.MappingsContainer = new FileUsmapTypeMappingsProvider(usmap);
        provider.Initialize();
        provider.SubmitKey(new FGuid(), new FAesKey("0x0000000000000000000000000000000000000000000000000000000000000000"));
        provider.PostMount();
        Console.Error.WriteLine($"mounted files: {provider.Files.Count}");

        switch (args[0])
        {
            case "list":
                foreach (var f in provider.Files.Keys.Where(k => k.Contains(args[1], StringComparison.OrdinalIgnoreCase)).OrderBy(k => k)) Console.WriteLine(f);
                return 0;
            case "json":
            {
                var obj = provider.LoadPackageObject(args[1]);
                File.WriteAllText(args[2], JsonConvert.SerializeObject(obj, Formatting.Indented), new UTF8Encoding(false));
                Console.WriteLine($"wrote {args[2]} ({obj.ExportType})");
                return 0;
            }
            case "tex":
                return SaveTexture(provider, args[1], args[2]) ? 0 : 1;
            case "vision":
            {
                var id = args[1]; var outDir = args[2]; Directory.CreateDirectory(outDir);
                var battle = $"/Game/Chara/summon/summon{id}/summon{id}";
                foreach (var suffix in new[] { "_tex", "_normal", "_mreo" })
                    SaveTexture(provider, battle + suffix, Path.Combine(outDir, $"summon{id}{suffix}.png"));
                var ss6 = provider.LoadPackageObject(battle);
                File.WriteAllText(Path.Combine(outDir, $"summon{id}.ss6project.json"), JsonConvert.SerializeObject(ss6, Formatting.Indented), new UTF8Encoding(false));
                Console.WriteLine($"wrote summon{id}.ss6project.json ({ss6.ExportType})");
                var menu = $"/Game/Chara/menu/summon{id}/summon{id}";
                SaveTexture(provider, menu + "_tex", Path.Combine(outDir, $"menu_summon{id}_tex.png"));
                try
                {
                    var menuObj = provider.LoadPackageObject(menu);
                    File.WriteAllText(Path.Combine(outDir, $"menu_summon{id}.ss6project.json"), JsonConvert.SerializeObject(menuObj, Formatting.Indented), new UTF8Encoding(false));
                }
                catch (Exception e) { Console.Error.WriteLine("menu project: " + e.Message); }
                return 0;
            }
            default: Console.Error.WriteLine("unknown command"); return 2;
        }
    }

    static bool SaveTexture(DefaultFileProvider provider, string objectPath, string outPng)
    {
        try
        {
            var obj = provider.LoadPackageObject(objectPath);
            if (obj is not UTexture2D tex) { Console.Error.WriteLine($"{objectPath}: not a Texture2D ({obj.ExportType})"); return false; }
            var decoded = tex.Decode();
            if (decoded == null) { Console.Error.WriteLine($"{objectPath}: decode failed"); return false; }
            using var bmp = decoded.ToSkBitmap();
            using var img = SkiaSharp.SKImage.FromBitmap(bmp);
            using var data = img.Encode(SkiaSharp.SKEncodedImageFormat.Png, 100);
            File.WriteAllBytes(outPng, data.ToArray());
            Console.WriteLine($"wrote {outPng} {tex.PlatformData.SizeX}x{tex.PlatformData.SizeY} {tex.Format}");
            return true;
        }
        catch (Exception e) { Console.Error.WriteLine($"{objectPath}: {e.Message}"); return false; }
    }
}
