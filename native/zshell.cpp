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
#include <stdarg.h>

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

// 菜单必须在【右键抬起之后】才弹：TPM_RECURSE 是右键【按下】就把 WM_CONTEXTMENU
// 转发过来，此时 TrackPopupMenu 会让菜单进入「按下跟踪」模式（KB 65256：这种菜单
// 只在按住期间显示，一松手就消失、并按菜单语义选中光标下那一项）——而菜单永远弹在
// 光标处，于是首项「打开」被直接执行（真实 bug：A 菜单开着右键 B，B 被打开）。
// 等物理右键松开再弹（wait_rbutton_up），新菜单就与「第一次右键」走完全相同的路径。
// 别再用全局 WH_MOUSE_LL 钩子去吞那次抬起：那是把局部时序问题升级成全系统输入故障
// 的路径（本项目已两次踩坑）。腾讯桌面整理的同类做法是【线程级】WH_GETMESSAGE +
// SetCapture（见 AGENTS.md），作用域不出本进程。
static void dbg_log(const char *fmt, ...);   // 定义在后文（ZSHELL_LOG 门控）

// 诊断日志：仅 ZSHELL_LOG 环境变量非 0 时落盘 %TEMP%\zshell_host.log，正常运行为零开销。
static void dbg_log(const char *fmt, ...) {
    static int enabled = -1;
    if (enabled < 0) {
        wchar_t v[8] = {0};
        DWORD n = GetEnvironmentVariableW(L"ZSHELL_LOG", v, 8);
        enabled = (n > 0 && v[0] != L'0') ? 1 : 0;
    }
    if (!enabled)
        return;
    FILE *lf = NULL;
    wchar_t tmp[MAX_PATH];
    GetTempPathW(MAX_PATH, tmp);
    wcscat_s(tmp, L"zshell_host.log");
    if (_wfopen_s(&lf, tmp, L"ab") == 0 && lf) {
        va_list ap;
        va_start(ap, fmt);
        vfprintf(lf, fmt, ap);
        va_end(ap);
        fclose(lf);
    }
}

// 输入钩子请属主窗（hhidden）把菜单关掉用的自定义消息
#define ZM_ENDMENU (WM_APP + 1)

static LRESULT CALLBACK MenuWndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case ZM_ENDMENU:
        // 键盘来了、或右键落在菜单自身上：菜单自己让位（EndMenu 必须在属主线程上调）
        EndMenu();
        return 0;
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

// AttachThreadInput 的作用域守卫：保证 attach 与 detach 成对——把本线程的输入队列
// 留在 attach 状态（比如中途提前 return）会让前台/焦点行为出各种怪事。
class ThreadInputAttach {
    DWORD a_, b_;
    bool on_;
public:
    ThreadInputAttach(DWORD a, DWORD b, bool on) : a_(a), b_(b), on_(on) {
        if (on_) AttachThreadInput(a_, b_, TRUE);
    }
    ~ThreadInputAttach() { if (on_) AttachThreadInput(a_, b_, FALSE); }
};

