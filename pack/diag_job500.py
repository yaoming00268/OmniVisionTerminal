# diag_job500.py — 打印 job/start 的 500 错误详情
import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:7902"


def post(path, data):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=90)
        return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def main():
    # 上传
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
        r = urllib.request.urlopen(req, timeout=90)
        print("QUEUE", r.status, r.read().decode("utf-8")[:200])
    except urllib.error.HTTPError as e:
        print("QUEUE_ERR", e.code, e.read().decode("utf-8")[:400])

    print("START", post("/api/job/start", {"type": "batch"}))
    print("DIAG_DONE")


if __name__ == "__main__":
    main()
