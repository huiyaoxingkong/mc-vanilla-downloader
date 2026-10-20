"""把原版 / 加载器版本安装到 .minecraft/versions/<id>/。

安装完成后的目录结构与官方启动器 / PCL 一致：

    <mc_dir>/
      versions/<id>/<id>.json
      versions/<id>/<id>.jar
      libraries/<maven 路径>.jar
      assets/indexes/<assetIndexId>.json
      assets/objects/<hash 前两位>/<hash>

PCL、HMCL、官方启动器都能直接识别这套结构。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import manifest as _manifest
from . import mirrors as _mirrors
from .netio import DownloadError, download_file, fetch_json, human_bytes, iter_parallel
from .rules import bitness, is_allowed, os_arch, os_name

ASSET_BASE = "https://resources.download.minecraft.net"


@dataclass
class InstallOptions:
    mc_dir: Path
    mirror: _mirrors.Mirror
    threads: int = 16
    with_assets: bool = True
    with_libraries: bool = True
    dry_run: bool = False
    force: bool = False
    timeout: float = 20.0
    retries: int = 3
    quiet: bool = False
    name: str | None = None  # 自定义版本名（PCL 的“版本名称”）
    loader: str | None = None
    loader_version: str | None = None
    java: str | None = None
    progress_cb: object | None = None  # GUI 用：Callable[[processed, total], None]


@dataclass
class Task:
    urls: list[str]
    dest: Path
    sha1: str | None = None
    size: int | None = None
    kind: str = "file"
    label: str = ""


@dataclass
class InstallResult:
    version_id: str
    version_json: dict
    processed: int = 0
    bytes_downloaded: int = 0
    elapsed: float = 0.0
    version_dir: Path | None = None


def maven_path(name: str) -> str:
    """把 Maven 坐标 group:artifact:version[:classifier][@ext] 转成相对路径。"""
    classifier = None
    ext = "jar"
    coords = name
    if "@" in coords:
        coords, ext = coords.rsplit("@", 1)
    parts = coords.split(":")
    if len(parts) < 3:
        raise ValueError(f"无法解析 Maven 坐标：{name}")
    group, artifact, version = parts[0], parts[1], parts[2]
    if len(parts) >= 4:
        classifier = parts[3]
    filename = f"{artifact}-{version}" + (f"-{classifier}" if classifier else "") + f".{ext}"
    return f"{group.replace('.', '/')}/{artifact}/{version}/{filename}"


def library_entries(lib: dict, current_os: str, current_arch: str) -> list[dict]:
    """返回该库在当前平台需要下载的文件（artifact + natives）。"""
    if not is_allowed(lib.get("rules"), current_os, current_arch):
        return []
    downloads = lib.get("downloads") or {}
    entries: list[dict] = []
    artifact = downloads.get("artifact")
    if artifact and artifact.get("url"):
        entries.append(artifact)
    natives = lib.get("natives") or {}
    native_key = natives.get(current_os)
    if native_key:
        native_key = native_key.replace("${arch}", bitness())
        classifier = (downloads.get("classifiers") or {}).get(native_key)
        if classifier and classifier.get("url"):
            entries.append(classifier)
    return entries


def library_files(lib: dict, current_os: str | None = None, current_arch: str | None = None) -> list[dict]:
    """把一条库记录展开成 {path, url, sha1, size} 列表。

    兼容两种写法：
    1) downloads.artifact 里直接给 url/path（Mojang 原版、Forge 新版）；
    2) 只给 name + url 基地址（Fabric/Quilt 的 maven），路径由坐标推出。
    """
    current_os = current_os or os_name()
    current_arch = current_arch or os_arch()
    if not is_allowed(lib.get("rules"), current_os, current_arch):
        return []

    downloads = lib.get("downloads") or {}
    name = lib.get("name", "")
    base_url = (lib.get("url") or "").rstrip("/") + "/"
    files: list[dict] = []

    artifact = downloads.get("artifact")
    if artifact and artifact.get("url"):
        files.append(
            {
                "path": artifact.get("path") or maven_path(name),
                "url": artifact["url"],
                "sha1": artifact.get("sha1"),
                "size": artifact.get("size"),
            }
        )
    elif name and base_url:
        rel = maven_path(name)
        files.append({"path": rel, "url": base_url + rel, "sha1": None, "size": None})

    natives = lib.get("natives") or {}
    native_key = natives.get(current_os)
    if native_key:
        native_key = native_key.replace("${arch}", bitness())
        classifier = (downloads.get("classifiers") or {}).get(native_key)
        if classifier and classifier.get("url"):
            files.append(
                {
                    "path": classifier.get("path") or maven_path(f"{name}:{native_key}"),
                    "url": classifier["url"],
                    "sha1": classifier.get("sha1"),
                    "size": classifier.get("size"),
                }
            )
    return files


def relative_path(entry: dict, lib_name: str) -> str:
    path = entry.get("path")
    return path if path else maven_path(lib_name)


def mirror_urls(mirror: _mirrors.Mirror, official_url: str) -> list[str]:
    """主源地址 + 其它镜像作为回退。"""
    urls = [mirror.rewrite(official_url)]
    for other in _mirrors.ALL_MIRRORS:
        candidate = other.rewrite(official_url)
        if candidate not in urls:
            urls.append(candidate)
    return urls


def build_client_task(version_json: dict, target_id: str, mc_dir: Path, opts: InstallOptions) -> Task | None:
    client = (version_json.get("downloads") or {}).get("client")
    if not client or not client.get("url"):
        return None
    dest = mc_dir / "versions" / target_id / f"{target_id}.jar"
    return Task(
        urls=mirror_urls(opts.mirror, client["url"]),
        dest=dest,
        sha1=client.get("sha1"),
        size=client.get("size"),
        kind="client",
        label=f"versions/{target_id}/{target_id}.jar",
    )


def build_library_tasks(version_json: dict, mc_dir: Path, opts: InstallOptions) -> list[Task]:
    tasks: list[Task] = []
    for lib in version_json.get("libraries", []):
        for entry in library_files(lib):
            dest = mc_dir / "libraries" / Path(entry["path"])
            tasks.append(
                Task(
                    urls=mirror_urls(opts.mirror, entry["url"]),
                    dest=dest,
                    sha1=entry.get("sha1"),
                    size=entry.get("size"),
                    kind="library",
                    label=entry["path"],
                )
            )
    return tasks


def build_asset_tasks(index: dict, mc_dir: Path, opts: InstallOptions) -> list[Task]:
    tasks: list[Task] = []
    for name, obj in (index.get("objects") or {}).items():
        digest = obj.get("hash")
        if not digest:
            continue
        sub = digest[:2]
        url = f"{ASSET_BASE}/{sub}/{digest}"
        dest = mc_dir / "assets" / "objects" / sub / digest
        tasks.append(
            Task(
                urls=mirror_urls(opts.mirror, url),
                dest=dest,
                sha1=digest,
                size=obj.get("size"),
                kind="asset",
                label=name,
            )
        )
    return tasks


class Progress:
    def __init__(self, total_files: int, silent: bool = False, callback: object | None = None) -> None:
        self.total_files = total_files
        self.processed = 0
        self.downloaded_bytes = 0
        self.callback = callback
        self._lock = threading.Lock()
        self._last = 0.0
        self.silent = silent
        self.start = time.perf_counter()

    def add_bytes(self, count: int) -> None:
        with self._lock:
            self.downloaded_bytes += count

    def tick(self) -> None:
        with self._lock:
            self.processed += 1
            processed, total = self.processed, self.total_files
            now = time.perf_counter()
            do_render = not self.silent and now - self._last >= 0.3
            if do_render:
                self._last = now
        if self.callback is not None:
            try:
                self.callback(processed, total)
            except Exception:  # noqa: BLE001 - 回调失败不影响下载
                pass
        if do_render:
            self._render()

    def _render(self) -> None:
        elapsed = max(time.perf_counter() - self.start, 1e-6)
        line = (
            f"\r  {self.processed}/{self.total_files} 个文件"
            f" | {human_bytes(self.downloaded_bytes)}"
            f" | {human_bytes(self.downloaded_bytes / elapsed)}/s"
            f" | {elapsed:0.0f}s"
        )
        sys.stderr.write(line[:120].ljust(78))
        sys.stderr.flush()

    def finish(self) -> None:
        if self.silent:
            return
        elapsed = max(time.perf_counter() - self.start, 1e-6)
        sys.stderr.write("\r" + " " * 90 + "\r")
        sys.stderr.write(
            f"  处理 {self.processed} 个文件，下载 {human_bytes(self.downloaded_bytes)}"
            f"，耗时 {elapsed:0.1f}s，平均 {human_bytes(self.downloaded_bytes / elapsed)}/s\n"
        )
        sys.stderr.flush()


def run_tasks(tasks: list[Task], opts: InstallOptions, progress: Progress, kind: str) -> None:
    if not tasks:
        return

    def worker(task: Task) -> None:
        download_file(
            task.urls,
            task.dest,
            sha1=task.sha1,
            size=task.size,
            timeout=opts.timeout,
            retries=opts.retries,
            progress=progress.add_bytes,
            force=opts.force,
        )
        progress.tick()

    errors: list[str] = []

    def safe_worker(task: Task) -> None:
        try:
            worker(task)
        except Exception as exc:  # noqa: BLE001 - 汇总后统一抛出
            errors.append(f"{task.kind}:{task.label}: {exc}")

    iter_parallel(tasks, safe_worker, opts.threads)
    if errors:
        raise DownloadError(f"{kind}下载失败：{len(errors)} 个文件出错，例如 {errors[0]}")


_run_tasks = run_tasks  # 兼容旧名字


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def install(version_spec: str, opts: InstallOptions) -> InstallResult:
    manifest = _manifest.get_manifest(opts.mirror, timeout=opts.timeout, retries=opts.retries)
    entry = _manifest.pick_version(manifest, version_spec)
    version_id = entry["id"]
    version_json = _manifest.get_version_json(entry, opts.mirror, timeout=opts.timeout, retries=opts.retries)
    version_json.setdefault("id", version_id)
    return install_payload(version_json, version_id, opts, entry=entry)


def install_payload(
    version_json: dict,
    base_version_id: str,
    opts: InstallOptions,
    *,
    entry: dict | None = None,
    loader_info: dict | None = None,
) -> InstallResult:
    """按给定的版本 JSON 安装。

    适用于：
    - 原版（JSON 自带 downloads.client / assetIndex）；
    - Fabric/Quilt（JSON 只有 libraries，通过 inheritsFrom 继承原版）；
    - 其它自定义版本（例如把某个版本的 JSON 换个名字再装一遍）。
    """
    started = time.perf_counter()
    mc_dir = opts.mc_dir
    target_id = opts.name or base_version_id
    version_json = dict(version_json)
    version_json["id"] = target_id
    version_dir = mc_dir / "versions" / target_id

    asset_index = version_json.get("assetIndex") or {}
    index_payload: dict | None = None
    index_task: Task | None = None
    if opts.with_assets and asset_index.get("url"):
        index_name = asset_index.get("id", "index")
        index_task = Task(
            urls=mirror_urls(opts.mirror, asset_index["url"]),
            dest=mc_dir / "assets" / "indexes" / f"{index_name}.json",
            sha1=asset_index.get("sha1"),
            size=asset_index.get("size"),
            kind="asset-index",
            label=f"assets/indexes/{index_name}.json",
        )
        index_payload = fetch_json(index_task.urls, timeout=opts.timeout, retries=opts.retries)

    tasks: list[Task] = []
    client_task = build_client_task(version_json, target_id, mc_dir, opts)
    if client_task:
        tasks.append(client_task)
    if opts.with_libraries:
        tasks.extend(build_library_tasks(version_json, mc_dir, opts))
    if index_payload is not None:
        tasks.extend(build_asset_tasks(index_payload, mc_dir, opts))

    total_files = len(tasks) + (1 if index_task else 0)
    total_bytes = sum(t.size or 0 for t in tasks) + ((index_task.size or 0) if index_task else 0)

    if opts.dry_run:
        by_kind: dict[str, list[Task]] = {}
        for task in tasks:
            by_kind.setdefault(task.kind, []).append(task)
        print(f"目标版本：{target_id}" + (f"（继承自 {base_version_id}）" if target_id != base_version_id else ""))
        print(f"目标目录：{version_dir}")
        print(f"下载源：{opts.mirror.name}")
        print("\n[试运行] 计划下载：")
        for kind, group in by_kind.items():
            size = sum(t.size or 0 for t in group)
            print(f"  - {kind:<12} {len(group):>5} 个文件  {human_bytes(size)}")
        print(f"  - {'合计':<12} {total_files:>5} 个文件  {human_bytes(total_bytes)}")
        return InstallResult(version_id=target_id, version_json=version_json, version_dir=version_dir)

    if not opts.quiet:
        label = f"{target_id}"
        if target_id != base_version_id:
            label += f"（继承自 {base_version_id}）"
        print(f"目标版本：{label}")
        if entry:
            print(f"游戏版本：{base_version_id}（{entry.get('type')}，{entry.get('releaseTime', '?')}）")
        print(f"目标目录：{version_dir}")
        print(f"下载源：{opts.mirror.name}（{opts.mirror.description}）")
        print(f"共 {total_files} 个文件，约 {human_bytes(total_bytes)}，并发 {opts.threads}\n")

    progress = Progress(total_files, silent=opts.quiet, callback=opts.progress_cb)

    if index_task is not None:
        run_tasks([index_task], opts, progress, "资源索引")

    if not opts.quiet:
        print("[1/3] 客户端 jar 与版本 JSON")
    if client_task:
        run_tasks([client_task], opts, progress, "客户端")
    write_json(version_dir / f"{target_id}.json", version_json)

    library_tasks = [t for t in tasks if t.kind == "library"]
    if library_tasks:
        if not opts.quiet:
            print(f"[2/3] 依赖库（{len(library_tasks)} 个）")
        run_tasks(library_tasks, opts, progress, "依赖库")

    asset_tasks = [t for t in tasks if t.kind == "asset"]
    if asset_tasks:
        if not opts.quiet:
            print(f"[3/3] 资源文件（{len(asset_tasks)} 个）")
        run_tasks(asset_tasks, opts, progress, "资源")

    if index_payload is not None:
        _materialize_legacy_assets(index_payload, asset_index.get("id", "legacy"), mc_dir)

    meta = {
        "installer": "mcvd",
        "installedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "version": target_id,
        "baseVersion": base_version_id,
        "mirror": opts.mirror.name,
        "fileCount": total_files,
    }
    if loader_info:
        meta.update(loader_info)
    write_json(version_dir / "mcvd-install.json", meta)

    progress.finish()
    elapsed = time.perf_counter() - started
    result = InstallResult(
        version_id=target_id,
        version_json=version_json,
        processed=progress.processed,
        bytes_downloaded=progress.downloaded_bytes,
        elapsed=elapsed,
        version_dir=version_dir,
    )
    if not opts.quiet:
        print(f"\n安装完成：{target_id} -> {version_dir}")
        print(f"处理 {result.processed} 个文件，下载 {human_bytes(result.bytes_downloaded)}，耗时 {elapsed:0.1f}s")
    return result


def _materialize_legacy_assets(index: dict, index_id: str, mc_dir: Path) -> None:
    """1.6~1.7 时代的资源索引带 virtual / map_to_resources 标记。

    官方启动器会把 objects 再复制一份成可读文件名；这里一并处理，
    保证 PCL 启动这些古老版本时也能找到资源。
    """
    objects_dir = mc_dir / "assets" / "objects"
    targets: list[Path] = []
    if index.get("virtual"):
        targets.append(mc_dir / "assets" / "virtual" / index_id)
    if index.get("map_to_resources"):
        targets.append(mc_dir / "resources")

    for base in targets:
        for name, obj in (index.get("objects") or {}).items():
            digest = obj.get("hash")
            if not digest:
                continue
            source = objects_dir / digest[:2] / digest
            if not source.is_file():
                continue
            dest = base / name
            if dest.is_file():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(source, dest)  # 硬链接，省空间
            except OSError:
                shutil.copy2(source, dest)
