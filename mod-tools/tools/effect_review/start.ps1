$ErrorActionPreference = 'Stop'
$reviewRepo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$reviewUrl = 'http://127.0.0.1:8767'
$reviewHealth = $null
try { $reviewHealth = Invoke-RestMethod -Uri "$reviewUrl/api/health" -TimeoutSec 2 } catch {}
if ($null -ne $reviewHealth -and $reviewHealth.service -ne 'ffr-effect-review') {
    throw 'Port 8767 is in use by another service.'
}
if ($null -eq $reviewHealth) {
    $reviewPython = (Get-Command python).Source
    $reviewLog = Join-Path $reviewRepo 'docs\effect-review'
    Start-Process -FilePath $reviewPython -ArgumentList @('-B','-m','tools.effect_review.serve','--port','8767') -WorkingDirectory $reviewRepo -WindowStyle Hidden -RedirectStandardOutput (Join-Path $reviewLog 'server.log') -RedirectStandardError (Join-Path $reviewLog 'server-error.log')
    for ($reviewAttempt = 0; $reviewAttempt -lt 30; $reviewAttempt++) {
        Start-Sleep -Milliseconds 200
        try { $reviewHealth = Invoke-RestMethod -Uri "$reviewUrl/api/health" -TimeoutSec 1; break } catch {}
    }
    if ($null -eq $reviewHealth) { throw 'The review server did not start. Check docs/effect-review/server-error.log.' }
}
Start-Process $reviewUrl
