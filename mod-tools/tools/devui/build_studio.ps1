param([switch]$IfNeeded)
$ErrorActionPreference = 'Stop'
$studioToolsRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$studioAppRoot = Split-Path -Parent $studioToolsRoot
$studioExe = Join-Path $studioAppRoot 'build/windows/x64/runner/Release/ffr_vision_studio.exe'
$studioInputs = @(
    Get-ChildItem -LiteralPath (Join-Path $studioAppRoot 'lib'),(Join-Path $studioAppRoot 'windows/runner') -Recurse -File
    Get-Item -LiteralPath (Join-Path $studioAppRoot 'pubspec.yaml'),(Join-Path $studioAppRoot 'pubspec.lock')
)
if ($IfNeeded -and (Test-Path -LiteralPath $studioExe)) {
    $studioBuildTime = (Get-Item -LiteralPath $studioExe).LastWriteTimeUtc
    if (-not ($studioInputs | Where-Object { $_.LastWriteTimeUtc -gt $studioBuildTime })) { return }
}
Push-Location $studioAppRoot
try {
    & flutter build windows --release
    if ($LASTEXITCODE -ne 0) { throw 'Studio build failed. Check the Flutter build output.' }
} finally { Pop-Location }
