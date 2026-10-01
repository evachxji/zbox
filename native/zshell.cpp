// zshell_host.exe —— 格子文件右键菜单宿主：独立进程弹出与资源管理器逐项一致的系统外壳菜单。
// 为什么必须是独立 exe 而不是内嵌 DLL：Defender 扫描（EPP 扩展）会检查宿主进程，
// 在真正的 Python 解释器进程里 QueryContextMenu 返回成功但一项不加（已排除 exe 名/路径/
// 版本资源/签名/清单/python312.dll 加载等全部表象，只有真 python.exe 进程被拒）；
// 本 exe 是我们自己的原生进程，EPP 正常加项。菜单构建契约与坑详见 AGENTS.md「格子文件右键」。
//
// 两种用法：
//   zshell_host.exe <hwnd十进制> <x> <y> <路径1> [路径2 ...]   一次性弹菜单（调试用）
//   zshell_host.exe --serve                                    常驻服务模式（面板用）
// 服务模式协议（stdin/stdout，UTF-8 行）：
//   请求: "M <hwnd> <路径数>\n" + 每行一个路径；响应: "R <退出码>\n"
//   退出码: 0=已执行所选命令或用户取消；2=用户选了「重命名」（调用方做行内重命名）；1=失败。
//   常驻 + 预热（启动时先构建一次菜单把壳扩展 DLL 全部载入）解决每次右键 ~500ms 的延迟。
#include <windows.h>
#include <shlobj.h>
#include <shlwapi.h>
#include <stdio.h>

#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "shlwapi.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "advapi32.lib")

typedef HRESULT (WINAPI *PFN_SHCreateDataObject)(PCIDLIST_ABSOLUTE, UINT, PCUITEMID_CHILD_ARRAY, IDataObject*, REFIID, void**);
typedef HRESULT (WINAPI *PFN_SHCreateDefaultContextMenu)(const void*, REFIID, void**);

// DEFCONTEXTMENU(0x48) + 扩展尾部：IDataObject / 站点（Explorer 用的完整形态）
struct DCM_EXT {
    HWND hwnd;
    IUnknown *pcmcb;
    PCIDLIST_ABSOLUTE pidlFolder;
    IShellFolder *psf;
    UINT cidl;
    UINT _p0;
    PCUITEMID_CHILD_ARRAY apidl;
    IUnknown *punkAssocInfo;
    UINT cKeys;
    UINT _p1;
    const HKEY *aKeys;
    IDataObject *pdtobj;
    IUnknown *punkSite;
};

// 最小站点：IOleWindow + IServiceProvider。EPP 只检查站点非空，
// QueryService 一律 E_NOINTERFACE 即可（实测）。
class CMinimalSite : public IOleWindow, public IServiceProvider {
public:
    HWND _hwnd;
    CMinimalSite(HWND h) : _hwnd(h) {}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void **ppv) override {
        if (riid == IID_IUnknown || riid == IID_IOleWindow) { *ppv = (IOleWindow*)this; AddRef(); return S_OK; }
        if (riid == IID_IServiceProvider) { *ppv = (IServiceProvider*)this; AddRef(); return S_OK; }
        *ppv = NULL; return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return 2; }
    ULONG STDMETHODCALLTYPE Release() override { return 1; }
    HRESULT STDMETHODCALLTYPE GetWindow(HWND *ph) override { *ph = _hwnd; return S_OK; }
    HRESULT STDMETHODCALLTYPE ContextSensitiveHelp(BOOL) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE QueryService(REFGUID, REFIID, void **ppv) override { *ppv = NULL; return E_NOINTERFACE; }
};

// TrackPopupMenu 期间转发菜单消息的对象（单次弹窗内有效）
static IContextMenu2 *g_pcm2 = NULL;
static IContextMenu3 *g_pcm3 = NULL;

static LRESULT CALLBACK MenuWndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_INITMENUPOPUP:
    case WM_DRAWITEM:
    case WM_MEASUREITEM:
    case WM_MENUCHAR:
        if (g_pcm3) {
            LRESULT lr = 0;
            if (SUCCEEDED(g_pcm3->HandleMenuMsg2(msg, wp, lp, &lr)))
                return lr;
        } else if (g_pcm2) {
            if (SUCCEEDED(g_pcm2->HandleMenuMsg(msg, wp, lp)))
                return 0;
        }
        break;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

