// 全能视像解析终端 — WebUI 模式 (C++ Win32 原生,无依赖)
// 启动引擎并自动打开浏览器;窗体常驻,可停止服务
// 编译: g++ -municode -O2 -mwindows -o 全能视像解析终端_WebUI模式.exe WebUiMode.cpp -lwininet -lgdi32 -luser32 -lshell32
#include <windows.h>
#include <wininet.h>
#include <shellapi.h>
#include <string>

#pragma comment(lib, "wininet.lib")
#pragma comment(lib, "gdi32.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "shell32.lib")

static std::wstring W(const char* utf8) {
    if (!utf8) return L"";
    int n = MultiByteToWideChar(CP_UTF8, 0, utf8, -1, NULL, 0);
    if (n <= 1) return L"";
    std::wstring ws(n - 1, 0);
    MultiByteToWideChar(CP_UTF8, 0, utf8, -1, &ws[0], n);
    return ws;
}

static std::string ReadFileUtf8(const wchar_t* path) {
    std::string out;
    HANDLE h = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) return out;
    DWORD sz = GetFileSize(h, NULL);
    if (sz > 0 && sz < 8 * 1024 * 1024) {
        out.resize(sz);
        DWORD rd = 0;
        ReadFile(h, &out[0], sz, &rd, NULL);
        out.resize(rd);
    }
    CloseHandle(h);
    return out;
}

static int CfgIntFile(const wchar_t* path, const char* key, int def) {
    std::string s = ReadFileUtf8(path);
    std::string k = "\"";
    k += key; k += "\"";
    size_t p = s.find(k);
    if (p == std::string::npos) return def;
    p += k.size();
    while (p < s.size() && (s[p] == ' ' || s[p] == ':' || s[p] == '\t')) p++;
    if (p < s.size() && s[p] == '"') {
        p++; std::string v;
        while (p < s.size() && s[p] != '"') v += s[p++];
        return v.empty() ? def : atoi(v.c_str());
    }
    return def;
}

// ---------- 服务检测 (Winsock TCP,拒绝连接立即返回,不阻塞 UI) ----------
static bool PortAlive(int port) {
    static bool wsaReady = false;
    if (!wsaReady) {
        WSADATA wsa;
        if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) return false;
        wsaReady = true;
    }
    SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == INVALID_SOCKET) return false;
    u_long nb = 1;
    ioctlsocket(s, FIONBIO, &nb);
    sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((u_short)port);
    addr.sin_addr.S_un.S_addr = inet_addr("127.0.0.1");
    bool alive = false;
    if (connect(s, (sockaddr*)&addr, sizeof(addr)) == 0) {
        alive = true;
    } else {
        fd_set wf;
        FD_ZERO(&wf);
        FD_SET(s, &wf);
        timeval tv;
        tv.tv_sec = 0;
        tv.tv_usec = 300000;
        if (select(0, NULL, &wf, NULL, &tv) > 0) {
            int err = 0, len = sizeof(err);
            getsockopt(s, SOL_SOCKET, SO_ERROR, (char*)&err, &len);
            alive = (err == 0);
        }
    }
    closesocket(s);
    return alive;
}

static int FindRunningPort() {
    for (int p = 7860; p <= 7880; p++)
        if (PortAlive(p)) return p;
    return -1;
}

static bool WaitPortClosed(int port, int timeoutMs) {
    DWORD start = GetTickCount();
    for (;;) {
        if (!PortAlive(port)) return true;
        if (GetTickCount() - start > (DWORD)timeoutMs) return !PortAlive(port);
        Sleep(200);
    }
}

static void KillEngineByPid(DWORD pid) {
    wchar_t cmd[64];
    wsprintfW(cmd, L"taskkill.exe /F /T /PID %lu", pid);
    STARTUPINFOW si = { 0 }; si.cb = sizeof(si);
    PROCESS_INFORMATION pi = { 0 };
    if (CreateProcessW(NULL, cmd, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi)) {
        CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    }
}

