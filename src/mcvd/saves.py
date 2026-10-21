"""存档（世界）发现与「注册到官方启动器」。

背景：启用版本隔离后，存档不再放在 `.minecraft/saves`，而是放在
`versions/<版本>/saves`。官方启动器默认只看 `.minecraft/saves`，所以这些
隔离存档在官方启动器里“看不见”。解决办法是往 `launcher_profiles.json`
写一条带 `gameDir`（指向 versions/<版本>）的自定义配置。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from . import compat


@dataclass
class SaveInfo:
    name: str
    path: Path
    version: str | None = None  # 所属版本目录名；None 表示全局 saves
    isolated: bool = False
    size: int = 0
    mtime: float = 0.0

    @property
    def label(self) -> str:
        return f"{self.name}"


def _looks_like_save(path: Path) -> bool:
    return path.is_dir() and (path / "level.dat").is_file()


def _dir_size(path: Path, limit: int = 50_000) -> int:
    total = 0
    count = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
            count += 1
            if count >= limit:
                return total
    return total


def _save_mtime(path: Path) -> float:
    try:
        return (path / "level.dat").stat().st_mtime
    except OSError:
        return 0.0


def discover_saves(mc_dir: Path, with_size: bool = True) -> list[SaveInfo]:
    """找出全局存档与各隔离版本的存档。"""
    saves: list[SaveInfo] = []

    global_saves = mc_dir / "saves"
    if global_saves.is_dir():
        for child in sorted(global_saves.iterdir()):
            if _looks_like_save(child):
                saves.append(
                    SaveInfo(
                        name=child.name,
                        path=child,
                        version=None,
                        isolated=False,
                        size=_dir_size(child) if with_size else 0,
                        mtime=_save_mtime(child),
                    )
                )

    versions_dir = mc_dir / "versions"
    if versions_dir.is_dir():
        for version_dir in sorted(versions_dir.iterdir()):
            if not version_dir.is_dir():
                continue
            version_saves = version_dir / "saves"
            if not version_saves.is_dir():
                continue
            for child in sorted(version_saves.iterdir()):
                if _looks_like_save(child):
                    saves.append(
                        SaveInfo(
                            name=child.name,
                            path=child,
                            version=version_dir.name,
                            isolated=True,
                            size=_dir_size(child) if with_size else 0,
                            mtime=_save_mtime(child),
                        )
                    )

    saves.sort(key=lambda item: item.mtime, reverse=True)
    return saves


def official_game_dir(mc_dir: Path, save: SaveInfo) -> Path | None:
    """官方启动器里能看见这个存档所需要的 gameDir。"""
    if save.isolated and save.version:
        return mc_dir / "versions" / save.version
    return None


def register_save(mc_dir: Path, save: SaveInfo, profile_name: str | None = None) -> str | None:
    """把存档（或其所属隔离版本）注册成官方启动器的一条配置。"""
    game_dir = official_game_dir(mc_dir, save)
    version_id = save.version or "latest-release"
    name = profile_name or (f"{save.name}" + (f"（{save.version}）" if save.version else ""))
    return compat.register_official_profile(
        mc_dir,
        version_id,
        display_name=name,
        icon="Grass",
        game_dir=game_dir,
    )


def register_all_isolated(mc_dir: Path) -> int:
    """把所有隔离版本注册到官方启动器，返回成功条数。"""
    count = 0
    for version_dir in sorted((mc_dir / "versions").glob("*")):
        if not version_dir.is_dir():
            continue
        if not (version_dir / f"{version_dir.name}.json").is_file():
            continue
        if not (version_dir / "saves").is_dir():
            continue
        if compat.register_official_profile(
            mc_dir, version_dir.name, display_name=version_dir.name, game_dir=version_dir
        ):
            count += 1
    return count


def save_summary(mc_dir: Path) -> dict:
    saves = discover_saves(mc_dir, with_size=False)
    isolated = [item for item in saves if item.isolated]
    return {
        "total": len(saves),
        "isolated": len(isolated),
        "global": len(saves) - len(isolated),
        "versions": sorted({item.version for item in isolated if item.version}),
    }