// 菜单在屏期间的输入钩子（键盘 + 落在【菜单自身】上的右键），**线程级**。
// ① 键盘：菜单必须占前台（见 show_menu_once 前台锁的说明），于是用户这时敲的键会进
//    菜单被当成助记符、**直接执行菜单项**（2026-10 实测：菜单在屏时注入 'O' → 菜单返回
//    cmd=163 打开了目录）。所以菜单在屏时键盘消息一律吃掉，并让菜单自己关掉——键盘绝
//    不执行菜单项，用户下一次按键起就回到自己的窗口（代价：触发关闭的那个键会丢）。
// ② 落在【我们自己菜单矩形内】的右键：TPM_RECURSE **只转发菜单外**的右键，落在菜单内的
//    会被菜单自己吞掉——既不关菜单、也不产生新请求。而菜单弹在第一次右键处、向右下展开，
//    用户连点列表时后几次点击正好落在菜单里 ⇒ 第一个菜单卡住不消失、后面的请求全堵在
//    管道里排队，等它终于被关掉才一个个顶上来（2026-10 用户实测原话）。所以这里主动接手：
//    按下 → 吃掉 + 请属主窗 EndMenu 关掉它；补发 WM_CONTEXTMENU（重定向）由
//    show_menu_once 在 TPM 之后做——钩子里等不到那次抬起（EndMenu 让 TPM 立刻返回、
//    钩子随之卸掉，而松手在那之后），实测会丢。这也就是资源管理器/桌面整理的
//    「右键连击重定向」。
// ⚠️ 必须【线程级】：SetWindowsHookExW(WH_GETMESSAGE, proc, NULL, GetCurrentThreadId())
// ——hMod 传 NULL、线程号是本线程，只有本线程消息泵（TPM 的模态循环）取到的消息才进来，
// 看不到也影响不到别的进程，与那套会冻全系统的全局 WH_MOUSE_LL 完全不是一回事。
// 回调里查的窗口（EnumThreadWindows 自己线程 / GetWindowRect 自己的窗口）都是本进程内
// 的本地调用，不是当初 LL 钩子里那种跨线程窗口查询。
// WH_GETMESSAGE 丢消息的正规做法是**改 MSG**（不是返回非零，那样别的钩子收不到通知）。
static HHOOK g_in_hook = NULL;
static HWND g_menu_owner = NULL;    // 本次 TPM 的属主窗（请它 EndMenu）
static bool g_retarget = false;     // 本次右键落在菜单内：抬起时要补发

// 找【我们自己线程】正在显示的菜单窗（#32768）
static HWND find_own_menu() {
    struct Ctx { HWND hit; };
    Ctx ctx = { NULL };
    EnumThreadWindows(GetCurrentThreadId(), [](HWND h, LPARAM lp) -> BOOL {
        wchar_t cls[16];
        if (GetClassNameW(h, cls, 16) && lstrcmpW(cls, L"#32768") == 0 &&
            IsWindowVisible(h)) {
            ((Ctx*)lp)->hit = h;
            return FALSE;
        }
        return TRUE;
    }, (LPARAM)&ctx);
    return ctx.hit;
}

static bool cursor_in_own_menu() {
    HWND m = find_own_menu();
    RECT rc;
    POINT pt;
    return m && GetWindowRect(m, &rc) && GetCursorPos(&pt) && PtInRect(&rc, pt);
}

static LRESULT CALLBACK MenuInputProc(int code, WPARAM wp, LPARAM lp) {
    if (code == HC_ACTION && wp == PM_REMOVE) {
        MSG *m = (MSG*)lp;
        switch (m->message) {
        case WM_KEYDOWN:  case WM_KEYUP:
        case WM_SYSKEYDOWN: case WM_SYSKEYUP:
        case WM_CHAR:     case WM_SYSCHAR:
            m->message = WM_NULL;       // 见 ①
            if (g_menu_owner)
                PostMessageW(g_menu_owner, ZM_ENDMENU, 0, 0);
            break;
        case WM_RBUTTONDOWN:
            if (cursor_in_own_menu()) {  // 见 ②
                g_retarget = true;
                m->message = WM_NULL;
                if (g_menu_owner)
                    PostMessageW(g_menu_owner, ZM_ENDMENU, 0, 0);
            } else {
                g_retarget = false;      // 菜单外：交给 TPM_RECURSE，别留上次的残flag
            }
            break;
        }
    }
    return CallNextHookEx(g_in_hook, code, wp, lp);
}

// KB 65256 的官方 workaround：清掉本线程键盘状态里的按钮位，让菜单按「抬起触发」
// 跟踪——清掉之后菜单不再看按下状态，所以按住期间/按下瞬间创建都不会变成
// 「按下跟踪」。这是唯一能【确定性】关掉那类竞态的开关（单靠等待总有残余窗口：
// 按下可能落在等待返回之后、TPM 内部建菜单之前）。Win11 是否仍读这份线程键盘
// 状态未实测，所以 wait_rbutton_up 那两处时序防御照样留着，两条腿走路。
static void clear_button_keystate() {
    BYTE ks[256];
    if (!GetKeyboardState(ks))
        return;
    ks[VK_RBUTTON] = 0;
    ks[VK_LBUTTON] = 0;
    SetKeyboardState(ks);
}