// 跟随系统明暗：uxtheme #135 SetPreferredAppMode（深色 2 / 浅色 3）+ #136 FlushMenuThemes
static void apply_menu_theme() {
    DWORD light = 1, sz = sizeof(light);
    RegGetValueW(HKEY_CURRENT_USER,
                 L"Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize",
                 L"AppsUseLightTheme", RRF_RT_REG_DWORD, NULL, &light, &sz);
    HMODULE ux = GetModuleHandleW(L"uxtheme.dll");
    if (!ux) ux = LoadLibraryW(L"uxtheme.dll");
    if (!ux) return;
    typedef void (WINAPI *PFN_AppMode)(int);
    typedef void (WINAPI *PFN_Flush)();
    PFN_AppMode pSet = (PFN_AppMode)GetProcAddress(ux, (LPCSTR)135);
    PFN_Flush pFlush = (PFN_Flush)GetProcAddress(ux, (LPCSTR)136);
    if (pSet) pSet(light ? 3 : 2);
    if (pFlush) pFlush();
}

// 构建菜单对象（不含弹窗）：336 + SetSite + QueryContextMenu。预热与弹窗共用。
static IContextMenu *build_menu(HWND hwnd, int pathc, wchar_t **pathv, HMENU hmenu) {
    PIDLIST_ABSOLUTE abs_pidls[64];
    PCUITEMID_CHILD kids[64];
    int count = 0;
    IShellFolder *psf = NULL;
    PIDLIST_ABSOLUTE pidlFolder = NULL;
    IDataObject *pdtobj = NULL;
    IContextMenu *pcm = NULL;

    if (pathc > 64) pathc = 64;
    for (count = 0; count < pathc; count++) {
        if (SHParseDisplayName(pathv[count], NULL, &abs_pidls[count], 0, NULL) != S_OK)
            break;
        IShellFolder *psfOne = NULL;
        PCUITEMID_CHILD kid = NULL;
        if (SHBindToParent(abs_pidls[count], IID_IShellFolder, (void**)&psfOne, &kid) != S_OK || !kid) {
            ILFree(abs_pidls[count]);
            break;
        }
        if (!psf) {
            psf = psfOne;
            pidlFolder = ILClone(abs_pidls[count]);
            ILRemoveLastID(pidlFolder);
        } else {
            psfOne->Release();   // 格子列表必然同目录，父目录只留第一份
        }
        kids[count] = kid;
    }
    if (count == 0 || !psf)
        goto cleanup;

    {
        HMODULE sh = GetModuleHandleW(L"shell32.dll");
        PFN_SHCreateDataObject pDO = (PFN_SHCreateDataObject)GetProcAddress(sh, (LPCSTR)335);
        PFN_SHCreateDefaultContextMenu pCM = (PFN_SHCreateDefaultContextMenu)GetProcAddress(sh, (LPCSTR)336);
        if (!pDO || !pCM) goto cleanup;
        if (FAILED(pDO(pidlFolder, count, kids, NULL, IID_IDataObject, (void**)&pdtobj)))
            goto cleanup;
        DCM_EXT dcm = {};
        dcm.hwnd = hwnd;
        dcm.pidlFolder = pidlFolder;
        dcm.psf = psf;
        dcm.cidl = count;
        dcm.apidl = kids;
        dcm.pdtobj = pdtobj;
        if (FAILED(pCM(&dcm, IID_IContextMenu, (void**)&pcm)) || !pcm)
            goto cleanup;
    }

    // SetSite：EPP（Defender 扫描）等扩展加项的前提。
    // 站点必须在 pcm 整个生命周期内存活（扩展 AddRef 后存的是裸指针），
    // 所以挂到堆上，跟随 pcm 一起释放（简化：站点泄漏到进程结束，服务模式下一次弹窗一个，可接受）。
    {
        CMinimalSite *site = new CMinimalSite(hwnd);
        IObjectWithSite *pows = NULL;
        if (SUCCEEDED(pcm->QueryInterface(IID_IObjectWithSite, (void**)&pows))) {
            pows->SetSite((IOleWindow*)site);
            pows->Release();
        }
        // CMF_EXPLORE|CMF_CANRENAME = 0x14：对齐资源管理器（带「重命名」）
        if (FAILED(pcm->QueryContextMenu(hmenu, 0, 1, 0x7FFF, CMF_EXPLORE | CMF_CANRENAME))) {
            pcm->Release();
            pcm = NULL;
            goto cleanup;
        }
    }

cleanup:
    if (pdtobj) pdtobj->Release();
    if (psf) psf->Release();
    if (pidlFolder) ILFree(pidlFolder);
    for (int i = 0; i < count; i++) ILFree(abs_pidls[i]);
    return pcm;
}

