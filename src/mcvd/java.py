"""查找本机可用的 Java（运行 Forge/NeoForge 安装器需要）。"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
from pathlib import Path

_JAVA_VERSION_RE = re.compile(r'version "(\d+)(?:\.(\d+))?')


def java_major(java_exe: str) -> int | None:
    try:
        proc = subprocess.run(
            [java_exe, "-version"],
            capture_output=True,
            text=True,
            timeout=20,
            encoding="utf-8",
            errors="replace",
        )
        text = (proc.stderr or "") + (proc.stdout or "")
    except (OSError, subprocess.SubprocessError):
        return None
    match = _JAVA_VERSION_RE.search(text)
    if not match:
        return None
    major = int(match.group(1))
    if major == 1 and match.group(2):
        major = int(match.group(2))
    return major


def _candidate_paths() -> list[str]:
    candidates: list[str] = []
    if os.environ.get("JAVA_HOME"):
        candidates.append(str(Path(os.environ["JAVA_HOME"]) / "bin" / "java.exe"))
    found = shutil.which("java")
    if found:
        candidates.append(found)

    patterns = [
        r"C:\Program Files\Java\*\bin\java.exe",
        r"C:\Program Files (x86)\Java\*\bin\java.exe",
        r"D:\Program Files\Java\*\bin\java.exe",
        r"C:\Program Files\Eclipse Adoptium\*\bin\java.exe",
        r"C:\Program Files\Microsoft\jdk*\bin\java.exe",
        r"C:\Program Files\Zulu\*\bin\java.exe",
        r"C:\Program Files\BellSoft\*\bin\java.exe",
        str(Path(os.environ.get("APPDATA", "")) / ".minecraft" / "runtime" / "*" / "bin" / "java.exe"),
        str(Path(os.environ.get("APPDATA", "")) / ".minecraft" / "runtime" / "*" / "*" / "bin" / "java.exe"),
    ]
    for pattern in patterns:
        if not pattern:
            continue
        candidates.extend(glob.glob(pattern))
    return candidates


def list_javas() -> list[dict]:
    seen: dict[str, int | None] = {}
    for path in _candidate_paths():
        if not path or not os.path.isfile(path):
            continue
        resolved = os.path.normcase(os.path.abspath(path))
        if resolved in seen:
            continue
        seen[resolved] = java_major(path)
    result = [{"path": path, "major": major} for path, major in seen.items()]
    result.sort(key=lambda item: (item["major"] is None, item["major"] or 0))
    return result


def required_major(game_version: str) -> int:
    """按游戏版本推断运行 Forge 安装器所需的 Java 大版本。"""
    match = re.match(r"(\d+)\.(\d+)", game_version or "")
    if not match:
        return 17
    major, minor = int(match.group(1)), int(match.group(2))
    if major >= 26:
        return 25
    if major == 1:
        if (minor, 0) >= (20, 5):
            return 21
        if minor >= 18:
            return 17
        if minor == 17:
            return 17
        if minor >= 13:
            return 8
        return 8
    return 17


def find_java(preferred: str | None = None, min_major: int = 17) -> str:
    """返回一个可用的 java.exe 路径。

    有 preferred 时直接用它；否则从本机候选里挑「满足 ≥min_major 的最小版本」，
    没有满足的再退化为最高版本。
    """
    if preferred:
        if not os.path.isfile(preferred):
            raise FileNotFoundError(f"指定的 Java 不存在：{preferred}")
        return preferred

    javas = [item for item in list_javas() if item["major"] is not None]
    if not javas:
        raise FileNotFoundError("本机没有找到 Java，请先安装 Java 或用 --java 指定 java.exe 路径")

    sufficient = [item for item in javas if item["major"] >= min_major]
    if sufficient:
        return min(sufficient, key=lambda item: item["major"])["path"]
    return max(javas, key=lambda item: item["major"])["path"]
