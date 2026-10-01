using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Web.WebView2.WinForms;

namespace VisionTerminal
{
    static class DesktopConsole
    {
        [STAThread]
        static void Main(string[] args)
        {
            if (Common.SelfTest(args, "console")) return;
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new ConsoleForm());
        }
    }

    class ConsoleForm : Form
    {
        Label statusLabel, portLabel;
        TextBox portBox;
        Button startStopBtn, outDirBtn, browserBtn, exitBtn;
        WebView2 webView;
        Panel overlay;
        Label overlayLabel;

        Process spawnedProc;
        Thread waitThread;
        volatile bool closing = false;
        volatile bool stopping = false;
        volatile int currentPort = 7860;
        string engineExe;
        string iniPath;

        Color barBg = Color.FromArgb(31, 35, 43);
        Color green = Color.FromArgb(7, 193, 96);
        Color amber = Color.FromArgb(250, 173, 20);
        Color gray = Color.FromArgb(125, 130, 140);

        public ConsoleForm()
        {
            Text = "全能视像解析终端";
            ClientSize = new Size(1220, 800);
            MinimumSize = new Size(920, 600);
            StartPosition = FormStartPosition.CenterScreen;
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

            engineExe = Common.FindEngine();
            iniPath = Path.Combine(Common.AppDir, "console.ini");

            /* 顶栏 */
            Panel topBar = new Panel();
            topBar.BackColor = barBg;
            topBar.Dock = DockStyle.Top;
            topBar.Height = 46;

            statusLabel = new Label();
            statusLabel.Font = new Font("Microsoft YaHei", 9F);
            statusLabel.ForeColor = gray;
            statusLabel.TextAlign = ContentAlignment.MiddleLeft;
            statusLabel.SetBounds(14, 8, 360, 30);
            statusLabel.Text = "正在检测服务状态...";

            Label titleLabel = new Label();
            titleLabel.Font = new Font("Microsoft YaHei", 10F, FontStyle.Bold);
            titleLabel.ForeColor = Color.White;
            titleLabel.TextAlign = ContentAlignment.MiddleLeft;
            titleLabel.SetBounds(384, 8, 160, 30);
            titleLabel.Text = "全能视像解析终端";

            portLabel = new Label();
            portLabel.Font = new Font("Microsoft YaHei", 9F);
            portLabel.ForeColor = gray;
            portLabel.TextAlign = ContentAlignment.MiddleRight;
            portLabel.SetBounds(556, 8, 40, 30);
            portLabel.Text = "端口";
            portLabel.Anchor = AnchorStyles.Top | AnchorStyles.Right;

            portBox = new TextBox();
            portBox.Font = new Font("Microsoft YaHei", 9F);
            portBox.SetBounds(600, 12, 66, 24);
            portBox.Text = LoadIni("port", "7860");
            portBox.Anchor = AnchorStyles.Top | AnchorStyles.Right;

            startStopBtn = MakeBarButton("启动服务", 680, 120, green, barBg);
            outDirBtn = MakeBarButton("打开输出目录", 806, 120, barBg, Color.FromArgb(46, 51, 62));
            browserBtn = MakeBarButton("浏览器打开", 932, 104, barBg, Color.FromArgb(46, 51, 62));
            exitBtn = MakeBarButton("退出", 1042, 70, barBg, Color.FromArgb(46, 51, 62));

            startStopBtn.Click += new EventHandler(StartStopClick);
            outDirBtn.Click += new EventHandler(OutDirClick);
            browserBtn.Click += new EventHandler(BrowserClick);
            exitBtn.Click += new EventHandler(ExitClick);

            topBar.Controls.Add(statusLabel);
            topBar.Controls.Add(titleLabel);
            topBar.Controls.Add(portLabel);
            topBar.Controls.Add(portBox);
            topBar.Controls.Add(startStopBtn);
            topBar.Controls.Add(outDirBtn);
            topBar.Controls.Add(browserBtn);
            topBar.Controls.Add(exitBtn);

            /* WebView2 主区域 */
            webView = new WebView2();
            webView.Dock = DockStyle.Fill;
            webView.DefaultBackgroundColor = Color.FromArgb(16, 18, 22);

            overlay = new Panel();
            overlay.Dock = DockStyle.Fill;
            overlay.BackColor = Color.FromArgb(16, 18, 22);

            overlayLabel = new Label();
            overlayLabel.Dock = DockStyle.Fill;
            overlayLabel.TextAlign = ContentAlignment.MiddleCenter;
            overlayLabel.Font = new Font("Microsoft YaHei", 12F);
            overlayLabel.ForeColor = gray;
            overlayLabel.Text = "服务未启动";
            overlay.Controls.Add(overlayLabel);

            Controls.Add(webView);
            Controls.Add(overlay);
            Controls.Add(topBar);
            overlay.BringToFront();
            topBar.BringToFront();

            if (engineExe == null)
            {
                statusLabel.Text = "未找到 PhantomCore 引擎,请保持目录文件完整";
                SetStatusColor(gray);
                startStopBtn.Enabled = false;
            }

            Shown += new EventHandler(OnShown);
            FormClosing += new FormClosingEventHandler(OnClosing);
        }

        Button MakeBarButton(string text, int x, int w, Color back, Color hover)
        {
            Button b = new Button();
            b.Text = text;
            b.Font = new Font("Microsoft YaHei", 9F);
            b.SetBounds(x, 10, w, 28);
            b.Anchor = AnchorStyles.Top | AnchorStyles.Right;
            b.FlatStyle = FlatStyle.Flat;
            b.FlatAppearance.BorderSize = 0;
            b.BackColor = back;
            b.ForeColor = Color.White;
            b.Cursor = Cursors.Hand;
            b.TabStop = false;
            b.MouseEnter += delegate(object s, EventArgs e) { b.BackColor = hover; };
            b.MouseLeave += delegate(object s, EventArgs e) { b.BackColor = back; };
            return b;
        }

        async void OnShown(object sender, EventArgs e)
        {
            int port = ReadPort();
            if (port > 0) currentPort = port;

            /* 并行启动:先拉起引擎(约 1 秒就绪),再初始化 WebView2,互不等待 */
            if (engineExe != null && !Common.ServiceAlive(currentPort))
            {
                int found = Common.FindRunningPort();
                if (found > 0)
                {
                    currentPort = found;
                    portBox.Text = found.ToString();
                }
                else
                {
                    AutoStartService();
                }
            }

            try
            {
                await webView.EnsureCoreWebView2Async(null);
            }
            catch (Exception)
            {
                overlayLabel.Text = "未检测到 WebView2 运行时(Edge 内核)。\n\n请安装 Microsoft Edge WebView2 Runtime 后重试,\n或使用顶栏『浏览器打开』按钮访问。";
                return;
            }

            if (Common.ServiceAlive(currentPort))
            {
                SetRunning(currentPort);
                Navigate(currentPort);
            }
            else
            {
                ShowOverlay("正在启动引擎(约 1-3 秒)...\n\n界面加载完成后即可使用");
            }
        }

        void AutoStartService()
        {
            int port = ReadPort();
            if (port <= 0) port = 7860;
            currentPort = port;
            SaveIni("port", port.ToString());
            SetStarting();
            ShowOverlay("正在自动启动引擎(约 1-3 秒)...\n\n请稍候,界面加载完成后即可使用");
            StartEngine();
        }

        void Navigate(int port)
        {
            try
            {
                if (webView.CoreWebView2 != null)
                {
                    webView.CoreWebView2.Navigate("http://127.0.0.1:" + port + "/");
                }
            }
            catch { }
        }

        void ShowOverlay(string text)
        {
            overlayLabel.Text = text;
            overlay.Visible = true;
            overlay.BringToFront();
        }

        void HideOverlay()
        {
            overlay.Visible = false;
        }

        int ReadPort()
        {
            int p;
            if (int.TryParse(portBox.Text.Trim(), out p) && p >= 1024 && p <= 65535) return p;
            return -1;
        }

        void SetRunning(int port)
        {
            currentPort = port;
            statusLabel.Text = "● 服务运行中 · 端口 " + port;
            SetStatusColor(green);
            startStopBtn.Text = "停止服务";
            startStopBtn.BackColor = Color.FromArgb(180, 60, 60);
            startStopBtn.Enabled = true;
            portBox.Enabled = false;
            SaveIni("port", port.ToString());
        }

        void SetStarting()
        {
            statusLabel.Text = "● 服务启动中(约 1-3 秒)...";
            SetStatusColor(amber);
            startStopBtn.Enabled = false;
            portBox.Enabled = false;
        }

        void SetStopped()
        {
            statusLabel.Text = "○ 服务未启动";
            SetStatusColor(gray);
            startStopBtn.Text = "启动服务";
            startStopBtn.BackColor = green;
            startStopBtn.Enabled = true;
            portBox.Enabled = true;
        }

        void SetStatusColor(Color c)
        {
            statusLabel.ForeColor = c;
        }

        void StartStopClick(object sender, EventArgs e)
        {
            if (Common.ServiceAlive(currentPort))
            {
                StopService();
            }
            else
            {
                StartService();
            }
        }

        void StartService()
        {
            int port = ReadPort();
            if (port <= 0)
            {
                MessageBox.Show(this, "请输入有效端口(1024-65535)。", "提示");
                return;
            }
            currentPort = port;
            SaveIni("port", port.ToString());
            SetStarting();
            ShowOverlay("正在启动引擎(约 1-3 秒)...\n\n首次使用会自动加载模型引擎");
            StartEngine();
        }

        void StartEngine()
        {
            ProcessStartInfo psi = new ProcessStartInfo(engineExe, "--no-browser --port " + currentPort);
            psi.WorkingDirectory = Path.GetDirectoryName(engineExe);
            psi.UseShellExecute = true;
            psi.CreateNoWindow = true;
            try
            {
                spawnedProc = Process.Start(psi);
            }
            catch (Exception ex)
            {
                SetStopped();
                ShowOverlay("启动失败: " + ex.Message);
                return;
            }

            waitThread = new Thread(WaitLoop);
            waitThread.IsBackground = true;
            waitThread.Start();
        }

        void WaitLoop()
        {
            int port = currentPort;
            for (int i = 0; i < 360; i++)
            {
                Thread.Sleep(500);
                if (closing || stopping) return;
                try
                {
                    if (spawnedProc != null && spawnedProc.HasExited)
                    {
                        BeginInvoke(new Action(delegate()
                        {
                            SetStopped();
                            ShowOverlay("引擎进程异常退出。\n\n请确认目录文件完整后重试。");
                        }));
                        return;
                    }
                }
                catch { }
                if (Common.ServiceAlive(port))
                {
                    BeginInvoke(new Action(delegate()
                    {
                        SetRunning(port);
                        HideOverlay();
                        Navigate(port);
                    }));
                    return;
                }
            }
            BeginInvoke(new Action(delegate()
            {
                SetStopped();
                ShowOverlay("等待服务启动超时(180 秒)。\n\n请检查端口是否被占用或尝试重启程序。");
            }));
        }

        void StopService()
        {
            stopping = true;
            bool killed = false;
            if (spawnedProc != null && !spawnedProc.HasExited)
            {
                killed = Common.KillEngineByPid(spawnedProc.Id);
            }
            if (!killed)
            {
                killed = Common.KillEngineByName();
            }
            /* 等待端口释放,确保服务完全关闭 */
            Common.WaitPortClosed(currentPort);
            spawnedProc = null;
            stopping = false;
            SetStopped();
            ShowOverlay("服务已停止\n\n点击顶栏『启动服务』重新开始");
        }

        void OutDirClick(object sender, EventArgs e)
        {
            if (Common.ServiceAlive(currentPort))
            {
                if (Common.HttpPostJson("http://127.0.0.1:" + currentPort + "/api/open_dir", "{}", 3000))
                {
                    return;
                }
            }
            MessageBox.Show(this, "无法打开输出目录(服务未运行或请求失败)。", "提示");
        }

        void BrowserClick(object sender, EventArgs e)
        {
            try
            {
                Process.Start("http://127.0.0.1:" + currentPort + "/");
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, "打开浏览器失败: " + ex.Message, "错误");
            }
        }

        void ExitClick(object sender, EventArgs e)
        {
            Close();
        }

        void OnClosing(object sender, FormClosingEventArgs e)
        {
            if (!closing && (Common.ServiceAlive(currentPort) || (spawnedProc != null && !spawnedProc.HasExited)))
            {
                DialogResult r = MessageBox.Show(this,
                    "服务仍在运行,退出前是否停止?\n\n是:停止服务并退出\n否:服务保持后台运行,仅关闭窗口\n取消:留在程序",
                    "全能视像解析终端", MessageBoxButtons.YesNoCancel, MessageBoxIcon.Question);
                if (r == DialogResult.Cancel)
                {
                    e.Cancel = true;
                    return;
                }
                if (r == DialogResult.Yes)
                {
                    stopping = true;
                    if (spawnedProc != null && !spawnedProc.HasExited)
                        Common.KillEngineByPid(spawnedProc.Id);
                    else
                        Common.KillEngineByName();
                    Common.WaitPortClosed(currentPort);
                    spawnedProc = null;
                }
            }
            closing = true;
            int port = ReadPort();
            if (port > 0) SaveIni("port", port.ToString());
            if (webView != null)
            {
                try { webView.Dispose(); } catch { }
            }
            // 选择"否"时服务保持后台运行,用户可随时重新打开控制台或使用浏览器访问
        }

        string LoadIni(string key, string def)
        {
            try
            {
                if (!File.Exists(iniPath)) return def;
                foreach (string line in File.ReadAllLines(iniPath, System.Text.Encoding.UTF8))
                {
                    int idx = line.IndexOf('=');
                    if (idx > 0 && line.Substring(0, idx).Trim() == key)
                        return line.Substring(idx + 1).Trim();
                }
            }
            catch { }
            return def;
        }

        void SaveIni(string key, string value)
        {
            try
            {
                System.Collections.Generic.Dictionary<string, string> map =
                    new System.Collections.Generic.Dictionary<string, string>();
                if (File.Exists(iniPath))
                {
                    foreach (string line in File.ReadAllLines(iniPath, System.Text.Encoding.UTF8))
                    {
                        int idx = line.IndexOf('=');
                        if (idx > 0) map[line.Substring(0, idx).Trim()] = line.Substring(idx + 1).Trim();
                    }
                }
                map[key] = value;
                System.Text.StringBuilder sb = new System.Text.StringBuilder();
                foreach (var kv in map) sb.AppendLine(kv.Key + "=" + kv.Value);
                File.WriteAllText(iniPath, sb.ToString(), System.Text.Encoding.UTF8);
            }
            catch { }
        }
    }
}
