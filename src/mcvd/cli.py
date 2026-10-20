"""命令行入口。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from . import loaders as _loaders
from . import manifest as _manifest
from . import mirrors as _mirrors
from . import verify as _verify
from .installer import InstallOptions, install
from .netio import DownloadError, human_bytes

MIRROR_CHOICES = ["auto", "official", "bmclapi"]
LOADER_CHOICES = list(_loaders.SUPPORTED_LOADERS)


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


def _make_options(args: argparse.Namespace, mirror: _mirrors.Mirror) -> InstallOptions:
    return InstallOptions(
        mc_dir=Path(getattr(args, "dir", None) or default_mc_dir()).expanduser(),
        mirror=mirror,
        threads=getattr(args, "threads", 16),
        with_assets=not getattr(args, "no_assets", False),
        with_libraries=not getattr(args, "no_libraries", False),
        dry_run=getattr(args, "dry_run", False),
        force=getattr(args, "force", False),
        timeout=getattr(args, "timeout", 20.0),
        retries=getattr(args, "retries", 3),
        quiet=getattr(args, "quiet", False),
        name=getattr(args, "name", None),
        loader=getattr(args, "loader", None),
        loader_version=getattr(args, "loader_version", None),
        java=getattr(args, "java", None),
    )


# ------------------------------------------------------------------ 子命令


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
    options = _make_options(args, mirror)

    if args.loader:
        result = _loaders.install_loader(
            args.loader,
            args.version,
            args.loader_version,
            options,
            installer_path=args.installer,
        )
        if args.dry_run:
            return 0
        print(f"\n完成：版本 {result.version_id} 已安装到 {options.mc_dir / 'versions' / result.version_id}")
        return 0

    result = install(args.version, options)
    if args.dry_run:
        return 0
    print(f"\n提示：PCL / HMCL / 官方启动器打开 {options.mc_dir} 即可看到版本 {result.version_id}。")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    mirror = resolve_mirror(args.mirror, args.timeout, quiet=args.quiet)
    options = _make_options(args, mirror)
    options.threads = args.threads

    targets = [args.version] if args.version else _verify.all_versions(options.mc_dir)
    if not targets:
        print(f"{options.mc_dir} 下没有已安装的版本")
        return 1

    reports = [_verify.verify_version(name, options.mc_dir, options, fix=args.fix) for name in targets]
    exit_code = 0
    for report in reports:
        print(_verify.format_report(report, verbose=args.verbose))
        print()
        if not report.healthy:
            exit_code = 1
    total_bad = sum(len(report.problems) for report in reports)
    if total_bad and not args.fix:
        print(f"共 {total_bad} 个文件有问题。加 --fix 可自动重新下载。")
    return exit_code


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
    print(f"客户端大小 ：{human_bytes(((payload.get('downloads') or {}).get('client') or {}).get('size', 0))}")
    print(f"依赖库     ：{len(libraries)} 条")
    print(f"资源索引   ：{assets.get('id', '?')}")
    if java:
        print(f"Java 版本  ：{java.get('majorVersion', '?')}（{java.get('component', '?')}）")
    print(f"主类       ：{payload.get('mainClass', '?')}")
    return 0


def cmd_loaders(args: argparse.Namespace) -> int:
    versions = _loaders.loaders_for(args.version, args.loader)
    if not versions:
        print("没有查到可用版本（该加载器可能不支持此游戏版本）")
        return 1
    print(f"{args.loader} / Minecraft {args.version} 可用版本（{len(versions)} 个，最新在前）：")
    for version in versions[: args.limit]:
        print(f"  {version}")
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    from . import gui

    return gui.main()


# ------------------------------------------------------------------ 交互模式（备用，命令行里用 mcvd tui）


BANNER = f"""
╭──────────────────────────────────────────────╮
│   mcvd v{__version__}  Minecraft 原版安装器          │
│   官方 / BMCLAPI 双源自动选源 · SHA-1 校验       │
╰──────────────────────────────────────────────╯
"""


def _ask(prompt: str, default: str = "") -> str:
    suffix = f"（默认 {default}）" if default else ""
    try:
        value = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        raise SystemExit(0)
    return value or default


def _interactive_install(loader: str | None) -> None:
    game = _ask("游戏版本（直接回车 = 最新正式版）", "latest")
    name = _ask("自定义版本名（直接回车 = 自动生成）", "")
    loader_version = ""
    if loader:
        loader_version = _ask(f"{loader} 版本（回车 = 自动选最新稳定版）", "")

    argv = ["install", game, "--threads", "16"]
    if loader:
        argv += ["--loader", loader, "--loader-version", loader_version] if loader_version else ["--loader", loader]
    if name:
        argv += ["--name", name]
    main(argv)


def interactive() -> int:
    print(BANNER)
    menu = """
  1) 安装原版（最新正式版）
  2) 安装原版（指定版本）
  3) 安装 Fabric
  4) 安装 Forge
  5) 安装 Quilt
  6) 校验已安装版本（可自动修复）
  7) 测试下载源
  8) 查看可用版本列表
  0) 退出