// 等物理右键松开（上限 cap_ms）：让 TrackPopupMenu 永远在「抬起之后」被调用，从而
// 进入 KB 65256 的「抬起跟踪」模式（松手后菜单继续显示），从根上避免新菜单被那一次
// 还没松的抬起选中首项。普通右键在这里是零开销——键早已松开，一次查询即返回。
// 必须用 GetAsyncKeyState（win32k 异步查询，不需要消息泵）；不能用 GetKeyState，
// 那是本线程消息队列里的状态，而本线程此刻阻塞在 fgets 上根本没在处理消息。
// 等待期间不泵消息：上一份菜单已被 TPM_RECURSE 关掉、hhidden 也在上一轮销毁了，
// 本线程没有任何窗口，泵消息只会重蹈 TPM 前「排干队列」要解决的那个坑。
// 返回等待毫秒数；out_timeout 报告是否撞到上限（撞到就带着按下状态照常弹菜单）。
static DWORD wait_rbutton_up(DWORD cap_ms, bool *out_timeout) {
    *out_timeout = false;
    if (!(GetAsyncKeyState(VK_RBUTTON) & 0x8000))
        return 0;
    DWORD t0 = GetTickCount();
    while (GetAsyncKeyState(VK_RBUTTON) & 0x8000) {
        DWORD waited = GetTickCount() - t0;
        if (waited >= cap_ms) {
            *out_timeout = true;
            return waited;
        }
        Sleep(10);
    }
    return GetTickCount() - t0;
}

