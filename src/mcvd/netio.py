"""HTTP 下载与校验：多源回退、断点续传、SHA-1 校验、重试、连接复用。

Minecraft 的一次安装往往包含上万个几 KB~几 MB 的小文件（资源对象），
每次请求都重新做 TLS 握手会非常慢，因此下载部分使用线程内复用的
HTTP 长连接（keep-alive）；JSON 等零散请求继续用 urllib 即可。
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import random
import socket
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Iterable, Sequence
from urllib.parse import urlsplit

USER_AGENT = "mcvd/0.1.0 (+https://github.com/huiyaoxingkong/mc-vanilla-downloader)"

CHUNK = 1 << 16  # 64 KiB
MAX_REDIRECTS = 5


class DownloadError(RuntimeError):
    """下载失败（已尝试所有候选源与重试）。"""


def human_bytes(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024 or unit == "GB":
            return f"{num:.2f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return f"{num:.2f} GB"


def _request(url: str, headers: dict[str, str] | None = None, timeout: float = 20.0) -> urllib.request.Request:
    base = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        base.update(headers)
    return urllib.request.Request(url, headers=base)


def fetch_json(urls: Sequence[str], timeout: float = 20.0, retries: int = 3) -> dict:
    """按顺序尝试多个 URL，返回第一个成功的 JSON。"""
    last_error: Exception | None = None
    for attempt in range(max(retries, 1)):
        for url in urls:
            try:
                with urllib.request.urlopen(_request(url), timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except (urllib.error.URLError, socket.timeout, json.JSONDecodeError, OSError) as exc:
                last_error = exc
        time.sleep(min(2**attempt * 0.5, 4) + random.random() * 0.2)
    raise DownloadError(f"获取 JSON 失败：{urls[0]}（{last_error}）")


def sha1_of_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def digest_matches(path: Path, sha1: str | None, size: int | None) -> bool:
    if not path.is_file():
        return False
    if size is not None and path.stat().st_size != size:
        return False
    if sha1 and sha1_of_file(path) != sha1.lower():
        return False
    return True


# ---------------------------------------------------------------- 连接复用

_tls = __import__("threading").local()


def _connection(scheme: str, host: str, timeout: float):
    key = (scheme, host, timeout)
    conn = getattr(_tls, "conn", None)
    if conn is not None and getattr(_tls, "key", None) == key:
        return conn
    _drop_connection()
    if scheme == "https":
        conn = http.client.HTTPSConnection(host, timeout=timeout, context=ssl.create_default_context())
    else:
        conn = http.client.HTTPConnection(host, timeout=timeout)
    _tls.conn = conn
    _tls.key = key
    return conn


def _drop_connection() -> None:
    conn = getattr(_tls, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 - 关闭失败无关紧要
            pass
    _tls.conn = None
    _tls.key = None


def _stream_to_file(url: str, part: Path, timeout: float, progress: Callable[[int], None] | None) -> None:
    """下载 url 到 part（支持续传），使用线程内复用的长连接。"""
    current = url
    offset = part.stat().st_size if part.exists() else 0

    for _ in range(MAX_REDIRECTS):
        parts = urlsplit(current)
        scheme = parts.scheme or "https"
        conn = _connection(scheme, parts.netloc, timeout)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        headers = {"User-Agent": USER_AGENT, "Accept": "*/*", "Connection": "keep-alive"}
        if offset > 0:
            headers["Range"] = f"bytes={offset}-"
        try:
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
        except (http.client.HTTPException, OSError):
            _drop_connection()
            raise

        if resp.status in (301, 302, 303, 307, 308):
            location = resp.getheader("Location")
            resp.read()
            if not location:
                raise DownloadError(f"重定向缺少 Location：{url}")
            current = location
            if urlsplit(current).netloc != parts.netloc:
                _drop_connection()
            continue

        if resp.status == 416:
            resp.read()
            part.unlink(missing_ok=True)
            offset = 0
            continue

        if resp.status not in (200, 206):
            resp.read()
            raise DownloadError(f"HTTP {resp.status}：{current}")

        if offset and resp.status != 206:
            offset = 0  # 服务器不支持 Range，从头写

        mode = "ab" if offset else "wb"
        with part.open(mode) as handle:
            while True:
                block = resp.read(CHUNK)
                if not block:
                    break
                handle.write(block)
                if progress:
                    progress(len(block))
        resp.read()
        return

    raise DownloadError(f"重定向次数过多：{url}")


def download_file(
    urls: Sequence[str],
    dest: Path,
    *,
    sha1: str | None = None,
    size: int | None = None,
    timeout: float = 20.0,
    retries: int = 3,
    progress: Callable[[int], None] | None = None,
    force: bool = False,
) -> dict:
    """下载到 dest，返回 {"skipped": bool, "bytes": int, "url": str}。

    支持 .part 断点续传；成功后校验 SHA-1；失败时在多个源之间轮换重试。
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not force and digest_matches(dest, sha1, size):
        return {"skipped": True, "bytes": dest.stat().st_size, "url": ""}

    part = dest.with_name(dest.name + ".part")
    last_error: Exception | None = None
    attempts = max(retries, 1) * max(len(urls), 1)

    for attempt in range(attempts):
        url = urls[attempt % len(urls)]
        try:
            _stream_to_file(url, part, timeout, progress)
            if sha1 and sha1_of_file(part) != sha1.lower():
                part.unlink(missing_ok=True)
                raise DownloadError(f"SHA-1 校验失败：{url}")
            os.replace(part, dest)
            return {"skipped": False, "bytes": dest.stat().st_size, "url": url}
        except (urllib.error.URLError, socket.timeout, OSError, DownloadError, http.client.HTTPException) as exc:
            last_error = exc
            time.sleep(min(2 ** (attempt // len(urls)) * 0.4, 3) + random.random() * 0.2)

    raise DownloadError(f"下载失败：{dest}（{last_error}）")


def iter_parallel(items: Iterable, worker: Callable, threads: int) -> list:
    """并发执行，异常由调用方在 worker 内收集。"""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=max(1, threads)) as pool:
        return list(pool.map(worker, items))
