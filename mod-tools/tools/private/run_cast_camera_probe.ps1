param([int]$VisionId=13503,[int]$SkillId=444040,[string]$CameraWork='build/cast-camera-step1',[switch]$AllEnemies,[int]$EnemyId=9462,[int]$SecondEnemyId=9463)
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$bin=(Resolve-Path -LiteralPath 'T:\SteamLibrary\steamapps\common\FINAL FANTASY RESONANCE DEMO\FFRS\Binaries\Win64').Path
if (Get-Process -Name FFRS-Win64-Shipping -ErrorAction SilentlyContinue) { throw 'FFR is already running.' }
$moved=@()
try {
    foreach ($name in @('ue4ss','dwmapi.dll','steam_appid.txt')) {
        $source=[IO.Path]::GetFullPath((Join-Path $bin $name))
        $dest=[IO.Path]::GetFullPath((Join-Path $bin ($name+'.cast-camera-preserved')))
        if ([IO.Path]::GetDirectoryName($source) -ne $bin -or [IO.Path]::GetDirectoryName($dest) -ne $bin) { throw 'Runtime preservation boundary failed.' }
        if (Test-Path -LiteralPath $dest) { throw 'Previous runtime preservation exists; inspect before running.' }
        if (Test-Path -LiteralPath $source) {
            Move-Item -LiteralPath $source -Destination $dest
            $moved += @{source=$source;preserved=$dest}
        }
    }
    $runtime=Join-Path $repo ($CameraWork+'/runtime/run.ps1')
    $extra=@{}; if($CameraWork -ne 'build/cast-camera-step1') { $extra['AllEnemies']=[bool]$AllEnemies }
    & $runtime -Run -FullParty -VisionId $VisionId -SkillId $SkillId -EnemyId $EnemyId -SecondEnemyId $SecondEnemyId -Seconds 120 -ExpectedInstalledManifest (Join-Path $repo ($CameraWork+'/installation.json')) @extra
} finally {
    if (Get-Process -Name FFRS-Win64-Shipping -ErrorAction SilentlyContinue) { throw 'Game is still running; preserved runtime retained for recovery.' }
    foreach ($entry in $moved) {
        if (Test-Path -LiteralPath $entry.source) { throw "Test runtime not cleaned; preserved runtime remains at $($entry.preserved)" }
        Move-Item -LiteralPath $entry.preserved -Destination $entry.source
    }
}