static int show_menu_once(HWND hwnd, int pathc, wchar_t **pathv) {
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

    // —— 关键时序：等物理右键松开再弹菜单（原因见文件顶部注释；KB 65256）——
    // 放在建隐藏窗之前：等待期间本线程连一个窗口都没有，不泵消息也不会有消息积压。
    bool wait_to = false;
    DWORD waited = wait_rbutton_up(1200, &wait_to);
    if (waited)
        dbg_log("  wait_rbutton_up=%lums timeout=%d\n", waited, wait_to ? 1 : 0);

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

    // 前台锁：【必须抢】。菜单要能被「点别处」关掉/切换，靠的是它持有鼠标捕获，
    // 而捕获只对前台线程生效——实测（%TEMP%\repro_menu_click.py 的 outside 模式）
    // 不抢前台时，点在菜单外的鼠标事件直接进了别的应用，菜单收不到、关不掉，
    // 只能靠选中某一项才能消失。所以这里仍然 AttachThreadInput + SetForegroundWindow。
    // 代价是菜单在屏期间用户应用的**键盘输入被我们接管**——单独由下面的线程级
    // 键盘钩子（MenuKeyProc）抵消：菜单在屏时键盘一律吃掉并让菜单自行关闭，绝不让
    // 它变成菜单助记符去执行菜单项（2026-10 事故，见 AGENTS.md ⑨-b）。
    HWND hFore = GetForegroundWindow();
    DWORD foreTid = hFore ? GetWindowThreadProcessId(hFore, NULL) : 0;
    DWORD myTid = GetCurrentThreadId();
    bool can_attach = foreTid && foreTid != myTid && !IsHungAppWindow(hFore);
    {
        ThreadInputAttach att(myTid, foreTid, can_attach);
        SetForegroundWindow(hhidden);
        SetActiveWindow(hhidden);
    }

    // 菜单位置取当前光标物理坐标（Qt 传过来的是逻辑像素，125% 缩放下会偏移）；
    // TPM_RECURSE：菜单开着时在别处再点右键，系统先关旧菜单再把 WM_CONTEXTMENU
    // 转发给落点窗口——对齐资源管理器的「右键连击」体验，不给就只有关菜单的效果。
    POINT pt;
    GetCursorPos(&pt);
    // 排干线程队列里积压的鼠标/上下文菜单消息：serve 循环平时阻塞在 fgets
    // 不泵消息，上一次菜单经 TPM_RECURSE 转发给属主窗的右键消息一直积压在
    // 队列里，下次 TPM 的消息循环一上来就捞到它，按 TPM_RECURSE 语义立刻
    // 取消自己（实测 0ms 闪现取消的根因：Win+D 回桌面/切过程序后首次右键）。
    {
        MSG dm;
        while (PeekMessageW(&dm, NULL, WM_MOUSEFIRST, WM_MOUSELAST, PM_REMOVE)) {}
        while (PeekMessageW(&dm, NULL, WM_CONTEXTMENU, WM_CONTEXTMENU, PM_REMOVE)) {}
    }
    // 最后一次按键状态确认——必须在【紧挨着 TPM】的位置，别往前挪：
    // 上面那串动作（建隐藏窗 / AttachThreadInput / SetForegroundWindow / 取坐标 /
    // 排干队列）本身要花十几到几十毫秒，用户完全可能在期间又按下去（连点时必中），
    // 而那正是 KB 65256 的按下跟踪模式：菜单在按住状态下被创建 → 松手即选中首项。
    // 第一处 wait 只是「等这次点击松开」（改善观感），真正堵住竞态的是这两行：
    // 等一次 + 清键盘状态。清状态让它**确定性**成立，等待让菜单出现在松手之后。
    DWORD recheck = wait_rbutton_up(1200, &wait_to);
    clear_button_keystate();
    if (recheck)
        dbg_log("  pre-tpm recheck waited=%lums timeout=%d\n", recheck, wait_to ? 1 : 0);
    DWORD t0 = GetTickCount();
    g_menu_owner = hhidden;
    g_retarget = false;
    g_in_hook = SetWindowsHookExW(WH_GETMESSAGE, MenuInputProc, NULL, GetCurrentThreadId());
    UINT cmd = (UINT)TrackPopupMenu(hmenu, TPM_RETURNCMD | TPM_RECURSE, pt.x, pt.y, 0, hhidden, NULL);
    if (g_in_hook) {
        UnhookWindowsHookEx(g_in_hook);
        g_in_hook = NULL;
    }
    g_menu_owner = NULL;
    bool retarget_hit = g_retarget;   // 先取走标志再清（本线程独占，无并发问题）
    g_retarget = false;

    // 右键落在【菜单自身】上（上面的钩子已把它吃掉并关掉了菜单）：在这里补发一次
    // WM_CONTEXTMENU 给调用方（格子列表），让面板为**光标下那一项**重新弹菜单。
    // 必须在这里、不能在钩子里：EndMenu 让 TPM 立刻返回、钩子随之卸掉，而用户松手在
    // 那之后，且本线程随即阻塞回 fgets 不再取消息——钩子里永远等不到那次抬起（实测丢）。
    // 这一步就是「右键连击重定向」：连点列表时每次点击都关旧弹新，不会再有菜单卡住、
    // 后面请求排队的现象。
    if (retarget_hit) {
        bool to = false;
        wait_rbutton_up(500, &to);          // 等这次右键松手，新菜单才不会被按下状态带偏
        POINT rpt;
        if (hwnd && GetCursorPos(&rpt)) {
            PostMessageW(hwnd, WM_CONTEXTMENU, (WPARAM)hwnd,
                         (LPARAM)MAKELONG(rpt.x, rpt.y));
            dbg_log("  retarget -> WM_CONTEXTMENU caller=%p pt=(%ld,%ld)\n",
                    (void*)hwnd, rpt.x, rpt.y);
        }
    }
    DWORD elapsed = GetTickCount() - t0;
    dbg_log("  tpm cmd=%u elapsed=%lums hFore=%p hhidden=%p btnR=%d\n",
            cmd, elapsed, (void*)hFore, (void*)hhidden,
            (GetAsyncKeyState(VK_RBUTTON) & 0x8000) ? 1 : 0);

    // 先销毁隐藏窗、再把前台还给原窗口：hhidden 只是弹菜单期间的属主，此刻已无用；
    // 而它是个 0×0 不可见窗、其线程接下来只阻塞在 fgets 上不再泵消息——这种窗口若
    // 留在前台，系统对着一个「不响应」的前台窗口做激活，用户点别的窗口会被一次次
    // 失败的激活吃掉（症状：移动/悬停正常、点击全失灵，2026-10 真实事故）。销毁它
    // 会把前台置空，紧接着的恢复就是把前台交回正确的地方。
    // 顺序铁律：**先恢复前台、再销毁隐藏窗**。反过来（先销毁）会让本进程在恢复那一刻
    // 已经不是前台进程，SetForegroundWindow 的资格随之失去，恢复必然失败 → 前台变 NULL
    // → 下一个菜单拿不到鼠标捕获（没有可 attach 的前台线程）→ 点菜单外关不掉、菜单卡住、
    // 后续请求排队再一个个顶上来（2026-10 实测事故，就是这么被我自己的"加固"引入的）。
    bool restored = false;
    if (hFore && IsWindow(hFore)) {
        foreTid = GetWindowThreadProcessId(hFore, NULL);
        bool re_attach = foreTid && foreTid != myTid && !IsHungAppWindow(hFore);
        ThreadInputAttach att(myTid, foreTid, re_attach);
        restored = SetForegroundWindow(hFore) != FALSE;
        if (!restored) {
            wchar_t cn[64] = L"?";
            GetClassNameW(hFore, cn, 64);
            dbg_log("  restore fg to %p (class=%ls tid=%lu attach=%d) failed\n",
                    (void*)hFore, cn, foreTid, re_attach ? 1 : 0);
        }
    }
    DestroyWindow(hhidden);
    if (!restored) {
        // 兜底：前台若停成 NULL，下一个菜单就再也拿不到捕获（上面那条链）。注意
        // **shell/桌面窗口（GetShellWindow）是置不上前台的**（实测失败），要找的是
        // 一个普通可激活窗口——用任务栏 Shell_TrayWnd（explorer 的普通窗口，能激活，
        // 且下一个菜单能 attach 上 explorer 的线程重新拿到捕获）。
        HWND hFallback = FindWindowW(L"Shell_TrayWnd", NULL);
        if (hFallback) {
            DWORD ft = GetWindowThreadProcessId(hFallback, NULL);
            bool fa = ft && ft != myTid && !IsHungAppWindow(hFallback);
            ThreadInputAttach att(myTid, ft, fa);
            dbg_log("  fallback fg -> tray=%p ok=%d\n",
                    (void*)hFallback, SetForegroundWindow(hFallback) ? 1 : 0);
        }
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

    DestroyMenu(hmenu);   // hhidden 已在恢复前台之前销毁（见上）
    if (g_pcm3) { g_pcm3->Release(); g_pcm3 = NULL; }
    if (g_pcm2) { g_pcm2->Release(); g_pcm2 = NULL; }
    pcm->Release();
    return rc;
}

// 弹一次菜单的入口（serve 循环与一次性模式共用）。
// 这里原本还有一条「闪现取消（cmd==0 且 <60ms）就 Sleep(150) 重弹一次」的兜底，现已
// 删除：它的主因（上一次菜单经 TPM_RECURSE 转发、积压在属主窗队列里的右键消息）已由
// TPM 前的排干解决；而给它换守卫时发现两条候选都不成立——「右键是否按下」是空守卫
//（等待已保证弹菜单时键是抬起的），「管道里还有没有新请求」也不可靠（serve 用 fgets，
// CRT 预读整块，已被缓冲的请求在管道句柄上查不到）。留一个不生效的守卫比没有更糟：
// 用户主动连击时会把过期菜单再闪一次。将来「Win+D 后首次右键不弹」若重现，去修排干
// 那一步，不要加盲重试。
static int show_menu_impl(HWND hwnd, int pathc, wchar_t **pathv) {
    return show_menu_once(hwnd, pathc, pathv);
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
        {
            SYSTEMTIME st;
            GetLocalTime(&st);
            dbg_log("%02d:%02d:%02d.%03d req hwnd=%lld n=%d rc=%d\n",
                    st.wHour, st.wMinute, st.wSecond, st.wMilliseconds,
                    hwnd, got, rc);
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