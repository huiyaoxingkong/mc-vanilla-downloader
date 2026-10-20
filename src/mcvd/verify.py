"""已安装版本完整性校验（对应 PCL 的「版本校验」）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import mirrors as _mirrors
from .installer import (
    ASSET_BASE,
    InstallOptions,
    Progress,
    Task,
    build_asset_tasks,
    build_client_task,
    build_library_tasks,
    mirror_urls,
    run_tasks,
)
from .netio import digest_matches, human_bytes


@dataclass
class VerifyReport:
    version: str
    checked: int = 0
    ok: int = 0
    missing: list[str] = field(default_factory=list)
    corrupt: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    fixed: int = 0
    broken_tasks: list[Task] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return not self.missing and not self.corrupt

    @property
    def problems(self) -> list[str]:
        return self.missing + self.corrupt


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def version_chain(version_id: str, mc_dir: Path) -> tuple[list[tuple[str, dict]], list[str]]:
    """沿 inheritsFrom 收集版本 JSON（自身 + 所有父版本）。"""
    chain: list[tuple[str, dict]] = []
    notes: list[str] = []
    current = version_id
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        path = mc_dir / "versions" / current / f"{current}.json"
        payload = _load_json(path)
        if payload is None:
            notes.append(f"缺少版本 JSON：{path}")
            break
        chain.append((current, payload))
        current = payload.get("inheritsFrom")
    return chain, notes


def collect_tasks(version_id: str, mc_dir: Path, opts: InstallOptions) -> tuple[list[Task], list[str]]:
    """列出该版本（含继承链）应该存在的全部文件。"""
    chain, notes = version_chain(version_id, mc_dir)
    tasks: list[Task] = []
    seen_paths: set[str] = set()

    def add(task: Task | None) -> None:
        if task is None:
            return
        key = str(task.dest).lower()
        if key in seen_paths:
            return
        seen_paths.add(key)
        tasks.append(task)

    for owner, payload in chain:
        add(build_client_task(payload, owner, mc_dir, opts))
        for task in build_library_tasks(payload, mc_dir, opts):
            add(task)

        asset_index = payload.get("assetIndex") or {}
        if asset_index.get("id"):
            index_path = mc_dir / "assets" / "indexes" / f"{asset_index['id']}.json"
            if asset_index.get("url"):
                add(
                    Task(
                        urls=mirror_urls(opts.mirror, asset_index["url"]),
                        dest=index_path,
                        sha1=asset_index.get("sha1"),
                        size=asset_index.get("size"),
                        kind="asset-index",
                        label=f"assets/indexes/{asset_index['id']}.json",
                    )
                )
            index_payload = _load_json(index_path)
            if index_payload is None:
                notes.append(f"缺少资源索引：{index_path}")
                continue
            for task in build_asset_tasks(index_payload, mc_dir, opts):
                add(task)
    return tasks, notes


def verify_version(version_id: str, mc_dir: Path, opts: InstallOptions, fix: bool = False) -> VerifyReport:
    report = VerifyReport(version=version_id)
    chain, notes = version_chain(version_id, mc_dir)
    if not chain:
        report.missing.append(f"versions/{version_id}/{version_id}.json（版本 JSON 缺失）")
        report.notes.extend(notes)
        return report

    tasks, notes = collect_tasks(version_id, mc_dir, opts)
    report.notes.extend(notes)

    for task in tasks:
        report.checked += 1
        if digest_matches(task.dest, task.sha1, task.size):
            report.ok += 1
        elif not task.dest.exists():
            report.missing.append(f"{task.kind}: {task.label}（缺失）")
            report.broken_tasks.append(task)
        else:
            report.corrupt.append(f"{task.kind}: {task.label}（内容损坏）")
            report.broken_tasks.append(task)

    if fix and report.broken_tasks:
        progress = Progress(len(report.broken_tasks), silent=opts.quiet)
        run_tasks(report.broken_tasks, opts, progress, "修复")
        progress.finish()
        report.fixed = len(report.broken_tasks)
        # 修完再复核一次
        still_bad = [t for t in report.broken_tasks if not digest_matches(t.dest, t.sha1, t.size)]
        report.fixed -= len(still_bad)
        if still_bad:
            report.notes.append(f"仍有 {len(still_bad)} 个文件修复失败")
        else:
            report.missing.clear()
            report.corrupt.clear()
            report.ok = report.checked
    return report


def all_versions(mc_dir: Path) -> list[str]:
    versions_dir = mc_dir / "versions"
    if not versions_dir.is_dir():
        return []
    result = []
    for child in sorted(versions_dir.iterdir()):
        if child.is_dir() and (child / f"{child.name}.json").is_file():
            result.append(child.name)
    return result


def format_report(report: VerifyReport, verbose: bool = False) -> str:
    lines = []
    status = "完整" if report.healthy else "有问题"
    lines.append(f"版本 {report.version}：{status}（检查 {report.checked} 个文件，正常 {report.ok} 个）")
    if report.fixed:
        lines.append(f"  已自动修复 {report.fixed} 个文件")
    for note in report.notes:
        lines.append(f"  注意：{note}")
    shown = 0
    for item in report.problems:
        if shown >= (50 if not verbose else 10_000):
            lines.append(f"  ……（其余 {len(report.problems) - shown} 个略）")
            break
        lines.append(f"  ✗ {item}")
        shown += 1
    return "\n".join(lines)


def estimate_size(tasks: list[Task]) -> int:
    return sum(task.size or 0 for task in tasks)


def verify_all(mc_dir: Path, opts: InstallOptions, fix: bool = False) -> list[VerifyReport]:
    return [verify_version(version_id, mc_dir, opts, fix=fix) for version_id in all_versions(mc_dir)]


__all__ = [
    "VerifyReport",
    "all_versions",
    "collect_tasks",
    "estimate_size",
    "format_report",
    "verify_all",
    "verify_version",
    "version_chain",
    "human_bytes",
    "ASSET_BASE",
    "_mirrors",
]
