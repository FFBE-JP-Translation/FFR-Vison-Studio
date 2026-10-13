"""Extend the existing protected camera fixture to capture complete effect timelines."""
from pathlib import Path

def configure(runtime):
    path=runtime/'run.ps1'; source=path.read_text(encoding='utf-8-sig')
    source=source.replace("Copy-Item -LiteralPath $SourceJob -Destination (Join-Path $runDirectory 'source-job.json')", """$trialPlans=Get-Content -LiteralPath (Join-Path $PSScriptRoot '../plans.json') -Raw | ConvertFrom-Json
$trialJob=@($trialPlans | Where-Object { $_.skill -eq $SkillId -and $_.vision -eq $VisionId })
if ($trialJob.Count -ne 1) { throw 'Missing selected effect trial plan.' }
$trialJob[0] | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath (Join-Path $runDirectory 'source-job.json') -Encoding utf8NoBOM
$events=$trialJob[0].plan.events
$castTick=($events | Where-Object { $_.set.EventType -eq 'NativeParticipantCamera' } | Select-Object -First 1).time
$actionTick=($events | Where-Object { $_.set.Unit_PlayAnimByName_AnimationName -in @('LB1','attack_A','magic_attack') } | Select-Object -First 1).time
$restoreTick=($events | Where-Object { $_.set.EventType -eq 'CameraSetDefault' } | Select-Object -Last 1).time
$actionFrame=[int][Math]::Ceiling(($actionTick-$castTick)/400)
$lastFrame=[int][Math]::Ceiling(($restoreTick-$castTick)/400)+24
$captureFrames=@(0,12,30,48)
for($i=0;$i -lt 6;$i++) { $captureFrames += [int][Math]::Round($actionFrame+($lastFrame-$actionFrame)*$i/5) }
$captureFramesLua='{'+($captureFrames -join ',')+'}'
$actionTimeout=[int][Math]::Ceiling($trialJob[0].plan.duration/24000)+8""")
    source=source.replace('return {protectedSaves=true,vision=', 'return {captureFrames=$captureFramesLua,actionTimeout=$actionTimeout,protectedSaves=true,vision=')
    path.write_text(source,encoding='utf-8')
    path=runtime/'main.lua'; source=path.read_text(encoding='utf-8-sig')
    source=source.replace('local captures={0,12,30,48,66,84,102,120,210,240}', 'local captures=config.captureFrames or {0,12,30,48,66,84,102,120,210,240}')
    source=source.replace('captured[240]', 'captured[captures[#captures]]')
    source=source.replace('t-started>15', 't-started>(config.actionTimeout or 30)')
    source=source.replace("emit('sample',sample)", """sample.effects={}
                    for _,effect in ipairs(FindAllOf('SsPlayerActor') or {}) do
                        if effect:IsValid() then
                            local ok,info=pcall(function()
                                local player=effect:GetSsPlayer()
                                return {actor=effect:GetFullName(),location=xyz(player:K2_GetComponentLocation()),visible=player:IsVisible()}
                            end)
                            if ok then table.insert(sample.effects,info) end
                        end
                    end
                    emit('sample',sample)""")
    path.write_text(source,encoding='utf-8')
