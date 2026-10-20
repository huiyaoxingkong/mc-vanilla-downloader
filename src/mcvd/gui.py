"""图形界面（tkinter）。

设计目标：
- 不依赖命令行：双击 exe 直接进这个界面；
- 下载目录可自由选择，并自动识别目录里已有什么（版本、资源、PCL 版本隔离设置…）；
- 「创建游戏文件夹」对话框：选位置、文件夹名、默认版本隔离，可写 PCL 便携配置；
- 安装 / 校验 / 测速全部后台线程执行，界面不卡。
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from . import detect, loaders, manifest, mirrors, verify
from .installer import InstallOptions, install
from .netio import DownloadError
from .rules import os_name

APP_TITLE = f"mcvd v{__version__} · Minecraft 原版安装器"
LOG_LIMIT = 4000


class _QueueWriter:
    """把 print 的输出转进 GUI 队列。"""

    def __init__(self, target: "App", kind: str = "log") -> None:
        self.app = target
        self.kind = kind

    def write(self, text: str) -> None:
        if text:
            self.app.queue.put((self.kind, text))

    def flush(self) -> None:
        pass


class CreateDirDialog(tk.Toplevel):
    def __init__(self, master: "App", initial_parent: Path, initial_name: str = ".minecraft") -> None:
        super().__init__(master.root)
        self.app = master
        self.result: Path | None = None
        self.title("创建游戏文件夹")
        self.resizable(False, False)
        self.transient(master.root)
        self.grab_set()

        self.parent_var = tk.StringVar(value=str(initial_parent))
        self.name_var = tk.StringVar(value=initial_name or ".minecraft")
        self.isolation_var = tk.StringVar(value=detect.ISOLATION_CHOICES[-1][1])
        self.write_pcl_var = tk.BooleanVar(value=True)
        self.structure_var = tk.BooleanVar(value=True)
        self.preview_var = tk.StringVar()

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="创建位置").grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Entry(body, textvariable=self.parent_var, width=52).grid(row=0, column=1, sticky="we", padx=8)
        ttk.Button(body, text="浏览…", command=self._browse).grid(row=0, column=2)

        ttk.Label(body, text="文件夹名称").grid(row=1, column=0, sticky="w", pady=(8, 4))
        ttk.Entry(body, textvariable=self.name_var, width=52).grid(row=1, column=1, sticky="we", padx=8)
        ttk.Label(body, text="通常就叫 .minecraft", foreground="#777").grid(row=1, column=2, sticky="w")

        ttk.Label(body, text="默认版本隔离").grid(row=2, column=0, sticky="nw", pady=(12, 4))
        combo = ttk.Combobox(
            body,
            textvariable=self.isolation_var,
            values=[label for _v, label, _d in detect.ISOLATION_CHOICES],
            state="readonly",
            width=49,
        )
        combo.grid(row=2, column=1, columnspan=2, sticky="we", padx=8, pady=(12, 4))
        self.hint = ttk.Label(body, text="", foreground="#555", wraplength=520, justify="left")
        self.hint.grid(row=3, column=0, columnspan=3, sticky="w", padx=(0, 0))
        combo.bind("<<ComboboxSelected>>", lambda _e: self._update_hint())

        ttk.Checkbutton(body, text="创建基础结构（versions / assets / libraries / launcher_profiles.json）",
                        variable=self.structure_var).grid(row=4, column=0, columnspan=3, sticky="w", pady=(10, 2))
        ttk.Checkbutton(body, text="写入 PCL 便携配置（PCL/Setup.ini 的「默认版本隔离」）",
                        variable=self.write_pcl_var).grid(row=5, column=0, columnspan=3, sticky="w")

        ttk.Separator(body, orient="horizontal").grid(row=6, column=0, columnspan=3, sticky="we", pady=12)
        ttk.Label(body, text="将创建：").grid(row=7, column=0, sticky="nw")
        ttk.Label(body, textvariable=self.preview_var, foreground="#0a5", wraplength=400,
                  justify="left").grid(row=7, column=1, columnspan=2, sticky="w", padx=8)

        buttons = ttk.Frame(body)
        buttons.grid(row=8, column=0, columnspan=3, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="取消", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="创建", command=self._create).pack(side="right")

        for var in (self.parent_var, self.name_var, self.isolation_var):
            var.trace_add("write", lambda *_: self._update_preview())
        self._update_hint()
        self._update_preview()
        self.bind("<Escape>", lambda _e: self.destroy())

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(parent=self, title="选择创建位置", initialdir=self.parent_var.get())
        if chosen:
            self.parent_var.set(chosen)

    def _selected_isolation(self) -> int:
        label = self.isolation_var.get()
        for value, text, _desc in detect.ISOLATION_CHOICES:
            if text == label:
                return value
        return 4

    def _update_hint(self) -> None:
        for value, text, desc in detect.ISOLATION_CHOICES:
            if text == self.isolation_var.get():
                self.hint.configure(text=f"值 {value}：{desc}")
                return

    def _update_preview(self) -> None:
        target = Path(self.parent_var.get() or ".") / (self.name_var.get() or ".minecraft")
        self.preview_var.set(str(target))

    def _create(self) -> None:
        parent = Path(self.parent_var.get().strip())
        try:
            parent.mkdir(parents=True, exist_ok=True)
            target = detect.create_mc_dir(
                parent,
                self.name_var.get(),
                isolation=self._selected_isolation(),
                write_pcl=self.write_pcl_var.get(),
                make_structure=self.structure_var.get(),
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("创建失败", str(exc), parent=self)
            return
        self.result = target
        self.destroy()


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.queue: queue.Queue = queue.Queue()
        self.busy = False
        self.mirror: mirrors.Mirror | None = None
        self.version_list: list[str] = []

        root.title(APP_TITLE)
        self._build_style()
        self._build_ui()
        root.update_idletasks()
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        width = min(max(root.winfo_reqwidth() + 32, 980), int(screen_w * 0.92))
        height = min(max(root.winfo_reqheight() + 32, 760), int(screen_h * 0.92))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.minsize(900, 680)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(100, self._poll)

        default_dir = Path(os.environ.get("APPDATA", str(Path.home()))) / ".minecraft"
        self.dir_var.set(str(default_dir))
        self._log(f"mcvd v{__version__} 启动。默认目录：{default_dir}\n")
        self.refresh_dir_info()
        self.refresh_versions()

    # ---------------------------------------------------------------- UI

    def _build_style(self) -> None:
        style = ttk.Style()
        if os_name() == "windows":
            try:
                style.theme_use("vista")
            except tk.TclError:
                pass
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Status.TLabel", font=("Microsoft YaHei UI", 9))
        style.configure("Hint.TLabel", foreground="#666666")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        # ---- 游戏目录
        dir_frame = ttk.LabelFrame(outer, text=" 游戏目录 ", padding=10)
        dir_frame.pack(fill="x")
        dir_frame.columnconfigure(1, weight=1)

        ttk.Label(dir_frame, text="Minecraft 目录").grid(row=0, column=0, sticky="w")
        self.dir_var = tk.StringVar()
        ttk.Entry(dir_frame, textvariable=self.dir_var).grid(row=0, column=1, sticky="we", padx=8)
        ttk.Button(dir_frame, text="浏览…", command=self._browse_dir, width=8).grid(row=0, column=2)
        ttk.Button(dir_frame, text="刷新", command=self.refresh_dir_info, width=6).grid(row=0, column=3, padx=4)
        ttk.Button(dir_frame, text="创建游戏文件夹…", command=self._open_create_dialog).grid(row=0, column=4)
        ttk.Button(dir_frame, text="打开", command=self._open_dir, width=5).grid(row=0, column=5, padx=(4, 0))
        ttk.Button(dir_frame, text="详情", command=self._show_details, width=5).grid(row=0, column=6, padx=(4, 0))

        self.dir_status = ttk.Label(dir_frame, text="正在检测……", style="Status.TLabel",
                                    justify="left", wraplength=1100)
        self.dir_status.grid(row=1, column=0, columnspan=7, sticky="w", pady=(8, 0))
        dir_frame.bind("<Configure>", lambda e: self.dir_status.configure(wraplength=max(400, e.width - 30)))

        # ---- 安装设置
        install_frame = ttk.LabelFrame(outer, text=" 安装设置 ", padding=10)
        install_frame.pack(fill="x", pady=(10, 0))
        for col in (1, 3, 5):
            install_frame.columnconfigure(col, weight=1)

        self.version_var = tk.StringVar(value="latest")
        self.version_type_var = tk.StringVar(value="正式版")
        self.loader_var = tk.StringVar(value="无（仅原版）")
        self.loader_version_var = tk.StringVar(value="自动")
        self.name_var = tk.StringVar()
        self.mirror_var = tk.StringVar(value="自动测速")
        self.threads_var = tk.StringVar(value="16")
        self.skip_assets_var = tk.BooleanVar(value=False)
        self.auto_verify_var = tk.BooleanVar(value=True)
        self.register_profile_var = tk.BooleanVar(value=True)

        ttk.Label(install_frame, text="游戏版本").grid(row=0, column=0, sticky="w")
        self.version_combo = ttk.Combobox(install_frame, textvariable=self.version_var, width=20)
        self.version_combo.grid(row=0, column=1, sticky="we", padx=8)
        ttk.Button(install_frame, text="刷新版本", command=self.refresh_versions, width=9).grid(row=0, column=2)

        ttk.Label(install_frame, text="版本类型").grid(row=0, column=3, sticky="e")
        ttk.Combobox(install_frame, textvariable=self.version_type_var, values=["正式版", "快照", "全部"],
                     state="readonly", width=8).grid(row=0, column=4, sticky="we", padx=8)

        ttk.Label(install_frame, text="线程").grid(row=0, column=5, sticky="e")
        ttk.Spinbox(install_frame, from_=1, to=64, textvariable=self.threads_var, width=5).grid(
            row=0, column=6, sticky="we", padx=8)

        ttk.Label(install_frame, text="加载器").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.loader_combo = ttk.Combobox(
            install_frame,
            textvariable=self.loader_var,
            values=["无（仅原版）", "Fabric", "Quilt", "Forge", "NeoForge"],
            state="readonly",
            width=20,
        )
        self.loader_combo.grid(row=1, column=1, sticky="we", padx=8, pady=(8, 0))
        self.loader_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_loader_change())

        ttk.Label(install_frame, text="加载器版本").grid(row=1, column=3, sticky="e", pady=(8, 0))
        self.loader_version_combo = ttk.Combobox(install_frame, textvariable=self.loader_version_var,
                                                 values=["自动"], width=16, state="readonly")
        self.loader_version_combo.grid(row=1, column=4, columnspan=3, sticky="we", padx=8, pady=(8, 0))
        self.loader_version_combo.configure(state="disabled")

        ttk.Label(install_frame, text="版本名（可选）").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(install_frame, textvariable=self.name_var).grid(row=2, column=1, columnspan=2,
                                                                  sticky="we", padx=8, pady=(8, 0))
        ttk.Label(install_frame, text="对应 PCL 的「版本名称」", style="Hint.TLabel").grid(
            row=2, column=3, columnspan=2, sticky="w", padx=8, pady=(8, 0))

        ttk.Label(install_frame, text="下载源").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(install_frame, textvariable=self.mirror_var,
                     values=["自动测速", "官方源", "BMCLAPI 镜像"], state="readonly",
                     width=20).grid(row=3, column=1, columnspan=2, sticky="we", padx=8, pady=(8, 0))
        ttk.Checkbutton(install_frame, text="跳过资源文件（体积最大，可后续补）",
                        variable=self.skip_assets_var).grid(row=3, column=3, sticky="w", pady=(8, 0))
        ttk.Checkbutton(install_frame, text="装完自动校验", variable=self.auto_verify_var).grid(
            row=3, column=4, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Checkbutton(install_frame, text="注册到官方启动器（写入 launcher_profiles.json）",
                        variable=self.register_profile_var).grid(row=4, column=0, columnspan=4,
                                                                 sticky="w", pady=(6, 0))
        ttk.Label(install_frame, text="PCL / HMCL / BakaXL / LauncherX 扫描 versions/ 即可识别，无需额外注册",
                  style="Hint.TLabel").grid(row=4, column=4, columnspan=3, sticky="w", pady=(6, 0))

        # ---- 操作按钮
        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(10, 0))
        self.install_btn = ttk.Button(actions, text="开始安装", command=self.start_install)
        self.install_btn.pack(side="left")
        self.verify_btn = ttk.Button(actions, text="校验并修复", command=self.start_verify)
        self.verify_btn.pack(side="left", padx=(8, 0))
        self.probe_btn = ttk.Button(actions, text="测速下载源", command=self.start_probe)
        self.probe_btn.pack(side="left", padx=(8, 0))
        self.progress = ttk.Progressbar(actions, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True, padx=(16, 8))
        self.progress_text = ttk.Label(actions, text="就绪", width=18)
        self.progress_text.pack(side="left")

        # ---- 日志
        log_frame = ttk.LabelFrame(outer, text=" 日志 ", padding=6)
        log_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.log_text = tk.Text(log_frame, height=14, wrap="word", state="disabled",
                                font=("Consolas", 9), background="#fbfbfb", relief="flat")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    # ---------------------------------------------------------------- 小工具

    def _log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        # 限制日志长度
        if int(self.log_text.index("end-1c").split(".")[0]) > LOG_LIMIT:
            self.log_text.delete("1.0", "500.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for btn in (self.install_btn, self.verify_btn, self.probe_btn):
            btn.configure(state=state)

    def _on_close(self) -> None:
        if self.busy and not messagebox.askyesno("正在运行", "还有任务在跑，确定退出吗？"):
            return
        self.root.destroy()

    def _on_loader_change(self) -> None:
        loader = self.loader_var.get()
        if loader.startswith("无"):
            self.loader_version_combo.configure(state="disabled", values=["自动"])
            self.loader_version_var.set("自动")
            return
        self.loader_version_combo.configure(state="normal", values=["自动"])
        self.loader_version_var.set("自动")
        self._load_loader_versions(loader)

    def _load_loader_versions(self, loader: str) -> None:
        name = loader.lower()
        version = self.version_var.get().strip() or "latest"

        def worker() -> None:
            try:
                game = self._resolve_game_id(version)
                opts = self._make_options()
                versions = loaders.loaders_for(game, name)
                self.queue.put(("loader_versions", versions[:40]))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("log", f"[加载器版本] 获取失败：{exc}\n"))

        threading.Thread(target=worker, daemon=True).start()

    def _resolve_game_id(self, spec: str) -> str:
        manifest_payload = manifest.get_manifest(self._mirror())
        return manifest.pick_version(manifest_payload, spec)["id"]

    def _mirror(self) -> mirrors.Mirror:
        if self.mirror is None:
            self.mirror = self._resolve_mirror()
        return self.mirror

    def _resolve_mirror(self) -> mirrors.Mirror:
        mode = self.mirror_var.get()
        if mode == "官方源":
            return mirrors.MIRROR_OFFICIAL
        if mode.startswith("BMCLAPI"):
            return mirrors.MIRROR_BMCLAPI
        results = manifest.probe_mirrors(mirrors.ALL_MIRRORS, timeout=10.0)
        available = [item for item in results if item["ok"]]
        for item in results:
            state = f"{item['seconds'] * 1000:.0f} ms" if item["ok"] else "不可用"
            self.queue.put(("log", f"  {item['mirror'].name:<10} {state}\n"))
        if not available:
            raise DownloadError("所有下载源都不可用，请检查网络")
        return min(available, key=lambda item: item["seconds"])["mirror"]

    def _make_options(self) -> InstallOptions:
        loader = self.loader_var.get()
        loader_key = None if loader.startswith("无") else loader.lower()
        loader_version = self.loader_version_var.get().strip()
        if loader_version in ("", "自动"):
            loader_version = None
        try:
            threads = max(1, min(64, int(self.threads_var.get())))
        except ValueError:
            threads = 16
        return InstallOptions(
            mc_dir=Path(self.dir_var.get().strip()).expanduser(),
            mirror=self._mirror(),
            threads=threads,
            with_assets=not self.skip_assets_var.get(),
            name=self.name_var.get().strip() or None,
            loader=loader_key,
            loader_version=loader_version,
            register_profile=self.register_profile_var.get(),
            progress_cb=lambda done, total: self.queue.put(("progress", done, total)),
        )

    # ---------------------------------------------------------------- 目录

    def _browse_dir(self) -> None:
        chosen = filedialog.askdirectory(title="选择 Minecraft 目录", initialdir=self.dir_var.get())
        if chosen:
            self.dir_var.set(chosen)
            self.refresh_dir_info()

    def _open_dir(self) -> None:
        path = Path(self.dir_var.get().strip())
        if path.is_dir():
            if os_name() == "windows":
                os.startfile(str(path))  # noqa: S606
            else:
                os.system(f'xdg-open "{path}"')
        else:
            messagebox.showwarning("目录不存在", str(path), parent=self.root)

    def _open_create_dialog(self) -> None:
        current = Path(self.dir_var.get().strip() or ".")
        # 默认在「当前目录的上一级」创建同名目录，避免 .minecraft\.minecraft
        parent = current.parent if current.parent != current else current
        name = current.name or ".minecraft"
        dialog = CreateDirDialog(self, parent, name)
        self.root.wait_window(dialog)
        if dialog.result:
            self.dir_var.set(str(dialog.result))
            self.refresh_dir_info()
            self._log(f"已创建游戏文件夹：{dialog.result}\n")

    def refresh_dir_info(self) -> None:
        path = Path(self.dir_var.get().strip()).expanduser()
        self.dir_status.configure(text="正在检测……")
        self._last_info: detect.McDirInfo | None = None

        def worker() -> None:
            try:
                quick = detect.inspect(path, with_size=False, with_java=False)
                self.queue.put(("inspect", detect.describe(quick, brief=True)))
                partial = detect.inspect(path, with_size=False, with_java=True)
                self.queue.put(("inspect_info", partial))
                self.queue.put(("inspect", detect.describe(partial, brief=True)))
                full = detect.inspect(path, with_size=True, with_java=True)
                self.queue.put(("inspect_info", full))
                self.queue.put(("inspect", detect.describe(full, brief=True)))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("inspect", f"检测失败：{exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _show_details(self) -> None:
        info = getattr(self, "_last_info", None)
        if info is None:
            messagebox.showinfo("详情", "还没有检测结果，请先点「刷新」。", parent=self.root)
            return
        window = tk.Toplevel(self.root)
        window.title("目录详情")
        window.geometry("760x520")
        window.transient(self.root)
        text = tk.Text(window, wrap="word", font=("Microsoft YaHei UI", 9), padx=10, pady=10)
        scroll = ttk.Scrollbar(window, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        text.insert("1.0", detect.describe(info, brief=False))
        text.configure(state="disabled")

    # ---------------------------------------------------------------- 版本

    def refresh_versions(self) -> None:
        kind_map = {"正式版": "release", "快照": "snapshot", "全部": "all"}
        kind = kind_map.get(self.version_type_var.get(), "release")

        def worker() -> None:
            try:
                payload = manifest.get_manifest(self._mirror())
                versions = manifest.filter_versions(payload, kind)
                ids = [item["id"] for item in versions]
                self.queue.put(("versions", ids))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("log", f"[版本列表] 获取失败：{exc}\n"))

        threading.Thread(target=worker, daemon=True).start()

    # ---------------------------------------------------------------- 动作

    def start_probe(self) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self.progress_text.configure(text="测速中…")
        self.mirror = None

        def worker() -> None:
            self.queue.put(("log", "\n=== 下载源测速 ===\n"))
            try:
                chosen = self._resolve_mirror()
                self.queue.put(("log", f"选用：{chosen.name}（{chosen.description}）\n"))
                self.queue.put(("probe_done", chosen.name))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", str(exc)))
            finally:
                self.queue.put(("busy", False))

        threading.Thread(target=worker, daemon=True).start()

    def start_install(self) -> None:
        if self.busy:
            return
        version = self.version_var.get().strip()
        if not version:
            messagebox.showwarning("缺少版本", "请先选择或输入游戏版本", parent=self.root)
            return
        target = Path(self.dir_var.get().strip()).expanduser()
        if not target.is_dir():
            if not messagebox.askyesno("目录不存在", f"{target}\n\n要创建这个目录吗？", parent=self.root):
                return
            target.mkdir(parents=True, exist_ok=True)

        self._set_busy(True)
        self.progress.configure(mode="determinate", maximum=100, value=0)
        self.progress_text.configure(text="准备中…")
        self._log("\n" + "=" * 60 + "\n")

        def worker() -> None:
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout = _QueueWriter(self)
            sys.stderr = _QueueWriter(self)
            try:
                options = self._make_options()
                loader = self.loader_var.get()
                self.queue.put(("log", f"目标目录：{options.mc_dir}\n"))
                if loader.startswith("无"):
                    result = install(version, options)
                else:
                    result = loaders.install_loader(
                        loader.lower(), version, options.loader_version, options
                    )
                self.queue.put(("log", f"\n完成：{result.version_id}\n"))
                if self.auto_verify_var.get():
                    self.queue.put(("log", "\n开始校验……\n"))
                    report = verify.verify_version(result.version_id, options.mc_dir, options)
                    self.queue.put(("log", verify.format_report(report) + "\n"))
                self.queue.put(("done", result.version_id))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("log", traceback.format_exc()))
                self.queue.put(("error", str(exc)))
            finally:
                sys.stdout, sys.stderr = old_out, old_err
                self.queue.put(("busy", False))

        threading.Thread(target=worker, daemon=True).start()

    def start_verify(self) -> None:
        if self.busy:
            return
        path = Path(self.dir_var.get().strip()).expanduser()
        if not path.is_dir():
            messagebox.showwarning("目录不存在", str(path), parent=self.root)
            return
        self._set_busy(True)
        self.progress.configure(mode="determinate", maximum=100, value=0)
        self.progress_text.configure(text="校验中…")
        self._log("\n" + "=" * 60 + "\n")

        def worker() -> None:
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout = _QueueWriter(self)
            sys.stderr = _QueueWriter(self)
            try:
                options = self._make_options()
                history = verify.all_versions(options.mc_dir)
                if not history:
                    self.queue.put(("error", "这个目录下没有已安装的版本"))
                    return
                bad_total = 0
                for name in history:
                    report = verify.verify_version(name, options.mc_dir, options, fix=True)
                    self.queue.put(("log", verify.format_report(report) + "\n"))
                    bad_total += len(report.problems)
                if bad_total:
                    self.queue.put(("error", f"仍有 {bad_total} 个文件有问题"))
                else:
                    self.queue.put(("done", "校验完成"))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("log", traceback.format_exc()))
                self.queue.put(("error", str(exc)))
            finally:
                sys.stdout, sys.stderr = old_out, old_err
                self.queue.put(("busy", False))

        threading.Thread(target=worker, daemon=True).start()

    # ---------------------------------------------------------------- 轮询

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _handle(self, kind: str, payload) -> None:
        if kind == "log":
            self._log(payload)
        elif kind == "progress":
            done, total = payload
            self.progress.configure(maximum=max(total, 1), value=done)
            self.progress_text.configure(text=f"{done}/{total}")
        elif kind == "inspect":
            self.dir_status.configure(text=payload)
        elif kind == "inspect_info":
            self._last_info = payload
        elif kind == "versions":
            self.version_list = payload
            self.version_combo.configure(values=payload)
            if payload and self.version_var.get() not in payload:
                self.version_var.set(payload[0])
        elif kind == "loader_versions":
            self.loader_version_combo.configure(values=["自动"] + list(payload))
        elif kind == "probe_done":
            self.progress_text.configure(text=f"选用 {payload}")
        elif kind == "done":
            self.progress_text.configure(text=f"完成：{payload}")
        elif kind == "error":
            self.progress_text.configure(text="出错")
            messagebox.showerror("出错了", str(payload), parent=self.root)
        elif kind == "busy":
            self._set_busy(bool(payload))


def run() -> int:
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


def main() -> int:
    try:
        return run()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        try:
            messagebox.showerror("mcvd 启动失败", traceback.format_exc())
        except Exception:  # noqa: BLE001
            pass
        return 1
