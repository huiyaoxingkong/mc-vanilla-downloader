"""版本清单与版本 JSON 的解析。"""

from __future__ import annotations

import time
from typing import Sequence

from . import mirrors as _mirrors
from .netio import fetch_json


class VersionNotFound(LookupError):
    pass


def get_manifest(mirror: _mirrors.Mirror, timeout: float = 20.0, retries: int = 3) -> dict:
    """下载版本清单，失败时自动尝试其它镜像。"""
    urls = [mirror.manifest_url()]
    for other in _mirrors.ALL_MIRRORS:
        candidate = other.manifest_url()
        if candidate not in urls:
            urls.append(candidate)
    return fetch_json(urls, timeout=timeout, retries=retries)


def pick_version(manifest: dict, spec: str) -> dict:
    """把 latest / latest-snapshot / 版本号 解析成清单里的版本条目。"""
    spec_clean = spec.strip()
    lowered = spec_clean.lower()
    latest = manifest.get("latest", {})

    if lowered in ("latest", "release", "最新", "正式版"):
        target = latest.get("release")
        if not target:
            raise VersionNotFound("版本清单中没有 latest.release")
        spec_clean = target
    elif lowered in ("latest-snapshot", "snapshot", "最新快照", "快照"):
        target = latest.get("snapshot")
        if not target:
            raise VersionNotFound("版本清单中没有 latest.snapshot")
        spec_clean = target

    for entry in manifest.get("versions", []):
        if entry.get("id") == spec_clean:
            return entry
    # 大小写不敏感兜底
    for entry in manifest.get("versions", []):
        if str(entry.get("id", "")).lower() == spec_clean.lower():
            return entry
    raise VersionNotFound(f"版本清单中找不到 {spec!r}")


def filter_versions(manifest: dict, kind: str = "release", limit: int | None = None) -> list[dict]:
    versions = manifest.get("versions", [])
    if kind not in ("release", "snapshot", "all"):
        raise ValueError("kind 只能是 release / snapshot / all")
    if kind != "all":
        versions = [v for v in versions if v.get("type") == kind]
    return versions[:limit] if limit else versions


def version_json_urls(entry: dict, mirror: _mirrors.Mirror) -> list[str]:
    url = entry.get("url")
    if not url:
        raise VersionNotFound("版本条目缺少 url 字段")
    urls = [mirror.rewrite(url)]
    for other in _mirrors.ALL_MIRRORS:
        candidate = other.rewrite(url)
        if candidate not in urls:
            urls.append(candidate)
    return urls


def get_version_json(entry: dict, mirror: _mirrors.Mirror, timeout: float = 20.0, retries: int = 3) -> dict:
    return fetch_json(version_json_urls(entry, mirror), timeout=timeout, retries=retries)


def probe_mirrors(mirrors: Sequence[_mirrors.Mirror], timeout: float = 8.0) -> list[dict]:
    """逐个下载版本清单，测量可用性与耗时（用于 auto 选源）。"""
    results: list[dict] = []
    for mirror in mirrors:
        started = time.perf_counter()
        try:
            fetch_json([mirror.manifest_url()], timeout=timeout, retries=1)
            elapsed = time.perf_counter() - started
            results.append({"mirror": mirror, "ok": True, "seconds": round(elapsed, 3)})
        except Exception as exc:  # noqa: BLE001 - 探测失败不应中断流程
            results.append({"mirror": mirror, "ok": False, "seconds": None, "error": str(exc)})
    return results
