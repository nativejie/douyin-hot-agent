"""生图：Vizluma API（https://docs.vizluma.online，企业开通制，key 找对接人要）。make_ip.py 用它出 IP 的定稿图、头像和角色贴纸。

    python3 gen_image.py out.png "提示词" [--size 16:9] [--ref a.png --ref b.png] [--model gpt-image-2] [-n 2]

- 没有参考图：POST /v1/images/generations（JSON）。有参考图：POST /v1/images/edits（multipart 上传，最多 15 张）。
  两个接口都是同步的：一次请求等到图出来（单张 1K 约 30 秒，高分辨率更久），不用轮询。
- 模型：gpt-image-2.5-flare（默认）、gpt-image-2.5-sunburst、gpt-image-2，统一 ¥0.20／张，1K / 2K / 4K 同价。
- --size 写比例（16:9、9:16、4:3、3:4、1:1），按 SIZES 换成像素；也可以直接写像素，例 2048x1152。
- 密钥只从环境变量 VIZLUMA_API_KEY 读（地址可用 VIZLUMA_BASE_URL 改），不写盘、不打印。
- **默认直连、不走系统代理**：生图要等几十秒到几分钟，长连接经过本地代理（HTTPS_PROXY）容易被掐断，
  服务端照样生成、照样扣费，你却拿不到图；图床走代理也可能连不上。确实要走代理就设 VIZLUMA_USE_PROXY=1。
  连接另外开了 TCP 保活，防止中间设备把等待中的连接当成空闲断掉。
- **生成请求不自动重试**：超时、断连、504 时图可能已经生成并扣了钱，脚本报错退出，先去控制台 sub.vizluma.online 看调用记录。
  只有下载图片失败会重试（重下不花钱）。
- 别的脚本用：from gen_image import generate；generate(prompt, size="16:9", refs=[Path(...)]) -> [bytes, ...]
"""
import argparse
import base64
import http.client
import json
import mimetypes
import os
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE_URL = os.environ.get("VIZLUMA_BASE_URL", "https://api.vizluma.online/v1").rstrip("/")
MODEL = os.environ.get("VIZLUMA_MODEL", "gpt-image-2.5-flare")
TIMEOUT = 600
# 比例 -> 像素。2K 一档；网关文档里 1024x1024、2048x2048（编辑）验过，其余是网关配置里的尺寸，用之前先出一张看实际尺寸
SIZES = {"16:9": "2048x1152", "9:16": "1152x2048", "4:3": "2048x1536", "3:4": "1536x2048", "1:1": "2048x2048"}


class _KeepAliveHTTPS(http.client.HTTPSConnection):
    def connect(self):
        super().connect()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if hasattr(socket, "SIO_KEEPALIVE_VALS"):                       # Windows：30 秒没动静就探一次
            self.sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 30000, 10000))
        elif hasattr(socket, "TCP_KEEPIDLE"):                            # Linux
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
        elif hasattr(socket, "TCP_KEEPALIVE"):                           # macOS
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, 30)


class _KeepAliveHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_KeepAliveHTTPS, req, context=self._context)


_handlers = [_KeepAliveHandler()]
if os.environ.get("VIZLUMA_USE_PROXY") != "1":
    _handlers.insert(0, urllib.request.ProxyHandler({}))                 # 不走系统代理
_OPENER = urllib.request.build_opener(*_handlers)


def _key() -> str:
    key = os.environ.get("VIZLUMA_API_KEY", "").strip()
    if not key:
        sys.exit("VIZLUMA_API_KEY 没设。去 sub.vizluma.online 控制台拿 key，设成环境变量（别贴进对话、别写进文件）。")
    return key


