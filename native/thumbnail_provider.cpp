// Explorer's isolated COM surrogate only copies bytes and supervises a decoder.
// Qt, LibRaw and all image parsing live in a bounded child Picer.exe process.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <shlobj.h>
#include <thumbcache.h>
#include <propsys.h>
#include <algorithm>
#include <cwctype>
#include <new>
#include <string>
#include <vector>

static const CLSID CLSID_PicerThumbnail =
    {0x7759159a, 0x5a69, 0x4ba7, {0x9c, 0x87, 0x21, 0x44, 0xe7, 0x43, 0xc8, 0xdd}};
static HMODULE moduleHandle;
static volatile LONG objects = 0;
static INIT_ONCE slotsOnce = INIT_ONCE_STATIC_INIT;
static HANDLE slotsHandle = nullptr;
constexpr ULONGLONG MAX_INPUT = 512ull * 1024 * 1024;

static BOOL CALLBACK InitializeSlots(PINIT_ONCE, PVOID, PVOID*) {
    slotsHandle = CreateSemaphoreW(nullptr, 2, 2, nullptr);
    return slotsHandle != nullptr;
}

struct Slot {
    bool acquired = false;
    Slot() {
        if (InitOnceExecuteOnce(&slotsOnce, InitializeSlots, nullptr, nullptr))
            acquired = WaitForSingleObject(slotsHandle, 3000) == WAIT_OBJECT_0;
    }
    ~Slot() { if (acquired) ReleaseSemaphore(slotsHandle, 1, nullptr); }
};

struct Handle {
    HANDLE value = INVALID_HANDLE_VALUE;
    explicit Handle(HANDLE h = INVALID_HANDLE_VALUE) : value(h) {}
    ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
};

struct Workspace {
    std::wstring directory, source, output;
    ~Workspace() {
        if (!source.empty()) DeleteFileW(source.c_str());
        if (!output.empty()) DeleteFileW(output.c_str());
        if (!directory.empty()) {
            DeleteFileW((directory + L"\\thumbnail.tmp").c_str());
            RemoveDirectoryW(directory.c_str());
        }
    }
};

static HRESULT MakeWorkspace(Workspace& work, IStream* stream) {
    PWSTR root = nullptr;
    HRESULT hr = SHGetKnownFolderPath(FOLDERID_LocalAppDataLow, KF_FLAG_CREATE, nullptr, &root);
    if (FAILED(hr)) return hr;
    std::wstring base(root);
    CoTaskMemFree(root);
    // A low-integrity thumbnail surrogate can write here, never beside the original.
    base += L"\\PicerThumbnails";
    if (!CreateDirectoryW(base.c_str(), nullptr) && GetLastError() != ERROR_ALREADY_EXISTS)
        return HRESULT_FROM_WIN32(GetLastError());
    GUID id;
    if (FAILED(CoCreateGuid(&id))) return E_FAIL;
    wchar_t guid[40];
    StringFromGUID2(id, guid, 40);
    work.directory = base + L"\\" + guid;
    if (!CreateDirectoryW(work.directory.c_str(), nullptr))
        return HRESULT_FROM_WIN32(GetLastError());
    std::wstring suffix = L".img";
    STATSTG stat = {};
    if (SUCCEEDED(stream->Stat(&stat, STATFLAG_DEFAULT))) {
        if (stat.pwcsName) {
            std::wstring name(stat.pwcsName);
            CoTaskMemFree(stat.pwcsName);
            size_t dot = name.find_last_of(L'.');
            if (dot != std::wstring::npos && name.size() - dot <= 13) {
                std::wstring candidate = name.substr(dot);
                bool valid = candidate.size() > 1;
                for (size_t n = 1; n < candidate.size(); ++n) {
                    candidate[n] = static_cast<wchar_t>(towlower(candidate[n]));
                    valid = valid && ((candidate[n] >= L'a' && candidate[n] <= L'z') ||
                                      (candidate[n] >= L'0' && candidate[n] <= L'9'));
                }
                if (valid) suffix = candidate;
            }
        }
        if (stat.cbSize.QuadPart > MAX_INPUT) return HRESULT_FROM_WIN32(ERROR_FILE_TOO_LARGE);
    }
    work.source = work.directory + L"\\source" + suffix;
    work.output = work.directory + L"\\thumbnail.bmp";
    Handle file(CreateFileW(work.source.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW,
                            FILE_ATTRIBUTE_TEMPORARY, nullptr));
    if (file.value == INVALID_HANDLE_VALUE) return HRESULT_FROM_WIN32(GetLastError());
    LARGE_INTEGER zero = {};
    hr = stream->Seek(zero, STREAM_SEEK_SET, nullptr);
    if (FAILED(hr)) return hr;
    BYTE buffer[65536];
    ULONGLONG total = 0;
    for (;;) {
        ULONG got = 0;
        hr = stream->Read(buffer, sizeof(buffer), &got);
        if (FAILED(hr)) return hr;
        if (!got) return total ? S_OK : E_FAIL;
        total += got;
        if (total > MAX_INPUT) return HRESULT_FROM_WIN32(ERROR_FILE_TOO_LARGE);
        DWORD written = 0;
        if (!WriteFile(file.value, buffer, got, &written, nullptr) || written != got) return E_FAIL;
    }
}

