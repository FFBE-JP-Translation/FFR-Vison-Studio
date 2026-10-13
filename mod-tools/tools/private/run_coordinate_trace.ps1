# Starts the normal game with a passive observer; no fixture, level travel or
# command setup. Original saves remain read-only for this bounded diagnostic.
param(
    [switch]$Run,
    [ValidateRange(30,600)][int]$Seconds = 120,
    [ValidateRange(50,500)][int]$IntervalMilliseconds = 100,
    [string]$ExpectedInstalledManifest,
    [string]$GameBin = 'T:\SteamLibrary\steamapps\common\FINAL FANTASY RESONANCE DEMO\FFRS\Binaries\Win64'
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$auditRoot = [IO.Path]::GetFullPath((Join-Path $repo 'build\ffbe-coordinate-audit'))
$gameDirectory = (Resolve-Path -LiteralPath $GameBin).Path
$gameExe = Join-Path $gameDirectory 'FFRS-Win64-Shipping.exe'
$paksDirectory = [IO.Path]::GetFullPath((Join-Path $gameDirectory '..\..\Content\Paks'))
$runtimeDirectory = Join-Path $gameDirectory 'ue4ss'
$proxy = Join-Path $gameDirectory 'dwmapi.dll'
$appIdFile = Join-Path $gameDirectory 'steam_appid.txt'
$sourceRuntime = Join-Path $repo 'tools\UE4SS'
$observer = Join-Path $PSScriptRoot 'ffbe_coordinate_trace.lua'
function Hash([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Write-State { $state | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath (Join-Path $runDirectory 'run.json') -Encoding utf8NoBOM }
if (Get-Process -Name 'FFRS-Win64-Shipping' -ErrorAction SilentlyContinue) { throw 'FFR is already running.' }
foreach ($path in @($runtimeDirectory,$proxy,$appIdFile)) {
    if (Test-Path -LiteralPath $path) { throw "Existing runtime path must not be replaced: $path" }
}
if ((Hash $gameExe) -ne 'e06401cdf4e64d55f652043bdd2012267d5529a00c3dbc36ee4365e0ce49caad') { throw 'Unexpected game executable.' }
if ((Hash (Join-Path $sourceRuntime 'ue4ss\UE4SS.dll')) -ne '7082324aa440169fc992c02812a10f5c68a975d83f95273134c1c7ccddbe4b2d') { throw 'Unexpected UE4SS binary.' }
if (-not (Test-Path -LiteralPath $observer)) { throw 'Passive observer missing.' }
$packageFiles = @(Get-ChildItem -LiteralPath $paksDirectory -File -Recurse | Where-Object {
    $_.Extension -in @('.pak','.utoc','.ucas') -and $_.Name -match '^z'
})
$beforePackages = @{}; foreach ($file in $packageFiles) { $beforePackages[$file.FullName] = Hash $file.FullName }
if ($ExpectedInstalledManifest) {
    $expected = (Get-Content -LiteralPath $ExpectedInstalledManifest -Raw | ConvertFrom-Json).packageHashes
    if (-not $expected) { throw 'Expected installation manifest requires packageHashes.' }
    if (@($expected.PSObject.Properties).Count -ne $packageFiles.Count) { throw 'Installed package set differs.' }
    foreach ($entry in $expected.PSObject.Properties) {
        $matches = @($packageFiles | Where-Object Name -eq $entry.Name)
        if ($matches.Count -ne 1 -or $beforePackages[$matches[0].FullName] -ne $entry.Value) { throw "Installed package differs: $($entry.Name)" }
    }
}
if (-not $Run) {
    [ordered]@{status='preflight_passed_no_launch';mode='passive_normal_startup';game=$gameExe;observer=$observer;
        requiredForRun='-Run -ExpectedInstalledManifest <reviewed installed package hashes>';
        changes='temporary observer only; no artwork, fixture, level travel, command setup, or presentation setters';
        observationLimit='A real encounter must actually occur; normal startup alone is not battle evidence.'} | ConvertTo-Json
    return
}
if (-not $ExpectedInstalledManifest) { throw 'A reviewed installation manifest is required.' }
$runDirectory = [IO.Path]::GetFullPath((Join-Path $auditRoot ('runs\' + [DateTime]::UtcNow.ToString('yyyyMMdd_HHmmss_fff'))))
if (-not $runDirectory.StartsWith($auditRoot+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Run directory escaped workspace.' }
$probe = Join-Path $runDirectory 'Mods\FFBECoordinateTrace\Scripts'
$captureDirectory = Join-Path $runDirectory 'captures'
$null = New-Item -ItemType Directory -Path $probe,$captureDirectory
Copy-Item -LiteralPath $observer -Destination (Join-Path $probe 'main.lua')
Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $runDirectory 'runner.ps1')
Copy-Item -LiteralPath $ExpectedInstalledManifest -Destination (Join-Path $runDirectory 'expected-installation.json')
$mods = Join-Path $runDirectory 'Mods'
Set-Content -LiteralPath (Join-Path $mods 'mods.txt') -Value 'FFBECoordinateTrace : 1' -Encoding utf8NoBOM
$luaOutput = $captureDirectory.Replace('\','/').Replace("'","\'")
Set-Content -LiteralPath (Join-Path $probe 'config.lua') -Value "return {protectedSaves=true,output='$luaOutput',seconds=$Seconds,intervalMilliseconds=$IntervalMilliseconds}" -Encoding utf8NoBOM
$saveRoots = @((Join-Path $env:LOCALAPPDATA 'FFRS\Saved\SaveGames'), (Join-Path $env:LOCALAPPDATA 'FFRS_DEMO'))
foreach ($user in Get-ChildItem -LiteralPath 'S:\Program Files (x86)\Steam\userdata' -Directory) {
    $saveRoots += Join-Path $user.FullName '4474710'
}
$beforeSaves = @{}; $protectedSaves = @(); $backupManifest = @{}
$saveBackups = Join-Path $runDirectory 'original-save-backup'
$null = New-Item -ItemType Directory -Path $saveBackups
foreach ($saveRoot in $saveRoots) {
    if (Test-Path -LiteralPath $saveRoot) {
        foreach ($file in Get-ChildItem -LiteralPath $saveRoot -Recurse -File) {
            $beforeSaves[$file.FullName] = Hash $file.FullName
            if ($file.Extension -eq '.sav') {
                $backupName = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($file.FullName))).ToLowerInvariant() + '.sav'
                Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $saveBackups $backupName)
                $backupManifest[$file.FullName] = $backupName; $protectedSaves += $file.FullName
            }
        }
    }
}
$state = [ordered]@{mode='passive_normal_battle_coordinates';started=$false;cleaned=$false;runDirectory=$runDirectory;
    beforeSaves=$beforeSaves;saveBackups=$backupManifest;beforePackages=$beforePackages;seconds=$Seconds;
    observerSha256=(Hash $observer);saveProtection='original .sav files locked without write/delete sharing';
    fixtureUsed=$false;presentationMutated=$false;normalBattleObserved=$false}
Write-State
$saveLocks = @(); $process = $null; $createdRuntime = $false; $createdProxy = $false; $createdAppId = $false
$proxyHash = Hash (Join-Path $sourceRuntime 'dwmapi.dll')
try {
    foreach ($path in $protectedSaves) { $saveLocks += [IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read) }
    if ($saveLocks.Count -lt 1) { throw 'No original saves were protected; refusing launch.' }
    $null = New-Item -ItemType Directory -Path $runtimeDirectory; $createdRuntime = $true
    Copy-Item -LiteralPath (Join-Path $sourceRuntime 'ue4ss\UE4SS.dll') -Destination $runtimeDirectory
    $settings = Get-Content -LiteralPath (Join-Path $sourceRuntime 'ue4ss\UE4SS-settings.ini') -Raw
    foreach ($pair in @(@('MajorVersion','5'),@('MinorVersion','6'),@('ModsFolderPath',$mods.Replace('\','/')),
        @('ControllingModsTxt',(Join-Path $mods 'mods.txt').Replace('\','/')),@('GuiConsoleEnabled','0'),@('ConsoleEnabled','0'))) {
        $settings = $settings -replace ('(?m)^'+$pair[0]+'\s*=.*$'), ($pair[0]+' = '+$pair[1])
    }
    Set-Content -LiteralPath (Join-Path $runtimeDirectory 'UE4SS-settings.ini') -Value $settings -Encoding utf8NoBOM
    Copy-Item -LiteralPath (Join-Path $sourceRuntime 'dwmapi.dll') -Destination $proxy; $createdProxy = $true
    [IO.File]::WriteAllText($appIdFile,'4474710',[Text.Encoding]::ASCII); $createdAppId = $true
    # The normal entry map and existing resolution/settings are retained. No
    # debug level, forced camera, render-offscreen flag, or saved-game loading.
    $arguments = @('FFRS','-unattended',('-abslog="'+(Join-Path $runDirectory 'game.log')+'"'))
    $state.arguments = $arguments
    $process = Start-Process -FilePath $gameExe -WorkingDirectory $gameDirectory -ArgumentList $arguments -WindowStyle Hidden -PassThru
    $state.started=$true; $state.processId=$process.Id; Write-State
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while (-not $process.HasExited -and $timer.Elapsed.TotalSeconds -lt $Seconds) {
        Start-Sleep -Milliseconds 500; $process.Refresh()
    }
    $state.elapsedSeconds = $timer.Elapsed.TotalSeconds
} catch { $state.error=$_.Exception.Message; throw }
finally {
    if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force; $process.WaitForExit() }
    $live = @()
    for ($i=0; $i -lt 50; $i++) {
        $live = @(Get-Process -Name 'FFRS-Win64-Shipping' -ErrorAction SilentlyContinue | Where-Object { -not $_.HasExited })
        if (-not $live.Count) { break }; Start-Sleep -Milliseconds 100
    }
    if ($live.Count) { $state.cleanupDeferred=$true; Write-State; throw 'Game still running; temporary runtime retained.' }
    if ($createdRuntime) {
        $resolved = (Resolve-Path -LiteralPath $runtimeDirectory).Path
        $destination = [IO.Path]::GetFullPath((Join-Path $runDirectory 'collected-ue4ss'))
        if ($resolved -ne (Join-Path $gameDirectory 'ue4ss') -or -not $destination.StartsWith($runDirectory+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Runtime cleanup path check failed.' }
        Move-Item -LiteralPath $resolved -Destination $destination
    }
    if ($createdProxy) { if ((Hash $proxy) -ne $proxyHash) { throw 'Temporary proxy changed; retained.' }; Remove-Item -LiteralPath $proxy }
    if ($createdAppId) { if ([IO.File]::ReadAllText($appIdFile) -ne '4474710') { throw 'Temporary app-ID changed; retained.' }; Remove-Item -LiteralPath $appIdFile }
    foreach ($lock in $saveLocks) { $lock.Dispose() }
    $state.changedSaveFiles = @(); foreach ($path in $beforeSaves.Keys) {
        if (-not (Test-Path -LiteralPath $path) -or (Hash $path) -ne $beforeSaves[$path]) { $state.changedSaveFiles += $path }
    }
    $state.changedPackages = @(); foreach ($path in $beforePackages.Keys) {
        if (-not (Test-Path -LiteralPath $path) -or (Hash $path) -ne $beforePackages[$path]) { $state.changedPackages += $path }
    }
    $state.newSaveFiles = @(); foreach ($saveRoot in $saveRoots) {
        if (Test-Path -LiteralPath $saveRoot) {
            foreach ($file in Get-ChildItem -LiteralPath $saveRoot -Recurse -File) {
                if (-not $beforeSaves.ContainsKey($file.FullName)) { $state.newSaveFiles += $file.FullName }
            }
        }
    }
    $trace = Join-Path $captureDirectory 'coordinates.jsonl'
    if (Test-Path -LiteralPath $trace) {
        $state.traceSha256 = Hash $trace
        $state.normalBattleObserved = @(Get-Content -LiteralPath $trace | ForEach-Object { $_ | ConvertFrom-Json } |
            Where-Object { $_.kind -eq 'world' -and $_.isDebugFixture -eq $false }).Count -gt 0
    }
    $state.cleaned=$true; Write-State
    if ($state.changedSaveFiles.Count -or $state.changedPackages.Count) { throw 'Post-run save/package audit failed; inspect run.json.' }
}
Write-Output "Passive trace collected: $runDirectory (normal battle observed: $($state.normalBattleObserved))"
