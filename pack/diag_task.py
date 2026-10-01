# diag_task.py — 启动任务后读取状态日志
import json
import time
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:7903"


def post(path, data):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def main():
    from PIL import Image
    Image.new("RGB", (64, 64), (10, 200, 100)).save(r"G:\chaofen5\pack\_t64.png")
    boundary = "----b"
    with open(r"G:\chaofen5\pack\_t64.png", "rb") as f:
        content = f.read()
    body = b"\r\n".join([
        b"--" + boundary.encode(),
        b'Content-Disposition: form-data; name="file"; filename="_t64.png"',
        b"Content-Type: image/png", b"", content,
        b"--" + boundary.encode() + b"--"])
    req = urllib.request.Request(
        BASE + "/api/queue", data=body,
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    try:
        r = urllib.request.urlopen(req, timeout=60)
        print("QUEUE", r.status)
    except urllib.error.HTTPError as e:
        print("QUEUE_ERR", e.code, e.read().decode("utf-8")[:300])

    cfg = json.loads(urllib.request.urlopen(BASE + "/api/config", timeout=30).read())
    cfg["use_cpu"] = True
    cfg["model_choice"] = "pro-conservative-up2x"
    cfg["scale"] = 2
    post("/api/config", cfg)
    print("START", post("/api/job/start", {"type": "batch"}))

    for i in range(6):
        time.sleep(3)
        try:
            raw = urllib.request.urlopen(BASE + "/api/job/status", timeout=30).read().decode("utf-8")
            st = json.loads(raw)
        except Exception as e:
            print("STATUS_ERR", e)
            continue
        print("T+%ds JOBS_RAW=%s" % ((i + 1) * 3, json.dumps(st.get("jobs"), ensure_ascii=False)[:400]))
        jb = (st.get("jobs") or {}).get("batch") or {}
        if not jb:
            continue
        log = jb.get("log") or []
        print("   progress=%s running=%s done=%s" % (jb.get("progress"), jb.get("running"), jb.get("done")))
        for line in log[-3:]:
            print("   LOG:", line[:120])
        if jb.get("done") or jb.get("progress") == 100:
            print("OUTPUTS", len(jb.get("outputs") or []))
            break
    print("DIAG_TASK_END")


if __name__ == "__main__":
    main()