static HRESULT Decode(const Workspace& work, UINT edge) {
    wchar_t modulePath[32768];
    DWORD count = GetModuleFileNameW(moduleHandle, modulePath, 32768);
    if (!count || count >= 32768) return E_FAIL;
    std::wstring path(modulePath, count);
    size_t slash = path.find_last_of(L"\\/");
    if (slash == std::wstring::npos) return E_FAIL;
    path.resize(slash); // .../Picer/shell
    slash = path.find_last_of(L"\\/");
    if (slash == std::wstring::npos) return E_FAIL;
    std::wstring executable = path.substr(0, slash) + L"\\Picer.exe";
    std::wstring command = L"\"" + executable + L"\" --shell-thumbnail \"" +
        work.directory + L"\" " + std::to_wstring(edge);
    Handle job(CreateJobObjectW(nullptr, nullptr));
    if (!job.value) return E_FAIL;
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits = {};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE |
        JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_ACTIVE_PROCESS;
    limits.ProcessMemoryLimit = 1536ull * 1024 * 1024;
    limits.BasicLimitInformation.ActiveProcessLimit = 1;
    if (!SetInformationJobObject(job.value, JobObjectExtendedLimitInformation, &limits, sizeof(limits)))
        return HRESULT_FROM_WIN32(GetLastError());
    STARTUPINFOW startup = {};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION process = {};
    if (!CreateProcessW(executable.c_str(), command.data(), nullptr, nullptr, FALSE,
                        CREATE_NO_WINDOW | CREATE_SUSPENDED, nullptr, work.directory.c_str(),
                        &startup, &process)) return HRESULT_FROM_WIN32(GetLastError());
    Handle child(process.hProcess), thread(process.hThread);
    if (!AssignProcessToJobObject(job.value, child.value)) {
        TerminateProcess(child.value, 1);
        WaitForSingleObject(child.value, 2000);
        return E_FAIL;
    }
    ResumeThread(thread.value);
    if (WaitForSingleObject(child.value, 15000) != WAIT_OBJECT_0) {
        TerminateJobObject(job.value, 1);
        WaitForSingleObject(child.value, 2000);
        return HRESULT_FROM_WIN32(ERROR_TIMEOUT);
    }
    DWORD code = 1;
    if (!GetExitCodeProcess(child.value, &code) || code != 0) return E_FAIL;
    return S_OK;
}

