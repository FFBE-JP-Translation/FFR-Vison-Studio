using System.Buffers.Binary;
using System.Text;
using UAssetAPI;
using UAssetAPI.ExportTypes;

static class AtomBankTools
{
    // SoundAtomCueSheet's four-byte tail prefix is a data-resource index.
    // Unreal loads using that resource's offset/size, not the ACB's own header.
    public static ReadOnlySpan<byte> Validate(UAsset asset)
    {
        if (asset.Exports.Count != 1 || asset.Exports[0] is not NormalExport ex ||
            !ex.ClassIndex.IsImport() || ex.ClassIndex.ToImport(asset).ObjectName.ToString() != "SoundAtomCueSheet")
            throw new InvalidDataException("Expected a single SoundAtomCueSheet export");
        if (asset.DataResources.Count != 1 || ex.Extras.Length < 12 ||
            BinaryPrimitives.ReadInt32LittleEndian(ex.Extras) != 0)
            throw new InvalidDataException("Unsupported Atom bank data-resource layout");
        var resource = asset.DataResources[0];
        long payloadOffset = ex.SerialSize - ex.Extras.Length + 4;
        long payloadSize = ex.Extras.Length - 4;
        // Restrict validation to this shell's observed bulk-data layout.
        if ((uint)resource.LegacyBulkDataFlags != 0x40000 || !resource.OuterIndex.IsNull() ||
            resource.DuplicateSerialOffset != -1)
            throw new InvalidDataException("Unsupported Atom bank bulk-data storage");
        if (resource.SerialOffset != payloadOffset || resource.SerialSize != payloadSize || resource.RawSize != payloadSize)
            throw new InvalidDataException($"Atom bank bulk metadata mismatch: offset {resource.SerialOffset}/{payloadOffset}, " +
                $"size {resource.SerialSize}/{payloadSize}, raw {resource.RawSize}/{payloadSize}");
        var payload = ex.Extras.AsSpan(4);
        if (Encoding.ASCII.GetString(payload[..4]) != "@UTF" ||
            BinaryPrimitives.ReadUInt32BigEndian(payload.Slice(4, 4)) + 8L != payload.Length)
            throw new InvalidDataException("Atom bank ACB header does not cover the embedded payload");
        return payload;
    }
}