static void KillEngineByName() {
    STARTUPINFOW si = { 0 }; si.cb = sizeof(si);
    PROCESS_INFORMATION pi = { 0 };
    wchar_t cmd[] = L"taskkill.exe /F /T /IM PhantomCore.exe";
    if (CreateProcessW(NULL, cmd, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi)) {
        CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    }
}

static bool LaunchUrl(const wchar_t* url) {
    return (intptr_t)ShellExecuteW(NULL, L"open", url, NULL, NULL, SW_SHOWNORMAL) > 32;
}

static bool StartEngineProc(const wchar_t* exe, const wchar_t* workdir, const wchar_t* args, DWORD* outPid) {
    wchar_t cmdline[512];
    wsprintfW(cmdline, L"\"%s\" %s", exe, args);
    STARTUPINFOW si = { 0 }; si.cb = sizeof(si);
    PROCESS_INFORMATION pi = { 0 };
    BOOL ok = CreateProcessW(exe, cmdline, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, workdir, &si, &pi);
    if (!ok) return false;
    if (outPid) *outPid = pi.dwProcessId;
    CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    return true;
}

static const wchar_t* EXE_NAME = L"全能视像解析终端";

class WebUiWnd {
public:
    HWND hwnd;
    std::wstring engineDir, engineExe;
    int status = 0;          // 0=启动中 1=运行中 2=停止 3=失败
    int curPort = 7860;
    DWORD pid = 0;
    bool closing = false;
    bool stopping = false;
    bool browserOpened = false;

    void Paint(HDC hdc) {
        RECT rc; GetClientRect(hwnd, &rc);
        HBRUSH bg = CreateSolidBrush(RGB(22, 25, 30));
        FillRect(hdc, &rc, bg);
        DeleteObject(bg);

        HFONT fSt = CreateFontW(-22, 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET,
            0, 0, CLEARTYPE_QUALITY, 0, L"Microsoft YaHei");
        HFONT fHint = CreateFontW(-14, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET,
            0, 0, CLEARTYPE_QUALITY, 0, L"Microsoft YaHei");
        HFONT fBtn = CreateFontW(-15, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET,
            0, 0, CLEARTYPE_QUALITY, 0, L"Microsoft YaHei");

        SetBkMode(hdc, TRANSPARENT);

        // 状态
        if (status == 1) SetTextColor(hdc, RGB(7, 193, 96));
        else if (status == 0) SetTextColor(hdc, RGB(250, 173, 20));
        else SetTextColor(hdc, RGB(125, 130, 140));
        HFONT old = (HFONT)SelectObject(hdc, fSt);
        std::wstring st;
        if (status == 0) st = L"正在启动引擎(约 1-3 秒)...";
        else if (status == 1) { wchar_t b[64]; wsprintfW(b, L"服务运行中 · 端口 %d", curPort); st = b; }
        else if (status == 2) st = L"服务未启动";
        else st = L"启动失败";
        RECT tr{ 0, 34, 440, 68 };
        DrawTextW(hdc, st.c_str(), -1, &tr, DT_CENTER | DT_SINGLELINE | DT_VCENTER);

        // 提示
        SelectObject(hdc, fHint);
        SetTextColor(hdc, RGB(125, 130, 140));
        RECT hr{ 20, 72, 420, 108 };
        DrawTextW(hdc, L"关闭本窗口时请选择是否停止服务;\n若选择保持运行,可随时再次打开本程序访问。", -1, &hr,
            DT_CENTER | DT_WORDBREAK);

        // 按钮
        DrawBtn(hdc, 70, 118, 130, RGB(7, 193, 96), RGB(6, 160, 80), L"浏览器打开", fBtn);
        DrawBtn(hdc, 216, 118, 154, RGB(180, 60, 60), RGB(150, 45, 45), L"停止服务并退出", fBtn);

        SelectObject(hdc, old);
        DeleteObject(fSt); DeleteObject(fHint); DeleteObject(fBtn);
    }

