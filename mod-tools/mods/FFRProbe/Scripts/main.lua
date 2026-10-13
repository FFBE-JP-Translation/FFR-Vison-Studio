-- FFRProbe (UE4SS Lua). Output: ue4ss/UE4SS.log
--   F9  : one-shot dump of battle units (sprite project, vision), sequencer sprite actors, loaded Ss6Projects, custom icon rows.
--   F8  : toggle the timeline trace: every 100 ms log the level sequence players (current time / duration / playing), every
--         battle unit's sprite player state (playing? / anim pack) and every sequencer sprite actor (anim name, T). Use it
--         right before triggering a Resonance to see when the sequence ends and when the unit's motion stops.
local function L(s) print("[FFRProbe] " .. tostring(s) .. "\n") end
local function safe(f, ...) local ok, r = pcall(f, ...); if ok then return r end; return "ERR:" .. tostring(r) end

local function probe()
    L("==== probe ====")
    local units = FindAllOf("CPP_BtlUnit")
    if not units then L("no CPP_BtlUnit objects") else
        for _, u in ipairs(units) do
            if u:IsValid() then
                local id, proj, vis, owner, idx = "?", "?", "?", "?", "?"
                local p = u.m_pUnitParameter
                if p and p:IsValid() then
                    id = safe(function() return p:GetUnitId() end)
                    local v = p.m_pVision; if v and v:IsValid() then vis = v:GetFullName() end
                    local o = p.m_pVisionOwner; if o and o:IsValid() then owner = o:GetFullName() end
                end
                local c = u.m_pSsPlayerComponent
                if c and c:IsValid() then
                    local sp = c.SsProject; if sp and sp:IsValid() then proj = sp:GetFullName() end
                end
                idx = safe(function() return u.m_AnimationAssetIndex end)
                L(string.format("unit %s | id=%s | assetIdx=%s | project=%s | vision=%s | owner=%s", u:GetFullName(), tostring(id), tostring(idx), proj, vis, owner))
            end
        end
    end
    local seq = FindAllOf("CPP_BtlSequencerSsPlayerActor")
    if seq then
        for _, a in ipairs(seq) do
            if a:IsValid() then
                local c = a.m_pSsPlayerComponent or a.SsPlayerComponent
                local proj = "?"
                if c and c:IsValid() then local sp = c.SsProject; if sp and sp:IsValid() then proj = sp:GetFullName() end end
                L(string.format("seqActor %s | ID=%s | VisionNumber=%s | anim=%s/%s | project=%s", a:GetFullName(), tostring(safe(function() return a.ID end)),
                    tostring(safe(function() return a.VisionNumber end)), tostring(safe(function() return a.AnimPackName:ToString() end)),
                    tostring(safe(function() return a.animName:ToString() end)), proj))
            end
        end
    end
    local projs = FindAllOf("Ss6Project")
    if projs then for _, pj in ipairs(projs) do if pj:IsValid() then L("Ss6Project loaded: " .. pj:GetFullName()) end end end
    L("==== end ====")
end

-- ---------------------------------------------------------------- timeline trace (F10)
local tracing = false
local t0 = 0
local function now() return os.clock() end