static int show_menu_impl(HWND hwnd, int pathc, wchar_t **pathv) {
    apply_menu_theme();

    HMENU hmenu = CreatePopupMenu();
    if (!hmenu) return 1;
    IContextMenu *pcm = build_menu(hwnd, pathc, pathv, hmenu);
    if (!pcm) {
        DestroyMenu(hmenu);
        return 1;
    }
    pcm->QueryInterface(IID_IContextMenu2, (void**)&g_pcm2);
    pcm->QueryInterface(IID_IContextMenu3, (void**)&g_pcm3);

    // 隐藏窗当 TrackPopupMenu 属主：转发菜单消息（图标懒加载/自绘/键盘加速）
    HWND hhidden = NULL;
    {
        static ATOM cls = 0;
        if (!cls) {
            WNDCLASSW wc = {};
            wc.lpfnWndProc = MenuWndProc;
            wc.hInstance = GetModuleHandleW(NULL);
            wc.lpszClassName = L"ZviberShellMenu";
            cls = RegisterClassW(&wc);
        }
        hhidden = CreateWindowExW(0, (LPCWSTR)cls, L"", WS_POPUP,
                                  0, 0, 0, 0, NULL, NULL, GetModuleHandleW(NULL), NULL);
    }

    // 前台锁：宿主是独立进程，拿不到 SetForegroundWindow 权限时菜单
    // （#32768）收不到键盘输入，Esc/方向键/助记符全哑。AttachThreadInput
    // 挂到当前前台线程共享输入状态后即可置前台（经典解法）。
    HWND hFore = GetForegroundWindow();
    DWORD foreTid = hFore ? GetWindowThreadProcessId(hFore, NULL) : 0;
    DWORD myTid = GetCurrentThreadId();
    if (foreTid && foreTid != myTid)
        AttachThreadInput(myTid, foreTid, TRUE);
    SetForegroundWindow(hhidden);
    SetActiveWindow(hhidden);
    if (foreTid && foreTid != myTid)
        AttachThreadInput(myTid, foreTid, FALSE);

    // 菜单位置取当前光标物理坐标（Qt 传过来的是逻辑像素，125% 缩放下会偏移）；
    // TPM_RECURSE：菜单开着时在别处再点右键，系统先关旧菜单再把 WM_CONTEXTMENU
    // 转发给落点窗口——对齐资源管理器的「右键连击」体验，不给就只有关菜单的效果。
    POINT pt;
    GetCursorPos(&pt);
    UINT cmd = (UINT)TrackPopupMenu(hmenu, TPM_RETURNCMD | TPM_RECURSE, pt.x, pt.y, 0, hhidden, NULL);

    // 焦点还给原来的前台窗口（同样要借输入状态）
    if (hFore && IsWindow(hFore)) {
        foreTid = GetWindowThreadProcessId(hFore, NULL);
        if (foreTid && foreTid != myTid)
            AttachThreadInput(myTid, foreTid, TRUE);
        SetForegroundWindow(hFore);
        if (foreTid && foreTid != myTid)
            AttachThreadInput(myTid, foreTid, FALSE);
    }

    int rc = 0;   // 默认：用户取消
    if (cmd != 0) {
        // rename 交回调用方：内联重命名（rename 动词没有文件夹视图不会生效）
        wchar_t verb[64] = {0};
        HRESULT hrG = pcm->GetCommandString(cmd - 1, GCS_VERBW, NULL, (LPSTR)verb, 63);
        if (SUCCEEDED(hrG) && verb[0] && lstrcmpiW(verb, L"rename") == 0) {
            rc = 2;
        } else {
            CMINVOKECOMMANDINFOEX ci = {};
            ci.cbSize = sizeof(ci);
            ci.fMask = CMIC_MASK_UNICODE | CMIC_MASK_ASYNCOK;
            ci.hwnd = hwnd;
            ci.lpVerb = MAKEINTRESOURCEA(cmd - 1);
            ci.lpVerbW = MAKEINTRESOURCEW(cmd - 1);
            ci.nShow = SW_SHOWNORMAL;
            pcm->InvokeCommand((CMINVOKECOMMANDINFO*)&ci);
            rc = 0;
        }
    }

    DestroyMenu(hmenu);
    DestroyWindow(hhidden);
    if (g_pcm3) { g_pcm3->Release(); g_pcm3 = NULL; }
    if (g_pcm2) { g_pcm2->Release(); g_pcm2 = NULL; }
    pcm->Release();
    return rc;
}