    void DrawBtn(HDC hdc, int x, int y, int w, COLORREF base, COLORREF hoverc,
        const wchar_t* text, HFONT f) {
        POINT pt;
        GetCursorPos(&pt);
        ScreenToClient(hwnd, &pt);
        bool hov = pt.x >= x && pt.x < x + w && pt.y >= y && pt.y < y + 34;
        HBRUSH br = CreateSolidBrush(hov ? hoverc : base);
        RECT r{ x, y, x + w, y + 34 };
        FillRect(hdc, &r, br);
        DeleteObject(br);
        HFONT old = (HFONT)SelectObject(hdc, f);
        SetTextColor(hdc, RGB(255, 255, 255));
        DrawTextW(hdc, text, -1, &r, DT_CENTER | DT_SINGLELINE | DT_VCENTER);
        SelectObject(hdc, old);
    }

    int HitBtn(int mx, int my) {
        if (mx >= 70 && mx < 200 && my >= 118 && my < 152) return 0;   // 浏览器
        if (mx >= 216 && mx < 370 && my >= 118 && my < 152) return 1;   // 停止
        return -1;
    }

    void OpenBrowser() {
        wchar_t url[64];
        wsprintfW(url, L"http://127.0.0.1:%d/", curPort);
        LaunchUrl(url);
    }

    void StartEngine() {
        int port = 7860;
        wchar_t cfgPath[MAX_PATH];
        wsprintfW(cfgPath, L"%s\\upscale_config.json", engineDir.c_str());
        if (GetFileAttributesW(cfgPath) == INVALID_FILE_ATTRIBUTES)
            wsprintfW(cfgPath, L"%s\\PhantomCore\\upscale_config.json", engineDir.c_str());
        int cport = CfgIntFile(cfgPath, "webui_port", 7860);
        if (cport >= 1024 && cport <= 65535) port = cport;
        curPort = port;
        wchar_t args[64];
        wsprintfW(args, L"--no-browser --port %d", port);
        if (!StartEngineProc(engineExe.c_str(), engineDir.c_str(), args, &pid)) {
            status = 3;
            InvalidateRect(hwnd, NULL, TRUE);
            MessageBoxW(hwnd, L"引擎启动失败,请确认目录文件完整。", EXE_NAME, MB_OK);
            return;
        }
        SetTimer(hwnd, 1, 500, NULL);
    }

    void StopService() {
        if (pid) KillEngineByPid(pid);
        else KillEngineByName();
        WaitPortClosed(curPort, 8000);
        pid = 0;
        status = 2;
        KillTimer(hwnd, 1);
        InvalidateRect(hwnd, NULL, TRUE);
    }

    void AskStopAndClose() {
        int r = MessageBoxW(hwnd,
            L"服务仍在运行,退出前是否停止?\n\n是:停止服务并退出\n否:服务保持后台运行,仅关闭窗口\n取消:留在程序",
            EXE_NAME, MB_YESNOCANCEL | MB_ICONQUESTION);
        if (r == IDCANCEL) return;
        if (r == IDYES) {
            stopping = true;
            if (pid) KillEngineByPid(pid);
            else KillEngineByName();
            WaitPortClosed(curPort, 8000);
            pid = 0;
        }
        closing = true;
        DestroyWindow(hwnd);
    }
};

static WebUiWnd g;

