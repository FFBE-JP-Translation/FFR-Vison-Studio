param([string]$CameraWork='build/cast-camera-step1')
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$work=Join-Path $repo $CameraWork
$stage=Get-Content -LiteralPath (Join-Path $work 'stage.json') -Raw | ConvertFrom-Json
$verification=Get-Content -LiteralPath (Join-Path $work 'mounted-verification.json') -Raw | ConvertFrom-Json
$cooked=Get-Content -LiteralPath (Join-Path $work 'cooked-verification.json') -Raw | ConvertFrom-Json
$unitSpec=Get-Content -LiteralPath (Join-Path $work 'units.json') -Raw | ConvertFrom-Json
$expectedMoves=4
foreach ($unit in $unitSpec) { $expectedMoves += @($unit.skills.PSObject.Properties).Count }
if (@($verification).Count -ne 4 -or @($cooked).Count -ne $expectedMoves) { throw 'Incomplete candidate verification.' }
if (Get-Process -Name 'FFRS-Win64-Shipping' -ErrorAction SilentlyContinue) { throw 'Close FFR before installation.' }
$mods=Join-Path $stage.game 'FFRS\Content\Paks\~mods'
function Hash([string]$p) { (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant() }
$current=@(Get-ChildItem -LiteralPath $mods -File)
$oldInstallPath=Join-Path $work 'installation.json'
$oldInstall=if(Test-Path -LiteralPath $oldInstallPath) { Get-Content -LiteralPath $oldInstallPath -Raw | ConvertFrom-Json } else { $null }
$existingCandidate=@($stage.candidate.PSObject.Properties | Where-Object {Test-Path -LiteralPath (Join-Path $mods $_.Name)})
if ($current.Count -ne (@($stage.before.PSObject.Properties).Count+$existingCandidate.Count)) { throw 'Installed mod inventory changed.' }
foreach ($p in $existingCandidate) {
    if (-not $oldInstall -or (Hash (Join-Path $mods $p.Name)) -ne $oldInstall.packageHashes.($p.Name)) { throw 'Existing candidate changed outside this task.' }
}
foreach ($p in $stage.before.PSObject.Properties) { if ((Hash (Join-Path $mods $p.Name)) -ne $p.Value) { throw "Installed file changed: $($p.Name)" } }
foreach ($p in $stage.candidate.PSObject.Properties) { if ((Hash (Join-Path $repo ('build\out\'+$p.Name))) -ne $p.Value) { throw "Candidate changed: $($p.Name)" } }
$copied=@()
$backup=Join-Path $work ('previous-candidate-'+[DateTime]::UtcNow.ToString('yyyyMMdd_HHmmss'))
$null=New-Item -ItemType Directory -Path $backup
try {
    foreach ($p in $stage.candidate.PSObject.Properties) {
        $destination=Join-Path $mods $p.Name
        if (Test-Path -LiteralPath $destination) { Copy-Item -LiteralPath $destination -Destination $backup }
        Copy-Item -LiteralPath (Join-Path $repo ('build\out\'+$p.Name)) -Destination $destination
        $copied += $destination
        if ((Hash $destination) -ne $p.Value) { throw 'Installed hash mismatch.' }
    }
} catch {
    foreach ($p in $copied) {
        if ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($p)) -ne [IO.Path]::GetFullPath($mods)) { throw 'Rollback boundary failed.' }
        $old=Join-Path $backup ([IO.Path]::GetFileName($p))
        if (Test-Path -LiteralPath $old) { Copy-Item -LiteralPath $old -Destination $p } else { Remove-Item -LiteralPath $p }
    }
    throw
}
$hashes=@{};foreach ($file in Get-ChildItem -LiteralPath $mods -File) { $hashes[$file.Name]=Hash $file.FullName }
@{packageHashes=$hashes;added=$copied;retainedFilesUnchanged=$true;saveFilesModified=$false;installedAt=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $work 'installation.json') -Encoding utf8NoBOM
Copy-Item -LiteralPath (Join-Path $work 'units-before.json') -Destination (Join-Path $work 'units-rollback.json')
Copy-Item -LiteralPath (Join-Path $work 'units.json') -Destination (Join-Path $repo 'mods\EstherTsukiko\units.json')
Write-Output 'Installed the three verified camera-step packages. Existing packages and saves were retained.'