// 服务模式预热：用自身 exe 构建一次菜单并立刻销毁，
// 把全部壳扩展 DLL（EPP/压缩/网盘等）留在进程里，首个右键菜单就快了。
static void warmup() {
    wchar_t self[MAX_PATH];
    GetModuleFileNameW(NULL, self, MAX_PATH);
    wchar_t *paths[1] = { self };
    HMENU h = CreatePopupMenu();
    if (!h) return;
    IContextMenu *pcm = build_menu(NULL, 1, paths, h);
    if (pcm) pcm->Release();
    DestroyMenu(h);
}

// 服务模式：逐请求弹菜单。stdin 关闭（面板退出）时自然结束。
static int serve() {
    // 控制台 stdin/stdout 按字节处理（路径走 UTF-8，文件名不可能含换行）
    SetConsoleOutputCP(CP_UTF8);
    warmup();
    // 就绪信号：告诉面板预热完成，可以发请求了
    fputs("READY\n", stdout);
    fflush(stdout);

    char line[256];
    while (fgets(line, sizeof(line), stdin)) {
        if (line[0] != 'M')
            continue;
        long long hwnd = 0;
        int n = 0;
        sscanf_s(line + 1, "%lld %d", &hwnd, &n);
        if (n < 1 || n > 64) {
            fputs("R 1\n", stdout);
            fflush(stdout);
            continue;
        }
        wchar_t *paths[64];
        wchar_t bufs[64][MAX_PATH];
        int got = 0;
        for (; got < n; got++) {
            char u8[MAX_PATH * 2];
            if (!fgets(u8, sizeof(u8), stdin))
                break;
            size_t len = strlen(u8);
            while (len && (u8[len - 1] == '\n' || u8[len - 1] == '\r'))
                u8[--len] = 0;
            MultiByteToWideChar(CP_UTF8, 0, u8, -1, bufs[got], MAX_PATH);
            paths[got] = bufs[got];
        }
        int rc = 1;
        if (got == n) {
            __try {
                rc = show_menu_impl((HWND)(ULONG_PTR)hwnd, got, paths);
            } __except (EXCEPTION_EXECUTE_HANDLER) {
                rc = 1;
            }
        }
        fprintf(stdout, "R %d\n", rc);
        fflush(stdout);
    }
    return 0;
}

int wmain(int argc, wchar_t **argv) {
    // DPI 感知必须在任何 UI 之前：不声明则菜单被系统按 96 DPI 渲染再位图放大（字体发糊）
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
    int rc = 1;
    if (argc >= 2 && lstrcmpW(argv[1], L"--serve") == 0) {
        rc = serve();
    } else if (argc >= 5) {
        // 一次性模式（调试用）：x/y 参数忽略，位置取 GetCursorPos
        HWND hwnd = (HWND)(ULONG_PTR)_wcstoui64(argv[1], NULL, 10);
        __try {
            rc = show_menu_impl(hwnd, argc - 4, argv + 4);
        } __except (EXCEPTION_EXECUTE_HANDLER) {
            rc = 1;
        }
    }
    CoUninitialize();
    return rc;
}