#include "bridge_core.hpp"
#include "query_bridge.hpp"
#include <Mod/CppUserModBase.hpp>
#include <LuaMadeSimple/LuaMadeSimple.hpp>
#include <bcrypt.h>
#include <array>
#include <charconv>
#include <cstdio>
#include <fstream>
#include <iomanip>
#include <sstream>

namespace {
using RC::LuaMadeSimple::Lua;
// This process-lifetime object remains valid after Lua/C++ mod stop. Once a
// detour is installed the DLL is pinned, and stopping invalidates its Lua
// callback. A new process is required to change the bound command set.
ffr::GuardBridge bridge;
ffr::QueryBridge queryBridge;
const Lua* hookLua{};
const Lua* queryLua{};
constexpr auto gameHash="e06401cdf4e64d55f652043bdd2012267d5529a00c3dbc36ee4365e0ce49caad";
constexpr auto ue4ssHash="7082324aa440169fc992c02812a10f5c68a975d83f95273134c1c7ccddbe4b2d";

std::wstring module_path(HMODULE module) {
    std::array<wchar_t,32768> path{};
    const auto n=GetModuleFileNameW(module,path.data(),static_cast<DWORD>(path.size()));
    if(!n || n>=path.size()) throw std::runtime_error("cannot resolve loaded module path");
    return {path.data(),n};
}
using ffr::file_sha256;
ffr::Guard verified_target() {
    const auto executable=GetModuleHandleW(nullptr);
    const auto ue4ss=GetModuleHandleW(L"UE4SS.dll");
    if(!ue4ss || file_sha256(module_path(executable))!=gameHash || file_sha256(module_path(ue4ss))!=ue4ssHash)
        throw std::runtime_error("unsupported game or UE4SS binary fingerprint");
    const auto target=reinterpret_cast<std::uintptr_t>(executable)+0x4f44800;
    constexpr std::array<unsigned char,15> prologue{0x48,0x89,0x5c,0x24,0x08,0x48,0x89,0x74,0x24,0x10,0x57,0x48,0x83,0xec,0x20};
    std::array<unsigned char,15> actual{}; SIZE_T count{};
    if(!ReadProcessMemory(GetCurrentProcess(),reinterpret_cast<void*>(target),actual.data(),actual.size(),&count) ||
        count!=actual.size() || actual!=prologue) throw std::runtime_error("native guard prologue changed or already hooked");
    return reinterpret_cast<ffr::Guard>(target);
}
bool authorize(const ffr::GuardContext& context) {
    if(!hookLua || !hookLua->is_global_function("FFRAvailabilityOnNativeGuard")) return false;
    const auto stack=hookLua->get_stack_size();
    try {
        hookLua->prepare_function_call("FFRAvailabilityOnNativeGuard");
        hookLua->set_integer(static_cast<std::int64_t>(context.job));
        hookLua->set_integer(static_cast<std::int64_t>(context.actor));
        hookLua->set_integer(static_cast<std::int64_t>(context.rootJob));
        hookLua->set_integer(context.skillId); hookLua->set_integer(context.objectIndex);
        hookLua->set_integer(context.actionCount); hookLua->set_integer(context.targetCount);
        hookLua->set_bool(context.nativeAllowed);
        hookLua->call_function(8,1);
        const bool result=hookLua->is_bool(-1) && hookLua->get_bool(-1);
        while(hookLua->get_stack_size()>stack) hookLua->discard_value(-1);
        return result;
    } catch(...) {
        while(hookLua->get_stack_size()>stack) hookLua->discard_value(-1);
        return false;
    }
}
ffr::Query verified_query_target() {
    const auto executable=GetModuleHandleW(nullptr);
    const auto ue4ss=GetModuleHandleW(L"UE4SS.dll");
    if(!ue4ss || file_sha256(module_path(executable))!=gameHash || file_sha256(module_path(ue4ss))!=ue4ssHash)
        throw std::runtime_error("unsupported game or UE4SS binary fingerprint");
    const auto target=reinterpret_cast<std::uintptr_t>(executable)+0x4f439d0;
    constexpr std::array<unsigned char,14> prologue{0x48,0x89,0x5c,0x24,8,0x4c,0x89,0x4c,0x24,0x20,0x89,0x54,0x24,0x10};
    std::array<unsigned char,14> actual{};SIZE_T count{};
    if(!ReadProcessMemory(GetCurrentProcess(),reinterpret_cast<void*>(target),actual.data(),actual.size(),&count) ||
       count!=actual.size() || actual!=prologue) throw std::runtime_error("native query prologue changed or already hooked");
    return reinterpret_cast<ffr::Query>(target);
}
bool query(const ffr::QueryContext& context) {
    if(!queryLua || !queryLua->is_global_function("FFRAvailabilityOnNativeQuery")) return false;
    const auto stack=queryLua->get_stack_size();
    try {
        queryLua->prepare_function_call("FFRAvailabilityOnNativeQuery");
        queryLua->set_integer(context.uniqueId);queryLua->set_integer(context.skillId);
        queryLua->set_bool(context.nativeAllowed);
        queryLua->set_integer(static_cast<std::int64_t>(context.caller-reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr))));
        // The address is observation context, never a logical selection token.
        queryLua->set_integer(static_cast<std::int64_t>(context.selections));queryLua->set_bool(context.option);
        queryLua->call_function(6,1);
        const bool result=queryLua->is_bool(-1) && queryLua->get_bool(-1);
        while(queryLua->get_stack_size()>stack) queryLua->discard_value(-1);
        return result;
    } catch(...) {
        while(queryLua->get_stack_size()>stack) queryLua->discard_value(-1);
        return false;
    }
}
int attach_query(const Lua& lua) {
    try {
        if(lua.get_stack_size()!=2 || !lua.is_bool(1) || !lua.is_string(2))
            throw std::runtime_error("query attach expects boolean enforcement and comma-separated active skill IDs");
        const bool enforce=lua.get_bool(1);
        const std::string text(lua.get_string(1));
        auto ids=ffr::parse_query_commands(text,enforce);
        if(queryBridge.installed()) throw std::runtime_error("native query bridge already attached; restart required");
        if(!lua.is_global_function("FFRAvailabilityOnNativeQuery")) throw std::runtime_error("native query callback is not ready");
        if(!lua.is_global_function("IsInGameThread")) throw std::runtime_error("game thread check unavailable");
        lua.prepare_function_call("IsInGameThread");lua.call_function(0,1);
        if(!lua.is_bool(-1) || !lua.get_bool(-1)) throw std::runtime_error("native query requires the game thread");
        const auto target=verified_query_target();
        HMODULE pinned{};
        if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,
                              reinterpret_cast<LPCWSTR>(&attach_query),&pinned)) throw std::runtime_error("could not pin native query module");
        std::string error;
        queryLua=&lua;
        if(!queryBridge.attach(target,std::move(ids),enforce,query,GetCurrentThreadId(),error)) {
            queryLua=nullptr;throw std::runtime_error(error);
        }
        lua.set_bool(true);lua.set_string("native query attached");return 2;
    } catch(const std::exception& error) { lua.set_bool(false);lua.set_string(error.what());return 2; }
}
int attach(const Lua& lua) {
    try {
        if(lua.get_stack_size()!=2 || !lua.is_bool(1) || !lua.is_string(2)) throw std::runtime_error("attach expects boolean enforcement and comma-separated command IDs");
        const bool enforce=lua.get_bool(1);
        const std::string text(lua.get_string(1));
        if(text.size()>6144) throw std::runtime_error("managed command list too large");
        std::vector<std::int32_t> ids;
        std::size_t start=0;
        while(start<text.size()) {
            const auto stop=text.find(',',start);
            const auto end=stop==std::string::npos ? text.size() : stop;
            std::int32_t id{};
            const auto [at,error]=std::from_chars(text.data()+start,text.data()+end,id);
            if(error!=std::errc{} || at!=text.data()+end || id<=0 || ids.size()>=512) throw std::runtime_error("invalid managed command ID");
            ids.push_back(id); start=end+1;
            if(start==text.size()) throw std::runtime_error("trailing command separator");
        }
        // UE4SS starts the C++ lifecycle before main.lua and creates its hook
        // coroutine lazily. Bind the actual calling coroutine here, after Lua
        // has scheduled this API through ExecuteInGameThread.
        if(bridge.installed()) throw std::runtime_error("native bridge already attached; restart required");
        if(!lua.is_global_function("FFRAvailabilityOnNativeGuard")) throw std::runtime_error("native guard callback is not ready");
        const auto target=verified_target();
        HMODULE pinned{};
        if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,
                              reinterpret_cast<LPCWSTR>(&attach),&pinned)) throw std::runtime_error("could not pin native bridge module");
        std::string error;
        hookLua=&lua;
        if(!bridge.attach(target,std::move(ids),enforce,authorize,GetCurrentThreadId(),error)) throw std::runtime_error(error);
        std::printf("[FFRAvailabilityNative] Attached native guard; mode=%s; native lifecycle binding remains required.\n",enforce?"enforce":"observe");
        lua.set_bool(true); lua.set_string("attached"); return 2;
    } catch(const std::exception& error) {
        lua.set_bool(false); lua.set_string(error.what()); return 2;
    }
}
class AvailabilityMod final : public RC::CppUserModBase {
public:
    AvailabilityMod() {
        ModName=STR("FFRAvailabilityRuntime"); ModVersion=STR("0.1.0");
        ModDescription=STR("Direct native execution bridge for FFBE ability availability");
        ModAuthors=STR("FFR Vision Studio");
    }
    ~AvailabilityMod() override {
        bridge.invalidate_callback();queryBridge.invalidate_callback();hookLua=nullptr;queryLua=nullptr;
    }
    void on_lua_start(Lua&,Lua& main,Lua&,Lua*) override {
        if(bridge.installed() || queryBridge.installed()) {
            std::printf("[FFRAvailabilityNative] Restart required after runtime stop; command ownership is not rebound.\n"); return;
        }
        main.register_function("FFRAvailabilityNativeAttach",attach);
        main.register_function("FFRAvailabilityNativeAttachQuery",attach_query);
    }
    void on_lua_stop(Lua&,Lua&,Lua&,Lua*) override {
        bridge.invalidate_callback();queryBridge.invalidate_callback();hookLua=nullptr;queryLua=nullptr;
        std::printf("[FFRAvailabilityNative] Lua stopped; configured enforcement remains closed. Restart required.\n");
    }
};
static_assert(sizeof(RC::CppUserModBase)==0xc0,"public UE4SS mod class layout mismatch");
}
extern "C" __declspec(dllexport) RC::CppUserModBase* start_mod() {
    // Check before constructing the SDK class, whose layout belongs to this
    // exact UE4SS build. Returning null is supported by CppMod::start_mod.
    try {
        const auto ue4ss=GetModuleHandleW(L"UE4SS.dll");
        if(!ue4ss || file_sha256(module_path(ue4ss))!=ue4ssHash) throw std::runtime_error("unsupported UE4SS binary");
        return new AvailabilityMod();
    } catch(const std::exception& error) {
        std::printf("[FFRAvailabilityNative] Refused initialization: %s\n",error.what()); return nullptr;
    }
}
extern "C" __declspec(dllexport) void uninstall_mod(RC::CppUserModBase* mod) { delete mod; }
