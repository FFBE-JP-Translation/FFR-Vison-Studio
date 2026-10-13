param(
    [ValidateRange(20,120)][int]$Seconds = 60,
    [switch]$LuaOnly,
    [switch]$OpenBattleTest,
    [switch]$ProtectedSaveTest,
    [switch]$TestSaveOverride,
    [switch]$StartBattle,
    [switch]$ConvertedAbility,
    [switch]$ConvertedExpiry,
    [switch]$DenyConverted,
    [switch]$LimitedConverted,
    [switch]$MenuLimited,
    [switch]$SourceAvailability,
    [switch]$OwnedSource,
    [switch]$VisionSource,
    [switch]$LifeSource,
    [switch]$CancelSource,
    [switch]$BattleReturn,
    [switch]$ResetSource,
    [switch]$LoadoutSource,
    [switch]$MultiCommand,
    [switch]$MultiCancel,
    [switch]$RepeatCommand,
    [switch]$RepeatControl,
    [switch]$RepeatSuppressed,
    [switch]$SelectionJobs,
    [string]$GameBin = 'T:\SteamLibrary\steamapps\common\FINAL FANTASY RESONANCE DEMO\FFRS\Binaries\Win64'
)
$ErrorActionPreference = 'Stop'
if ($SelectionJobs -and (-not $ConvertedAbility -or (-not $MultiCommand -and -not $RepeatCommand))) { throw 'Selection/job observation requires a converted manual or automatic repeat case.' }
if ($RepeatControl -and -not $RepeatCommand) { throw 'Repeat control requires -RepeatCommand.' }
if ($RepeatSuppressed -and (-not $RepeatCommand -or $RepeatControl)) { throw 'Repeat suppression requires the active repeat passive.' }
if ($RepeatCommand -and (-not $ConvertedAbility -or $ConvertedExpiry -or $DenyConverted -or $LimitedConverted -or $BattleReturn -or $LuaOnly -or $MultiCommand)) { throw 'Automatic repeat requires only the converted Fire battle.' }
if ($MultiCancel -and -not $MultiCommand) { throw 'Multi-command cancellation requires -MultiCommand.' }
if ($MultiCommand -and (-not $ConvertedAbility -or $ConvertedExpiry -or $DenyConverted -or $LimitedConverted -or $BattleReturn -or $LuaOnly)) { throw 'Multi-command observation requires only the converted Fire battle.' }
if ($LoadoutSource -and (-not $VisionSource -or $LifeSource -or $CancelSource -or $ResetSource -or $BattleReturn)) { throw 'Loadout changes require only the equipped Vision source mode.' }
if ($ResetSource) { $BattleReturn = $true }
if ($ResetSource -and (-not $OwnedSource -or $VisionSource -or $LifeSource -or $CancelSource)) { throw 'Battle reset requires ordinary owned source abilities.' }
if ($BattleReturn -and (-not $StartBattle -or ($ConvertedAbility -and -not $ResetSource) -or $LuaOnly)) { throw 'Battle return diagnostics require a protected stock or reset native battle.' }
if ($StartBattle -and (-not $OpenBattleTest -or -not $ProtectedSaveTest)) { throw 'Starting a debug battle requires -OpenBattleTest and -ProtectedSaveTest.' }
if ($ConvertedAbility -and (-not $StartBattle -or $LuaOnly)) { throw 'Converted ability validation requires a protected native battle.' }
if ($ConvertedExpiry -and -not $ConvertedAbility) { throw 'Expiry observation requires a converted ability battle.' }
if ($DenyConverted -and (-not $ConvertedAbility -or $ConvertedExpiry)) { throw 'Native denial requires a converted ability battle without expiry mode.' }
if ($LimitedConverted -and (-not $ConvertedAbility -or $ConvertedExpiry -or $DenyConverted)) { throw 'Limited-use fixture requires a converted ability battle without other fixture modes.' }
if ($MenuLimited -and -not $LimitedConverted) { throw 'Menu availability requires the limited-use fixture.' }
if ($SourceAvailability -and (-not $LimitedConverted -or -not $MenuLimited)) { throw 'Source availability requires both limited execution and menu query bindings.' }
if ($OwnedSource -and -not $SourceAvailability) { throw 'Native ownership validation requires a source availability fixture.' }
if ($VisionSource -and -not $OwnedSource) { throw 'Vision ownership validation requires -OwnedSource.' }
if ($LifeSource -and (-not $OwnedSource -or $VisionSource)) { throw 'Death/revival validation requires ordinary -OwnedSource.' }
if ($CancelSource -and (-not $OwnedSource -or $VisionSource -or $LifeSource)) { throw 'Command cancellation requires ordinary -OwnedSource without other ownership modes.' }
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$gameDirectory = (Resolve-Path -LiteralPath $GameBin).Path
$gameExe = Join-Path $gameDirectory 'FFRS-Win64-Shipping.exe'
$runtimeDirectory = Join-Path $gameDirectory 'ue4ss'
$proxy = Join-Path $gameDirectory 'dwmapi.dll'
$appIdFile = Join-Path $gameDirectory 'steam_appid.txt'
$staged = Join-Path $repo 'build\abilities\runtime-native\FFRAvailabilityRuntime'
$sourceRuntime = Join-Path $repo 'tools\UE4SS'
if (Get-Process -Name 'FFRS-Win64-Shipping' -ErrorAction SilentlyContinue) { throw 'FFR is already running.' }
if ((Test-Path -LiteralPath $runtimeDirectory) -or (Test-Path -LiteralPath $proxy)) { throw 'A game UE4SS installation already exists; refusing to replace it.' }
if (Test-Path -LiteralPath $appIdFile) { throw 'A Steam app-ID file already exists; refusing to replace it.' }
if ((Get-FileHash -LiteralPath $gameExe).Hash.ToLowerInvariant() -ne 'e06401cdf4e64d55f652043bdd2012267d5529a00c3dbc36ee4365e0ce49caad') { throw 'Unexpected game executable.' }
if ((Get-FileHash -LiteralPath (Join-Path $sourceRuntime 'ue4ss\UE4SS.dll')).Hash.ToLowerInvariant() -ne '7082324aa440169fc992c02812a10f5c68a975d83f95273134c1c7ccddbe4b2d') { throw 'Unexpected UE4SS DLL.' }
$manifest = Get-Content -LiteralPath (Join-Path $staged 'manifest.json') -Raw | ConvertFrom-Json
if ($manifest.mode -ne 'observe' -or $manifest.enabled -or $manifest.installed -or $manifest.status -ne 'passed') { throw 'Staged package must be a validated, disabled observer.' }
foreach ($entry in $manifest.files.PSObject.Properties) {
    $file = [IO.Path]::GetFullPath((Join-Path $staged $entry.Name))
    if (-not $file.StartsWith($staged + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid staged manifest path.' }
    if ((Get-FileHash -LiteralPath $file).Hash.ToLowerInvariant() -ne $entry.Value) { throw "Staged file changed: $($entry.Name)" }
}
$runDirectory = Join-Path $repo ('build\abilities\native-battle-runs\' + [DateTime]::UtcNow.ToString('yyyyMMdd_HHmmss_fff'))
$saveTitle = 'FFR_Ability_Observer_' + (Split-Path $runDirectory -Leaf)
$null = New-Item -ItemType Directory -Path $runDirectory
Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $runDirectory 'observe.ps1')
$mods = Join-Path $runDirectory 'Mods'
$null = New-Item -ItemType Directory -Path $mods
Copy-Item -LiteralPath $staged -Destination $mods -Recurse
$probe = Join-Path $mods 'FFRBattleProbe\Scripts'
$null = New-Item -ItemType Directory -Path $probe -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'battle_probe.lua') -Destination (Join-Path $probe 'main.lua')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'battle_driver.lua') -Destination (Join-Path $probe 'battle_driver.lua')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'converted_driver.lua') -Destination (Join-Path $probe 'converted_driver.lua')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'fire_driver.lua') -Destination (Join-Path $probe 'fire_driver.lua')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'deny_driver.lua') -Destination (Join-Path $probe 'deny_driver.lua')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'limited_driver.lua') -Destination (Join-Path $probe 'limited_driver.lua')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'source_driver.lua') -Destination (Join-Path $probe 'source_driver.lua')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'cooldown_driver.lua') -Destination (Join-Path $probe 'cooldown_driver.lua')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'owned_driver.lua') -Destination (Join-Path $probe 'owned_driver.lua')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'life_driver.lua') -Destination (Join-Path $probe 'life_driver.lua')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'loadout_driver.lua') -Destination (Join-Path $probe 'loadout_driver.lua')
if ($MultiCommand) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'multicommand_driver.lua') -Destination (Join-Path $probe 'multicommand_driver.lua')
    $probeScript = Get-Content -LiteralPath (Join-Path $probe 'main.lua') -Raw
    if ($MultiCancel) { $probeScript = "FFRBattleProbeMultiCancel = true`n" + $probeScript }
    Set-Content -LiteralPath (Join-Path $probe 'main.lua') -Value ("FFRBattleProbeMultiCommand = true`n" + $probeScript) -Encoding utf8NoBOM
}
if ($RepeatCommand) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'repeat_driver.lua') -Destination (Join-Path $probe 'repeat_driver.lua')
    $probeScript = Get-Content -LiteralPath (Join-Path $probe 'main.lua') -Raw
    if ($RepeatControl) { $probeScript = "FFRBattleProbeRepeatControl = true`n" + $probeScript }
    if ($RepeatSuppressed) { $probeScript = "FFRBattleProbeRepeatSuppressed = true`n" + $probeScript }
    Set-Content -LiteralPath (Join-Path $probe 'main.lua') -Value ("FFRBattleProbeRepeatCommand = true`n" + $probeScript) -Encoding utf8NoBOM
}
if ($BattleReturn) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'return_driver.lua') -Destination (Join-Path $probe 'return_driver.lua')
    $probeScript = Get-Content -LiteralPath (Join-Path $probe 'main.lua') -Raw
    Set-Content -LiteralPath (Join-Path $probe 'main.lua') -Value ("FFRBattleProbeReturn = true`n" + $probeScript) -Encoding utf8NoBOM
    if ($ResetSource) {
        $probeScript = Get-Content -LiteralPath (Join-Path $probe 'main.lua') -Raw
        Set-Content -LiteralPath (Join-Path $probe 'main.lua') -Value ("FFRBattleProbeResetSource = true`n" + $probeScript) -Encoding utf8NoBOM
    }
}
$abilityFixture = $null
if ($ConvertedAbility) {
    $abilityManifestPath = Join-Path $repo 'build\abilities\converted-ability-fixture.json'
    $abilityFixture = Get-Content -LiteralPath $abilityManifestPath -Raw | ConvertFrom-Json
    $abilityCase = $abilityFixture.case
    if ($MultiCommand -and ($abilityCase -ne 'fire' -or $abilityFixture.experiment.weaknessPhase -ne 'after')) { throw 'Multi-command observation requires production after-damage Fire.' }
    if ($RepeatCommand -and ($abilityCase -ne 'fire' -or $abilityFixture.experiment.weaknessPhase -ne 'after')) { throw 'Automatic repeat requires production after-damage Fire.' }
    if ($abilityFixture.status -ne 'built' -or $abilityCase -notin @('cure','fire','limited','cooldown') -or $abilityFixture.scope -ne "temporary_converted_${abilityCase}_fixture" -or $abilityFixture.skillId -ne 900010) { throw 'Build a supported converted ability fixture first.' }
    if (($abilityCase -in @('limited','cooldown')) -ne [bool]$SourceAvailability) { throw 'The source availability payload requires its explicit runtime binding mode.' }
    if ([bool]$abilityFixture.nativeOwnedSource -ne [bool]$OwnedSource) { throw 'Native skill grants require the matching ownership fixture mode.' }
    if ([bool]$abilityFixture.nativeVisionSource -ne [bool]$VisionSource) { throw 'Vision grants require the matching Vision fixture mode.' }
    if ([bool]$abilityFixture.nativeLifeSource -ne [bool]$LifeSource) { throw 'Native lifecycle controls require the matching life fixture mode.' }
    if ([bool]$abilityFixture.nativeMultiCommand -ne [bool]$MultiCommand) { throw 'Multi-command native grant requires the matching fixture mode.' }
    if ([bool]$abilityFixture.nativeRepeatCommand -ne [bool]$RepeatCommand -or [bool]$abilityFixture.nativeRepeatControl -ne [bool]$RepeatControl) { throw 'Automatic repeat grants require their matching fixture mode.' }
    if ([bool]$abilityFixture.nativeRepeatSuppressed -ne [bool]$RepeatSuppressed) { throw 'Repeat suppression requires its matching fixture mode.' }
    if ($OwnedSource -and $abilityCase -ne 'limited') { throw 'The ownership fixture requires the limited-use source.' }
    if ($ConvertedExpiry -and ($abilityCase -ne 'fire' -or $abilityFixture.experiment.weaknessPhase -ne 'after')) { throw 'Expiry observation requires the original after-damage Fire fixture.' }
    if (($DenyConverted -or $LimitedConverted) -and -not $SourceAvailability -and ($abilityCase -ne 'fire' -or $abilityFixture.experiment.weaknessPhase -ne 'after')) { throw 'Synthetic native gate fixtures require the original after-damage Fire fixture.' }
    if ($SourceAvailability) {
        $expectedSource = if ($abilityCase -eq 'cooldown') { 'JP_2022/ability/1007200' } else { 'GL_2024/ability/150300' }
        if ($abilityFixture.source -ne $expectedSource -or $abilityFixture.experiment.productionSupported -or -not $abilityFixture.experiment.productionHold) { throw 'Expected the retained, held FFBE source availability fixture.' }
    }
    foreach ($entry in $abilityFixture.inputs.PSObject.Properties) {
        $sourcePath = [IO.Path]::GetFullPath((Join-Path $repo $entry.Name))
        if (-not $sourcePath.StartsWith($repo + '\', [StringComparison]::OrdinalIgnoreCase) -or (Get-FileHash -LiteralPath $sourcePath).Hash.ToLowerInvariant() -ne $entry.Value) { throw 'Converted ability fixture inputs are stale.' }
    }
    if (@($abilityFixture.files.PSObject.Properties).Count -ne 3) { throw 'Expected three converted fixture package files.' }
    foreach ($entry in $abilityFixture.files.PSObject.Properties) {
        $sourcePath = [IO.Path]::GetFullPath($entry.Name)
        if (-not $sourcePath.StartsWith((Join-Path $repo 'build\abilities\'), [StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetFileName($sourcePath) -notmatch '^zzzzzz_FFRConvertedAbilityProbe_100_P\.(pak|ucas|utoc)$' -or (Get-FileHash -LiteralPath $sourcePath).Hash.ToLowerInvariant() -ne $entry.Value) { throw 'Converted fixture package failed verification.' }
    }
    if ($MultiCommand -or $RepeatCommand) {
        if (@($abilityFixture.nativeGrants).Count -ne 1 -or $abilityFixture.nativeGrants[0].unitId -ne 1001) { throw 'Expected one native Fire learning grant.' }
        $sourcePath = Join-Path $abilityFixture.directory 'cooked-grant-1001.json'
        if ((Get-FileHash -LiteralPath $sourcePath).Hash.ToLowerInvariant() -ne $abilityFixture.nativeGrants[0].cookedSha256) { throw 'Multi-command learning table changed.' }
        Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $runDirectory 'native-grant-1001.json')
    }
    if ($RepeatCommand) {
        if ($abilityFixture.nativeRepeatPassive.id -ne 90000 -or $abilityFixture.nativeRepeatPassive.templateEffectId -ne 1012) { throw 'Unexpected native repeat passive.' }
        $sourcePath = Join-Path $abilityFixture.directory 'cooked-repeat-passive.json'
        if ((Get-FileHash -LiteralPath $sourcePath).Hash.ToLowerInvariant() -ne $abilityFixture.nativeRepeatPassive.cookedSha256) { throw 'Repeat passive table changed.' }
        Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $runDirectory 'native-repeat-passive.json')
        if ($RepeatSuppressed) {
            $sourcePath = Join-Path $abilityFixture.directory 'cooked-general.json'
            if ((Get-FileHash -LiteralPath $sourcePath).Hash.ToLowerInvariant() -ne $abilityFixture.cookedGeneralSha256) { throw 'Native repeat exclusion changed.' }
            Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $runDirectory 'native-repeat-general.json')
        }
    }
    Copy-Item -LiteralPath $abilityManifestPath -Destination (Join-Path $runDirectory 'converted-ability-build.json')
    $profilePath = Join-Path $abilityFixture.directory 'profile.json'
    if ((Get-FileHash -LiteralPath $profilePath).Hash.ToLowerInvariant() -ne $abilityFixture.profileSha256) { throw 'Converted source profile changed.' }
    Copy-Item -LiteralPath $profilePath -Destination (Join-Path $runDirectory 'converted-profile.json')
    $probeScript = Get-Content -LiteralPath (Join-Path $probe 'main.lua') -Raw
    Set-Content -LiteralPath (Join-Path $probe 'main.lua') -Value ("FFRBattleProbeConvertedAbility = 900010`nFFRBattleProbeConvertedCase = '$abilityCase'`n" + $probeScript) -Encoding utf8NoBOM
    if ($ConvertedExpiry) {
        $probeScript = Get-Content -LiteralPath (Join-Path $probe 'main.lua') -Raw
        Set-Content -LiteralPath (Join-Path $probe 'main.lua') -Value ("FFRBattleProbeConvertedExpiry = true`n" + $probeScript) -Encoding utf8NoBOM
    }
    if ($DenyConverted -or $LimitedConverted) {
        $gateFixtureModule = if ($OwnedSource) { 'owned_fixture' } elseif ($LimitedConverted) { 'limited_fixture' } else { 'denial_fixture' }
        $gateDriver = if ($LoadoutSource) { 'loadout_driver.lua' } elseif ($LifeSource) { 'life_driver.lua' } elseif ($OwnedSource) { 'owned_driver.lua' } elseif ($SourceAvailability -and $abilityCase -eq 'cooldown') { 'cooldown_driver.lua' } elseif ($SourceAvailability) { 'source_driver.lua' } elseif ($LimitedConverted) { 'limited_driver.lua' } else { 'deny_driver.lua' }
        $gateGlobal = if ($LimitedConverted) { 'FFRBattleProbeLimitedConverted' } else { 'FFRBattleProbeDenyConverted' }
        $probeScript = Get-Content -LiteralPath (Join-Path $probe 'main.lua') -Raw
        if ($MenuLimited) { $probeScript = "FFRBattleProbeMenuLimited = true`n" + $probeScript }
        if ($SourceAvailability) { $probeScript = "FFRBattleProbeSourceAvailability = true`n" + $probeScript }
        if ($OwnedSource) { $probeScript = "FFRBattleProbeOwnedSource = true`n" + $probeScript }
        if ($VisionSource) { $probeScript = "FFRBattleProbeVisionSource = true`n" + $probeScript }
        if ($LifeSource) { $probeScript = "FFRBattleProbeLifeSource = true`n" + $probeScript }
        if ($CancelSource) { $probeScript = "FFRBattleProbeCancelSource = true`n" + $probeScript }
        if ($LoadoutSource) { $probeScript = "FFRBattleProbeLoadoutSource = true`n" + $probeScript }
        Set-Content -LiteralPath (Join-Path $probe 'main.lua') -Value ("$gateGlobal = true`n" + $probeScript) -Encoding utf8NoBOM
        $runtimeScripts = Join-Path $mods 'FFRAvailabilityRuntime\Scripts'
        Copy-Item -LiteralPath (Join-Path $runtimeScripts 'main.lua') -Destination (Join-Path $runtimeScripts 'main.observer.lua')
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot ($gateFixtureModule + '.lua')) -Destination (Join-Path $runtimeScripts ($gateFixtureModule + '.lua'))
        if ($MenuLimited) { Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'query_fixture.lua') -Destination (Join-Path $runtimeScripts 'query_fixture.lua') }
        $originalMain = [IO.File]::ReadAllText((Join-Path $runtimeScripts 'main.observer.lua'))
        $derivedMain = $originalMain.Replace('{mode="observe",reason=reason}', '{mode="enforce_fixture",reason=reason}')
        if ($derivedMain -eq $originalMain) { throw 'Native observer handshake changed; review the denial fixture overlay.' }
        $gatePrefix = if ($MenuLimited) { "FFRAvailabilityFixtureMenu = true`n" } else { '' }
        if ($VisionSource) { $gatePrefix = "FFRAvailabilityFixtureVision = true`n" + $gatePrefix }
        if ($LifeSource) { $gatePrefix = "FFRAvailabilityFixtureLife = true`n" + $gatePrefix }
        if ($ResetSource) { $gatePrefix = "FFRAvailabilityFixtureReset = true`n" + $gatePrefix }
        if ($LoadoutSource) { $gatePrefix = "FFRAvailabilityFixtureLoadout = true`n" + $gatePrefix }
        if ($SourceAvailability) {
            $gatePrefix = "FFRAvailabilityFixtureSource = true`n" + $gatePrefix
            $sourceArtifacts = @{ 'availability-plan.json'='availabilityPlanSha256'; 'experimental-profile.json'='experimentalProfileSha256'; 'source_contract.lua'='sourceContractSha256' }
            foreach ($name in $sourceArtifacts.Keys) {
                $sourcePath = Join-Path $abilityFixture.directory $name
                $digest = $abilityFixture.($sourceArtifacts[$name])
                if (-not $digest -or (Get-FileHash -LiteralPath $sourcePath).Hash.ToLowerInvariant() -ne $digest) { throw "Source availability artifact changed: $name" }
                $destination = if ($name -eq 'source_contract.lua') { Join-Path $runtimeScripts $name } else { Join-Path $runDirectory $name }
                Copy-Item -LiteralPath $sourcePath -Destination $destination
            }
            if ($OwnedSource) {
                if (@($abilityFixture.nativeGrants).Count -ne 2) { throw 'Expected two native actor grants.' }
                foreach ($grant in $abilityFixture.nativeGrants) {
                    if ($grant.unitId -notin @(1001,1002)) { throw 'Unexpected ownership fixture unit.' }
                    $sourcePath = Join-Path $abilityFixture.directory ("cooked-grant-" + $grant.unitId + '.json')
                    if ((Get-FileHash -LiteralPath $sourcePath).Hash.ToLowerInvariant() -ne $grant.cookedSha256) { throw 'Native grant table changed.' }
                    Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $runDirectory ("native-grant-" + $grant.unitId + '.json'))
                }
                if ($VisionSource) {
                    $sourcePath = Join-Path $abilityFixture.directory 'cooked-general.json'
                    if ((Get-FileHash -LiteralPath $sourcePath).Hash.ToLowerInvariant() -ne $abilityFixture.cookedGeneralSha256) { throw 'Native equipper binding changed.' }
                    Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $runDirectory 'native-general.json')
                }
            }
        }
        [IO.File]::WriteAllText((Join-Path $runtimeScripts 'main.lua'), ($gatePrefix + "require('$gateFixtureModule')`n" + $derivedMain), [Text.UTF8Encoding]::new($false))
    }
}
if ($StartBattle) {
    $probeScript = Get-Content -LiteralPath (Join-Path $probe 'main.lua') -Raw
    Set-Content -LiteralPath (Join-Path $probe 'main.lua') -Value ("FFRBattleProbeStartBattle = true`n" + $probeScript) -Encoding utf8NoBOM
}
if ($OpenBattleTest) {
    $probeScript = Get-Content -LiteralPath (Join-Path $probe 'main.lua') -Raw
    Set-Content -LiteralPath (Join-Path $probe 'main.lua') -Value ("FFRBattleProbeOpenTest = true`n" + $probeScript) -Encoding utf8NoBOM
}
$runtimeEnabled = if ($LuaOnly) { 0 } else { 1 }
$fixtureLine = ''
$selectionLine = ''
if ($SelectionJobs) {
    $selectionManifestPath = Join-Path $repo 'build\abilities\native-selection-build.json'
    $selectionManifest = Get-Content -LiteralPath $selectionManifestPath -Raw | ConvertFrom-Json
    if ($selectionManifest.status -ne 'built' -or $selectionManifest.scope -ne 'selection_entry_job_observation_only' -or
        (Get-FileHash -LiteralPath $selectionManifest.dll).Hash.ToLowerInvariant() -ne $selectionManifest.dllSha256) { throw 'Build the separate selection observer first.' }
    foreach ($entry in $selectionManifest.inputs.PSObject.Properties) {
        if ((Get-FileHash -LiteralPath (Join-Path $repo $entry.Name)).Hash.ToLowerInvariant() -ne $entry.Value) { throw 'Selection observer build is stale.' }
    }
    $selectionDllDirectory = Join-Path $mods 'FFRSelectionProbe\dlls'
    $null = New-Item -ItemType Directory -Path $selectionDllDirectory -Force
    Copy-Item -LiteralPath $selectionManifest.dll -Destination (Join-Path $selectionDllDirectory 'main.dll')
    Copy-Item -LiteralPath $selectionManifestPath -Destination (Join-Path $runDirectory 'selection-build.json')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'selection_driver.lua') -Destination (Join-Path $probe 'selection_driver.lua')
    $probeScript = Get-Content -LiteralPath (Join-Path $probe 'main.lua') -Raw
    Set-Content -LiteralPath (Join-Path $probe 'main.lua') -Value ("FFRBattleProbeSelectionJobs = true`n" + $probeScript) -Encoding utf8NoBOM
    $selectionLine = "FFRSelectionProbe : 1`n"
}
if ($StartBattle) {
    $fixtureManifestPath = Join-Path $repo 'build\abilities\native-fixture-build.json'
    $fixtureManifest = Get-Content -LiteralPath $fixtureManifestPath -Raw | ConvertFrom-Json
    if ($fixtureManifest.status -ne 'built' -or (Get-FileHash -LiteralPath $fixtureManifest.dll).Hash.ToLowerInvariant() -ne $fixtureManifest.dllSha256) { throw 'Build the current separate battle-fixture DLL first.' }
    foreach ($entry in $fixtureManifest.inputs.PSObject.Properties) {
        if ((Get-FileHash -LiteralPath (Join-Path $repo $entry.Name)).Hash.ToLowerInvariant() -ne $entry.Value) { throw 'Battle-fixture build is stale.' }
    }
    $fixtureDllDirectory = Join-Path $mods 'FFRBattleFixture\dlls'
    $null = New-Item -ItemType Directory -Path $fixtureDllDirectory -Force
    Copy-Item -LiteralPath $fixtureManifest.dll -Destination (Join-Path $fixtureDllDirectory 'main.dll')
    Copy-Item -LiteralPath $fixtureManifestPath -Destination (Join-Path $runDirectory 'fixture-build.json')
    $fixtureLine = "FFRBattleFixture : 1`n"
}
Set-Content -LiteralPath (Join-Path $mods 'mods.txt') -Value ("FFRAvailabilityRuntime : $runtimeEnabled`n" + $fixtureLine + $selectionLine + 'FFRBattleProbe : 1') -Encoding utf8NoBOM
$userDirectory = Join-Path $runDirectory 'user'
$null = New-Item -ItemType Directory -Path $userDirectory
$proxyHash = (Get-FileHash -LiteralPath (Join-Path $sourceRuntime 'dwmapi.dll')).Hash
$saveRoots = @((Join-Path $env:LOCALAPPDATA 'FFRS\Saved\SaveGames'))
$saveRoots += Join-Path $env:LOCALAPPDATA 'FFRS_DEMO'
$steamUserData = 'S:\Program Files (x86)\Steam\userdata'
foreach ($user in Get-ChildItem -LiteralPath $steamUserData -Directory) {
    $saveRoots += Join-Path $user.FullName '4474710'
}
$beforeSaves = @{}
$protectedSaves = @()
$saveBackups = Join-Path $runDirectory 'original-save-backup'
$null = New-Item -ItemType Directory -Path $saveBackups
foreach ($saveRoot in $saveRoots) {
    if (Test-Path -LiteralPath $saveRoot) {
        foreach ($file in Get-ChildItem -LiteralPath $saveRoot -Recurse -File) {
            $beforeSaves[$file.FullName] = (Get-FileHash -LiteralPath $file.FullName).Hash
            if ($file.Extension -eq '.sav') {
                $backupName = ([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($file.FullName)))).ToLowerInvariant() + '.sav'
                Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $saveBackups $backupName)
                $protectedSaves += $file.FullName
            }
        }
    }
}
$state = [ordered]@{ mode='observation_only'; debugCombatRequested=[bool]$StartBattle; convertedAbilityRequested=[bool]$ConvertedAbility; nativeBridgeEnabled=(-not $LuaOnly); runDirectory=$runDirectory; installedPaths=@($runtimeDirectory,$proxy,$appIdFile); started=$false; cleaned=$false; beforeSaves=$beforeSaves }
$state.convertedExpiryRequested = [bool]$ConvertedExpiry
$state.nativeDenialRequested = [bool]$DenyConverted
$state.nativeLimitedRequested = [bool]$LimitedConverted
$state.nativeMenuLimitedRequested = [bool]$MenuLimited
$state.nativeSourceAvailabilityRequested = [bool]$SourceAvailability
$state.nativeOwnedSourceRequested = [bool]$OwnedSource
$state.nativeVisionSourceRequested = [bool]$VisionSource
$state.nativeLifeSourceRequested = [bool]$LifeSource
$state.nativeCancelSourceRequested = [bool]$CancelSource
$state.battleReturnRequested = [bool]$BattleReturn
$state.nativeResetSourceRequested = [bool]$ResetSource
$state.nativeLoadoutSourceRequested = [bool]$LoadoutSource
$state.nativeMultiCommandRequested = [bool]$MultiCommand
$state.nativeMultiCancelRequested = [bool]$MultiCancel
$state.nativeRepeatRequested = [bool]$RepeatCommand
$state.nativeRepeatControlRequested = [bool]$RepeatControl
$state.nativeRepeatSuppressedRequested = [bool]$RepeatSuppressed
if ($DenyConverted) { $state.mode = 'native_denial_fixture' }
if ($LimitedConverted) { $state.mode = 'native_limited_fixture' }
if ($MenuLimited) { $state.mode = 'native_limited_menu_fixture' }
if ($SourceAvailability) { $state.mode = 'native_source_availability_fixture' }
if ($OwnedSource) { $state.mode = 'native_owned_source_fixture' }
if ($VisionSource) { $state.mode = 'native_vision_source_fixture' }
if ($LifeSource) { $state.mode = 'native_life_source_fixture' }
if ($CancelSource) { $state.mode = 'native_cancel_source_fixture' }
if ($BattleReturn) { $state.mode = 'native_battle_return_diagnostic' }
if ($ResetSource) { $state.mode = 'native_reset_source_fixture' }
if ($LoadoutSource) { $state.mode = 'native_loadout_source_fixture' }
if ($MultiCommand) { $state.mode = 'native_multicommand_diagnostic' }
if ($MultiCancel) { $state.mode = 'native_multicommand_cancel_diagnostic' }
if ($RepeatCommand) { $state.mode = 'native_repeat_diagnostic' }
if ($RepeatControl) { $state.mode = 'native_repeat_control_diagnostic' }
if ($RepeatSuppressed) { $state.mode = 'native_repeat_suppressed_diagnostic' }
$state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runDirectory 'run.json') -Encoding utf8NoBOM
$process = $null
$createdRuntime = $false
$createdProxy = $false
$createdAppId = $false
$createdConfig = $false
$saveLocks = @()
$createdAbilityPackages = @{}
try {
    foreach ($path in $protectedSaves) {
        $saveLocks += [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    }
    if ($ProtectedSaveTest) {
        if ($saveLocks.Count -lt 1) { throw 'No original saves were protected; refusing test-map travel.' }
        $probeScript = Get-Content -LiteralPath (Join-Path $probe 'main.lua') -Raw
        Set-Content -LiteralPath (Join-Path $probe 'main.lua') -Value ("FFRBattleProbeProtectedSaves = true`n" + $probeScript) -Encoding utf8NoBOM
        $state.saveProtection = 'existing_sav_files_locked_against_write_and_delete'
        $state.protectedSaveFiles = $protectedSaves
    }
    $null = New-Item -ItemType Directory -Path $runtimeDirectory
    $createdRuntime = $true
    Copy-Item -LiteralPath (Join-Path $sourceRuntime 'ue4ss\UE4SS.dll') -Destination $runtimeDirectory
    $settings = Get-Content -LiteralPath (Join-Path $sourceRuntime 'ue4ss\UE4SS-settings.ini') -Raw
    $settings = $settings -replace '(?m)^MajorVersion\s*=.*$', 'MajorVersion = 5'
    $settings = $settings -replace '(?m)^MinorVersion\s*=.*$', 'MinorVersion = 6'
    $settings = $settings -replace '(?m)^ModsFolderPath\s*=.*$', ('ModsFolderPath = ' + $mods.Replace('\','/'))
    $settings = $settings -replace '(?m)^ControllingModsTxt\s*=.*$', ('ControllingModsTxt = ' + (Join-Path $mods 'mods.txt').Replace('\','/'))
    $settings = $settings -replace '(?m)^GuiConsoleEnabled\s*=.*$', 'GuiConsoleEnabled = 0'
    $settings = $settings -replace '(?m)^ConsoleEnabled\s*=.*$', 'ConsoleEnabled = 0'
    Set-Content -LiteralPath (Join-Path $runtimeDirectory 'UE4SS-settings.ini') -Value $settings -Encoding utf8NoBOM
    Copy-Item -LiteralPath (Join-Path $sourceRuntime 'dwmapi.dll') -Destination $proxy
    $createdProxy = $true
    # Valve documents this file for direct executable/debugger launches. Use the
    # installed demo's real app ID; Steam remains responsible for authentication.
    [IO.File]::WriteAllText($appIdFile, '4474710', [Text.Encoding]::ASCII)
    $createdAppId = $true
    # Retained as an explicit diagnostic only: both config override mechanisms
    # left GameTitle unchanged in the tested shipping build.
    if ($TestSaveOverride) {
    $configRoot = Join-Path $runDirectory 'config'
    $configPath = Join-Path $configRoot 'FFRS\Config\DefaultSQEXSaveGameSystem.ini'
    $null = New-Item -ItemType Directory -Path (Split-Path $configPath -Parent) -Force
    Set-Content -LiteralPath $configPath -Value ("[/Script/SQEXSaveGameSystemModule.SQEXSaveGameSystemSettings]`nGameTitle=" + $saveTitle) -Encoding utf8NoBOM
    $configPak = Join-Path $runDirectory ($saveTitle + '_P.pak')
    $repak = Join-Path $repo 'tools\repak\repak.exe'
    & $repak pack --version V11 $configRoot $configPak > (Join-Path $runDirectory 'config-pack.log')
    if ($LASTEXITCODE -ne 0) { throw 'Observer config packaging failed.' }
    $roundTrip = & $repak get $configPak 'FFRS/Config/DefaultSQEXSaveGameSystem.ini'
    if ($LASTEXITCODE -ne 0 -or ($roundTrip -join "`n") -notmatch [regex]::Escape($saveTitle)) { throw 'Observer config round-trip failed.' }
    $paksDirectory = [IO.Path]::GetFullPath((Join-Path $gameDirectory '..\..\Content\Paks'))
    $installedConfig = Join-Path $paksDirectory ([IO.Path]::GetFileName($configPak))
    if (Test-Path -LiteralPath $installedConfig) { throw 'Temporary config package already exists.' }
    $configHash = (Get-FileHash -LiteralPath $configPak).Hash
    Copy-Item -LiteralPath $configPak -Destination $installedConfig
    $createdConfig = $true
    $state.installedPaths += $installedConfig
    $state.requestedSaveTitle = $saveTitle
    }
    $arguments = @('FFRS', '/Game/Debug/BattleTest/DBG_BattleTest', '-RenderOffscreen', '-Windowed', '-ResX=960', '-ResY=540', '-ForceRes', '-nosound', '-unattended', ('-UserDir="' + $userDirectory + '"'), ('-abslog="' + (Join-Path $runDirectory 'game.log') + '"'), ('-seconds=' + $Seconds))
    if ($TestSaveOverride) { $arguments += '-ini:SQEXSaveGameSystem:[/Script/SQEXSaveGameSystemModule.SQEXSaveGameSystemSettings]:GameTitle=' + $saveTitle }
    $state.arguments = $arguments
    $state.inputHashes = @{}
    foreach ($path in @($PSCommandPath, (Join-Path $probe 'fire_driver.lua'), (Join-Path $probe 'main.lua'), (Join-Path $probe 'battle_driver.lua'), (Join-Path $probe 'converted_driver.lua'), (Join-Path $mods 'FFRAvailabilityRuntime\dlls\main.dll'), (Join-Path $mods 'FFRAvailabilityRuntime\Scripts\main.lua'))) {
        $state.inputHashes[$path] = (Get-FileHash -LiteralPath $path).Hash
    }
    if ($DenyConverted -or $LimitedConverted) {
        foreach ($path in @((Join-Path $probe $gateDriver), (Join-Path $runtimeScripts ($gateFixtureModule + '.lua')), (Join-Path $runtimeScripts 'main.observer.lua'))) {
            $state.inputHashes[$path] = (Get-FileHash -LiteralPath $path).Hash
        }
        if ($MenuLimited) {
            $path = Join-Path $runtimeScripts 'query_fixture.lua'
            $state.inputHashes[$path] = (Get-FileHash -LiteralPath $path).Hash
        }
    }
    if ($BattleReturn) {
        $path = Join-Path $probe 'return_driver.lua'
        $state.inputHashes[$path] = (Get-FileHash -LiteralPath $path).Hash
    }
    if ($MultiCommand) {
        $path = Join-Path $probe 'multicommand_driver.lua'
        $state.inputHashes[$path] = (Get-FileHash -LiteralPath $path).Hash
        $path = Join-Path $runDirectory 'native-grant-1001.json'
        $state.inputHashes[$path] = (Get-FileHash -LiteralPath $path).Hash
    }
    if ($RepeatCommand) {
        if ($RepeatSuppressed) {
            $path = Join-Path $runDirectory 'native-repeat-general.json'
            $state.inputHashes[$path] = (Get-FileHash -LiteralPath $path).Hash
        }
        foreach ($path in @((Join-Path $probe 'repeat_driver.lua'), (Join-Path $runDirectory 'native-grant-1001.json'), (Join-Path $runDirectory 'native-repeat-passive.json'))) {
            $state.inputHashes[$path] = (Get-FileHash -LiteralPath $path).Hash
        }
    }
    if ($SourceAvailability) {
        foreach ($path in @((Join-Path $runDirectory 'availability-plan.json'),(Join-Path $runDirectory 'experimental-profile.json'),(Join-Path $runtimeScripts 'source_contract.lua'))) {
            $state.inputHashes[$path] = (Get-FileHash -LiteralPath $path).Hash
        }
    }
    if ($OwnedSource) {
        $path = Join-Path $probe 'owned_driver.lua'
        $state.inputHashes[$path] = (Get-FileHash -LiteralPath $path).Hash
        foreach ($id in @(1001,1002)) {
            $path = Join-Path $runDirectory ("native-grant-$id.json")
            $state.inputHashes[$path] = (Get-FileHash -LiteralPath $path).Hash
        }
        if ($VisionSource) {
            $path = Join-Path $runDirectory 'native-general.json'
            $state.inputHashes[$path] = (Get-FileHash -LiteralPath $path).Hash
        }
    }
    if ($StartBattle) {
        $fixturePath = Join-Path $fixtureDllDirectory 'main.dll'
        $state.inputHashes[$fixturePath] = (Get-FileHash -LiteralPath $fixturePath).Hash
        $fixtureBuildPath = Join-Path $runDirectory 'fixture-build.json'
        $state.inputHashes[$fixtureBuildPath] = (Get-FileHash -LiteralPath $fixtureBuildPath).Hash
    }
    $state.nativeSelectionJobsRequested = [bool]$SelectionJobs
    if ($SelectionJobs) {
        foreach ($path in @((Join-Path $selectionDllDirectory 'main.dll'), (Join-Path $runDirectory 'selection-build.json'), (Join-Path $probe 'selection_driver.lua'))) {
            $state.inputHashes[$path] = (Get-FileHash -LiteralPath $path).Hash
        }
    }
    $state.existingGamePackages = @{}
    $existingPaks = [IO.Path]::GetFullPath((Join-Path $gameDirectory '..\..\Content\Paks\~mods'))
    if (Test-Path -LiteralPath $existingPaks) {
        foreach ($file in Get-ChildItem -LiteralPath $existingPaks -File) { $state.existingGamePackages[$file.Name] = (Get-FileHash -LiteralPath $file.FullName).Hash }
    }
    if ($ConvertedAbility) {
        foreach ($entry in $abilityFixture.files.PSObject.Properties) {
            $destination = [IO.Path]::GetFullPath((Join-Path $existingPaks ([IO.Path]::GetFileName($entry.Name))))
            if (-not $destination.StartsWith($existingPaks + '\', [StringComparison]::OrdinalIgnoreCase) -or (Test-Path -LiteralPath $destination)) { throw 'Refusing to replace an installed converted fixture package.' }
        }
        foreach ($entry in $abilityFixture.files.PSObject.Properties) {
            $destination = Join-Path $existingPaks ([IO.Path]::GetFileName($entry.Name))
            Copy-Item -LiteralPath $entry.Name -Destination $destination
            $createdAbilityPackages[$destination] = $entry.Value
            $state.installedPaths += $destination
            $state.inputHashes[$entry.Name] = $entry.Value
        }
        foreach ($name in @('converted-ability-build.json','converted-profile.json')) {
            $path = Join-Path $runDirectory $name
            $state.inputHashes[$path] = (Get-FileHash -LiteralPath $path).Hash
        }
        $state.temporaryContentPackages = $createdAbilityPackages
    }
    $process = Start-Process -FilePath $gameExe -WorkingDirectory $gameDirectory -ArgumentList $arguments -WindowStyle Hidden -PassThru
    $state.started = $true
    $state.processId = $process.Id
    $state.startedUtc = [DateTime]::UtcNow.ToString('o')
    $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runDirectory 'run.json') -Encoding utf8NoBOM
    Write-Output "Observer run $runDirectory (PID $($process.Id))"
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while (-not $process.HasExited -and $timer.Elapsed.TotalSeconds -lt ($Seconds + 20)) {
        Start-Sleep -Seconds 2
        $process.Refresh()
        $liveLog = Join-Path $runtimeDirectory 'UE4SS.log'
        $completionMarker = if ($BattleReturn) { '[FFRReturnDriver] return_observation_complete' } elseif ($ConvertedAbility) { '[FFRConvertedDriver] converted_observation_complete' } else { '[FFRBattleDriver] stock_observation_complete' }
        if (($BattleReturn -or $DenyConverted -or $LimitedConverted -or $MultiCommand -or $RepeatCommand) -and (Test-Path -LiteralPath $liveLog) -and
            (Select-String -LiteralPath $liveLog -SimpleMatch -Pattern @('combat_driver_failed=', 'limited_binding_failed', 'owned_binding_failed') -Quiet)) {
            $state.fixtureFailed = $true
            break
        }
        if ($StartBattle -and (Test-Path -LiteralPath $liveLog) -and
            (Select-String -LiteralPath $liveLog -SimpleMatch $completionMarker -Quiet)) {
            $state.fixtureCompleted = $true
            break
        }
    }
    if (-not $process.HasExited) {
        if ($state.fixtureFailed) { $state.fixtureFailureTerminated = $true }
        elseif ($state.fixtureCompleted) { $state.fixtureTerminated = $true }
        else { $state.timeoutTerminated = $true }
        Stop-Process -Id $process.Id -Force
        $process.WaitForExit()
    }
    $state.exitCode = $process.ExitCode
    $state.elapsedSeconds = [Math]::Round($timer.Elapsed.TotalSeconds,2)
} catch {
    $state.error = $_.Exception.Message
    throw
} finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        $process.WaitForExit()
    }
    # Move only the directory created by this run; retain runtime logs and dumps.
    $remainingGameProcesses = @()
    for ($exitPoll = 0; $exitPoll -lt 20; $exitPoll++) {
        $remainingGameProcesses = @(Get-Process -Name 'FFRS-Win64-Shipping' -ErrorAction SilentlyContinue | Where-Object { -not $_.HasExited })
        if ($remainingGameProcesses.Count -eq 0) { break }
        Start-Sleep -Milliseconds 100
    }
    if ($remainingGameProcesses.Count -gt 0) {
        foreach ($lock in $saveLocks) { $lock.Dispose() }
        $state.error = 'Cleanup deferred because another game process remains live.'
        $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runDirectory 'run.json') -Encoding utf8NoBOM
        throw "An FFR process is running; cleanup deferred. See $runDirectory\run.json"
    }
    foreach ($lock in $saveLocks) { $lock.Dispose() }
    foreach ($path in $createdAbilityPackages.Keys) {
        if ((Get-FileHash -LiteralPath $path).Hash.ToLowerInvariant() -ne $createdAbilityPackages[$path]) { throw 'Temporary ability package changed; retaining for inspection.' }
        Remove-Item -LiteralPath $path
    }
    if ($createdRuntime) {
        $resolvedRuntime = (Resolve-Path -LiteralPath $runtimeDirectory).Path
        $destination = [IO.Path]::GetFullPath((Join-Path $runDirectory 'collected-ue4ss'))
        if ($resolvedRuntime -ne (Join-Path $gameDirectory 'ue4ss') -or -not $destination.StartsWith($runDirectory + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Cleanup path verification failed.' }
        Move-Item -LiteralPath $resolvedRuntime -Destination $destination
    }
    if ($createdProxy) {
        if ((Get-FileHash -LiteralPath $proxy).Hash -ne $proxyHash) { throw 'Temporary proxy was modified; retaining it for inspection.' }
        Remove-Item -LiteralPath $proxy
    }
    if ($createdAppId) {
        if ([IO.File]::ReadAllText($appIdFile) -ne '4474710') { throw 'Temporary app-ID file was modified; retaining it for inspection.' }
        Remove-Item -LiteralPath $appIdFile
    }
    if ($createdConfig) {
        if ((Get-FileHash -LiteralPath $installedConfig).Hash -ne $configHash) { throw 'Temporary config package was modified; retaining it for inspection.' }
        Remove-Item -LiteralPath $installedConfig
    }
    $state.cleaned = $true
    $state.endedUtc = [DateTime]::UtcNow.ToString('o')
    $saveChanges = @()
    foreach ($path in $beforeSaves.Keys) {
        if (-not (Test-Path -LiteralPath $path) -or (Get-FileHash -LiteralPath $path).Hash -ne $beforeSaves[$path]) { $saveChanges += $path }
    }
    $newSaves = @()
    foreach ($saveRoot in $saveRoots) {
        if (Test-Path -LiteralPath $saveRoot) {
            foreach ($file in Get-ChildItem -LiteralPath $saveRoot -Recurse -File) {
                if (-not $beforeSaves.ContainsKey($file.FullName)) { $newSaves += $file.FullName }
            }
        }
    }
    $state.changedSaveFiles = $saveChanges
    $state.createdSaveFiles = $newSaves
    $state.archivedDebugSaves = @()
    $retainedNewSaves = @()
    foreach ($newSave in $newSaves) {
        $savePath = (Resolve-Path -LiteralPath $newSave).Path
        $sqexRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'FFRS_DEMO'))
        if ($StartBattle -and [IO.Path]::GetFileName($savePath) -eq 'BattleTestSaveData.sav' -and $savePath.StartsWith($sqexRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
            $archivePath = [IO.Path]::GetFullPath((Join-Path $runDirectory 'BattleTestSaveData.sav'))
            if (-not $archivePath.StartsWith($runDirectory + '\', [StringComparison]::OrdinalIgnoreCase) -or (Test-Path -LiteralPath $archivePath)) { throw 'Invalid new debug-save archive path.' }
            $debugSaveHash = (Get-FileHash -LiteralPath $savePath).Hash
            Move-Item -LiteralPath $savePath -Destination $archivePath
            $state.archivedDebugSaves += @{ originalPath=$savePath; archivePath=$archivePath; sha256=$debugSaveHash }
        } else { $retainedNewSaves += $savePath }
    }
    $state.newSaveFiles = $retainedNewSaves
    $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runDirectory 'run.json') -Encoding utf8NoBOM
    Write-Output ($state | ConvertTo-Json -Depth 8)
}
