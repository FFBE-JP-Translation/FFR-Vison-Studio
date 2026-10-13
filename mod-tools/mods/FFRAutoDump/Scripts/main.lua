-- FFRAutoDump: one-shot generator for the .usmap mappings + CXX SDK headers
-- Runs a few seconds after the game finishes booting, only if no usmap exists yet.
-- Output lands in <game>/FFRS/Binaries/Win64/ue4ss/  (Mappings.usmap, CXXHeaderDump/)
local marker = "ue4ss/Mappings.usmap"
local function exists(path) local f = io.open(path, "r"); if f then f:close(); return true end; return false end

local ran = false
local function doDump()
    if ran then return end
    ran = true
    if exists(marker) then print("[FFRAutoDump] usmap already exists, skipping\n"); return end
    print("[FFRAutoDump] generating usmap + CXX headers...\n")
    local ok1, e1 = pcall(DumpUSMAP); print("[FFRAutoDump] DumpUSMAP -> " .. tostring(ok1) .. " " .. tostring(e1) .. "\n")
    local ok2, e2 = pcall(GenerateSDK); print("[FFRAutoDump] GenerateSDK -> " .. tostring(ok2) .. " " .. tostring(e2) .. "\n")
    print("[FFRAutoDump] done\n")
end

-- wait until the first PlayerController spawns (title screen), then dump on the game thread
RegisterHook("/Script/Engine.PlayerController:ClientRestart", function()
    ExecuteWithDelay(8000, function() ExecuteInGameThread(doDump) end)
end)
-- fallback if the hook never fires
ExecuteWithDelay(45000, function() ExecuteInGameThread(doDump) end)