local function traceOnce()
    local lines = {}
    local players = FindAllOf("LevelSequencePlayer")
    if players then
        for _, pl in ipairs(players) do
            if pl:IsValid() then
                local playing = safe(function() return pl:IsPlaying() end)
                if playing == true then
                    local function secs(t)
                        local ok, v = pcall(function() return t.Time.FrameNumber.Value / t.Rate.Numerator * t.Rate.Denominator end)
                        if ok and v then return string.format("%.2f", v) end
                        local ok2, f = pcall(function() return t.Time.FrameNumber.Value end)
                        if ok2 and f then return string.format("%.2f(t/24000)", f / 24000.0) end
                        return "?"
                    end
                    local cur = safe(function() return secs(pl:GetCurrentTime()) end)
                    local dur = safe(function() return secs(pl:GetDuration()) end)
                    local seqName = "?"
                    pcall(function() local s = pl:GetSequence(); if s and s:IsValid() then seqName = s:GetFullName() end end)
                    lines[#lines + 1] = string.format("seq %s t=%s/%s", seqName, tostring(cur), tostring(dur))
                end
            end
        end
    end
    local units = FindAllOf("CPP_BtlUnit")
    if units then
        for _, u in ipairs(units) do
            if u:IsValid() then
                local c = u.m_pSsPlayerComponent
                if c and c:IsValid() then
                    local id = "?"; pcall(function() id = u.m_pUnitParameter:GetUnitId() end)
                    local loc = safe(function() local l = u:K2_GetActorLocation(); return string.format("%.0f,%.0f,%.0f", l.X, l.Y, l.Z) end)
                    lines[#lines + 1] = string.format("unit %s playing=%s pack=%s at=%s", tostring(id), tostring(safe(function() return c:IsPlaying() end)),
                        tostring(safe(function() return u.m_AnimationPackName:ToString() end)), tostring(loc))
                end
            end
        end
    end
    local seq = FindAllOf("CPP_BtlSequencerSsPlayerActor")
    if seq then
        for _, a in ipairs(seq) do
            if a:IsValid() then
                local loc = safe(function() local l = a:K2_GetActorLocation(); return string.format("%.0f,%.0f,%.0f", l.X, l.Y, l.Z) end)
                local fol = safe(function() local f = a.m_pFollowingUnit; if f and f:IsValid() then return f:GetFullName() end; return "none" end)
                lines[#lines + 1] = string.format("ssActor ID=%s anim=%s T=%s at=%s follow=%s", tostring(safe(function() return a.ID end)),
                    tostring(safe(function() return a.animName:ToString() end)), tostring(safe(function() return a.T end)), tostring(loc), tostring(fol))
            end
        end
    end
    local cams = FindAllOf("CPP_BtlCamera")
    if cams then
        for _, cam in ipairs(cams) do
            if cam:IsValid() then
                local loc = safe(function() local l = cam:K2_GetActorLocation(); local r = cam:K2_GetActorRotation(); return string.format("%.0f,%.0f,%.0f yaw=%.0f pitch=%.0f", l.X, l.Y, l.Z, r.Yaw, r.Pitch) end)
                lines[#lines + 1] = "camera at=" .. tostring(loc)
                break
            end
        end
    end
    if #lines > 0 then L(string.format("[%.2fs] ", now() - t0) .. table.concat(lines, " | ")) end
end

local function traceLoop()
    if not tracing then return end
    ExecuteInGameThread(function() pcall(traceOnce) end)
    ExecuteWithDelay(100, traceLoop)
end

RegisterKeyBind(Key.F9, function() ExecuteInGameThread(probe) end)
RegisterKeyBind(Key.F8, function()
    tracing = not tracing
    if tracing then t0 = now(); L("==== trace ON (100 ms) ===="); traceLoop() else L("==== trace OFF ====") end
end)

-- animation calls made through the reflection path (sequencer director blueprints); native calls do not reach this hook
pcall(function()
    RegisterHook("/Script/mucha.CPP_BtlUnit:PlayAnimByName", function(self, AnimationName, InStartFrame, InPlayRate, InLoopCount)
        local u = self:get(); local id = "?"
        pcall(function() id = u.m_pUnitParameter:GetUnitId() end)
        L(string.format("[%.2fs] PlayAnimByName id=%s anim=%s start=%s rate=%s loop=%s", now() - t0, tostring(id), tostring(AnimationName:get()),
            tostring(InStartFrame:get()), tostring(InPlayRate:get()), tostring(InLoopCount:get())))
    end)
end)
L("ready: F9 = dump, F8 = toggle timeline trace (F10 is the UE4SS console)")
