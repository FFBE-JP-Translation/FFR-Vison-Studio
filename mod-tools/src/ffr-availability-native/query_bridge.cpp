#include "query_bridge.hpp"
#include <MinHook.h>
#include <algorithm>
#include <charconv>
#include <intrin.h>
#include <stdexcept>

namespace ffr {
// Shared with execution authorization: Lua must not be entered recursively
// through a different native hook while one of its callbacks is active.
extern thread_local bool nativeCallbackActive;
QueryBridge* QueryBridge::active_{};
bool active_skill_id(std::int32_t id) { return id>=100000 && id<1000000; }

std::vector<std::int32_t> parse_query_commands(std::string_view text, bool enforce) {
    if(text.size()>6144) throw std::runtime_error("managed query command list too large");
    std::vector<std::int32_t> ids;
    if(text.empty()) {
        if(enforce) throw std::runtime_error("query enforcement requires managed active skills");
        return ids;
    }
    std::size_t start=0;
    while(start<text.size()) {
        const auto stop=text.find(',',start);
        const auto end=stop==std::string_view::npos ? text.size() : stop;
        std::int32_t id{};
        const auto [at,error]=std::from_chars(text.data()+start,text.data()+end,id);
        if(error!=std::errc{} || at!=text.data()+end || !active_skill_id(id) || ids.size()>=512)
            throw std::runtime_error("invalid managed query active skill ID");
        ids.push_back(id);
        if(end==text.size()) break;
        start=end+1;
        if(start==text.size()) throw std::runtime_error("trailing query command separator");
    }
    std::sort(ids.begin(),ids.end());
    if(std::adjacent_find(ids.begin(),ids.end())!=ids.end()) throw std::runtime_error("duplicate managed query skill ID");
    return ids;
}

bool QueryBridge::attach(Query target, std::vector<std::int32_t> commands, bool enforce,
                         QueryDecision callback, DWORD gameThread, std::string& error) {
    if(active_ || target_ || !target || !callback || !gameThread || commands.size()>512) {
        error="invalid or already attached query bridge"; return false;
    }
    std::sort(commands.begin(),commands.end());
    if((enforce && commands.empty()) || std::any_of(commands.begin(),commands.end(),[](auto id){return !active_skill_id(id);}) ||
       std::adjacent_find(commands.begin(),commands.end())!=commands.end()) {
        error="invalid managed query active skill IDs"; return false;
    }
    auto status=MH_Initialize();
    if(status!=MH_OK && status!=MH_ERROR_ALREADY_INITIALIZED) { error=MH_StatusToString(status); return false; }
    status=MH_CreateHook(reinterpret_cast<void*>(target),reinterpret_cast<void*>(&intercepted),reinterpret_cast<void**>(&original_));
    if(status!=MH_OK) { error=MH_StatusToString(status); return false; }
    target_=target;commands_=std::move(commands);enforce_=enforce;callback_=std::move(callback);
    gameThread_=gameThread;observations_=0;active_=this;
    status=MH_EnableHook(reinterpret_cast<void*>(target_));
    if(status!=MH_OK) {
        MH_RemoveHook(reinterpret_cast<void*>(target_));active_=nullptr;target_=original_=nullptr;
        callback_={};error=MH_StatusToString(status);return false;
    }
    return true;
}

bool QueryBridge::intercepted(std::int32_t unique, std::int32_t skill, bool item, void* selections, bool option) {
    const auto caller=reinterpret_cast<std::uintptr_t>(_ReturnAddress());
    auto* self=active_;
    self->activeCalls_.fetch_add(1);
    // Run the complete original query once, forwarding every argument even
    // for items and unmanaged skills. Never replace its resource/target checks.
    const bool native=self->original_(unique,skill,item,selections,option);
    const bool allowed=self->decide({unique,skill,reinterpret_cast<std::uintptr_t>(selections),caller,option,native},item);
    self->activeCalls_.fetch_sub(1);
    return allowed;
}

bool QueryBridge::decide(const QueryContext& context, bool item) {
    if(item || !active_skill_id(context.skillId)) return context.nativeAllowed;
    if(!commands_.empty() && !std::binary_search(commands_.begin(),commands_.end(),context.skillId)) return context.nativeAllowed;
    if(GetCurrentThreadId()!=gameThread_ || nativeCallbackActive) return enforce_ ? false : context.nativeAllowed;
    if(!enforce_ && observations_.load()>=20000) return context.nativeAllowed;
    std::lock_guard lock(callbackMutex_);
    if(!callback_) return enforce_ ? false : context.nativeAllowed;
    observations_.fetch_add(1);
    nativeCallbackActive=true;
    bool permitted=false;
    try { permitted=callback_(context); } catch(...) { permitted=false; }
    nativeCallbackActive=false;
    return enforce_ ? context.nativeAllowed && permitted : context.nativeAllowed;
}

void QueryBridge::invalidate_callback() { std::lock_guard lock(callbackMutex_);callback_={}; }
bool QueryBridge::detach(std::string& error) {
    if(!target_) return true;
    if(nativeCallbackActive) { error="cannot detach inside a native callback";return false; }
    const auto status=MH_DisableHook(reinterpret_cast<void*>(target_));
    if(status!=MH_OK && status!=MH_ERROR_DISABLED) { error=MH_StatusToString(status);return false; }
    const auto deadline=GetTickCount64()+2000;
    while(activeCalls_.load()) {
        if(GetTickCount64()>=deadline) { error="query callbacks still active; retain bridge and module";return false; }
        Sleep(1);
    }
    const auto removed=MH_RemoveHook(reinterpret_cast<void*>(target_));
    if(removed!=MH_OK) { error=MH_StatusToString(removed);return false; }
    invalidate_callback();target_=original_=nullptr;active_=nullptr;
    return true;
}
}
