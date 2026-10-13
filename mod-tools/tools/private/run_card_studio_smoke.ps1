$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$socket=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0)
$socket.Start();$port=$socket.LocalEndpoint.Port;$socket.Stop()
$log=Join-Path $repo 'build/vision-cards'
$engine=Start-Process -FilePath 'C:/Users/Raegen/AppData/Local/Programs/Python/Python312/python.exe' -ArgumentList @('-X','utf8','tools/devui/launcher.py','--engine','--port',"$port") -WorkingDirectory $repo -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $log 'studio-engine.log') -RedirectStandardError (Join-Path $log 'studio-engine-errors.log')
$old=$env:FFR_STUDIO_API
try {
    $env:FFR_STUDIO_API="http://127.0.0.1:$port"
    $ready=$false
    for($i=0;$i -lt 40;$i++) {
        if($engine.HasExited) {throw 'Studio engine failed to start'}
        try { $null=Invoke-RestMethod "$env:FFR_STUDIO_API/api/vision-cards"; $ready=$true;break } catch {Start-Sleep -Milliseconds 250}
    }
    if(-not $ready) {throw 'Studio engine did not become ready'}
    Set-Location (Join-Path $repo 'app/ffr_vision_studio')
    & 'C:/Users/Raegen/Documents/SDKs/flutter/bin/flutter.bat' run -d windows -t test/vision_cards_desktop_smoke.dart --no-pub
    if($LASTEXITCODE -ne 0) {throw 'Desktop smoke test failed'}
} finally {
    $env:FFR_STUDIO_API=$old
    if(-not $engine.HasExited) {Stop-Process -Id $engine.Id}
}
