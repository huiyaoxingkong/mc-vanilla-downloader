"""启动器兼容层。

目标：装好的版本能被这些启动器直接识别：

- 官方启动器（Minecraft Launcher）：除 `versions/<id>/` 外，还需要在
  `launcher_profiles.json` 的 `profiles` 里注册一条自定义配置（`type: "custom"`）；
- HMCL：扫描 `versions/<id>/<id>.json`，标准结构即可；新版本把设置放在
  `config/launcher-settings.json`，老版本用 `hmcl.json`；
- PCL2 / PCL2-CE：便携模式读取 `PCL/Setup.ini`，扫描 `versions/`；
- BakaXL / LauncherX / MSL 等国内启动器：同样扫描标准 `.minecraft` 结构。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

LAUNCHER_PROFILES = "launcher_profiles.json"

DEFAULT_SETTINGS = {
    "crashAssistance": False,
    "enableAdvanced": False,
    "enableAnalytics": False,
    "enableHistorical": False,
    "enableReleases": True,
    "enableSnapshots": False,
    "keepLauncherOpen": True,
    "profileSorting": "ByLastPlayed",
    "showGameLog": False,
    "showMenu": False,
    "soundOn": False,
}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


@dataclass
class LauncherPresence:
    key: str
    name: str
    present: bool
    detail: str = ""


def load_profiles(mc_dir: Path) -> dict:
    path = mc_dir / LAUNCHER_PROFILES
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload.setdefault("profiles", {})
                payload.setdefault("settings", dict(DEFAULT_SETTINGS))
                payload.setdefault("version", 6)
                return payload
        except (OSError, json.JSONDecodeError):
            pass
    return {"profiles": {}, "settings": dict(DEFAULT_SETTINGS), "version": 6}


def save_profiles(mc_dir: Path, payload: dict) -> None:
    path = mc_dir / LAUNCHER_PROFILES
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def official_profile_entries(mc_dir: Path) -> list[dict]:
    payload = load_profiles(mc_dir)
    return list((payload.get("profiles") or {}).values())


def has_official_profile(mc_dir: Path, version_id: str) -> bool:
    return any(
        str(entry.get("lastVersionId", "")).lower() == version_id.lower()
        for entry in official_profile_entries(mc_dir)
    )


def register_official_profile(
    mc_dir: Path,
    version_id: str,
    *,
    display_name: str | None = None,
    icon: str = "Grass",
    overwrite: bool = True,
    game_dir: Path | str | None = None,
) -> str | None:
    """在 launcher_profiles.json 里注册 / 更新一条自定义配置。

    game_dir：官方启动器用这个字段决定「游戏目录」；设置成 versions/<id> 时，
    隔离版本里的存档就能在官方启动器里看到。
    """
    payload = load_profiles(mc_dir)
    profiles: dict = payload["profiles"]

    name = display_name or version_id
    target_game_dir = str(game_dir) if game_dir is not None else None
    existing_id = None
    for key, entry in profiles.items():
        if str(entry.get("lastVersionId", "")).lower() != version_id.lower():
            continue
        entry_game_dir = entry.get("gameDir")
        if target_game_dir is None:
            if entry_game_dir:
                continue
        else:
            if not entry_game_dir:
                continue
            try:
                if Path(entry_game_dir).resolve() != Path(target_game_dir).resolve():
                    continue
            except OSError:
                continue
        existing_id = key
        break

    if existing_id and not overwrite:
        return existing_id

    now = _now_iso()
    if existing_id:
        entry = profiles[existing_id]
        entry["name"] = name
        entry.setdefault("created", now)
        entry["lastUsed"] = now
        if target_game_dir is not None:
            entry["gameDir"] = target_game_dir
    else:
        existing_id = uuid.uuid4().hex
        entry = {
            "created": now,
            "icon": icon,
            "lastUsed": now,
            "lastVersionId": version_id,
            "name": name,
            "type": "custom",
        }
        if target_game_dir is not None:
            entry["gameDir"] = target_game_dir
        profiles[existing_id] = entry

    payload.setdefault("settings", dict(DEFAULT_SETTINGS))
    payload.setdefault("version", 6)
    save_profiles(mc_dir, payload)
    return existing_id


def ensure_official_launcher_profiles(mc_dir: Path) -> None:
    """官方启动器 / Forge 安装器要求目录里有合法的 launcher_profiles.json。"""
    mc_dir.mkdir(parents=True, exist_ok=True)
    if not (mc_dir / LAUNCHER_PROFILES).is_file():
        save_profiles(mc_dir, {"profiles": {}, "settings": dict(DEFAULT_SETTINGS), "version": 6})


def read_hmcl_settings(mc_dir: Path) -> dict:
    """尽量读出 HMCL 的隔离相关设置（兼容新旧两种配置位置）。"""
    result: dict = {}
    legacy = mc_dir / "hmcl.json"
    if legacy.is_file():
        try:
            raw = json.loads(legacy.read_text(encoding="utf-8", errors="replace"))
            if isinstance(raw, dict):
                for key in ("versionIsolation", "isolation", "defaultIsolationType"):
                    if key in raw:
                        result[key] = raw[key]
                result["_source"] = "hmcl.json"
        except (OSError, json.JSONDecodeError):
            pass
    modern = mc_dir / "config" / "launcher-settings.json"
    if modern.is_file():
        try:
            raw = json.loads(modern.read_text(encoding="utf-8", errors="replace"))
            if isinstance(raw, dict):
                result["_source"] = "config/launcher-settings.json"
                result.update({k: v for k, v in raw.items() if "isolation" in k.lower()})
        except (OSError, json.JSONDecodeError):
            pass
    return result


def detect_launchers(mc_dir: Path) -> list[LauncherPresence]:
    """识别这个目录被哪些启动器使用过 / 配置过。"""
    items: list[LauncherPresence] = []

    pcl_setup = mc_dir / "PCL" / "Setup.ini"
    items.append(
        LauncherPresence("pcl", "PCL2 / PCL2-CE", pcl_setup.is_file(),
                         "PCL/Setup.ini（便携模式）" if pcl_setup.is_file() else "未发现便携配置")
    )

    hmcl_legacy = mc_dir / "hmcl.json"
    hmcl_modern = mc_dir / "config" / "launcher-settings.json"
    hmcl_present = hmcl_legacy.is_file() or hmcl_modern.is_file()
    hmcl_detail = []
    if hmcl_legacy.is_file():
        hmcl_detail.append("hmcl.json")
    if hmcl_modern.is_file():
        hmcl_detail.append("config/launcher-settings.json")
    settings = read_hmcl_settings(mc_dir)
    iso = settings.get("defaultIsolationType") or settings.get("versionIsolation")
    if iso is not None:
        hmcl_detail.append(f"默认隔离={iso}")
    items.append(LauncherPresence("hmcl", "HMCL", hmcl_present, "、".join(hmcl_detail) or "未发现配置"))

    baka = (mc_dir / "BakaXL").is_dir() or (mc_dir / "BakaXL.exe").is_file()
    items.append(LauncherPresence("bakaxl", "BakaXL", baka, "BakaXL 目录" if baka else "未发现"))

    launcherx = (mc_dir / "launcherx.json").is_file()
    items.append(LauncherPresence("launcherx", "LauncherX", launcherx,
                                  "launcherx.json" if launcherx else "未发现"))

    msl = (mc_dir / "MSL.exe").is_file() or (mc_dir / "MSL").is_dir()
    items.append(LauncherPresence("msl", "MSL", msl, "MSL 文件" if msl else "未发现"))

    profiles_present = (mc_dir / LAUNCHER_PROFILES).is_file()
    count = len(official_profile_entries(mc_dir)) if profiles_present else 0
    items.append(
        LauncherPresence("official", "官方启动器", profiles_present,
                         f"launcher_profiles.json（{count} 个配置）" if profiles_present else "未发现")
    )
    return items


def describe_launchers(mc_dir: Path) -> str:
    items = detect_launchers(mc_dir)
    present = [item for item in items if item.present]
    if not present:
        return "启动器：未检测到（可以直接被 PCL / HMCL / 官方启动器扫描）"
    parts = [f"{item.name}（{item.detail}）" for item in present]
    return "启动器：" + "、".join(parts)
