# Run the local desktop build against this checkout's engine and data.
$ErrorActionPreference = 'Stop'
$studioRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
& (Join-Path $PSScriptRoot 'build_studio.ps1') -IfNeeded
$studioAppRoot = Split-Path -Parent $studioRoot
$studioExe = Join-Path $studioAppRoot 'build/windows/x64/runner/Release/ffr_vision_studio.exe'
if (-not (Test-Path -LiteralPath $studioExe)) { throw 'Build the app first: run flutter build windows --release from the repository root' }
$studioSocket = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$studioSocket.Start()
$studioPort = $studioSocket.LocalEndpoint.Port
$studioSocket.Stop()
$studioLog = Join-Path $studioRoot 'build/devui/studio-local'
New-Item -ItemType Directory -Force -Path $studioLog | Out-Null
$studioLauncher = Join-Path $PSScriptRoot 'launcher.py'
$studioPython = Join-Path $studioRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $studioPython)) { $studioPython = (Get-Command python).Source }
$studioPreviousConverted = $env:FFR_CONVERTED_UNITS
$studioConverted = Join-Path $studioRoot 'build/converted-moves-test/converted-units.json'
$studioShared = Join-Path $studioRoot 'build/animation-recovery/converted-units.json'
if (Test-Path -LiteralPath $studioShared) { $studioConverted = $studioShared }
if (Test-Path -LiteralPath $studioConverted) { $env:FFR_CONVERTED_UNITS = $studioConverted }
$studioEngine = Start-Process -FilePath $studioPython -ArgumentList @('-B', ('"' + $studioLauncher + '"'), '--engine', '--port', "$studioPort") -WorkingDirectory $studioRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $studioLog 'stdout.log') -RedirectStandardError (Join-Path $studioLog 'stderr.log')
$env:FFR_CONVERTED_UNITS = $studioPreviousConverted
$studioPreviousApi = $env:FFR_STUDIO_API
try {
    $studioReady = $false
    for ($studioAttempt = 0; $studioAttempt -lt 60; $studioAttempt++) {
        if ($studioEngine.HasExited) { throw "Studio engine exited. See $studioLog" }
        try {
            $null = Invoke-RestMethod "http://127.0.0.1:$studioPort/api/status" -TimeoutSec 2
            $studioReady = $true
            break
        } catch { Start-Sleep -Milliseconds 250 }
    }
    if (-not $studioReady) { throw "Studio engine did not become ready. See $studioLog" }
    $env:FFR_STUDIO_API = "http://127.0.0.1:$studioPort"
    # Open the interactive desktop app against the source engine.
    $studioApp = Start-Process -FilePath $studioExe -WorkingDirectory $studioAppRoot -PassThru
    $studioApp.WaitForExit()
} finally {
    $env:FFR_STUDIO_API = $studioPreviousApi
    if (-not $studioEngine.HasExited) { Stop-Process -Id $studioEngine.Id }
}
