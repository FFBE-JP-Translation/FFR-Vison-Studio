#pragma once
#include <Windows.h>
#include <atomic>
#include <cstdint>
#include <functional>
#include <mutex>
#include <string>
#include <vector>

namespace ffr {
std::string file_sha256(const std::wstring& path);
struct GuardContext {
    std::uintptr_t job{}, actor{}, rootJob{};
    std::int32_t skillId{}, objectIndex{}, actionCount{}, targetCount{};
    bool nativeAllowed{};
};
using Guard = bool (*)(void*);
using Authorize = std::function<bool(const GuardContext&)>;

// One immutable command set per attachment. Managed callback failures deny
// enforcement; observer mode always returns the original native decision.
class GuardBridge {
public:
    bool attach(Guard target, std::vector<std::int32_t> commands, bool enforce,
                Authorize callback, DWORD gameThread, std::string& error);
    void invalidate_callback();
    // Test/controlled-host teardown only: caller must prevent new native calls.
    // The game plugin keeps its hook and pinned module alive for the process.
    bool detach(std::string& error);
    bool installed() const { return target_ != nullptr; }
    std::uint64_t observations() const { return observations_.load(); }
    static bool snapshot(void* job, GuardContext& context);
private:
    static bool intercepted(void* job);
    bool decide(void* job, bool nativeAllowed);
    static GuardBridge* active_;
    Guard target_{}, original_{};
    std::vector<std::int32_t> commands_;
    bool enforce_{};
    DWORD gameThread_{};
    Authorize callback_;
    std::recursive_mutex callbackMutex_;
    std::atomic<std::uint32_t> activeCalls_{};
    std::atomic<std::uint64_t> observations_{};
};
}
