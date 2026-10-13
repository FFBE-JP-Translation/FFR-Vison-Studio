-- Optional read-only native entry/job correlation. Does not authorize casts.
local M={}
function M.setup()
    assert(FFRBattleProbeSelectionJobs and FFRBattleProbeProtectedSaves)
    local sequence=0
    local pre,post=RegisterHook('/Script/mucha.CPP_BtlDelEventCmd:OnExecuteDecideCommand',function(context,remote)
        local ok,why=pcall(function()
            local value=remote:get();sequence=sequence+1
            print(string.format('[FFRSelectionProbe] {"event":"native_selection_decide","sequence":%d,"receiver":%d,"delegate":%d,"count":%d}\n',
                sequence,context:get():GetAddress(),value:GetAddress(),value.cmdDecideDataList:GetArrayNum()))
        end)
        if not ok then print('[FFRSelectionProbe] selection_decide_failed='..tostring(why)..'\n') end
    end)
    assert(type(pre)=='number' and type(post)=='number','selection delegate observer failed')
    function FFRSelectionProbeOnObservation(line)
        assert(type(line)=='string' and #line<=32768,'invalid native selection observation')
        print('[FFRSelectionProbe] '..line..'\n')
    end
    local ok,why=FFRSelectionProbeAttach()
    assert(ok and why=='selection observer attached','native selection observer failed: '..tostring(why))
    print('[FFRSelectionProbe] attached read_only=true\n')
end
return M
