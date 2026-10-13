[CmdletBinding(SupportsShouldProcess)]
param([switch]$VerifyOnly, [switch]$RestoreSource, [switch]$RestoreBuildInputs, [switch]$RestoreDependencies)
$ErrorActionPreference = 'Stop'
$checkpoint = $PSScriptRoot
$repo = [IO.Path]::GetFullPath((Join-Path $checkpoint '..\..'))
$manifest = Get-Content -LiteralPath (Join-Path $checkpoint 'checkpoint.json') -Raw | ConvertFrom-Json
foreach ($entry in $manifest.files.PSObject.Properties) {
    $path = [IO.Path]::GetFullPath((Join-Path $checkpoint $entry.Name))
    if (-not $path.StartsWith($checkpoint + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe checkpoint path.' }
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value) { throw "Checkpoint changed: $($entry.Name)" }
}
Write-Output "Verified $($manifest.files.PSObject.Properties.Name.Count) checkpoint files."
if ($VerifyOnly) { return }
if (Get-Process -Name FFRS-Win64-Shipping -ErrorAction SilentlyContinue) { throw 'Close FFR before restoring this checkpoint.' }
$mods = Join-Path $manifest.game 'FFRS\Content\Paks\~mods'
$backup = Join-Path $repo ('build\checkpoint-restores\' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
function Restore-File([string]$source, [string]$destination, [string]$backupRelative) {
    if ($PSCmdlet.ShouldProcess($destination, 'Restore accepted camera step 2 (backing up current file)')) {
        if (Test-Path -LiteralPath $destination) {
            $saved = Join-Path $backup $backupRelative
            New-Item -ItemType Directory -Path (Split-Path $saved) -Force | Out-Null
            Copy-Item -LiteralPath $destination -Destination $saved
        }
        New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination
        if ((Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $destination).Hash) { throw "Restore readback failed: $destination" }
    }
}
$packageFolders = @('packages')
if ($RestoreDependencies) { $packageFolders += 'dependencies/packages' }
foreach ($folder in $packageFolders) {
    foreach ($file in Get-ChildItem -LiteralPath (Join-Path $checkpoint $folder) -File) {
        Restore-File $file.FullName (Join-Path $mods $file.Name) ('packages/' + $file.Name)
    }
}
$paths = if ($RestoreSource) { @($manifest.files.PSObject.Properties.Name | Where-Object { $_ -like 'source/*' }) } else { @('source/mods/EstherTsukiko/units.json') }
foreach ($path in $paths) {
    $relative = $path.Substring(7)
    $destination = [IO.Path]::GetFullPath((Join-Path $repo $relative))
    if (-not $destination.StartsWith($repo + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe source path.' }
    Restore-File (Join-Path $checkpoint $path) $destination ('source/' + $relative)
}
if ($RestoreBuildInputs) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    foreach ($name in @('workspace-inputs.zip', 'native-tools.zip')) {
        $archive = [IO.Compression.ZipFile]::OpenRead((Join-Path $checkpoint ('archives/' + $name)))
        try {
            foreach ($entry in $archive.Entries) {
                if (-not $entry.Name) { continue }
                $destination = [IO.Path]::GetFullPath((Join-Path $repo $entry.FullName))
                if (-not $destination.StartsWith($repo + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe archive path.' }
                if ($PSCmdlet.ShouldProcess($destination, 'Restore saved build input (backing up current file)')) {
                    if (Test-Path -LiteralPath $destination) {
                        $saved = Join-Path $backup ('inputs/' + $entry.FullName)
                        New-Item -ItemType Directory -Path (Split-Path $saved) -Force | Out-Null
                        Copy-Item -LiteralPath $destination -Destination $saved
                    }
                    New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
                    [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $destination, $true)
                }
            }
        } finally { $archive.Dispose() }
    }
}
Write-Output 'Requested checkpoint restore operations completed. No save files were changed.'
