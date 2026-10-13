param([string]$BetaPath)
$ErrorActionPreference='Stop'
$betaRepo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
if (-not $BetaPath) {$BetaPath=Join-Path $betaRepo 'build/studio-beta/20260928-b1'}
$betaRoot=[IO.Path]::GetFullPath($BetaPath)
$betaInfo=Get-Content -LiteralPath (Join-Path $betaRoot 'beta.json') -Raw | ConvertFrom-Json
$betaExe=Join-Path $betaRoot 'app/FFR Vision Studio Beta.exe'
if (-not (Test-Path -LiteralPath $betaExe)) {throw 'The beta app has not been built yet.'}
$betaLog=Join-Path $betaRoot 'logs'
New-Item -ItemType Directory -Force -Path $betaLog | Out-Null
# One beta per engine workspace, including launches from a second shortcut.
try {$betaLock=[IO.File]::Open((Join-Path $betaRoot 'launcher.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
catch {return}
$betaNames=@('FFR_CONVERTED_UNITS','FFR_STUDIO_API','FFR_STUDIO_HOME','FFR_UNIT_SPEC','FFR_HOST_INDEX','FFR_MOD_STEM','FFR_PRESENTATION_DIR')
$betaPrevious=@{}
foreach($name in $betaNames){$betaPrevious[$name]=[Environment]::GetEnvironmentVariable($name)}
$betaEngine=$null
try {
    $betaSocket=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0)
    $betaSocket.Start(); $betaPort=$betaSocket.LocalEndpoint.Port; $betaSocket.Stop()
    $env:FFR_CONVERTED_UNITS=$betaInfo.catalog
    $env:FFR_STUDIO_HOME=Join-Path $betaRoot 'home'
    $env:FFR_UNIT_SPEC=Join-Path $betaInfo.engine 'mods/EstherTsukiko/units.json'
    $env:FFR_HOST_INDEX=Join-Path $betaInfo.engine 'build/devui/ffbe_index_cache.json'
    $env:FFR_MOD_STEM=$null
    $env:FFR_PRESENTATION_DIR=$null
    $env:FFR_STUDIO_API="http://127.0.0.1:$betaPort"
    $betaEngine=Start-Process -FilePath $betaInfo.python -ArgumentList @('-B','-X','utf8','tools/devui/launcher.py','--engine','--port',"$betaPort") -WorkingDirectory $betaInfo.engine -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $betaLog 'engine.log') -RedirectStandardError (Join-Path $betaLog 'engine-errors.log')
    $betaReady=$false
    for($attempt=0;$attempt -lt 80;$attempt++) {
        if($betaEngine.HasExited){throw 'Beta engine failed to start. See the beta logs folder.'}
        try {$null=Invoke-RestMethod "$env:FFR_STUDIO_API/api/status" -TimeoutSec 2; $betaReady=$true; break} catch {Start-Sleep -Milliseconds 250}
    }
    if(-not $betaReady){throw 'Beta engine did not become ready.'}
    $betaApp=Start-Process -FilePath $betaExe -WorkingDirectory $betaRoot -PassThru
    $betaApp.WaitForExit()
} catch {
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $betaLog 'launch-error.txt')
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("The beta could not start. Details: $betaLog\launch-error.txt",'FFR Vision Studio Beta') | Out-Null
} finally {
    if($betaEngine -and -not $betaEngine.HasExited){Stop-Process -Id $betaEngine.Id}
    foreach($name in $betaNames){[Environment]::SetEnvironmentVariable($name,$betaPrevious[$name])}
    $betaLock.Dispose()
}
