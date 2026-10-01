using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Windows.Forms;

namespace VisionTerminal
{
    static class Launcher
    {
        [STAThread]
        static void Main(string[] args)
        {
            if (Common.SelfTest(args, "launcher")) return;
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new LauncherForm());
        }
    }

    class LauncherForm : Form
    {
        Label statusLabel;
        Button webBtn, deskBtn, bgBtn, exitBtn;
        string webExe, deskExe, engineExe;

        Color green = Color.FromArgb(7, 193, 96);
        Color greenHover = Color.FromArgb(6, 173, 86);
        Color blue = Color.FromArgb(59, 130, 246);
        Color blueHover = Color.FromArgb(37, 99, 235);
        Color gray = Color.FromArgb(107, 114, 128);
        Color grayHover = Color.FromArgb(75, 85, 99);
        Color cardBg = Color.FromArgb(248, 249, 251);

        public LauncherForm()
        {
            Text = "全能视像解析终端";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            ClientSize = new Size(420, 400);
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = Color.White;
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

            webExe = Path.Combine(Common.AppDir, "全能视像解析终端_WebUI模式.exe");
            deskExe = Path.Combine(Common.AppDir, "全能视像解析终端_桌面控制台.exe");
            engineExe = Common.FindEngine();

            Label title = new Label();
            title.Text = "全能视像解析终端";
            title.Font = new Font("Microsoft YaHei", 15F, FontStyle.Bold);
            title.ForeColor = Color.FromArgb(31, 41, 55);
            title.TextAlign = ContentAlignment.MiddleCenter;
            title.SetBounds(10, 22, 400, 32);

            statusLabel = new Label();
            statusLabel.Font = new Font("Microsoft YaHei", 9F);
            statusLabel.TextAlign = ContentAlignment.MiddleCenter;
            statusLabel.SetBounds(10, 58, 400, 22);
            statusLabel.ForeColor = gray;
            statusLabel.Text = "正在检测服务状态...";

            webBtn = MakeCardButton("WebUI 模式", "浏览器全功能操作界面", green, greenHover, 30, 92);
            webBtn.Click += new EventHandler(WebClick);

            deskBtn = MakeCardButton("桌面窗口模式", "内嵌界面,无需打开浏览器", blue, blueHover, 30, 162);
            deskBtn.Click += new EventHandler(DeskClick);

            bgBtn = MakeCardButton("仅后台服务", "静默运行,不打开任何界面", gray, grayHover, 30, 232);
            bgBtn.Click += new EventHandler(BgClick);

            exitBtn = new Button();
            exitBtn.Text = "退出";
            exitBtn.Font = new Font("Microsoft YaHei", 9F);
            exitBtn.SetBounds(30, 326, 360, 38);
            exitBtn.FlatStyle = FlatStyle.Flat;
            exitBtn.FlatAppearance.BorderColor = Color.FromArgb(229, 231, 235);
            exitBtn.BackColor = Color.White;
            exitBtn.ForeColor = gray;
            exitBtn.Cursor = Cursors.Hand;
            exitBtn.Click += new EventHandler(ExitClick);

            Controls.Add(title);
            Controls.Add(statusLabel);
            Controls.Add(webBtn);
            Controls.Add(deskBtn);
            Controls.Add(bgBtn);
            Controls.Add(exitBtn);

            if (engineExe == null)
            {
                statusLabel.Text = "未找到 PhantomCore 引擎,请保持目录文件完整";
                webBtn.Enabled = false;
                deskBtn.Enabled = false;
                bgBtn.Enabled = false;
            }
            else
            {
                Shown += new EventHandler(OnShown);
                Load += new EventHandler(OnLoadAutoMode);
            }
        }

        /* 依据设置中的 launcher_default_mode 自动进入对应模式(ask=显示本窗口) */
        void OnLoadAutoMode(object sender, EventArgs e)
        {
            string mode = Common.ConfigValue(Path.GetDirectoryName(engineExe), "launcher_default_mode");
            if (string.IsNullOrEmpty(mode)) mode = "ask";
            if (mode == "console") LaunchExe(deskExe);
            else if (mode == "webui") LaunchExe(webExe);
            else if (mode == "service") StartBackground();
        }

        Button MakeCardButton(string title, string desc, Color back, Color hover, int x, int y)
        {
            Button b = new Button();
            b.Text = title + "\n" + desc;
            b.Font = new Font("Microsoft YaHei", 10.5F, FontStyle.Bold);
            b.TextAlign = ContentAlignment.MiddleCenter;
            b.SetBounds(x, y, 360, 60);
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
            RefreshStatus();
        }

        void RefreshStatus()
        {
            int port = Common.FindRunningPort();
            if (port > 0)
            {
                statusLabel.Text = "● 服务运行中(端口 " + port + ")";
                statusLabel.ForeColor = green;
            }
            else
            {
                statusLabel.Text = "○ 服务未启动";
                statusLabel.ForeColor = gray;
            }
        }

        void WebClick(object sender, EventArgs e)
        {
            LaunchExe(webExe);
        }

        void DeskClick(object sender, EventArgs e)
        {
            LaunchExe(deskExe);
        }

        void BgClick(object sender, EventArgs e)
        {
            StartBackground();
        }

        void StartBackground()
        {
            int port = Common.ConfigPort(Path.GetDirectoryName(engineExe));
            if (port <= 0) port = 7860;
            ProcessStartInfo psi = new ProcessStartInfo(engineExe, "--no-browser --port " + port);
            psi.WorkingDirectory = Path.GetDirectoryName(engineExe);
            psi.UseShellExecute = true;
            psi.CreateNoWindow = true;
            try
            {
                Process.Start(psi);
                if (Visible)
                {
                    MessageBox.Show(this, "后台服务正在启动(约 10-30 秒)。\n完成后可随时重新打开启动器选择界面。", "提示");
                }
                Application.Exit();
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, "启动失败: " + ex.Message, "错误");
            }
        }

        void LaunchExe(string exe)
        {
            if (!File.Exists(exe))
            {
                MessageBox.Show(this, "未找到 " + Path.GetFileName(exe) + "\n请保持目录文件完整。", "提示");
                return;
            }
            try
            {
                Process.Start(exe);
                Application.Exit();
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, "启动失败: " + ex.Message, "错误");
            }
        }

        void ExitClick(object sender, EventArgs e)
        {
            Application.Exit();
        }
    }
}
