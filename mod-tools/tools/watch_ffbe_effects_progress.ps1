param(
    [string]$RunDir = "S:\Projects\ffr\build\ffbe-effects-catalog-v6",
    [int]$RefreshSeconds = 5,
    [int]$TailLogLines = 12,
    [switch]$Watch
)

function Show-Status {
    param(
        [string]$RunDir,
        [int]$TailLogLines
    )

    $catalogPath = Join-Path $RunDir "catalog-conversion.json"
    $workerPath = Join-Path $RunDir "worker.json"
    if (-not (Test-Path $catalogPath) -and -not (Test-Path $workerPath)) {
        Write-Host "No catalog status files found in:"
        Write-Host "  $RunDir"
        Write-Host "Run dir should point to build/ffbe-effects-catalog-<name>."
        return
    }

    $catalog = if (Test-Path $catalogPath) {
        Get-Content -Raw $catalogPath | ConvertFrom-Json
    } else {
        $null
    }

    $worker = if (Test-Path $workerPath) {
        Get-Content -Raw $workerPath | ConvertFrom-Json
    } else {
        $null
    }

    $summary = if ($catalog) { $catalog.summary } else { $null }
    $status = if ($worker) { $worker.status } else { "unknown" }
    $pid = if ($worker) { $worker.processId } else { $null }
    $processAlive = if ($pid) { Get-Process -Id $pid -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id } else { $null }

    $statusText = $status
    if ($status -eq "running") {
        if ($processAlive) {
            $statusText += " (process $pid alive)"
        } else {
            $statusText += " (process $pid ended)"
        }
    }

    $started = if ($worker) { [DateTime]::Parse($worker.startedUtc) } else { $null }
    $updated = if ($worker) { [DateTime]::Parse($worker.processStartedUtc) } else { $null }
    $now = Get-Date
    $elapsed = if ($started) { $now - $started } else { [timespan]::Zero }

    $selectedForms = [int]($summary.selectedForms ?? 0)
    $processedForms = [int]($summary.processedForms ?? 0)
    $bundledForms = [int]($summary.bundledForms ?? 0)
    $failedForms = [int]($summary.failedForms ?? 0)
    $activeMoves = [int]($summary.activeMoveMemberships ?? 0)
    $readyMoves = [int]($summary.readyMoveMemberships ?? 0)
    $preparedMoves = [int]($summary.preparedMoveMemberships ?? 0)
    $failedMoves = [int]($summary.failedMoveMemberships ?? 0)

    $formPct = if ($selectedForms -gt 0) { [math]::Round(($processedForms / $selectedForms) * 100, 2) } else { 0 }
    $movePct = if ($activeMoves -gt 0) { [math]::Round(($readyMoves / $activeMoves) * 100, 2) } else { 0 }
    $formsPerMin = if ($elapsed.TotalMinutes -gt 0) { [math]::Round(($processedForms / $elapsed.TotalMinutes), 2) } else { 0 }
    $movesPerMin = if ($elapsed.TotalMinutes -gt 0) { [math]::Round(($preparedMoves / $elapsed.TotalMinutes), 2) } else { 0 }
    $etaMinutes = if ($formsPerMin -gt 0) {
        [math]::Round((($selectedForms - $processedForms) / $formsPerMin) / 60, 2)
    } else {
        0
    }

    $errorCounts = @()
    if ($catalog -and $catalog.errors) {
        foreach ($prop in $catalog.errors.PSObject.Properties) {
            if ($prop.Name -eq "form") {
                continue
            }
            $count = @($prop.Value).Count
            $errorCounts += "$($prop.Name):$count"
        }
    }
    if ($errorCounts.Count -eq 0) {
        $errorCounts = @("none")
    }

    Write-Host ""
    Write-Host "FFBE catalog conversion status"
    Write-Host "RunDir: $RunDir"
    Write-Host "Status: $statusText"
    Write-Host "Started: $($started.ToString('yyyy-MM-dd HH:mm:ss'))  Updated: $($updated.ToString('yyyy-MM-dd HH:mm:ss'))"
    Write-Host ("Elapsed: {0}  ETA(form completion): {1:N2} min" -f $elapsed.ToString("hh\:mm\:ss"), $etaMinutes)
    Write-Host ("Forms: {0}/{1} processed ({2}%)  bundled: {3}  failed: {4}" -f $processedForms, $selectedForms, $formPct, $bundledForms, $failedForms)
    Write-Host ("Moves: ready {0}/{1} ({2}%)  prepared: {3}  failed: {4}" -f $readyMoves, $activeMoves, $movePct, $preparedMoves, $failedMoves)
    Write-Host ("Throughput: {0:N2} forms/min, {1:N2} moves/min" -f $formsPerMin, $movesPerMin)
    Write-Host ("Recent errors: {0}" -f ($errorCounts -join ", "))

    $errorLog = Join-Path $RunDir "conversion-errors.log"
    if (Test-Path $errorLog) {
        Write-Host ""
        Write-Host "Last $TailLogLines errors:"
        Get-Content $errorLog -Tail $TailLogLines
    }
}

if ($Watch) {
    while ($true) {
        Clear-Host
        Show-Status -RunDir $RunDir -TailLogLines $TailLogLines
        Write-Host ""
        Write-Host "Press Ctrl+C to stop. Refreshing every $RefreshSeconds seconds..."
        Start-Sleep -Seconds $RefreshSeconds
    }
} else {
    Show-Status -RunDir $RunDir -TailLogLines $TailLogLines
}
