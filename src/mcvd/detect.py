"""识别 / 创建 Minecraft 游戏目录（含 PCL 版本隔离设置）。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# PCL 全局「默认版本隔离」：LaunchArgumentIndieV2
# 0=关闭，1=仅隔离可安装 Mod 的版本，2=仅隔离非正式版，
# 3=非正式版 + 可安装 Mod 的版本，4（及其他）=隔离所有版本
ISOLATION_CHOICES: list[tuple[int, str, str]] = [
    (0, "关闭", "所有版本共用同一档案，存档、Mod、资源包均为公用"),
    (1, "隔离可安装 Mod 的版本", "Forge / Fabric 等版本互相独立，原版不隔离"),
    (2, "隔离非正式版", "快照、预发布、远古、愚人节版本与其他版本隔离"),
    (3, "隔离非正式版与可安装 Mod 的版本", "以上两类都隔离"),
    (4, "隔离所有版本", "每个版本使用独立档案（PCL 默认）"),
]

ISOLATION_TEXT = {value: label for value, label, _ in ISOLATION_CHOICES}

LEGACY_ISOLATION = {0: "关闭", 1: "开启", 2: "关闭"}


def read_ini(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                result[key.strip()] = value.strip()
    except OSError:
        pass
    return result


def write_ini(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}:{value}" for key, value in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@dataclass
class VersionInfo:
    name: str
    isolated: bool | None = None  # None = 未单独设置（跟随全局/自动判定）
    reason: str = ""


@dataclass
class McDirInfo:
    path: Path
    exists: bool = False
    is_minecraft: bool = False
    has_versions: bool = False
    has_assets: bool = False
    has_libraries: bool = False
    has_launcher_profiles: bool = False
    pcl_setup: Path | None = None
    global_isolation: int | None = None
    hmcl_config: Path | None = None
    versions: list[VersionInfo] = field(default_factory=list)
    java_list: list[dict] = field(default_factory=list)
    java_checked: bool = False
    size_bytes: int = 0
    launchers: list = field(default_factory=list)
    hmcl_isolation: str = ""
    error: str = ""

    @property
    def global_isolation_text(self) -> str:
        if self.global_isolation is None:
            return "未设置（PCL 默认：隔离所有版本）"
        return ISOLATION_TEXT.get(self.global_isolation, f"未知值 {self.global_isolation}")

    @property
    def pcl_portable(self) -> bool:
        return self.pcl_setup is not None


def _dir_size(path: Path, limit_files: int = 200_000) -> int:
    total = 0
    count = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
            count += 1
            if count >= limit_files:
                return total
    return total


def inspect(path: Path, with_size: bool = True, with_java: bool = True) -> McDirInfo:
    """检测一个目录是不是 Minecraft 目录、版本情况、PCL 版本隔离设置。"""
    info = McDirInfo(path=path)
    if not path.is_dir():
        info.error = "目录不存在"
        return info
    info.exists = True
    info.has_versions = (path / "versions").is_dir()
    info.has_assets = (path / "assets").is_dir()
    info.has_libraries = (path / "libraries").is_dir()
    info.has_launcher_profiles = (path / "launcher_profiles.json").is_file()
    info.is_minecraft = info.has_versions or info.has_assets or info.has_launcher_profiles

    setup = path / "PCL" / "Setup.ini"
    if setup.is_file():
        info.pcl_setup = setup
        values = read_ini(setup)
        raw = values.get("LaunchArgumentIndieV2")
        if raw is not None:
            try:
                info.global_isolation = int(raw)
            except ValueError:
                info.global_isolation = None
        elif values.get("LaunchArgumentIndie") is not None:
            try:
                legacy = int(values["LaunchArgumentIndie"])
                info.global_isolation = 0 if legacy == 0 else None
            except ValueError:
                pass

    hmcl = path / "hmcl.json"
    if hmcl.is_file():
        info.hmcl_config = hmcl

    from . import compat

    try:
        info.launchers = compat.detect_launchers(path)
        hmcl_settings = compat.read_hmcl_settings(path)
        iso = hmcl_settings.get("defaultIsolationType") or hmcl_settings.get("versionIsolation")
        info.hmcl_isolation = str(iso) if iso is not None else ""
    except Exception:  # noqa: BLE001
        info.launchers = []
        info.hmcl_isolation = ""

    versions_dir = path / "versions"
    if versions_dir.is_dir():
        for child in sorted(versions_dir.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir():
                continue
            if not (child / f"{child.name}.json").is_file():
                continue
            item = VersionInfo(name=child.name)
            instance_setup = child / "PCL" / "Setup.ini"
            if instance_setup.is_file():
                values = read_ini(instance_setup)
                raw = values.get("VersionArgumentIndieV2")
                if raw is not None:
                    item.isolated = raw.strip().lower() == "true"
                    item.reason = "版本独立设置"
                elif values.get("VersionArgumentIndie") is not None:
                    try:
                        code = int(values["VersionArgumentIndie"])
                    except ValueError:
                        code = -1
                    if code == 1:
                        item.isolated = True
                        item.reason = "旧版独立设置"
                    elif code == 2:
                        item.isolated = False
                        item.reason = "旧版独立设置"
            if item.isolated is None:
                has_mods = (child / "mods").is_dir() and any((child / "mods").iterdir())
                has_saves = (child / "saves").is_dir() and any((child / "saves").iterdir())
                if has_mods or has_saves:
                    item.isolated = True
                    item.reason = "自动判定（存在 mods / saves）"
            info.versions.append(item)

    if with_java:
        from . import java as _java

        info.java_checked = True
        try:
            info.java_list = _java.list_javas()
        except Exception:  # noqa: BLE001
            info.java_list = []

    if with_size:
        try:
            info.size_bytes = _dir_size(path)
        except OSError:
            info.size_bytes = 0
    return info


def describe(info: McDirInfo, brief: bool = True) -> str:
    """把检测结果拼成给人看的多行文本（brief=True 时只给摘要）。"""
    lines: list[str] = []
    if not info.exists:
        return "目录不存在，可以选择其它目录或点「创建游戏文件夹」。"
    if info.is_minecraft:
        lines.append("✔ 已识别为 Minecraft 目录")
    else:
        lines.append("⚠ 这个目录还不是 Minecraft 目录（缺少 versions/、assets/ 等）")

    if info.versions:
        names = "、".join(item.name for item in info.versions[:4])
        more = "…" if len(info.versions) > 4 else ""
        lines.append(f"版本：{len(info.versions)} 个（{names}{more}）")
    else:
        lines.append("版本：暂无已安装版本")

    marks = []
    marks.append("assets ✔" if info.has_assets else "assets ✘")
    marks.append("libraries ✔" if info.has_libraries else "libraries ✘")
    marks.append("launcher_profiles.json ✔" if info.has_launcher_profiles else "launcher_profiles.json ✘")
    lines.append("资源：" + "  ".join(marks))

    if info.pcl_setup:
        lines.append(f"PCL 便携配置：有（默认版本隔离 = {info.global_isolation_text}）")
    else:
        lines.append(f"PCL 便携配置：无（如需用 PCL，默认版本隔离按 PCL 默认 = {ISOLATION_TEXT[4]}）")

    if info.hmcl_config:
        lines.append("HMCL 配置：检测到 hmcl.json")

    if info.launchers:
        present = [item for item in info.launchers if item.present]
        if present:
            parts = []
            for item in present:
                if item.key == "official":
                    parts.append(f"{item.name}（{item.detail}）")
                elif item.key == "hmcl" and info.hmcl_isolation:
                    parts.append(f"{item.name}（默认隔离 {info.hmcl_isolation}）")
                else:
                    parts.append(item.name)
            lines.append("启动器：" + "、".join(parts))
        else:
            lines.append("启动器：未检测到配置（版本仍可被 PCL / HMCL / 官方启动器直接扫描）")

    if info.versions:
        on = sum(1 for item in info.versions if item.isolated is True)
        off = sum(1 for item in info.versions if item.isolated is False)
        follow = len(info.versions) - on - off
        if brief:
            lines.append(f"版本隔离：已开启 {on} 个 · 已关闭 {off} 个 · 跟随默认 {follow} 个（点「详情」可看逐个版本）")
        else:
            lines.append(f"版本隔离：已开启 {on} 个 · 已关闭 {off} 个 · 跟随默认 {follow} 个")
            for item in info.versions[:30]:
                if item.isolated is True:
                    state = "已开启"
                elif item.isolated is False:
                    state = "已关闭"
                else:
                    state = "跟随默认设置"
                suffix = f"（{item.reason}）" if item.reason else ""
                lines.append(f"  · {item.name}：{state}{suffix}")
            if len(info.versions) > 30:
                lines.append(f"  …… 其余 {len(info.versions) - 30} 个略")

    if info.java_checked:
        if info.java_list:
            majors = "、".join(str(item["major"]) for item in info.java_list if item["major"])
            lines.append(f"Java：{len(info.java_list)} 个可用（{majors}）")
        else:
            lines.append("Java：未检测到（安装 Forge / 新版游戏需要 Java）")

    if info.size_bytes:
        from .netio import human_bytes

        lines.append(f"占用空间：{human_bytes(info.size_bytes)}")
    return "\n".join(lines)


def create_mc_dir(
    parent: Path,
    name: str = ".minecraft",
    isolation: int | None = 4,
    write_pcl: bool = True,
    make_structure: bool = True,
) -> Path:
    """创建游戏文件夹，可选写入 PCL 便携配置里的默认版本隔离。"""
    name = name.strip() or ".minecraft"
    target = Path(parent).expanduser() / name
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"目标目录已存在且非空：{target}")
    target.mkdir(parents=True, exist_ok=True)

    if make_structure:
        (target / "versions").mkdir(exist_ok=True)
        (target / "assets").mkdir(exist_ok=True)
        (target / "libraries").mkdir(exist_ok=True)
    if not (target / "launcher_profiles.json").is_file():
        (target / "launcher_profiles.json").write_text(
            json.dumps({"profiles": {}, "settings": {}, "version": 3}, indent=2) + "\n",
            encoding="utf-8",
        )
    if write_pcl and isolation is not None:
        write_ini(target / "PCL" / "Setup.ini", {"LaunchArgumentIndieV2": str(isolation)})
    return target
