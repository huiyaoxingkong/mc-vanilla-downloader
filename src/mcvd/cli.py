"""命令行入口。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import __version__
from . import manifest as _manifest
from . import mirrors as _mirrors
from .installer import InstallOptions, install
from .netio import DownloadError, human_bytes

MIRROR_CHOICES = ["auto", "official", "bmclapi"]


def default_mc_dir() -> Path:
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / ".minecraft"
    return Path.home() / ".minecraft"


def _setup_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - 老终端兜底
            pass


def _fmt_time(value: str | None) -> str:
    if not value:
        return "?"
    return value.replace("T", " ")[:16]


def resolve_mirror(mode: str, timeout: float, quiet: bool = False) -> _mirrors.Mirror:
    if mode != "auto":
        return _mirrors.get_mirror(mode)

    results = _manifest.probe_mirrors(_mirrors.ALL_MIRRORS, timeout=min(timeout, 10.0))
    if not quiet:
        sys.stderr.write("测速：\n")
        for item in results:
            if item["ok"]:
                sys.stderr.write(f"  {item['mirror'].name:<10} {item['seconds'] * 1000:>7.0f} ms\n")
            else:
                sys.stderr.write(f"  {item['mirror'].name:<10}    不可用\n")
    available = [item for item in results if item["ok"]]
    if not available:
        raise DownloadError("所有下载源都不可用，请检查网络连接")
    available.sort(key=lambda item: item["seconds"])
    return available[0]["mirror"]


def cmd_list(args: argparse.Namespace) -> int:
    mirror = resolve_mirror(args.mirror, args.timeout, quiet=args.quiet)
    manifest = _manifest.get_manifest(mirror, timeout=args.timeout, retries=args.retries)
    versions = _manifest.filter_versions(manifest, args.type, args.limit)

    if args.json:
        print(json.dumps({"latest": manifest.get("latest"), "versions": versions}, ensure_ascii=False, indent=2))
        return 0

    latest = manifest.get("latest", {})
    print(f"最新正式版：{latest.get('release')}    最新快照：{latest.get('snapshot')}")
    print(f"（数据源：{mirror.name}，共 {len(versions)} 条）\n")
    print(f"{'版本':<22}{'类型':<12}{'发布时间'}")
    print("-" * 56)
    for entry in versions:
        print(f"{entry.get('id', '?'):<22}{entry.get('type', '?'):<12}{_fmt_time(entry.get('releaseTime'))}")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    mirror = resolve_mirror(args.mirror, args.timeout, quiet=args.quiet)
    mc_dir = Path(args.dir).expanduser() if args.dir else default_mc_dir()
    options = InstallOptions(
        mc_dir=mc_dir,
        mirror=mirror,
        threads=args.threads,
        with_assets=not args.no_assets,
        with_libraries=not args.no_libraries,
        dry_run=args.dry_run,
        force=args.force,
        timeout=args.timeout,
        retries=args.retries,
        quiet=args.quiet,
    )
    result = install(args.version, options)
    if args.dry_run:
        return 0
    print(f"\n提示：PCL / HMCL / 官方启动器打开 {mc_dir} 即可看到版本 {result.version_id}。")
    return 0


def cmd_mirrors(args: argparse.Namespace) -> int:
    print(f"{'名称':<10}{'状态':<8}{'耗时(ms)':<12}{'版本清单地址'}")
    print("-" * 90)
    results = _manifest.probe_mirrors(_mirrors.ALL_MIRRORS, timeout=args.timeout)
    for item in results:
        mirror = item["mirror"]
        if item["ok"]:
            ms = f"{item['seconds'] * 1000:.0f}"
            print(f"{mirror.name:<10}{'可用':<8}{ms:<12}{mirror.manifest_url()}")
        else:
            print(f"{mirror.name:<10}{'不可用':<8}{'-':<12}{mirror.manifest_url()}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    mirror = resolve_mirror(args.mirror, args.timeout, quiet=args.quiet)
    manifest = _manifest.get_manifest(mirror, timeout=args.timeout, retries=args.retries)
    entry = _manifest.pick_version(manifest, args.version)
    payload = _manifest.get_version_json(entry, mirror, timeout=args.timeout, retries=args.retries)
    assets = payload.get("assetIndex") or {}
    java = payload.get("javaVersion") or {}
    libraries = payload.get("libraries") or []
    print(f"版本       ：{entry.get('id')}（{entry.get('type')}）")
    print(f"发布时间   ：{_fmt_time(entry.get('releaseTime'))}")
    print(f"客户端大小 ：{human_bytes((payload.get('downloads', {}).get('client', {}) or {}).get('size', 0))}")
    print(f"依赖库     ：{len(libraries)} 条")
    print(f"资源索引   ：{assets.get('id', '?')}")
    if java:
        print(f"Java 版本  ：{java.get('majorVersion', '?')}（{java.get('component', '?')}）")
    print(f"主类       ：{payload.get('mainClass', '?')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcvd",
        description="Minecraft 原版下载/安装器：多源（官方 / BMCLAPI）自动选源、断点续传、SHA-1 校验。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  mcvd mirrors                       # 测一下国内镜像和官方源哪个快\n"
            "  mcvd list --type release --limit 10\n"
            "  mcvd install latest                # 下载最新正式版到 %%APPDATA%%\\.minecraft\n"
            "  mcvd install 26.3 --dry-run        # 只看要下多少，不实际下载\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"mcvd {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--mirror", choices=MIRROR_CHOICES, default="auto", help="下载源：auto（默认，自动测速）/ official / bmclapi")
    common.add_argument("--timeout", type=float, default=20.0, help="单次请求超时（秒），默认 20")
    common.add_argument("--retries", type=int, default=3, help="失败重试次数，默认 3")
    common.add_argument("--quiet", action="store_true", help="精简输出")

    p_list = sub.add_parser("list", parents=[common], help="列出可用版本")
    p_list.add_argument("--type", choices=["release", "snapshot", "all"], default="release", help="版本类型")
    p_list.add_argument("--limit", type=int, default=20, help="显示条数，默认 20")
    p_list.add_argument("--json", action="store_true", help="以 JSON 输出")
    p_list.set_defaults(func=cmd_list)

    p_install = sub.add_parser("install", parents=[common], help="下载并安装一个原版版本")
    p_install.add_argument("version", help="版本号，或 latest / latest-snapshot")
    p_install.add_argument("--dir", help="Minecraft 目录（默认 %%APPDATA%%\\.minecraft）")
    p_install.add_argument("--threads", type=int, default=16, help="并发下载线程数，默认 16")
    p_install.add_argument("--no-assets", action="store_true", help="跳过资源文件（体积最大）")
    p_install.add_argument("--no-libraries", action="store_true", help="跳过依赖库")
    p_install.add_argument("--dry-run", action="store_true", help="只估算大小，不下载")
    p_install.add_argument("--force", action="store_true", help="忽略已有文件，强制重新下载")
    p_install.set_defaults(func=cmd_install)

    p_mirrors = sub.add_parser("mirrors", parents=[common], help="检测各个下载源")
    p_mirrors.set_defaults(func=cmd_mirrors)

    p_info = sub.add_parser("info", parents=[common], help="查看某个版本的信息")
    p_info.add_argument("version", help="版本号，或 latest / latest-snapshot")
    p_info.set_defaults(func=cmd_info)

    return parser


def main(argv: list[str] | None = None) -> int:
    _setup_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        return 130
    except DownloadError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except KeyError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except LookupError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