static LRESULT CALLBACK WndProc(HWND hw, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_CREATE: {
        g.hwnd = hw;
        wchar_t buf[MAX_PATH];
        GetModuleFileNameW(NULL, buf, MAX_PATH);
        std::wstring exe(buf);
        size_t pos = exe.find_last_of(L"\\/");
        g.engineDir = (pos == std::wstring::npos) ? L"." : exe.substr(0, pos);
        std::wstring c1 = g.engineDir + L"\\PhantomCore\\PhantomCore.exe";
        std::wstring c2 = g.engineDir + L"\\PhantomCore.exe";
        if (GetFileAttributesW(c1.c_str()) != INVALID_FILE_ATTRIBUTES) g.engineExe = c1;
        else if (GetFileAttributesW(c2.c_str()) != INVALID_FILE_ATTRIBUTES) g.engineExe = c2;
        if (g.engineExe.empty()) {
            MessageBoxW(hw, L"未找到 PhantomCore 引擎,请保持目录文件完整。", EXE_NAME, MB_OK);
            PostMessageW(hw, WM_CLOSE, 0, 0);
            return 0;
        }
        PostMessageW(hw, WM_APP + 1, 0, 0);
        return 0;
    }
    case WM_APP + 1: {
        int running = FindRunningPort();
        if (running > 0) {
            g.curPort = running;
            g.status = 1;
            g.OpenBrowser();
        } else {
            g.status = 0;
            g.StartEngine();
        }
        InvalidateRect(hw, NULL, TRUE);
        return 0;
    }
    case WM_TIMER: {
        if (g.status == 1) return 0;
        if (PortAlive(g.curPort)) {
            g.status = 1;
            KillTimer(hw, 1);
            InvalidateRect(hw, NULL, TRUE);
            if (!g.browserOpened) { g.browserOpened = true; g.OpenBrowser(); }
        }
        return 0;
    }
    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC hdc = BeginPaint(hw, &ps);
        g.Paint(hdc);
        EndPaint(hw, &ps);
        return 0;
    }
    case WM_ERASEBKGND:
        return 1;
    case WM_MOUSEMOVE: {
        RECT rc; GetClientRect(hw, &rc);
        InvalidateRect(hw, NULL, FALSE);
        (void)rc;
        return 0;
    }
    case WM_LBUTTONDOWN: {
        int x = (short)LOWORD(lp), y = (short)HIWORD(lp);
        int b = g.HitBtn(x, y);
        if (b == 0) g.OpenBrowser();
        else if (b == 1) g.AskStopAndClose();
        return 0;
    }
    case WM_CLOSE: {
        bool alive = PortAlive(g.curPort);
        if (!g.closing && (alive || g.pid)) g.AskStopAndClose();
        else { g.closing = true; DestroyWindow(hw); }
        return 0;
    }
    case WM_DESTROY:
        KillTimer(hw, 1);
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hw, msg, wp, lp);
}

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE, LPWSTR, int nShow) {
    {
        int argc = 0;
        LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
        for (int i = 0; i < argc; i++)
            if (wcscmp(argv[i], L"--selftest") == 0) {
                wchar_t buf[MAX_PATH];
                GetModuleFileNameW(NULL, buf, MAX_PATH);
                std::wstring p(buf);
                size_t pos = p.find_last_of(L"\\/");
                std::wstring dir = (pos == std::wstring::npos) ? L"." : p.substr(0, pos);
                std::wstring mark = dir + L"\\selftest_webui.ok";
                HANDLE h = CreateFileW(mark.c_str(), GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, 0, NULL);
                if (h != INVALID_HANDLE_VALUE) { WriteFile(h, "ok", 2, NULL, NULL); CloseHandle(h); }
                return 0;
            }
        LocalFree(argv);
    }

    WNDCLASSW wc = { 0 };
    wc.lpfnWndProc = WndProc;
    wc.hInstance = hInst;
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.lpszClassName = L"VisionTerminalWebUi";
    RegisterClassW(&wc);

    HWND hw = CreateWindowExW(0, L"VisionTerminalWebUi", L"全能视像解析终端 - WebUI 模式",
        WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
        CW_USEDEFAULT, CW_USEDEFAULT, 440, 210, NULL, NULL, hInst, NULL);
    if (!hw) return 1;
    RECT rc; GetWindowRect(hw, &rc);
    int sw = GetSystemMetrics(SM_CXSCREEN), sh = GetSystemMetrics(SM_CYSCREEN);
    SetWindowPos(hw, NULL, (sw - (rc.right - rc.left)) / 2, (sh - (rc.bottom - rc.top)) / 2,
        0, 0, SWP_NOSIZE | SWP_NOZORDER);
    ShowWindow(hw, nShow);

    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    return (int)msg.wParam;
}
