param([string]$Catalog, [string]$SmokeWork, [string]$EngineRoot, [string]$Forms)
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$work=Join-Path $repo 'build/converted-moves-test'
if ($SmokeWork) {$work=[IO.Path]::GetFullPath($SmokeWork)}
New-Item -ItemType Directory -Force -Path $work | Out-Null
$socket=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0)
$socket.Start(); $port=$socket.LocalEndpoint.Port; $socket.Stop()
$names=@('FFR_CONVERTED_UNITS','FFR_UNIT_SPEC','FFR_STUDIO_API','FFR_SMOKE_HOME','FFR_SMOKE_RESULT','FFR_SMOKE_SPEC','FFR_SMOKE_FORMS')
$previous=@{}; foreach($name in $names) {$previous[$name]=[Environment]::GetEnvironmentVariable($name)}
$engine=$null
$engineSource=if ($EngineRoot) {[IO.Path]::GetFullPath($EngineRoot)} else {$repo}
try {
    $env:FFR_CONVERTED_UNITS=if ($Catalog) {[IO.Path]::GetFullPath($Catalog)} else {Join-Path $work 'converted-units.json'}
    $env:FFR_UNIT_SPEC=Join-Path $work 'studio-smoke-roster.json'
    Copy-Item -LiteralPath (Join-Path $engineSource 'mods/EstherTsukiko/units.json') -Destination $env:FFR_UNIT_SPEC
    $env:FFR_STUDIO_API="http://127.0.0.1:$port"
    $env:FFR_SMOKE_HOME=Join-Path $work 'studio-smoke-home'
    $env:FFR_SMOKE_RESULT=Join-Path $work 'studio-smoke-result.json'
    $env:FFR_SMOKE_SPEC=Join-Path $work 'new-unit-smoke.json'
    $env:FFR_SMOKE_FORMS=$Forms
    $engine=Start-Process -FilePath 'C:/Users/Raegen/AppData/Local/Programs/Python/Python312/python.exe' -ArgumentList @('-X','utf8','tools/devui/launcher.py','--engine','--port',"$port") -WorkingDirectory $engineSource -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $work 'smoke-engine.log') -RedirectStandardError (Join-Path $work 'smoke-engine-errors.log')
    $ready=$false
    for($i=0;$i -lt 60;$i++) {
        if($engine.HasExited) {throw 'Studio engine failed to start'}
        try {$null=Invoke-RestMethod "$env:FFR_STUDIO_API/api/status"; $ready=$true; break} catch {Start-Sleep -Milliseconds 250}
    }
    if(-not $ready) {throw 'Studio engine did not become ready'}
    Push-Location (Join-Path $repo 'app/ffr_vision_studio')
    try {
        & 'C:/Users/Raegen/Documents/SDKs/flutter/bin/flutter.bat' run -d windows -t test/converted_desktop_smoke.dart --no-pub
        if($LASTEXITCODE -ne 0) {throw 'Desktop smoke test failed'}
    } finally {Pop-Location}
    if(-not (Test-Path -LiteralPath $env:FFR_SMOKE_RESULT)) {throw 'Desktop smoke test did not finish'}
} finally {
    if($engine -and -not $engine.HasExited) {Stop-Process -Id $engine.Id}
    foreach($name in $names) {[Environment]::SetEnvironmentVariable($name,$previous[$name])}
}
