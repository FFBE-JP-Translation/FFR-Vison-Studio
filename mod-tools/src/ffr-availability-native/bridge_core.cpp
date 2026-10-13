#include "bridge_core.hpp"
#include <MinHook.h>
#include <algorithm>
#include <array>
#include <cstring>
#include <bcrypt.h>
#include <fstream>
#include <iomanip>
#include <sstream>

namespace ffr {
thread_local bool nativeCallbackActive{};
GuardBridge* GuardBridge::active_{};
std::string file_sha256(const std::wstring& path) {
    BCRYPT_ALG_HANDLE algorithm{}; BCRYPT_HASH_HANDLE hash{};
    const auto cleanup=[&] { if(hash) BCryptDestroyHash(hash); if(algorithm) BCryptCloseAlgorithmProvider(algorithm,0); };
    try {
        if(BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,nullptr,0)<0 ||
           BCryptCreateHash(algorithm,&hash,nullptr,0,nullptr,0,0)<0) throw std::runtime_error("SHA256 initialization failed");
        std::ifstream input(path,std::ios::binary);
        if(!input) throw std::runtime_error("cannot read loaded module file");
        std::array<unsigned char,65536> buffer{};
        while(input) {
            input.read(reinterpret_cast<char*>(buffer.data()),buffer.size());
            if(input.gcount()>0 && BCryptHashData(hash,buffer.data(),static_cast<ULONG>(input.gcount()),0)<0)
                throw std::runtime_error("SHA256 update failed");
        }
        if(!input.eof()) throw std::runtime_error("module read failed");
        std::array<unsigned char,32> digest{};
        if(BCryptFinishHash(hash,digest.data(),static_cast<ULONG>(digest.size()),0)<0) throw std::runtime_error("SHA256 finalization failed");
        std::ostringstream result;
        for(auto value:digest) result<<std::hex<<std::setw(2)<<std::setfill('0')<<static_cast<unsigned>(value);
        cleanup(); return result.str();
    } catch(...) { cleanup(); throw; }
}
namespace {
constexpr std::uint64_t maxObservations = 20000;
template<class T> bool read(std::uintptr_t address, T& result) {
    SIZE_T count{};
    return ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<void*>(address),
                             &result, sizeof(T), &count) && count == sizeof(T);
}
template<class T> T field(const std::array<std::byte,0x3b0>& data, std::size_t offset) {
    T value{}; std::memcpy(&value, data.data()+offset, sizeof(T)); return value;
}
}
bool GuardBridge::snapshot(void* job, GuardContext& context) {
    std::array<std::byte,0x3b0> data{};
    context = {}; context.job = reinterpret_cast<std::uintptr_t>(job);
    if (!read(context.job, data)) return false;
    context.skillId = field<std::int32_t>(data,0x338);
    context.objectIndex = field<std::int32_t>(data,0xc);
    context.actor = field<std::uintptr_t>(data,0x100);
    context.rootJob = field<std::uintptr_t>(data,0xf8);
    context.actionCount = field<std::int32_t>(data,0x30);
    context.targetCount = field<std::int32_t>(data,0x40);
    // Early native rejection may precede initialization of m_pActionUnit.
    if (!context.actor && context.actionCount > 0) {
        read(field<std::uintptr_t>(data,0x28), context.actor);
    }
    return true;
}
bool GuardBridge::attach(Guard target, std::vector<std::int32_t> commands, bool enforce,
                         Authorize callback, DWORD gameThread, std::string& error) {
    if (active_ || target_ || !target || !callback || !gameThread || commands.size()>512) {
        error="invalid or already attached bridge"; return false;
    }
    std::sort(commands.begin(),commands.end());
    if ((enforce && commands.empty()) || std::any_of(commands.begin(),commands.end(),[](auto id){return id<=0;}) ||
        std::adjacent_find(commands.begin(),commands.end())!=commands.end()) {
        error="invalid managed command IDs"; return false;
    }
    auto status=MH_Initialize();
    if (status!=MH_OK && status!=MH_ERROR_ALREADY_INITIALIZED) { error=MH_StatusToString(status); return false; }
    status=MH_CreateHook(reinterpret_cast<void*>(target),reinterpret_cast<void*>(&intercepted),reinterpret_cast<void**>(&original_));
    if(status!=MH_OK) { error=MH_StatusToString(status); return false; }
    target_=target; commands_=std::move(commands); enforce_=enforce; callback_=std::move(callback);
    gameThread_=gameThread; observations_=0; active_=this;
    status=MH_EnableHook(reinterpret_cast<void*>(target_));
    if(status!=MH_OK) {
        MH_RemoveHook(reinterpret_cast<void*>(target_)); active_=nullptr; target_=original_=nullptr;
        callback_={}; error=MH_StatusToString(status); return false;
    }
    return true;
}
bool GuardBridge::intercepted(void* job) {
    auto* self=active_;
    self->activeCalls_.fetch_add(1);
    const auto native=self->original_(job);
    const auto allowed=self->decide(job,native);
    self->activeCalls_.fetch_sub(1);
    return allowed;
}
bool GuardBridge::decide(void* job, bool nativeAllowed) {
    GuardContext context;
    if (!snapshot(job,context)) return enforce_ ? false : nativeAllowed;
    const bool managed=std::binary_search(commands_.begin(),commands_.end(),context.skillId);
    if(enforce_ && !managed) return nativeAllowed;
    if(!enforce_ && !commands_.empty() && !managed) return nativeAllowed;
    context.nativeAllowed=nativeAllowed;
    if (GetCurrentThreadId()!=gameThread_ || nativeCallbackActive) return enforce_ ? false : nativeAllowed;
    if (!enforce_ && observations_.load()>=maxObservations) return nativeAllowed;
    std::lock_guard lock(callbackMutex_);
    if(!callback_) return enforce_ ? false : nativeAllowed;
    observations_.fetch_add(1);
    bool permitted=false;
    nativeCallbackActive=true;
    try { permitted=callback_(context); } catch (...) { permitted=false; }
    nativeCallbackActive=false;
    return enforce_ ? nativeAllowed && permitted : nativeAllowed;
}
void GuardBridge::invalidate_callback() {
    std::lock_guard lock(callbackMutex_); callback_={};
}
bool GuardBridge::detach(std::string& error) {
    if(!target_) return true;
    if(nativeCallbackActive) { error="cannot detach inside an authorization callback"; return false; }
    const auto status=MH_DisableHook(reinterpret_cast<void*>(target_));
    if(status!=MH_OK && status!=MH_ERROR_DISABLED) { error=MH_StatusToString(status); return false; }
    const auto deadline=GetTickCount64()+2000;
    while(activeCalls_.load()) {
        if(GetTickCount64()>=deadline) { error="native callbacks still active; retain bridge and module"; return false; }
        Sleep(1);
    }
    const auto removed=MH_RemoveHook(reinterpret_cast<void*>(target_));
    if(removed!=MH_OK) { error=MH_StatusToString(removed); return false; }
    invalidate_callback(); target_=original_=nullptr; active_=nullptr;
    return true;
}
}
