"""整合包加载器安装：Fabric / Quilt / Forge / NeoForge。

- Fabric、Quilt：直接取官方 meta 的 profile JSON（带 inheritsFrom），
  把其中的库下载下来，再把它写成 versions/<名字>/<名字>.json。
- Forge、NeoForge：下载官方 installer.jar，用本机 Java 以
  `--installClient <目录>` 静默安装（由官方安装器处理 processors 等步骤）。
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from . import installer as _installer
from . import java as _java
from . import manifest as _manifest
from .netio import DownloadError, fetch_json
from .rules import os_arch, os_name

FABRIC_META = "https://meta.fabricmc.net/v2"
QUILT_META = "https://meta.quiltmc.org/v3"
FORGE_PROMOS = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
FORGE_MAVEN = "https://maven.minecraftforge.net"
NEOFORGE_MAVEN = "https://maven.neoforged.net/releases"

SUPPORTED_LOADERS = ("fabric", "quilt", "forge", "neoforge")


def loader_choices() -> list[str]:
    return list(SUPPORTED_LOADERS)


# ------------------------------------------------------------------ 公共


def resolve_game(game_spec: str, opts: _installer.InstallOptions) -> tuple[str, dict, dict]:
    manifest = _manifest.get_manifest(opts.mirror, timeout=opts.timeout, retries=opts.retries)
    entry = _manifest.pick_version(manifest, game_spec)
    version_json = _manifest.get_version_json(entry, opts.mirror, timeout=opts.timeout, retries=opts.retries)
    version_json.setdefault("id", entry["id"])
    return entry["id"], entry, version_json


def ensure_vanilla(game_id: str, entry: dict, version_json: dict, opts: _installer.InstallOptions) -> bool:
    """确保原版已安装（客户端 jar 存在且哈希正确）。返回是否新装了原版。"""
    from .netio import digest_matches

    client = (version_json.get("downloads") or {}).get("client") or {}
    jar = opts.mc_dir / "versions" / game_id / f"{game_id}.jar"
    if client and digest_matches(jar, client.get("sha1"), client.get("size")):
        return False
    if opts.dry_run:
        if not opts.quiet:
            print("（试运行：不检查/安装原版）")
        return False

    vanilla_opts = dataclasses.replace(opts, name=None, loader=None, loader_version=None)
    _installer.install_payload(version_json, game_id, vanilla_opts, entry=entry)
    return True


# ------------------------------------------------------------------ Fabric / Quilt


def _meta_profile(
    base: str,
    game_id: str,
    loader_version: str | None,
    *,
    list_path: str,
    profile_path: str,
) -> tuple[dict, str | None]:
    if loader_version:
        profile = fetch_json([f"{base}{profile_path.format(game=game_id, loader=loader_version)}"])
        return profile, loader_version

    versions = fetch_json([f"{base}{list_path.format(game=game_id)}"])
    if not versions:
        raise DownloadError(f"没有找到 {game_id} 可用的加载器版本")
    stable = [item for item in versions if (item.get("loader") or {}).get("stable")]
    picked = (stable or versions)[0]
    loader = (picked.get("loader") or {}).get("version")
    profile = fetch_json([f"{base}{profile_path.format(game=game_id, loader=loader)}"])
    return profile, loader


def fabric_loader_version(game_id: str) -> str:
    profile, loader = _meta_profile(
        FABRIC_META,
        game_id,
        None,
        list_path="/versions/loader/{game}",
        profile_path="/versions/loader/{game}/{loader}/profile/json",
    )
    return loader or profile.get("id", "")


def loaders_for(game_id: str, loader: str) -> list[str]:
    if loader == "fabric":
        data = fetch_json([f"{FABRIC_META}/versions/loader/{game_id}"])
        return [item["loader"]["version"] for item in data]
    if loader == "quilt":
        data = fetch_json([f"{QUILT_META}/versions/loader/{game_id}"])
        return [item["loader"]["version"] for item in data]
    return []


def install_meta_loader(
    loader: str,
    game_spec: str,
    loader_version: str | None,
    opts: _installer.InstallOptions,
) -> _installer.InstallResult:
    game_id, entry, version_json = resolve_game(game_spec, opts)
    if loader == "fabric":
        base = FABRIC_META
    else:
        base = QUILT_META
    list_path = "/versions/loader/{game}"
    profile_path = "/versions/loader/{game}/{loader}/profile/json"

    if not opts.quiet:
        print(f"原版：{game_id}")
        print("检查原版是否已安装……")
    fresh = ensure_vanilla(game_id, entry, version_json, opts)
    if not opts.quiet:
        print("已安装原版，跳过下载。" if not fresh else "原版安装完成。")

    profile, used_loader = _meta_profile(
        base, game_id, loader_version, list_path=list_path, profile_path=profile_path
    )
    profile = dict(profile)
    profile["inheritsFrom"] = profile.get("inheritsFrom") or game_id
    target = opts.name or profile.get("id") or f"{loader}-{used_loader}-{game_id}"
    profile["id"] = target

    if not opts.quiet:
        print(f"加载器：{loader} {used_loader}")
        print(f"版本名：{target}")

    loader_opts = dataclasses.replace(opts, name=target, loader=loader, loader_version=used_loader)
    return _installer.install_payload(
        profile,
        game_id,
        loader_opts,
        loader_info={
            "loader": loader,
            "loaderVersion": used_loader,
            "gameVersion": game_id,
        },
    )


# ------------------------------------------------------------------ Forge / NeoForge


def forge_promotions() -> dict:
    data = fetch_json([FORGE_PROMOS])
    return data.get("promos") or {}


def pick_forge_version(game_id: str, requested: str | None, channel: str = "recommended") -> str:
    if requested:
        return requested
    promos = forge_promotions()
    for key in (f"{game_id}-{channel}", f"{game_id}-latest", f"{game_id}-recommended"):
        if key in promos:
            return promos[key]
    raise DownloadError(f"Forge 没有为 {game_id} 提供可用的版本（可改用 --loader-version 指定）")


def neoforge_versions() -> list[str]:
    try:
        with urllib.request.urlopen(f"{NEOFORGE_MAVEN}/net/neoforged/neoforge/maven-metadata.xml", timeout=25) as resp:
            root = ET.fromstring(resp.read())
    except Exception as exc:  # noqa: BLE001
        raise DownloadError(
            "无法访问 NeoForge 的 maven（maven.neoforged.net），可能是网络问题；"
            f"也可以手动下载 installer 后用 --installer 指定。原始错误：{exc}"
        ) from exc
    versions = [node.text for node in root.iter("version") if node.text]
    return [v for v in versions if v and not v.startswith("0.")]


def neoforge_game_version(neo_version: str) -> str:
    """NeoForge 的版本号形如 21.1.72，对应 MC 1.21.1。"""
    parts = neo_version.split(".")
    if len(parts) >= 2 and parts[0].isdigit():
        return f"1.{parts[0]}.{parts[1]}"
    return ""


def pick_neoforge_version(game_id: str | None, requested: str | None) -> str:
    if requested:
        return requested
    versions = neoforge_versions()
    if not versions:
        raise DownloadError("NeoForge 版本列表为空")
    if game_id:
        matched = [v for v in versions if neoforge_game_version(v) == game_id]
        if matched:
            return matched[-1]
    return versions[-1]


def ensure_launcher_profiles(mc_dir: Path) -> None:
    """官方 Forge/NeoForge 安装器要求目标目录里有 launcher_profiles.json。"""
    path = mc_dir / "launcher_profiles.json"
    if path.is_file():
        return
    mc_dir.mkdir(parents=True, exist_ok=True)
    _installer.write_json(path, {"profiles": {}, "settings": {}, "version": 3})


def run_installer(jar: Path, mc_dir: Path, java_exe: str, timeout: int = 3600) -> subprocess.CompletedProcess:
    mc_dir.mkdir(parents=True, exist_ok=True)
    ensure_launcher_profiles(mc_dir)
    cmd = [java_exe, "-Dfile.encoding=UTF-8", "-jar", str(jar), "--installClient", str(mc_dir.resolve())]
    proc = subprocess.run(
        cmd,
        cwd=str(jar.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    log_tail = "\n".join(((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()[-15:])
    if proc.returncode != 0:
        raise DownloadError(f"官方安装器执行失败（退出码 {proc.returncode}）：\n{log_tail}")
    return proc


def install_jar_loader(
    loader: str,
    game_spec: str,
    loader_version: str | None,
    opts: _installer.InstallOptions,
    *,
    installer_path: str | None = None,
) -> _installer.InstallResult:
    if loader == "neoforge":
        game_id, entry, version_json = resolve_game(game_spec or "latest", opts)
        if not opts.quiet:
            print(f"原版：{game_id}")
        ensure_vanilla(game_id, entry, version_json, opts)
        used = pick_neoforge_version(game_id, loader_version)
        url = f"{NEOFORGE_MAVEN}/net/neoforged/neoforge/{used}/neoforge-{used}-installer.jar"
        installer_name = f"neoforge-{used}-installer.jar"
    else:
        game_id, entry, version_json = resolve_game(game_spec, opts)
        if not opts.quiet:
            print(f"原版：{game_id}")
        ensure_vanilla(game_id, entry, version_json, opts)
        used = pick_forge_version(game_id, loader_version)
        url = f"{FORGE_MAVEN}/net/minecraftforge/forge/{game_id}-{used}/forge-{game_id}-{used}-installer.jar"
        installer_name = f"forge-{game_id}-{used}-installer.jar"

    if not opts.quiet:
        print(f"加载器：{loader} {used}")

    java_exe = _java.find_java(opts.java, _java.required_major(game_id))
    if not opts.quiet:
        print(f"Java：{java_exe}")

    if opts.dry_run:
        target = opts.name or f"{game_id}-{loader}-{used}"
        print(f"[试运行] 安装器：{installer_path or url}")
        print(f"[试运行] 命令：{java_exe} -jar <installer> --installClient {opts.mc_dir}")
        print(f"[试运行] 预计版本目录：{opts.mc_dir / 'versions' / target}")
        return _installer.InstallResult(version_id=target, version_json={}, version_dir=opts.mc_dir / "versions" / target)

    tmp = Path(tempfile.mkdtemp(prefix="mcvd-installer-"))
    try:
        if installer_path:
            jar = Path(installer_path)
        else:
            jar = tmp / installer_name
            if not opts.quiet:
                print(f"下载安装器：{url}")
            _installer.run_tasks(
                [
                    _installer.Task(
                        urls=_installer.mirror_urls(opts.mirror, url),
                        dest=jar,
                        kind="installer",
                        label=installer_name,
                    )
                ],
                opts,
                _installer.Progress(1, silent=opts.quiet),
                "安装器",
            )

        if not opts.quiet:
            print("运行官方安装器（可能需要几分钟）……")
        started = time.perf_counter()
        run_installer(jar, opts.mc_dir, java_exe)
        if not opts.quiet:
            print(f"安装器完成，耗时 {time.perf_counter() - started:.1f}s")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    installed = find_installed_loader_version(opts.mc_dir, loader, game_id, used)
    if installed is None:
        raise DownloadError(f"安装器执行完毕，但没有在 versions/ 下找到 {loader} 版本")

    target = opts.name or installed
    version_dir = opts.mc_dir / "versions" / installed
    if target != installed:
        rename_version(opts.mc_dir, installed, target)
        version_dir = opts.mc_dir / "versions" / target

    payload = None
    json_path = version_dir / f"{target}.json"
    if json_path.is_file():
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
    return _installer.InstallResult(
        version_id=target,
        version_json=payload or {},
        version_dir=version_dir,
    )


def find_installed_loader_version(mc_dir: Path, loader: str, game_id: str, loader_version: str) -> str | None:
    versions_dir = mc_dir / "versions"
    if not versions_dir.is_dir():
        return None
    candidates = []
    for child in versions_dir.iterdir():
        if not child.is_dir():
            continue
        name = child.name.lower()
        if loader not in name:
            continue
        if game_id.lower() not in name and loader != "neoforge":
            continue
        candidates.append((child.stat().st_mtime, child.name))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]


def rename_version(mc_dir: Path, old_id: str, new_id: str) -> None:
    src = mc_dir / "versions" / old_id
    dst = mc_dir / "versions" / new_id
    if dst.exists():
        raise DownloadError(f"版本目录已存在：{dst}")
    src.rename(dst)
    old_json = dst / f"{old_id}.json"
    new_json = dst / f"{new_id}.json"
    if old_json.is_file():
        payload = json.loads(old_json.read_text(encoding="utf-8"))
        payload["id"] = new_id
        _installer.write_json(new_json, payload)
        old_json.unlink()
    meta = dst / "mcvd-install.json"
    if meta.is_file():
        try:
            payload = json.loads(meta.read_text(encoding="utf-8"))
            payload["version"] = new_id
            _installer.write_json(meta, payload)
        except (OSError, json.JSONDecodeError):
            pass


def install_loader(
    loader: str,
    game_spec: str,
    loader_version: str | None,
    opts: _installer.InstallOptions,
    *,
    installer_path: str | None = None,
) -> _installer.InstallResult:
    loader = loader.strip().lower()
    if loader in ("neo", "neo-forge"):
        loader = "neoforge"
    if loader not in SUPPORTED_LOADERS:
        raise DownloadError(f"不支持的加载器：{loader}（可选：{', '.join(SUPPORTED_LOADERS)}）")
    if loader in ("fabric", "quilt"):
        return install_meta_loader(loader, game_spec, loader_version, opts)
    return install_jar_loader(loader, game_spec, loader_version, opts, installer_path=installer_path)