def _multipart(fields: dict, files: list[Path]) -> tuple[bytes, str]:
    boundary = "----vz" + uuid.uuid4().hex
    out = bytearray()
    for k, v in fields.items():
        out += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    for f in files:
        ctype = mimetypes.guess_type(f.name)[0] or "image/png"
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{f.name}\"\r\n"
                f"Content-Type: {ctype}\r\n\r\n").encode()
        out += f.read_bytes() + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def _post(path: str, data: bytes, ctype: str) -> dict:
    req = urllib.request.Request(BASE_URL + path, data=data, method="POST",
                                 headers={"Authorization": "Bearer " + _key(), "Content-Type": ctype})
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as r:
            res = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:400]
        hint = {401: "（key 不对或过期）", 403: "（没开通这个模型、余额或额度不够）", 429: "（太快了，等一会儿）",
                504: "（等结果超时，图可能还是生成了，先看控制台调用记录再决定重不重出）"}.get(e.code, "")
        raise RuntimeError(f"HTTP {e.code}{hint}：{detail}") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise RuntimeError(f"没拿到确定结果（{e}）。图多半已经生成并扣费（控制台调用记录里能看到），别马上重发；连续断开的话检查网络 / 代理。") from None
    if res.get("error") or not res.get("data"):
        raise RuntimeError(f"没有图片结果：{json.dumps(res, ensure_ascii=False)[:300]}")
    return res


def _download(url: str) -> bytes:
    # 下载不带 key；图床会挡掉 Python 默认的 User-Agent（403），所以带一个普通浏览器的
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; gen_image/1.0)"})
    for attempt in range(1, 6):
        try:
            with _OPENER.open(req, timeout=120) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if attempt == 5:
                raise RuntimeError(f"图已经生成，但下载失败（{e}）。不用重新生图，手动下载：{url}") from None
            time.sleep(2 * attempt)


def generate(prompt: str, size: str = "16:9", refs: list[Path] | None = None, model: str | None = None, n: int = 1) -> list[bytes]:
    """出图，返回每张图的字节（PNG / JPEG / WebP，按文件头认）。"""
    size = SIZES.get(size, size)
    fields = {"model": model or MODEL, "prompt": prompt, "size": size, "n": n, "response_format": "url"}
    refs = [Path(r) for r in refs or []]
    if refs:
        if len(refs) > 15:
            raise ValueError("参考图最多 15 张")
        res = _post("/images/edits", *_multipart(fields, refs))
    else:
        res = _post("/images/generations", json.dumps(fields).encode(), "application/json")
    out = []
    for item in res["data"]:
        if item.get("b64_json"):
            b = item["b64_json"].split(",", 1)[-1]
            out.append(base64.b64decode(b + "=" * (-len(b) % 4)))
        elif item.get("url"):
            out.append(_download(item["url"]))
    if not out:
        raise RuntimeError("返回里没有图")
    return out


def save(raw: bytes, path: Path) -> Path:
    """按文件头存成对的格式（.png / .jpg / .webp），返回实际路径。"""
    ext = ".png" if raw.startswith(b"\x89PNG") else ".jpg" if raw.startswith(b"\xff\xd8\xff") else ".webp" if raw[8:12] == b"WEBP" else None
    if not ext:
        raise RuntimeError("下回来的不是 PNG / JPEG / WebP")
    path = Path(path).with_suffix(ext)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out", help="输出文件，例 img/art/hero.png（扩展名按实际格式改）")
    ap.add_argument("prompt")
    ap.add_argument("--size", default="16:9")
    ap.add_argument("--ref", action="append", default=[], help="参考图，可以给多张")
    ap.add_argument("--model", default=None)
    ap.add_argument("-n", type=int, default=1)
    a = ap.parse_args()
    t0 = time.time()
    try:
        imgs = generate(a.prompt, a.size, a.ref, a.model, a.n)
    except RuntimeError as e:
        sys.exit(f"失败：{e}")
    base = Path(a.out)
    for i, raw in enumerate(imgs):
        p = save(raw, base if len(imgs) == 1 else base.with_name(f"{base.stem}_{i + 1}{base.suffix}"))
        print(f"saved {p}")
    print(f"{len(imgs)} 张，{time.time() - t0:.0f} 秒，约 ¥{0.2 * len(imgs):.2f}")
