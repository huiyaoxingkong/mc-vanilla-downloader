"""Minecraft 版本 JSON 中的 rules 判定。

官方规范（https://minecraft.wiki/w/Client.json#Libraries）：
- 没有 rules 时，库默认适用于所有平台；
- 有 rules 时，默认不适用，按顺序应用匹配的规则，最后一条命中的规则决定结果。
"""

from __future__ import annotations

import platform
import sys


def os_name() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "osx"
    return "linux"


def os_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    if machine in ("i386", "i686", "x86"):
        return "x86"
    return machine


def bitness() -> str:
    """用于 ${arch} 占位符：64 位系统返回 64，32 位返回 32。"""
    return "64" if sys.maxsize > 2**32 else "32"


def _rule_matches(rule: dict, current_os: str, current_arch: str) -> bool:
    os_rule = rule.get("os")
    if os_rule:
        name = os_rule.get("name")
        if name and name != current_os:
            return False
        arch = os_rule.get("arch")
        if arch and arch != current_arch:
            return False
        # version 字段（Windows 10 等）极少出现于原版库，忽略即可
    features = rule.get("features")
    if features:
        # 原版下载场景中 features 只会是 demo / custom_resolution 等，
        # 我们一律按 False 处理（与官方启动器默认行为一致）。
        return all(not enabled for enabled in features.values())
    return True


def is_allowed(rules: list[dict] | None, current_os: str | None = None, current_arch: str | None = None) -> bool:
    current_os = current_os or os_name()
    current_arch = current_arch or os_arch()
    if not rules:
        return True
    allowed = False
    for rule in rules:
        if _rule_matches(rule, current_os, current_arch):
            allowed = rule.get("action") == "allow"
    return allowed
