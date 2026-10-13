param([int]$Seconds=40,[switch]$Native,[switch]$Packaged,[int]$SoakSeconds=8)
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$source='T:\SteamLibrary\steamapps\common\FINAL FANTASY RESONANCE DEMO'
$work=Join-Path $repo ('build/vision-cards/probe-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
if($Packaged) { $work=Join-Path 'T:/Projects/ffbe/.ffr-card-tests' ('probe-'+(Get-Date -Format 'yyyyMMdd-HHmmss')) }
$bin=Join-Path $work 'game/FFRS/Binaries/Win64'
$null=New-Item -ItemType Directory -Path $bin -Force
Get-ChildItem -LiteralPath (Join-Path $source 'FFRS/Binaries/Win64') -File | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $bin }
foreach($relative in @('Engine','FFRS/Binaries/Win64/D3D12','FFRS/Binaries/Win64/DML')) {
    $null=New-Item -ItemType Junction -Path (Join-Path $work ('game/'+$relative)) -Target (Join-Path $source $relative)
}
$content=Join-Path $work 'game/FFRS/Content'
if($Packaged) {
    $null=New-Item -ItemType Directory -Path (Join-Path $content 'Paks/~mods') -Force
    foreach($child in Get-ChildItem -LiteralPath (Join-Path $source 'FFRS/Content')) {
        if($child.Name -eq 'Paks') {continue}
        if($child.PSIsContainer) { $null=New-Item -ItemType Junction -Path (Join-Path $content $child.Name) -Target $child.FullName }
        else { Copy-Item -LiteralPath $child.FullName -Destination $content }
    }
    foreach($file in Get-ChildItem -LiteralPath (Join-Path $source 'FFRS/Content/Paks') -File) {
        # IoDispatcher rejects cross-volume symlink file sizes. Read-only hard
        # links on the game's volume preserve ordinary file metadata.
        $null=New-Item -ItemType HardLink -Path (Join-Path $content ('Paks/'+$file.Name)) -Target $file.FullName
    }
    foreach($file in Get-ChildItem -LiteralPath (Join-Path $source 'FFRS/Content/Paks/~mods') -File) {
        if(-not $file.BaseName.StartsWith('zzzzzz_VisionCards_')) { Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $content 'Paks/~mods') }
    }
    $package=(Get-Content -LiteralPath (Join-Path $repo 'build/vision-cards/latest-package.json') -Raw | ConvertFrom-Json).package
    Get-ChildItem -LiteralPath $package -File | ForEach-Object {Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $content 'Paks/~mods')}
} else { $null=New-Item -ItemType Junction -Path $content -Target (Join-Path $source 'FFRS/Content') }
$runtime=Join-Path $bin 'ue4ss'
$null=New-Item -ItemType Directory -Path (Join-Path $runtime 'Mods/VisionCardProbe/Scripts') -Force
Copy-Item -LiteralPath (Join-Path $repo 'tools/UE4SS/dwmapi.dll') -Destination $bin
Copy-Item -LiteralPath (Join-Path $repo 'tools/UE4SS/ue4ss/UE4SS.dll') -Destination $runtime
Copy-Item -LiteralPath (Join-Path $repo 'tools/UE4SS/ue4ss/UE4SS-settings.ini') -Destination $runtime
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'probe_vision_card_slot.lua') -Destination (Join-Path $runtime 'Mods/VisionCardProbe/Scripts/main.lua')
Set-Content -LiteralPath (Join-Path $runtime 'Mods/mods.txt') -Value 'VisionCardProbe : 1'
if($Native) {
    $cardMod=Join-Path $runtime 'Mods/FFRVisionCards'
    $null=New-Item -ItemType Directory -Path (Join-Path $cardMod 'Scripts'),(Join-Path $cardMod 'dlls') -Force
    Copy-Item -LiteralPath (Join-Path $repo 'build/vision-cards/native/Release/main.dll') -Destination (Join-Path $cardMod 'dlls/main.dll')
    Get-ChildItem -LiteralPath (Join-Path $repo 'src/ffr-vision-cards') -Filter '*.lua' | ForEach-Object {Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $cardMod 'Scripts')}
    if($Packaged) { Copy-Item -LiteralPath (Join-Path $repo 'build/vision-cards/runtime/FFRVisionCards/Scripts/catalog.lua') -Destination (Join-Path $cardMod 'Scripts/catalog.lua') }
    else { Set-Content -LiteralPath (Join-Path $cardMod 'Scripts/catalog.lua') -Value 'return {cards={}}' }
    $entry=Get-Content -LiteralPath (Join-Path $cardMod 'Scripts/main.lua') -Raw
    Set-Content -LiteralPath (Join-Path $cardMod 'Scripts/main.lua') -Value ("FFRVisionCardsProbe=true`nFFRVisionCardsPackaged="+$Packaged.ToString().ToLower()+"`n"+$entry)
    Set-Content -LiteralPath (Join-Path $runtime 'Mods/mods.txt') -Value 'FFRVisionCards : 1'
}
Set-Content -LiteralPath (Join-Path $bin 'steam_appid.txt') -Value '4474710'
$saveRoots=@((Join-Path $env:LOCALAPPDATA 'FFRS/Saved/SaveGames'),(Join-Path $env:LOCALAPPDATA 'FFRS_DEMO'))
Get-ChildItem -LiteralPath 'S:\Program Files (x86)\Steam\userdata' -Directory -ErrorAction SilentlyContinue | ForEach-Object { $saveRoots+=Join-Path $_.FullName '4474710' }
$locks=@();$hashes=@{}
try {
    foreach($saveRoot in $saveRoots) {
        if(Test-Path -LiteralPath $saveRoot) {
            foreach($file in Get-ChildItem -LiteralPath $saveRoot -Recurse -File -Filter '*.sav') {
                $hashes[$file.FullName]=(Get-FileHash -LiteralPath $file.FullName).Hash
                $locks += [IO.File]::Open($file.FullName,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
            }
        }
    }
    $exe=Join-Path $bin 'FFRS-Win64-Shipping.exe'
    # Test copies do not need network discovery. Otherwise every unique exe path
    # can produce another Windows Firewall prompt on the user's desktop.
    $arguments=@('FFRS','-UDPMESSAGING_TRANSPORT_ENABLE=0','-ini:Engine:[/Script/UdpMessaging.UdpMessagingSettings]:EnableTransport=False','-ini:Engine:[/Script/TcpMessaging.TcpMessagingSettings]:EnableTransport=False','-RenderOffscreen','-Windowed','-ResX=960','-ResY=540','-nosound','-unattended',('-UserDir="'+(Join-Path $work 'user')+'"'),('-abslog="'+(Join-Path $work 'game.log')+'"'),('-seconds='+$Seconds))
    $arguments+=@('-nosteam','-ini:Engine:[OnlineSubsystem]:DefaultPlatformService=Null','-ini:Engine:[OnlineSubsystemSteam]:bEnabled=False')
    $game=Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $bin -WindowStyle Hidden -PassThru
    $timer=[Diagnostics.Stopwatch]::StartNew()
    $complete=$false
    $completedAt=$null
    while(-not $game.HasExited -and $timer.Elapsed.TotalSeconds -lt $Seconds) {
        Start-Sleep -Milliseconds 500
        $log=Join-Path $runtime 'UE4SS.log'
        if((Test-Path -LiteralPath $log) -and (Select-String -LiteralPath $log -Pattern 'LUA_ERRRUN|\[VisionCardProbe\] error=|\[FFRVisionCards\] UI error:' -Quiet)) {break}
        if((Test-Path -LiteralPath $log) -and (Select-String -LiteralPath $log -SimpleMatch '[VisionCardProbe] complete' -Quiet)) {
            if($null -eq $completedAt) {$completedAt=$timer.Elapsed.TotalSeconds}
            if(($timer.Elapsed.TotalSeconds-$completedAt) -ge $SoakSeconds) { $complete=$true;break }
        }
    }
    if(-not $game.HasExited) { Stop-Process -Id $game.Id; $game.WaitForExit() }
    if(-not $complete) { throw 'Card probe did not complete; inspect the runtime log.' }
    if(Select-String -LiteralPath $log -Pattern 'LUA_ERRRUN|\[VisionCardProbe\] error=|\[FFRVisionCards\] UI error:' -Quiet) {throw 'Runtime error found after the card checks'}
} finally {
    foreach($lock in $locks) { $lock.Dispose() }
    foreach($path in $hashes.Keys) { if((Get-FileHash -LiteralPath $path).Hash -ne $hashes[$path]) { throw 'Original save changed during probe.' } }
    Write-Output $work
    $log=Join-Path $runtime 'UE4SS.log'
    if(Test-Path -LiteralPath $log) { Select-String -LiteralPath $log -Pattern 'VisionCardProbe|Error|error' | Select-Object -Last 25 }
}