"""
    while True:
        print(menu)
        choice = _ask("请选择")
        try:
            if choice == "1":
                main(["install", "latest", "--threads", "16"])
            elif choice == "2":
                game = _ask("要安装的版本号", "latest")
                name = _ask("自定义版本名（回车跳过）", "")
                argv = ["install", game, "--threads", "16"] + (["--name", name] if name else [])
                main(argv)
            elif choice == "3":
                _interactive_install("fabric")
            elif choice == "4":
                _interactive_install("forge")
            elif choice == "5":
                _interactive_install("quilt")
            elif choice == "6":
                fix = _ask("是否自动修复（y/N）", "n").lower().startswith("y")
                main(["verify"] + (["--fix"] if fix else []))
            elif choice == "7":
                main(["mirrors"])
            elif choice == "8":
                main(["list", "--limit", "15"])
            elif choice in ("0", "q", "exit", "退出"):
                return 0
            else:
                print("请输入菜单里的数字。")
        except (DownloadError, FileNotFoundError, LookupError, ValueError) as exc:
            print(f"\n出错了：{exc}\n")
        print()


# ------------------------------------------------------------------ 参数解析


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcvd",
        description="Minecraft 原版/加载器安装器：多源（官方 / BMCLAPI）自动选源、断点续传、SHA-1 校验。\n不带参数运行会进入交互模式（适合双击 exe）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  mcvd                              # 交互模式\n"
            "  mcvd mirrors                      # 测一下国内镜像和官方源哪个快\n"
            "  mcvd install latest               # 下载最新正式版\n"
            "  mcvd install 1.20.1 --loader forge --name 我的整合包\n"
            "  mcvd install 1.21.4 --loader fabric\n"
            "  mcvd verify --fix                 # 校验并修复全部已安装版本\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"mcvd {__version__}")
    sub = parser.add_subparsers(dest="command")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--mirror", choices=MIRROR_CHOICES, default="auto", help="下载源：auto（默认，自动测速）/ official / bmclapi")
    common.add_argument("--timeout", type=float, default=20.0, help="单次请求超时（秒），默认 20")
    common.add_argument("--retries", type=int, default=3, help="失败重试次数，默认 3")
    common.add_argument("--quiet", action="store_true", help="精简输出")
    common.add_argument("--dir", help="Minecraft 目录（默认 %%APPDATA%%\\.minecraft）")

    p_list = sub.add_parser("list", parents=[common], help="列出可用版本")
    p_list.add_argument("--type", choices=["release", "snapshot", "all"], default="release", help="版本类型")
    p_list.add_argument("--limit", type=int, default=20, help="显示条数，默认 20")
    p_list.add_argument("--json", action="store_true", help="以 JSON 输出")
    p_list.set_defaults(func=cmd_list)

    p_install = sub.add_parser("install", parents=[common], help="下载并安装原版或加载器版本")
    p_install.add_argument("version", help="游戏版本号，或 latest / latest-snapshot")
    p_install.add_argument("--loader", choices=LOADER_CHOICES, help="安装加载器：fabric / quilt / forge / neoforge")
    p_install.add_argument("--loader-version", help="加载器版本（默认自动选）")
    p_install.add_argument("--name", help="自定义版本名（对应 PCL 的“版本名称”）")
    p_install.add_argument("--java", help="运行 Forge/NeoForge 安装器使用的 java.exe 路径")
    p_install.add_argument("--installer", help="已下载好的 Forge/NeoForge installer.jar 路径（离线时用）")
    p_install.add_argument("--threads", type=int, default=16, help="并发下载线程数，默认 16")
    p_install.add_argument("--no-assets", action="store_true", help="跳过资源文件（体积最大）")
    p_install.add_argument("--no-libraries", action="store_true", help="跳过依赖库")
    p_install.add_argument("--dry-run", action="store_true", help="只估算大小，不下载")
    p_install.add_argument("--force", action="store_true", help="忽略已有文件，强制重新下载")
    p_install.set_defaults(func=cmd_install)

    p_verify = sub.add_parser("verify", parents=[common], help="校验已安装版本的完整性")
    p_verify.add_argument("version", nargs="?", help="要校验的版本（省略则校验全部）")
    p_verify.add_argument("--fix", action="store_true", help="重新下载缺失/损坏的文件")
    p_verify.add_argument("--threads", type=int, default=16, help="修复时的并发数")
    p_verify.add_argument("--verbose", action="store_true", help="打印全部问题")
    p_verify.set_defaults(func=cmd_verify)

    p_mirrors = sub.add_parser("mirrors", parents=[common], help="检测各个下载源")
    p_mirrors.set_defaults(func=cmd_mirrors)

    p_info = sub.add_parser("info", parents=[common], help="查看某个版本的信息")
    p_info.add_argument("version", help="版本号，或 latest / latest-snapshot")
    p_info.set_defaults(func=cmd_info)

    p_loaders = sub.add_parser("loaders", parents=[common], help="列出某个加载器支持的版本")
    p_loaders.add_argument("loader", choices=["fabric", "quilt"], help="加载器")
    p_loaders.add_argument("version", help="游戏版本号")
    p_loaders.add_argument("--limit", type=int, default=15)
    p_loaders.set_defaults(func=cmd_loaders)

    p_gui = sub.add_parser("gui", help="打开图形界面")
    p_gui.set_defaults(func=cmd_gui)

    p_tui = sub.add_parser("tui", help="打开文字交互菜单（没有图形环境时用）")
    p_tui.set_defaults(func=lambda _args: interactive())

    return parser


def _launch_gui() -> int:
    try:
        from . import gui

        return gui.main()
    except Exception:  # noqa: BLE001 - 没有图形环境时退回文字菜单
        print("无法启动图形界面，改用文字交互模式。", file=sys.stderr)
        return interactive()


def main(argv: list[str] | None = None) -> int:
    _setup_console()
    args_list = sys.argv[1:] if argv is None else argv
    if not args_list:
        try:
            return _launch_gui()
        except KeyboardInterrupt:
            print("\n已退出")
            return 0

    parser = build_parser()
    args = parser.parse_args(args_list)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        return 130
    except DownloadError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
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
