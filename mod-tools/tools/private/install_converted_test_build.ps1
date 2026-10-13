$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$work=Join-Path $repo 'build/converted-moves-test'
$stage=Get-Content -LiteralPath (Join-Path $work 'staged-build.json') -Raw | ConvertFrom-Json
if(Get-Process -Name 'FFRS-Win64-Shipping' -ErrorAction SilentlyContinue) {throw 'Close FFR before installing the prepared test build.'}
$mods=[IO.Path]::GetFullPath((Join-Path $stage.game 'FFRS/Content/Paks/~mods'))
function Hash([string]$path) {(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()}
$files=@(Get-ChildItem -LiteralPath $mods -File)
if($files.Count -ne @($stage.before.PSObject.Properties).Count) {throw 'The installed mod inventory changed; stage again.'}
foreach($entry in $stage.before.PSObject.Properties) {
    if((Hash (Join-Path $mods $entry.Name)) -ne $entry.Value) {throw "Installed file changed: $($entry.Name)"}
}
foreach($entry in $stage.sources.PSObject.Properties) {
    if((Hash $entry.Value) -ne $stage.packageHashes.($entry.Name)) {throw "Staged file changed: $($entry.Name)"}
}
$backup=Join-Path $work ('installed-backup-'+[DateTime]::UtcNow.ToString('yyyyMMdd_HHmmss'))
$null=New-Item -ItemType Directory -Path $backup
$changed=@($stage.sources.PSObject.Properties.Name)+@($stage.remove)
foreach($name in $changed) {
    $path=[IO.Path]::GetFullPath((Join-Path $mods $name))
    if([IO.Path]::GetDirectoryName($path) -ne $mods) {throw 'Invalid installation filename.'}
    if(Test-Path -LiteralPath $path) {Copy-Item -LiteralPath $path -Destination $backup}
}
try {
    foreach($entry in $stage.sources.PSObject.Properties) {
        $target=Join-Path $mods $entry.Name
        Copy-Item -LiteralPath $entry.Value -Destination $target
        if((Hash $target) -ne $stage.packageHashes.($entry.Name)) {throw 'Installed checksum mismatch.'}
    }
    foreach($name in $stage.remove) {Remove-Item -LiteralPath (Join-Path $mods $name)}
} catch {
    foreach($name in $changed) {
        $saved=Join-Path $backup $name
        if(Test-Path -LiteralPath $saved) {Copy-Item -LiteralPath $saved -Destination (Join-Path $mods $name)}
    }
    throw
}
$hashes=@{}
foreach($file in Get-ChildItem -LiteralPath $mods -File) {$hashes[$file.Name]=Hash $file.FullName}
@{installedAt=[DateTime]::UtcNow.ToString('o');game=$stage.game;backup=$backup;packageHashes=$hashes;retiredTrials=$stage.remove;savesModified=$false} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $work 'installation.json') -Encoding utf8NoBOM
Write-Output 'Installed the new Studio mod and refreshed party, five-choice battle NPC, and vision cards. Previous packages are backed up.'
