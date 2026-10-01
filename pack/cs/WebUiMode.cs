using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Threading;
using System.Windows.Forms;

namespace VisionTerminal
{
    static class WebUiMode
    {
        [STAThread]
        static void Main(string[] args)
        {
            if (Common.SelfTest(args, "webui")) return;
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new WebUiForm());
        }
    }

    /* WebUI 模式:启动引擎并打开浏览器;窗体常驻,提供停止服务的入口 */
    class WebUiForm : Form
    {
        Label statusLabel, hintLabel;
        Button browserBtn, stopBtn;
        Process spawnedProc;
        Thread waitThread;
        volatile bool closing = false;
        volatile bool stopping = false;
        volatile int currentPort = 7860;
        string engineExe;

        Color barBg = Color.FromArgb(31, 35, 43);
        Color green = Color.FromArgb(7, 193, 96);
        Color gray = Color.FromArgb(125, 130, 140);
        Color red = Color.FromArgb(180, 60, 60);

        public WebUiForm()
        {
            Text = "全能视像解析终端 - WebUI 模式";
            ClientSize = new Size(440, 210);
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = Color.FromArgb(22, 25, 30);
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

            engineExe = Common.FindEngine();
            if (engineExe == null)
            {
                MessageBox.Show("未找到 PhantomCore 引擎,请保持目录文件完整。", "全能视像解析终端");
                Environment.Exit(1);
            }

            statusLabel = new Label();
            statusLabel.Font = new Font("Microsoft YaHei", 11F, FontStyle.Bold);
            statusLabel.ForeColor = gray;
            statusLabel.TextAlign = ContentAlignment.MiddleCenter;
            statusLabel.SetBounds(0, 34, 440, 34);
            statusLabel.Text = "正在检测服务状态...";

            hintLabel = new Label();
            hintLabel.Font = new Font("Microsoft YaHei", 8.5F);
            hintLabel.ForeColor = gray;
            hintLabel.TextAlign = ContentAlignment.MiddleCenter;
            hintLabel.SetBounds(20, 72, 400, 36);
            hintLabel.Text = "关闭本窗口时请选择是否停止服务;\n若选择保持运行,可随时再次打开本程序访问。";

            browserBtn = MakeButton("浏览器打开", 70, 118, 130, green, Color.FromArgb(6, 160, 80));
            stopBtn = MakeButton("停止服务并退出", 216, 118, 154, red, Color.FromArgb(150, 45, 45));

            browserBtn.Click += new EventHandler(BrowserClick);
            stopBtn.Click += new EventHandler(StopClick);

            Controls.Add(statusLabel);
            Controls.Add(hintLabel);
            Controls.Add(browserBtn);
            Controls.Add(stopBtn);

            Shown += new EventHandler(OnShown);
            FormClosing += new FormClosingEventHandler(OnClosing);
        }

        Button MakeButton(string text, int x, int y, int w, Color back, Color hover)
        {
            Button b = new Button();
            b.Text = text;
            b.Font = new Font("Microsoft YaHei", 9F);
            b.SetBounds(x, y, w, 34);
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

        void OnShown(object sender, EventArgs e)
        {
            int running = Common.FindRunningPort();
            if (running > 0)
            {
                currentPort = running;
                SetRunning(running);
                OpenBrowser(running);
                return;
            }

            int port = Common.ConfigPort(Path.GetDirectoryName(engineExe));
            if (port <= 0) port = 7860;
            currentPort = port;
            SetStarting();

            try
            {
                ProcessStartInfo psi = new ProcessStartInfo(engineExe, "--port " + port);
                psi.WorkingDirectory = Path.GetDirectoryName(engineExe);
                psi.UseShellExecute = true;
                psi.CreateNoWindow = true;
                spawnedProc = Process.Start(psi);
            }
            catch (Exception ex)
            {
                SetStopped();
                statusLabel.Text = "启动失败";
                hintLabel.Text = ex.Message;
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
                            statusLabel.Text = "引擎进程异常退出";
                            hintLabel.Text = "请确认目录文件完整后重新打开本程序。";
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
                        OpenBrowser(port);
                    }));
                    return;
                }
            }
            BeginInvoke(new Action(delegate()
            {
                SetStopped();
                statusLabel.Text = "服务启动超时";
                hintLabel.Text = "请检查端口 " + port + " 是否被占用后重试。";
            }));
        }

        void SetStarting()
        {
            statusLabel.Text = "正在启动引擎(约 1-3 秒)...";
            statusLabel.ForeColor = Color.FromArgb(250, 173, 20);
            stopBtn.Enabled = false;
        }

        void SetRunning(int port)
        {
            statusLabel.Text = "服务运行中 · 端口 " + port;
            statusLabel.ForeColor = green;
            stopBtn.Enabled = true;
            stopBtn.Text = "停止服务并退出";
        }

        void SetStopped()
        {
            statusLabel.ForeColor = gray;
            stopBtn.Enabled = false;
        }

        void OpenBrowser(int port)
        {
            try { Process.Start("http://127.0.0.1:" + port + "/"); }
            catch { }
        }

        void BrowserClick(object sender, EventArgs e)
        {
            OpenBrowser(currentPort);
        }

        void StopClick(object sender, EventArgs e)
        {
            Close();
        }

        void OnClosing(object sender, FormClosingEventArgs e)
        {
            bool alive = Common.ServiceAlive(currentPort) || (spawnedProc != null && !spawnedProc.HasExited);
            if (!closing && alive)
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
        }
    }
}
