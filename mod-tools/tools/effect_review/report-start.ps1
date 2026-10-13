$ErrorActionPreference = 'Stop'
$abilityReviewRepo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$abilityReviewUrl = 'http://127.0.0.1:8768'
$abilityReviewHealth = $null
try { $abilityReviewHealth = Invoke-RestMethod -Uri "$abilityReviewUrl/api/health" -TimeoutSec 2 } catch {}
if ($null -ne $abilityReviewHealth -and $abilityReviewHealth.service -ne 'ffr-ability-review') { throw 'Port 8768 belongs to another service.' }
if ($null -eq $abilityReviewHealth) {
    $abilityReviewPython = (Get-Command python).Source
    Start-Process -FilePath $abilityReviewPython -ArgumentList @('-B','-m','tools.effect_review.report_server','--port','8768') -WorkingDirectory $abilityReviewRepo -WindowStyle Hidden -RedirectStandardOutput (Join-Path $abilityReviewRepo 'build\ability-review\server.log') -RedirectStandardError (Join-Path $abilityReviewRepo 'build\ability-review\server-error.log')
    for ($abilityReviewAttempt=0; $abilityReviewAttempt -lt 30; $abilityReviewAttempt++) {
        Start-Sleep -Milliseconds 200
        try { $abilityReviewHealth=Invoke-RestMethod -Uri "$abilityReviewUrl/api/health" -TimeoutSec 1; break } catch {}
    }
    if ($null -eq $abilityReviewHealth) { throw 'The report server did not start. Check build/ability-review/server-error.log.' }
}
Start-Process $abilityReviewUrl
