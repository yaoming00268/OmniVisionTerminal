using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;

namespace VisionTerminal
{
    static class Common
    {
        public static string AppDir
        {
            get { return AppDomain.CurrentDomain.BaseDirectory; }
        }

        public static string FindEngine()
        {
            string[] candidates = new string[] {
                Path.Combine(AppDir, "PhantomCore", "PhantomCore.exe"),
                Path.Combine(AppDir, "PhantomCore.exe"),
            };
            foreach (string c in candidates)
            {
                try { if (File.Exists(c)) return c; }
                catch { }
            }
            return null;
        }

        /* 读取 upscale_config.json 中的字符串配置项(引擎目录优先,其次应用目录) */
        public static string ConfigValue(string engineDir, string key)
        {
            try
            {
                string cfg = Path.Combine(engineDir, "upscale_config.json");
                if (!File.Exists(cfg)) cfg = Path.Combine(AppDir, "upscale_config.json");
                if (!File.Exists(cfg)) return null;
                string text = File.ReadAllText(cfg, Encoding.UTF8);
                Match m = Regex.Match(text, "\"" + Regex.Escape(key) + "\"\\s*:\\s*\"([^\"]*)\"");
                if (m.Success) return m.Groups[1].Value;
            }
            catch { }
            return null;
        }

        public static int ConfigPort(string engineDir)
        {
            try
            {
                string cfg = Path.Combine(engineDir, "upscale_config.json");
                if (!File.Exists(cfg)) cfg = Path.Combine(AppDir, "upscale_config.json");
                if (!File.Exists(cfg)) return -1;
                string text = File.ReadAllText(cfg, Encoding.UTF8);
                Match m = Regex.Match(text, "\"webui_port\"\\s*:\\s*(\\d+)");
                if (m.Success) return int.Parse(m.Groups[1].Value);
            }
            catch { }
            return -1;
        }

        public static bool ServiceAlive(int port)
        {
            try
            {
                HttpWebRequest req = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + port + "/api/config");
                req.Timeout = 1500;
                req.Method = "GET";
                try
                {
                    using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
                    {
                        return resp.StatusCode == HttpStatusCode.OK || resp.StatusCode == HttpStatusCode.Unauthorized;
                    }
                }
                catch (WebException ex)
                {
                    return ex.Response != null;
                }
            }
            catch { return false; }
        }

        public static int FindRunningPort()
        {
            for (int p = 7860; p <= 7880; p++)
            {
                if (ServiceAlive(p)) return p;
            }
            return -1;
        }

        public static bool SelfTest(string[] args, string name)
        {
            foreach (string a in args)
            {
                if (a == "--selftest")
                {
                    try { File.WriteAllText(Path.Combine(AppDir, "selftest_" + name + ".ok"), "ok"); }
                    catch { }
                    return true;
                }
            }
            return false;
        }

        public static string HttpGet(string url, int timeoutMs)
        {
            try
            {
                HttpWebRequest req = (HttpWebRequest)WebRequest.Create(url);
                req.Timeout = timeoutMs;
                req.Method = "GET";
                using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
                using (StreamReader reader = new StreamReader(resp.GetResponseStream(), Encoding.UTF8))
                {
                    return reader.ReadToEnd();
                }
            }
            catch { return null; }
        }

        public static bool HttpPostJson(string url, string json, int timeoutMs)
        {
            try
            {
                HttpWebRequest req = (HttpWebRequest)WebRequest.Create(url);
                req.Timeout = timeoutMs;
                req.Method = "POST";
                req.ContentType = "application/json";
                byte[] data = Encoding.UTF8.GetBytes(json);
                req.ContentLength = data.Length;
                using (Stream s = req.GetRequestStream())
                {
                    s.Write(data, 0, data.Length);
                }
                using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
                {
                    return resp.StatusCode == HttpStatusCode.OK;
                }
            }
            catch { return false; }
        }

        /* 停止引擎:按 PID 或按进程名,连同子进程树一起强制结束 */
        public static bool KillEngineByPid(int pid)
        {
            if (pid <= 0) return false;
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo("taskkill.exe", "/F /T /PID " + pid);
                psi.CreateNoWindow = true;
                psi.UseShellExecute = false;
                Process.Start(psi);
                return true;
            }
            catch { return false; }
        }

        public static bool KillEngineByName()
        {
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo("taskkill.exe", "/F /T /IM PhantomCore.exe");
                psi.CreateNoWindow = true;
                psi.UseShellExecute = false;
                Process.Start(psi);
                return true;
            }
            catch { return false; }
        }

        /* 等待端口服务停止响应(最多约 8 秒) */
        public static bool WaitPortClosed(int port)
        {
            for (int i = 0; i < 40; i++)
            {
                if (!ServiceAlive(port)) return true;
                System.Threading.Thread.Sleep(200);
            }
            return !ServiceAlive(port);
        }
    }
}
