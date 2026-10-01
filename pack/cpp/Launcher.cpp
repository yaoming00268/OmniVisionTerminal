// 全能视像解析终端 — 启动器 (C++ Win32 原生,无依赖)
// 编译: g++ -municode -O2 -mwindows -o 全能视像解析终端.exe Launcher.cpp -lwininet -lgdi32 -luser32 -lshell32
#include <windows.h>
#include <wininet.h>
#include <shellapi.h>
#include <string>
#include <vector>

#pragma comment(lib, "wininet.lib")
#pragma comment(lib, "gdi32.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "shell32.lib")

// ---------- UTF-8 工具 ----------
static std::wstring W(const char* utf8) {
    if (!utf8) return L"";
    int n = MultiByteToWideChar(CP_UTF8, 0, utf8, -1, NULL, 0);
    if (n <= 1) return L"";
    std::wstring ws(n - 1, 0);
    MultiByteToWideChar(CP_UTF8, 0, utf8, -1, &ws[0], n);
    return ws;
}

// ---------- 配置读取 ----------
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

static std::string FindConfigDir() {
    wchar_t buf[MAX_PATH];
    GetModuleFileNameW(NULL, buf, MAX_PATH);
    std::wstring exe(buf);
    size_t pos = exe.find_last_of(L"\\/");
    std::wstring dir = (pos == std::wstring::npos) ? L"." : exe.substr(0, pos);
    std::wstring cfg = dir + L"\\upscale_config.json";
    if (GetFileAttributesW(cfg.c_str()) != INVALID_FILE_ATTRIBUTES) {
        std::string s = ReadFileUtf8(cfg.c_str());
        if (!s.empty()) { std::wstring w = W(s.c_str()); return std::string(w.begin(), w.end()); }
    }
    std::wstring cfg2 = dir + L"\\PhantomCore\\upscale_config.json";
    std::string s2 = ReadFileUtf8(cfg2.c_str());
    std::wstring w2 = W(s2.c_str());
    return std::string(w2.begin(), w2.end());
}

// 从配置 JSON 提取字符串值(简单匹配,配置格式固定)
static std::string CfgValue(const std::string& cfg, const char* key) {
    std::string k = "\"";
    k += key;
    k += "\"";
    size_t p = cfg.find(k);
    if (p == std::string::npos) return "";
    p += k.size();
    while (p < cfg.size() && (cfg[p] == ' ' || cfg[p] == ':' || cfg[p] == '\t')) p++;
    if (p < cfg.size() && cfg[p] == '"') {
        p++;
        std::string v;
        while (p < cfg.size() && cfg[p] != '"') { v += cfg[p]; p++; }
        return v;
    }
    return "";
}

