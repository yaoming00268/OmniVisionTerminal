# verify_engine_task.py — 打包引擎真实超分任务验证(数据文件模式 torch)
import json
import time
import urllib.request

BASE = "http://127.0.0.1:7895"


def post(path, data):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=60).read().decode("utf-8"))


def main():
    # 1. 上传 64x64 测试图(multipart)
    from PIL import Image
    Image.new("RGB", (64, 64), (120, 90, 200)).save(r"G:\chaofen5\pack\_t64.png")
    boundary = "----vtboundary"
    with open(r"G:\chaofen5\pack\_t64.png", "rb") as f:
        content = f.read()
    parts = []
    parts.append(b"--" + boundary.encode())
    parts.append(b'Content-Disposition: form-data; name="file"; filename="_t64.png"')
    parts.append(b"Content-Type: image/png")
    parts.append(b"")
    parts.append(content)
    parts.append(b"--" + boundary.encode() + b"--")
    body = b"\r\n".join(parts)
    req = urllib.request.Request(
        BASE + "/api/queue", data=body,
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    q = json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))
    print("QUEUE_ADD ok=%s count=%s" % (q.get("ok"), q.get("count")))

    # 2. 配置 CPU + 小模型 + 2x
    cfg = get("/api/config")
    cfg["use_cpu"] = True
    cfg["model_choice"] = "pro-conservative-up2x"
    cfg["scale"] = 2
    post("/api/config", cfg)

    # 3. 启动 batch 任务
    r = post("/api/job/start", {"type": "batch"})
    print("JOB_START ok=%s err=%s" % (r.get("ok"), r.get("error", "")))

    # 4. 轮询直到完成
    for i in range(240):
        st = get("/api/job/status?type=batch")
        prog = st.get("progress")
        logs = st.get("logs") or []
        if i % 10 == 0:
            print("POLL %d progress=%s running=%s logs=%d" % (
                i, prog, st.get("running"), len(logs)))
            for lg in logs[-3:]:
                print("   LOG:", (lg.get("text") if isinstance(lg, dict) else lg)[:90])
        if st.get("done") or prog == 100:
            outs = st.get("outputs") or []
            print("JOB_DONE progress=%s outputs=%d" % (prog, len(outs)))
            if outs:
                print("FIRST_OUT=%s" % outs[0])
            break
        time.sleep(1)
    else:
        print("JOB_TIMEOUT")
    print("ENGINE_TASK_TEST_FINISHED")


if __name__ == "__main__":
    main()