static HRESULT Bitmap(const Workspace& work, UINT edge, HBITMAP* result) {
    Handle file(CreateFileW(work.output.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr,
                            OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    if (file.value == INVALID_HANDLE_VALUE) return E_FAIL;
    BITMAPFILEHEADER header = {};
    BITMAPINFO info = {};
    DWORD got = 0;
    if (!ReadFile(file.value, &header, sizeof(header), &got, nullptr) || got != sizeof(header)) return E_FAIL;
    if (!ReadFile(file.value, &info.bmiHeader, sizeof(BITMAPINFOHEADER), &got, nullptr) ||
        got != sizeof(BITMAPINFOHEADER)) return E_FAIL;
    const auto& b = info.bmiHeader;
    if (header.bfType != 0x4d42 || header.bfOffBits != 54 || b.biSize != 40 ||
        b.biWidth < 1 || b.biWidth > static_cast<LONG>(edge) || b.biHeight > -1 ||
        b.biHeight < -static_cast<LONG>(edge) || b.biBitCount != 32 || b.biPlanes != 1 ||
        b.biCompression != BI_RGB) return E_FAIL;
    DWORD bytes = b.biWidth * -b.biHeight * 4;
    LARGE_INTEGER size;
    if (!GetFileSizeEx(file.value, &size) || size.QuadPart != 54ull + bytes) return E_FAIL;
    void* pixels = nullptr;
    HBITMAP bitmap = CreateDIBSection(nullptr, &info, DIB_RGB_COLORS, &pixels, nullptr, 0);
    if (!bitmap) return E_OUTOFMEMORY;
    if (!ReadFile(file.value, pixels, bytes, &got, nullptr) || got != bytes) {
        DeleteObject(bitmap);
        return E_FAIL;
    }
    *result = bitmap;
    return S_OK;
}

class Thumbnail final : public IInitializeWithStream, public IThumbnailProvider {
    volatile LONG references = 1;
    IStream* stream = nullptr;
public:
    Thumbnail() { InterlockedIncrement(&objects); }
    ~Thumbnail() { if (stream) stream->Release(); InterlockedDecrement(&objects); }
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID id, void** out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (id == IID_IUnknown || id == __uuidof(IInitializeWithStream))
            *out = static_cast<IInitializeWithStream*>(this);
        else if (id == __uuidof(IThumbnailProvider)) *out = static_cast<IThumbnailProvider*>(this);
        else return E_NOINTERFACE;
        AddRef(); return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return InterlockedIncrement(&references); }
    ULONG STDMETHODCALLTYPE Release() override {
        ULONG count = InterlockedDecrement(&references);
        if (!count) delete this;
        return count;
    }
    HRESULT STDMETHODCALLTYPE Initialize(IStream* value, DWORD mode) override {
        if (!value) return E_INVALIDARG;
        if (stream) return HRESULT_FROM_WIN32(ERROR_ALREADY_INITIALIZED);
        if ((mode & 3) != STGM_READ) return STG_E_ACCESSDENIED;
        stream = value; stream->AddRef(); return S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetThumbnail(UINT edge, HBITMAP* bitmap, WTS_ALPHATYPE* alpha) override {
        if (!bitmap || !alpha) return E_POINTER;
        *bitmap = nullptr; *alpha = WTSAT_UNKNOWN;
        if (!stream || edge < 16 || edge > 1024) return E_INVALIDARG;
        try {
            Slot slot;
            if (!slot.acquired) return HRESULT_FROM_WIN32(ERROR_BUSY);
            Workspace work;
            HRESULT hr = MakeWorkspace(work, stream);
            if (SUCCEEDED(hr)) hr = Decode(work, edge);
            if (SUCCEEDED(hr)) hr = Bitmap(work, edge, bitmap);
            if (SUCCEEDED(hr)) *alpha = WTSAT_ARGB;
            return hr;
        } catch (const std::bad_alloc&) { return E_OUTOFMEMORY; }
          catch (...) { return E_FAIL; }
    }
};

class Factory final : public IClassFactory {
    volatile LONG references = 1;
public:
    Factory() { InterlockedIncrement(&objects); }
    ~Factory() { InterlockedDecrement(&objects); }
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID id, void** out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (id != IID_IUnknown && id != IID_IClassFactory) return E_NOINTERFACE;
        *out = static_cast<IClassFactory*>(this); AddRef(); return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return InterlockedIncrement(&references); }
    ULONG STDMETHODCALLTYPE Release() override {
        ULONG count = InterlockedDecrement(&references);
        if (!count) delete this;
        return count;
    }
    HRESULT STDMETHODCALLTYPE CreateInstance(IUnknown* outer, REFIID id, void** out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (outer) return CLASS_E_NOAGGREGATION;
        auto* instance = new (std::nothrow) Thumbnail();
        if (!instance) return E_OUTOFMEMORY;
        HRESULT hr = instance->QueryInterface(id, out);
        instance->Release(); return hr;
    }
    HRESULT STDMETHODCALLTYPE LockServer(BOOL lock) override {
        if (lock) InterlockedIncrement(&objects); else InterlockedDecrement(&objects);
        return S_OK;
    }
};

extern "C" HRESULT __stdcall DllGetClassObject(REFCLSID id, REFIID iid, void** out) {
    if (!out) return E_POINTER;
    *out = nullptr;
    if (id != CLSID_PicerThumbnail) return CLASS_E_CLASSNOTAVAILABLE;
    auto* factory = new (std::nothrow) Factory();
    if (!factory) return E_OUTOFMEMORY;
    HRESULT hr = factory->QueryInterface(iid, out);
    factory->Release(); return hr;
}
extern "C" HRESULT __stdcall DllCanUnloadNow() { return objects == 0 ? S_OK : S_FALSE; }
BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) moduleHandle = instance;
    if (reason == DLL_PROCESS_DETACH && slotsHandle) CloseHandle(slotsHandle);
    return TRUE;
}