static int CfgInt(const std::string& cfg, const char* key, int def) {
    std::string v = CfgValue(cfg, key);
    if (v.empty()) return def;
    return atoi(v.c_str());
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

// ---------- 进程启动 ----------
static bool LaunchExe(const wchar_t* path, const wchar_t* args, const wchar_t* workdir) {
    SHELLEXECUTEINFOW sei = { 0 };
    sei.cbSize = sizeof(sei);
    sei.fMask = SEE_MASK_NOASYNC;
    sei.lpFile = path;
    sei.lpParameters = args;
    sei.lpDirectory = workdir;
    sei.nShow = SW_SHOWNORMAL;
    return ShellExecuteExW(&sei) != FALSE;
}

// ---------- UI ----------
struct Rct { int x, y, w, h; };
static bool InRect(const Rct& r, int mx, int my) {
    return mx >= r.x && mx < r.x + r.w && my >= r.y && my < r.y + r.h;
}

static const wchar_t* EXE_NAME = L"全能视像解析终端";

class LauncherWnd {
public:
    HWND hwnd;
    int hover = -1;          // 悬停按钮索引
    int status = 0;          // 0=检测中 1=运行中 2=未启动 3=无引擎
    int runPort = 0;
    std::wstring engineDir;
    std::wstring engineExe;

    Rct webR{ 30, 92, 360, 60 };
    Rct deskR{ 30, 162, 360, 60 };
    Rct bgR{ 30, 232, 360, 60 };
    Rct exitR{ 30, 326, 360, 38 };

    void Paint(HDC hdc) {
        // 背景
        RECT rc; GetClientRect(hwnd, &rc);
        HBRUSH white = CreateSolidBrush(RGB(255, 255, 255));
        FillRect(hdc, &rc, white);
        DeleteObject(white);

        HFONT fTitle = CreateFontW(-24, 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET,
            0, 0, CLEARTYPE_QUALITY, 0, L"Microsoft YaHei");
        HFONT fSub = CreateFontW(-13, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET,
            0, 0, CLEARTYPE_QUALITY, 0, L"Microsoft YaHei");
        HFONT fBtn = CreateFontW(-17, 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET,
            0, 0, CLEARTYPE_QUALITY, 0, L"Microsoft YaHei");
        HFONT fBtnSub = CreateFontW(-12, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET,
            0, 0, CLEARTYPE_QUALITY, 0, L"Microsoft YaHei");

        SetBkMode(hdc, TRANSPARENT);

        // 标题
        SetTextColor(hdc, RGB(31, 41, 55));
        HFONT old = (HFONT)SelectObject(hdc, fTitle);
        RECT tr{ 10, 22, 410, 54 };
        DrawTextW(hdc, L"全能视像解析终端", -1, &tr, DT_CENTER | DT_SINGLELINE | DT_VCENTER);

        // 状态
        SelectObject(hdc, fSub);
        if (status == 1) SetTextColor(hdc, RGB(7, 193, 96));
        else if (status == 0) SetTextColor(hdc, RGB(107, 114, 128));
        else if (status == 3) SetTextColor(hdc, RGB(220, 60, 60));
        else SetTextColor(hdc, RGB(107, 114, 128));
        std::wstring st;
        if (status == 0) st = L"正在检测服务状态...";
        else if (status == 1) { wchar_t b[64]; wsprintfW(b, L"● 服务运行中(端口 %d)", runPort); st = b; }
        else if (status == 3) st = L"未找到 PhantomCore 引擎,请保持目录文件完整";
        else st = L"○ 服务未启动";
        RECT sr{ 10, 58, 410, 80 };
        DrawTextW(hdc, st.c_str(), -1, &sr, DT_CENTER | DT_SINGLELINE | DT_VCENTER);

        // 三个卡片按钮
        DrawCard(hdc, webR, RGB(7, 193, 96), RGB(6, 173, 86), L"WebUI 模式", L"浏览器全功能操作界面", fBtn, fBtnSub, 0);
        DrawCard(hdc, deskR, RGB(59, 130, 246), RGB(37, 99, 235), L"桌面窗口模式", L"内嵌界面,无需打开浏览器", fBtn, fBtnSub, 1);
        DrawCard(hdc, bgR, RGB(107, 114, 128), RGB(75, 85, 99), L"仅后台服务", L"静默运行,不打开任何界面", fBtn, fBtnSub, 2);

        // 退出
        SelectObject(hdc, fBtnSub);
        SetTextColor(hdc, RGB(107, 114, 128));
        HBRUSH eb = CreateSolidBrush(RGB(255, 255, 255));
        RECT er{ exitR.x, exitR.y, exitR.x + exitR.w, exitR.y + exitR.h };
        FillRect(hdc, &er, eb);
        DeleteObject(eb);
        HPEN ep = CreatePen(PS_SOLID, 1, RGB(229, 231, 235));
        HPEN eo = (HPEN)SelectObject(hdc, ep);
        Rectangle(hdc, er.left, er.top, er.right, er.bottom);
        SelectObject(hdc, eo); DeleteObject(ep);
        DrawTextW(hdc, L"退出", -1, &er, DT_CENTER | DT_SINGLELINE | DT_VCENTER);

        SelectObject(hdc, old);
        DeleteObject(fTitle); DeleteObject(fSub); DeleteObject(fBtn); DeleteObject(fBtnSub);
    }

    void DrawCard(HDC hdc, const Rct& r, COLORREF base, COLORREF hoverc,
        const wchar_t* title, const wchar_t* sub, HFONT fBtn, HFONT fBtnSub, int idx) {
        bool hov = (hover == idx);
        COLORREF col = hov ? hoverc : base;
        HBRUSH br = CreateSolidBrush(col);
        HRGN rgn = CreateRoundRectRgn(r.x, r.y, r.x + r.w, r.y + r.h, 14, 14);
        HGDIOBJ ob = SelectObject(hdc, br);
        // FillRgn 需要刷子已选入;直接 FillRgn
        FillRgn(hdc, rgn, br);
        SelectObject(hdc, ob);
        DeleteObject(rgn); DeleteObject(br);
        SetTextColor(hdc, RGB(255, 255, 255));
        HFONT old = (HFONT)SelectObject(hdc, fBtn);
        RECT t1{ r.x, r.y + 6, r.x + r.w, r.y + 34 };
        DrawTextW(hdc, title, -1, &t1, DT_CENTER | DT_SINGLELINE | DT_VCENTER);
        SelectObject(hdc, fBtnSub);
        SetTextColor(hdc, RGB(240, 244, 248));
        RECT t2{ r.x, r.y + 34, r.x + r.w, r.y + r.h - 4 };
        DrawTextW(hdc, sub, -1, &t2, DT_CENTER | DT_SINGLELINE | DT_VCENTER);
        SelectObject(hdc, old);
    }

    int HitTest(int mx, int my) {
        if (InRect(webR, mx, my)) return 0;
        if (InRect(deskR, mx, my)) return 1;
        if (InRect(bgR, mx, my)) return 2;
        if (InRect(exitR, mx, my)) return 3;
        return -1;
    }

    void Act(int idx) {
        if (idx < 0 || idx > 3) return;
        if (idx == 3) { PostMessageW(hwnd, WM_CLOSE, 0, 0); return; }
        if (engineExe.empty()) { MessageBoxW(hwnd, L"未找到 PhantomCore 引擎,请保持目录文件完整。", EXE_NAME, MB_OK); return; }
        wchar_t exePath[MAX_PATH];
        if (idx == 0) {
            wsprintfW(exePath, L"%s\\%s", engineDir.c_str(), L"全能视像解析终端_WebUI模式.exe");
        } else if (idx == 1) {
            wsprintfW(exePath, L"%s\\%s", engineDir.c_str(), L"全能视像解析终端_桌面控制台.exe");
        } else {
            // 仅后台服务:直接启动引擎
            int port = FindRunningPort();
            if (port > 0) { MessageBoxW(hwnd, L"服务已在运行中(端口 %d).", EXE_NAME, MB_OK); return; }
            wchar_t args[64];
            wsprintfW(args, L"--no-browser --port 7860");
            if (LaunchExe(engineExe.c_str(), args, engineDir.c_str())) {
                MessageBoxW(hwnd, L"后台服务正在启动(约 1-3 秒)。\n完成后可随时重新打开启动器选择界面。", EXE_NAME, MB_OK);
                PostMessageW(hwnd, WM_CLOSE, 0, 0);
            } else {
                MessageBoxW(hwnd, L"启动失败。", EXE_NAME, MB_OK);
            }
            return;
        }
        if (GetFileAttributesW(exePath) == INVALID_FILE_ATTRIBUTES) {
            wchar_t msg[256];
            wsprintfW(msg, L"未找到 %s\n请保持目录文件完整。", exePath);
            MessageBoxW(hwnd, msg, EXE_NAME, MB_OK);
            return;
        }
        if (LaunchExe(exePath, NULL, engineDir.c_str())) {
            PostMessageW(hwnd, WM_CLOSE, 0, 0);
        } else {
            MessageBoxW(hwnd, L"启动失败。", EXE_NAME, MB_OK);
        }
    }

    void AutoMode() {
        std::string cfg;
        wchar_t cfgPath[MAX_PATH];
        wsprintfW(cfgPath, L"%s\\upscale_config.json", engineDir.c_str());
        cfg = ReadFileUtf8(cfgPath);
        if (cfg.empty()) {
            wsprintfW(cfgPath, L"%s\\PhantomCore\\upscale_config.json", engineDir.c_str());
            cfg = ReadFileUtf8(cfgPath);
        }
        std::string mode = CfgValue(cfg, "launcher_default_mode");
        if (mode.empty()) mode = "ask";
        if (mode == "ask") return;
        if (mode == "console") Act(1);
        else if (mode == "webui") Act(0);
        else if (mode == "service") Act(2);
    }
};

static LauncherWnd g;

static LRESULT CALLBACK WndProc(HWND hw, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_CREATE: {
        g.hwnd = hw;
        // 定位引擎
        wchar_t buf[MAX_PATH];
        GetModuleFileNameW(NULL, buf, MAX_PATH);
        std::wstring exe(buf);
        size_t pos = exe.find_last_of(L"\\/");
        g.engineDir = (pos == std::wstring::npos) ? L"." : exe.substr(0, pos);
        std::wstring cand1 = g.engineDir + L"\\PhantomCore\\PhantomCore.exe";
        std::wstring cand2 = g.engineDir + L"\\PhantomCore.exe";
        if (GetFileAttributesW(cand1.c_str()) != INVALID_FILE_ATTRIBUTES) g.engineExe = cand1;
        else if (GetFileAttributesW(cand2.c_str()) != INVALID_FILE_ATTRIBUTES) g.engineExe = cand2;
        g.status = g.engineExe.empty() ? 3 : 0;
        // 自动模式(配置指定时直接进入对应模式)
        g.AutoMode();
        if (!g.engineExe.empty()) {
            SetTimer(hw, 1, 600, NULL);
        }
        return 0;
    }
    case WM_TIMER: {
        if (g.engineExe.empty()) return 0;
        int p = FindRunningPort();
        int newStatus = p > 0 ? 1 : 2;
        if (newStatus != g.status || p != g.runPort) {
            g.status = newStatus;
            g.runPort = p;
            InvalidateRect(hw, NULL, TRUE);
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
        int x = (short)LOWORD(lp), y = (short)HIWORD(lp);
        int h = g.HitTest(x, y);
        if (h != g.hover) { g.hover = h; InvalidateRect(hw, NULL, TRUE); }
        return 0;
    }
    case WM_LBUTTONDOWN: {
        int x = (short)LOWORD(lp), y = (short)HIWORD(lp);
        g.Act(g.HitTest(x, y));
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
    // selftest 标记
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
                std::wstring mark = dir + L"\\selftest_launcher.ok";
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
    wc.hbrBackground = NULL;
    wc.lpszClassName = L"VisionTerminalLauncher";
    RegisterClassW(&wc);

    HWND hw = CreateWindowExW(0, L"VisionTerminalLauncher", EXE_NAME,
        WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
        CW_USEDEFAULT, CW_USEDEFAULT, 420, 400, NULL, NULL, hInst, NULL);
    if (!hw) return 1;
    // 居中
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
