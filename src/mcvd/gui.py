"""图形界面（customtkinter）。

定位：Minecraft **游戏目录 / 存档管理**工具 —— 管理多个 .minecraft、版本隔离、
存档与「注册到官方启动器」，并提供原版 / 加载器安装。**不提供启动游戏功能**。

- 深色现代界面，左侧导航 + 卡片列表
- 后台线程执行网络 / 磁盘任务，错误只写日志，不弹窗
- 单实例：重复双击只把已有窗口提到前台
"""

from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from . import __version__
from . import compat, detect, loaders, manifest, mirrors, saves, verify
from .installer import InstallOptions, install
from .netio import DownloadError, human_bytes
from .rules import os_name

APP_NAME = "mcvd"
TITLE = f"{APP_NAME} {__version__} · Minecraft 存档与游戏目录管理"

ACCENT = "#3B82F6"
GREEN = "#22C55E"
AMBER = "#F59E0B"
MUTED = "#94A3B8"
CARD_BG = "#1E293B"
SIDEBAR_BG = "#0F172A"
PAGE_BG = "#0B1220"

FONT = "Microsoft YaHei UI"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


def default_mc_dir() -> Path:
    if os_name() == "windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / ".minecraft"
    return Path.home() / ".minecraft"


def _single_instance_guard() -> bool:
    """重复启动时把已有窗口提到前台并返回 False。"""
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW(None, False, "mcvd_single_instance_mutex")
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            _focus_existing_window()
            return False
    except Exception:  # noqa: BLE001 - 非 Windows 直接放行
        pass
    return True


def _focus_existing_window() -> None:
    try:
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        targets: list[int] = []

        def callback(hwnd, _lparam):  # noqa: ANN001
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if buffer.value.startswith(APP_NAME):
                targets.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(callback), 0)
        for hwnd in targets:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
    except Exception:  # noqa: BLE001
        pass


class CreateDirDialog(ctk.CTkToplevel):
    def __init__(self, master: "App", parent: Path, name: str) -> None:
        super().__init__(master)
        self.app = master
        self.result: Path | None = None
        self.title("创建游戏文件夹")
        self.geometry("620x420")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self.parent_var = tk.StringVar(value=str(parent))
        self.name_var = tk.StringVar(value=name or ".minecraft")
        self.isolation_var = tk.StringVar(value=detect.ISOLATION_CHOICES[-1][1])
        self.write_pcl_var = tk.BooleanVar(value=True)
        self.structure_var = tk.BooleanVar(value=True)
        self.preview_var = tk.StringVar(value="")

        pad = {"padx": 16, "pady": (8, 0)}
        ctk.CTkLabel(self, text="创建新的 Minecraft 游戏文件夹", font=(FONT, 18, "bold")).pack(anchor="w", padx=16, pady=(16, 4))
        ctk.CTkLabel(self, text="会生成标准 .minecraft 结构，PCL / HMCL / 官方启动器都能识别",
                     text_color=MUTED, font=(FONT, 12)).pack(anchor="w", padx=16)

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=16, pady=(12, 0))
        form.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(form, text="创建位置", font=(FONT, 13)).grid(row=0, column=0, sticky="w", pady=6)
        ctk.CTkEntry(form, textvariable=self.parent_var).grid(row=0, column=1, sticky="ew", padx=8)
        ctk.CTkButton(form, text="浏览…", width=70, command=self._browse).grid(row=0, column=2)

        ctk.CTkLabel(form, text="文件夹名", font=(FONT, 13)).grid(row=1, column=0, sticky="w", pady=6)
        ctk.CTkEntry(form, textvariable=self.name_var).grid(row=1, column=1, sticky="ew", padx=8)
        ctk.CTkLabel(form, text="通常为 .minecraft", text_color=MUTED).grid(row=1, column=2, sticky="w")

        ctk.CTkLabel(form, text="默认版本隔离", font=(FONT, 13)).grid(row=2, column=0, sticky="w", pady=6)
        ctk.CTkOptionMenu(form, variable=self.isolation_var,
                          values=[label for _v, label, _d in detect.ISOLATION_CHOICES],
                          command=lambda _v: self._update_hint()).grid(row=2, column=1, sticky="ew", padx=8)

        self.hint = ctk.CTkLabel(form, text="", text_color=MUTED, font=(FONT, 12), justify="left", wraplength=520)
        self.hint.grid(row=3, column=1, columnspan=2, sticky="w", padx=8)

        ctk.CTkCheckBox(self, text="创建基础结构（versions / assets / libraries / launcher_profiles.json）",
                        variable=self.structure_var, font=(FONT, 12)).pack(anchor="w", padx=16, pady=(10, 2))
        ctk.CTkCheckBox(self, text="写入 PCL 便携配置（PCL/Setup.ini 的默认版本隔离）",
                        variable=self.write_pcl_var, font=(FONT, 12)).pack(anchor="w", padx=16)

        self.preview = ctk.CTkLabel(self, text="", text_color=GREEN, font=(FONT, 12))
        self.preview.pack(anchor="w", padx=16, pady=(10, 0))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=14, side="bottom")
        ctk.CTkButton(row, text="创建", width=110, command=self._create).pack(side="right")
        ctk.CTkButton(row, text="取消", width=90, fg_color="transparent", border_width=1,
                      command=self.destroy).pack(side="right", padx=8)

        for var in (self.parent_var, self.name_var, self.isolation_var):
            var.trace_add("write", lambda *_: self._update_preview())
        self._update_hint()
        self._update_preview()

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(title="选择创建位置", initialdir=self.parent_var.get())
        if chosen:
            self.parent_var.set(chosen)

    def _selected_isolation(self) -> int:
        for value, label, _desc in detect.ISOLATION_CHOICES:
            if label == self.isolation_var.get():
                return value
        return 4

    def _update_hint(self) -> None:
        for value, label, desc in detect.ISOLATION_CHOICES:
            if label == self.isolation_var.get():
                self.hint.configure(text=f"值 {value}：{desc}")
                return

    def _update_preview(self) -> None:
        target = Path(self.parent_var.get() or ".") / (self.name_var.get() or ".minecraft")
        self.preview.configure(text=f"将创建：{target}")

    def _create(self) -> None:
        try:
            target = detect.create_mc_dir(
                Path(self.parent_var.get().strip()),
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


class App(ctk.CTk):
    NAV = [
        ("home", "📁", "游戏目录"),
        ("saves", "💾", "存档管理"),
        ("versions", "🧩", "版本管理"),
        ("install", "⬇", "安装游戏"),
        ("verify", "✅", "校验修复"),
        ("settings", "⚙", "设置"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.title(TITLE)
        self.geometry("1240x800")
        self.minsize(1060, 700)
        self.configure(fg_color=PAGE_BG)

        self.queue: queue.Queue = queue.Queue()
        self.busy = False
        self.mirror: mirrors.Mirror | None = None
        self.dir_var = tk.StringVar(value=str(default_mc_dir()))
        self.current_page = "home"
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        self._saves_cache: list[saves.SaveInfo] = []
        self._versions_cache: list = []

        self._build_layout()
        self.after(120, self._poll)
        self.refresh_all()
        self._log(f"mcvd {__version__} 已启动\n", "install")

    # ---------------------------------------------------------------- 布局

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=212, corner_radius=0, fg_color=SIDEBAR_BG)
        sidebar.grid(row=0, column=0, rowspan=2, sticky="nsw")
        sidebar.grid_propagate(False)

        ctk.CTkLabel(sidebar, text="mcvd", font=(FONT, 24, "bold")).pack(anchor="w", padx=20, pady=(22, 0))
        ctk.CTkLabel(sidebar, text="Minecraft 存档 / 目录管理", text_color=MUTED,
                     font=(FONT, 11)).pack(anchor="w", padx=20, pady=(0, 18))

        for key, icon, label in self.NAV:
            button = ctk.CTkButton(
                sidebar,
                text=f"  {icon}   {label}",
                anchor="w",
                height=40,
                corner_radius=8,
                fg_color="transparent",
                hover_color="#1E293B",
                font=(FONT, 14),
                command=lambda k=key: self.show_page(k),
            )
            button.pack(fill="x", padx=12, pady=2)
            self.nav_buttons[key] = button

        ctk.CTkLabel(sidebar, text=f"v{__version__} · 不提供启动游戏", text_color="#475569",
                     font=(FONT, 10)).pack(side="bottom", anchor="w", padx=20, pady=14)

        self.container = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.container.grid(row=0, column=1, sticky="nsew")
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        self.pages: dict[str, ctk.CTkFrame] = {}
        for key, _icon, _label in self.NAV:
            page = ctk.CTkFrame(self.container, corner_radius=0, fg_color="transparent")
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page
            builder = getattr(self, f"_page_{key}")
            builder(page)

        status = ctk.CTkFrame(self, height=36, corner_radius=0, fg_color="#0F172A")
        status.grid(row=1, column=1, sticky="ew")
        status.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(status, text="就绪", anchor="w", text_color=MUTED, font=(FONT, 12))
        self.status_label.grid(row=0, column=0, sticky="w", padx=16, pady=6)
        self.status_progress = ctk.CTkProgressBar(status, width=220, height=8)
        self.status_progress.grid(row=0, column=1, padx=16, pady=6)
        self.status_progress.set(0)

        self.show_page("home")

    def show_page(self, key: str) -> None:
        self.current_page = key
        self.pages[key].tkraise()
        for name, button in self.nav_buttons.items():
            button.configure(fg_color="#1E3A8A" if name == key else "transparent")
        if key == "saves":
            self.refresh_saves()
        elif key == "versions":
            self.refresh_installed_versions()

    def _page_frame(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, corner_radius=0, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=22, pady=18)
        return frame

    def _heading(self, parent: ctk.CTkFrame, title: str, subtitle: str) -> None:
        ctk.CTkLabel(parent, text=title, font=(FONT, 22, "bold")).pack(anchor="w")
        ctk.CTkLabel(parent, text=subtitle, text_color=MUTED, font=(FONT, 12)).pack(anchor="w", pady=(2, 12))

    # ---------------------------------------------------------------- 首页

    def _page_home(self, page: ctk.CTkFrame) -> None:
        body = self._page_frame(page)
        self._heading(body, "游戏目录", "选择任意 .minecraft，自动识别版本、存档、版本隔离与启动器配置")

        card = ctk.CTkFrame(body, corner_radius=12, fg_color=CARD_BG)
        card.pack(fill="x")
        card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(card, text="Minecraft 目录", font=(FONT, 13)).grid(row=0, column=0, padx=(16, 8), pady=14, sticky="w")
        ctk.CTkEntry(card, textvariable=self.dir_var, height=34).grid(row=0, column=1, sticky="ew", pady=14)
        for index, (text, command, width) in enumerate(
            [("浏览…", self._browse_dir, 70), ("刷新", self.refresh_all, 60),
             ("创建…", self._open_create, 64), ("打开", self._open_dir, 60),
             ("详情", self._show_details, 60)], start=2
        ):
            ctk.CTkButton(card, text=text, width=width, command=command).grid(row=0, column=index, padx=4, pady=14)

        stats = ctk.CTkFrame(body, fg_color="transparent")
        stats.pack(fill="x", pady=(12, 0))
        self.stat_labels: dict[str, ctk.CTkLabel] = {}
        for index, (key, title) in enumerate(
            [("versions", "已安装版本"), ("saves", "存档"), ("isolated", "隔离存档"), ("java", "可用 Java")]
        ):
            stats.grid_columnconfigure(index, weight=1)
            item = ctk.CTkFrame(stats, corner_radius=12, fg_color=CARD_BG)
            item.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 8, 0))
            ctk.CTkLabel(item, text=title, text_color=MUTED, font=(FONT, 11)).pack(anchor="w", padx=14, pady=(10, 0))
            value = ctk.CTkLabel(item, text="—", font=(FONT, 22, "bold"))
            value.pack(anchor="w", padx=14, pady=(0, 10))
            self.stat_labels[key] = value

        info_card = ctk.CTkFrame(body, corner_radius=12, fg_color=CARD_BG)
        info_card.pack(fill="both", expand=True, pady=(12, 0))
        self.home_info = ctk.CTkTextbox(info_card, font=(FONT, 12), wrap="word", fg_color="transparent")
        self.home_info.pack(fill="both", expand=True, padx=12, pady=10)
        self.home_info.insert("1.0", "正在检测……")
        self.home_info.configure(state="disabled")

    def _browse_dir(self) -> None:
        chosen = filedialog.askdirectory(title="选择 Minecraft 目录", initialdir=self.dir_var.get())
        if chosen:
            self.dir_var.set(chosen)
            self.refresh_all()

    def _open_dir(self) -> None:
        self._open_path(Path(self.dir_var.get().strip()))

    def _open_create(self) -> None:
        current = Path(self.dir_var.get().strip() or ".")
        parent = current.parent if current.parent != current else current
        dialog = CreateDirDialog(self, parent, current.name or ".minecraft")
        self.wait_window(dialog)
        if dialog.result:
            self.dir_var.set(str(dialog.result))
            self.refresh_all()

    def _show_details(self) -> None:
        info = getattr(self, "_last_info", None)
        if info is None:
            self._set_status("还没有检测结果，请先点「刷新」")
            return
        window = ctk.CTkToplevel(self)
        window.title("目录详情")
        window.geometry("780x620")
        window.transient(self)
        text = ctk.CTkTextbox(window, font=(FONT, 12), wrap="word")
        text.pack(fill="both", expand=True, padx=12, pady=12)
        text.insert("1.0", detect.describe(info, brief=False))
        text.configure(state="disabled")

    @staticmethod
    def _open_path(path: Path) -> None:
        if not path.exists():
            messagebox.showwarning("目录不存在", str(path))
            return
        if os_name() == "windows":
            os.startfile(str(path))  # noqa: S606
        else:
            os.system(f'xdg-open "{path}"')

    # ---------------------------------------------------------------- 存档

    def _page_saves(self, page: ctk.CTkFrame) -> None:
        body = self._page_frame(page)
        self._heading(body, "存档管理", "列表包含全局存档与各隔离版本（versions/<版本>/saves）里的存档")

        toolbar = ctk.CTkFrame(body, fg_color="transparent")
        toolbar.pack(fill="x")
        ctk.CTkButton(toolbar, text="刷新", width=70, command=self.refresh_saves).pack(side="left")
        ctk.CTkButton(toolbar, text="注册全部隔离版本到官方启动器", width=230,
                      command=self.register_all_isolated).pack(side="left", padx=8)
        ctk.CTkButton(toolbar, text="打开 saves 目录", width=130, fg_color="transparent", border_width=1,
                      command=lambda: self._open_path(Path(self.dir_var.get()) / "saves")).pack(side="left")
        self.saves_hint = ctk.CTkLabel(toolbar, text="", text_color=MUTED, font=(FONT, 12))
        self.saves_hint.pack(side="left", padx=12)

        self.saves_scroll = ctk.CTkScrollableFrame(body, fg_color="transparent", corner_radius=0)
        self.saves_scroll.pack(fill="both", expand=True, pady=(10, 0))

    def refresh_saves(self) -> None:
        mc_dir = Path(self.dir_var.get().strip())

        def worker() -> None:
            try:
                found = saves.discover_saves(mc_dir)
                self.queue.put(("saves", found))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("status", f"读取存档失败：{exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _render_saves(self, items: list) -> None:
        for child in self.saves_scroll.winfo_children():
            child.destroy()
        self._saves_cache = items
        if not items:
            ctk.CTkLabel(self.saves_scroll, text="没有找到存档。开始游戏并创建世界后，这里会列出 saves/ 与 versions/*/saves/ 里的存档。",
                         text_color=MUTED, font=(FONT, 12)).pack(anchor="w", pady=20)
            return

        for save in items:
            card = ctk.CTkFrame(self.saves_scroll, corner_radius=10, fg_color=CARD_BG)
            card.pack(fill="x", pady=5)
            card.grid_columnconfigure(0, weight=1)

            title_row = ctk.CTkFrame(card, fg_color="transparent")
            title_row.grid(row=0, column=0, sticky="w", padx=14, pady=(10, 0))
            ctk.CTkLabel(title_row, text=save.name, font=(FONT, 14, "bold")).pack(side="left")
            if save.isolated:
                ctk.CTkLabel(title_row, text=f"  隔离 · {save.version}", text_color=AMBER,
                             font=(FONT, 11)).pack(side="left", padx=6)
            else:
                ctk.CTkLabel(title_row, text="  全局", text_color=GREEN, font=(FONT, 11)).pack(side="left", padx=6)

            size_text = human_bytes(save.size) if save.size else "大小未知"
            time_text = ""
            if save.mtime:
                import datetime

                time_text = datetime.datetime.fromtimestamp(save.mtime).strftime("%Y-%m-%d %H:%M")
            ctk.CTkLabel(card, text=f"{size_text}   ·   最近游玩 {time_text or '未知'}",
                         text_color=MUTED, font=(FONT, 11)).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 8))

            buttons = ctk.CTkFrame(card, fg_color="transparent")
            buttons.grid(row=0, column=1, rowspan=2, padx=14)
            ctk.CTkButton(buttons, text="注册到官方启动器", width=150, height=30,
                          command=lambda s=save: self.register_save(s)).pack(side="left")
            ctk.CTkButton(buttons, text="打开", width=60, height=30, fg_color="transparent", border_width=1,
                          command=lambda s=save: self._open_path(s.path)).pack(side="left", padx=6)

    def register_save(self, save) -> None:
        try:
            profile_id = saves.register_save(Path(self.dir_var.get()), save)
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"注册失败：{exc}")
            return
        self._set_status(f"已注册「{save.name}」到官方启动器（profile {profile_id[:8]}）")
        self._log(f"已注册存档：{save.name} -> 官方启动器\n", "install")

    def register_all_isolated(self) -> None:
        try:
            count = saves.register_all_isolated(Path(self.dir_var.get()))
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"注册失败：{exc}")
            return
        self._set_status(f"已把 {count} 个隔离版本注册到官方启动器")
        self.refresh_saves()

    # ---------------------------------------------------------------- 版本

    def _page_versions(self, page: ctk.CTkFrame) -> None:
        body = self._page_frame(page)
        self._heading(body, "版本管理", "已安装的版本、版本隔离状态，以及是否已注册到官方启动器")

        toolbar = ctk.CTkFrame(body, fg_color="transparent")
        toolbar.pack(fill="x")
        ctk.CTkButton(toolbar, text="刷新", width=70, command=self.refresh_installed_versions).pack(side="left")
        ctk.CTkButton(toolbar, text="打开 versions 目录", width=140, fg_color="transparent", border_width=1,
                      command=lambda: self._open_path(Path(self.dir_var.get()) / "versions")).pack(side="left", padx=8)
        self.versions_hint = ctk.CTkLabel(toolbar, text="", text_color=MUTED, font=(FONT, 12))
        self.versions_hint.pack(side="left", padx=12)

        self.versions_scroll = ctk.CTkScrollableFrame(body, fg_color="transparent", corner_radius=0)
        self.versions_scroll.pack(fill="both", expand=True, pady=(10, 0))

    def refresh_installed_versions(self) -> None:
        mc_dir = Path(self.dir_var.get().strip())

        def worker() -> None:
            try:
                info = detect.inspect(mc_dir, with_size=False, with_java=False)
                profiles = compat.official_profile_entries(mc_dir)
                self.queue.put(("installed", (info, profiles)))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("status", f"读取版本失败：{exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _render_versions(self, info, profiles: list) -> None:
        for child in self.versions_scroll.winfo_children():
            child.destroy()
        self._versions_cache = info.versions
        if not info.versions:
            ctk.CTkLabel(self.versions_scroll, text="这个目录下还没有已安装的版本。",
                         text_color=MUTED, font=(FONT, 12)).pack(anchor="w", pady=20)
            return

        version_dirs = {p: info.path / "versions" / p for p in [v.name for v in info.versions]}
        registered = {}
        for entry in profiles:
            vid = str(entry.get("lastVersionId", ""))
            registered.setdefault(vid.lower(), []).append(entry)

        for item in info.versions:
            card = ctk.CTkFrame(self.versions_scroll, corner_radius=10, fg_color=CARD_BG)
            card.pack(fill="x", pady=5)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=item.name, font=(FONT, 14, "bold")).grid(
                row=0, column=0, sticky="w", padx=14, pady=(10, 0))

            if item.isolated is True:
                state, color = "版本隔离：已开启", AMBER
            elif item.isolated is False:
                state, color = "版本隔离：已关闭", GREEN
            else:
                state, color = "版本隔离：跟随默认设置", MUTED
            extra = f"（{item.reason}）" if item.reason else ""
            saves_dir = version_dirs[item.name] / "saves"
            save_count = sum(1 for _ in saves_dir.glob("*/level.dat")) if saves_dir.is_dir() else 0
            profile_count = len(registered.get(item.name.lower(), []))
            ctk.CTkLabel(card, text=f"{state}{extra}   ·   隔离存档 {save_count} 个   ·   官方启动器配置 {profile_count} 条",
                         text_color=color, font=(FONT, 11)).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 10))

            buttons = ctk.CTkFrame(card, fg_color="transparent")
            buttons.grid(row=0, column=1, rowspan=2, padx=14)
            ctk.CTkButton(buttons, text="注册到官方启动器", width=150, height=30,
                          command=lambda n=item.name: self.register_version(n)).pack(side="left")
            ctk.CTkButton(buttons, text="打开目录", width=80, height=30, fg_color="transparent", border_width=1,
                          command=lambda p=version_dirs[item.name]: self._open_path(p)).pack(side="left", padx=6)

    def register_version(self, version_id: str) -> None:
        mc_dir = Path(self.dir_var.get())
        version_dir = mc_dir / "versions" / version_id
        try:
            profile_id = compat.register_official_profile(
                mc_dir, version_id, display_name=version_id, game_dir=version_dir
            )
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"注册失败：{exc}")
            return
        self._set_status(f"已注册 {version_id} 到官方启动器（profile {profile_id[:8]}，gameDir=versions/{version_id}）")
        self.refresh_installed_versions()

    # ---------------------------------------------------------------- 安装

    def _page_install(self, page: ctk.CTkFrame) -> None:
        body = self._page_frame(page)
        self._heading(body, "安装游戏", "原版 / Fabric / Quilt / Forge / NeoForge，装完自动写入官方启动器配置")

        card = ctk.CTkFrame(body, corner_radius=12, fg_color=CARD_BG)
        card.pack(fill="x")
        for col in (1, 3):
            card.grid_columnconfigure(col, weight=1)

        self.version_var = tk.StringVar(value="latest")
        self.loader_var = tk.StringVar(value="无（仅原版）")
        self.loader_version_var = tk.StringVar(value="自动")
        self.name_var = tk.StringVar(value="")
        self.mirror_var = tk.StringVar(value="自动测速")
        self.threads_var = tk.StringVar(value="16")
        self.skip_assets_var = tk.BooleanVar(value=False)
        self.auto_verify_var = tk.BooleanVar(value=True)
        self.register_profile_var = tk.BooleanVar(value=True)

        ctk.CTkLabel(card, text="游戏版本", font=(FONT, 13)).grid(row=0, column=0, sticky="w", padx=(16, 8), pady=(14, 6))
        self.version_combo = ctk.CTkComboBox(card, variable=self.version_var, values=["latest"],
                                             command=lambda _v: self._on_game_version_change())
        self.version_combo.grid(row=0, column=1, sticky="ew", pady=(14, 6))
        ctk.CTkButton(card, text="刷新版本", width=90, command=self.refresh_versions).grid(row=0, column=2, padx=6, pady=(14, 6))

        ctk.CTkLabel(card, text="版本类型", font=(FONT, 13)).grid(row=0, column=3, sticky="e", padx=8, pady=(14, 6))
        self.version_type_var = tk.StringVar(value="正式版")
        ctk.CTkOptionMenu(card, variable=self.version_type_var, values=["正式版", "快照", "全部"],
                          command=lambda _v: self.refresh_versions()).grid(row=0, column=4, sticky="ew", padx=(0, 16), pady=(14, 6))

        ctk.CTkLabel(card, text="加载器", font=(FONT, 13)).grid(row=1, column=0, sticky="w", padx=(16, 8), pady=6)
        self.loader_menu = ctk.CTkOptionMenu(card, variable=self.loader_var,
                                             values=["无（仅原版）", "Fabric", "Quilt", "Forge", "NeoForge"],
                                             command=lambda _v: self._on_loader_change())
        self.loader_menu.grid(row=1, column=1, sticky="ew", pady=6)

        ctk.CTkLabel(card, text="加载器版本", font=(FONT, 13)).grid(row=1, column=3, sticky="e", padx=8, pady=6)
        self.loader_version_menu = ctk.CTkOptionMenu(card, variable=self.loader_version_var,
                                                     values=["自动"], state="disabled")
        self.loader_version_menu.grid(row=1, column=4, sticky="ew", padx=(0, 16), pady=6)

        ctk.CTkLabel(card, text="版本名（可选）", font=(FONT, 13)).grid(row=2, column=0, sticky="w", padx=(16, 8), pady=6)
        ctk.CTkEntry(card, textvariable=self.name_var, placeholder_text="对应 PCL 的「版本名称」").grid(
            row=2, column=1, columnspan=3, sticky="ew", pady=6)

        ctk.CTkLabel(card, text="下载源", font=(FONT, 13)).grid(row=3, column=0, sticky="w", padx=(16, 8), pady=6)
        ctk.CTkOptionMenu(card, variable=self.mirror_var, values=["自动测速", "官方源", "BMCLAPI 镜像"]).grid(
            row=3, column=1, sticky="ew", pady=6)

        ctk.CTkLabel(card, text="线程", font=(FONT, 13)).grid(row=3, column=3, sticky="e", padx=8, pady=6)
        ctk.CTkOptionMenu(card, variable=self.threads_var, values=["4", "8", "16", "32"]).grid(
            row=3, column=4, sticky="ew", padx=(0, 16), pady=6)

        options = ctk.CTkFrame(card, fg_color="transparent")
        options.grid(row=4, column=0, columnspan=5, sticky="w", padx=16, pady=(6, 4))
        ctk.CTkCheckBox(options, text="跳过资源文件", variable=self.skip_assets_var, font=(FONT, 12)).pack(side="left", padx=(0, 18))
        ctk.CTkCheckBox(options, text="装完自动校验", variable=self.auto_verify_var, font=(FONT, 12)).pack(side="left", padx=(0, 18))
        ctk.CTkCheckBox(options, text="注册到官方启动器", variable=self.register_profile_var, font=(FONT, 12)).pack(side="left")

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.pack(fill="x", pady=(12, 0))
        self.install_btn = ctk.CTkButton(actions, text="开始安装", width=130, height=38, command=self.start_install)
        self.install_btn.pack(side="left")
        self.install_progress = ctk.CTkProgressBar(actions, height=10)
        self.install_progress.pack(side="left", fill="x", expand=True, padx=14)
        self.install_progress.set(0)
        self.install_percent = ctk.CTkLabel(actions, text="就绪", width=160, text_color=MUTED)
        self.install_percent.pack(side="left")

        log_card = ctk.CTkFrame(body, corner_radius=12, fg_color=CARD_BG)
        log_card.pack(fill="both", expand=True, pady=(12, 0))
        self.install_log = ctk.CTkTextbox(log_card, font=("Consolas", 12), wrap="word")
        self.install_log.pack(fill="both", expand=True, padx=10, pady=10)

    # ---------------------------------------------------------------- 校验

    def _page_verify(self, page: ctk.CTkFrame) -> None:
        body = self._page_frame(page)
        self._heading(body, "校验修复", "沿 inheritsFrom 校验全部文件（SHA-1 + 大小），可自动重新下载损坏文件")

        toolbar = ctk.CTkFrame(body, fg_color="transparent")
        toolbar.pack(fill="x")
        ctk.CTkButton(toolbar, text="校验全部", width=110, command=lambda: self.start_verify(False)).pack(side="left")
        ctk.CTkButton(toolbar, text="校验并修复", width=130, command=lambda: self.start_verify(True)).pack(side="left", padx=8)
        self.verify_result = ctk.CTkLabel(toolbar, text="", text_color=MUTED, font=(FONT, 12))
        self.verify_result.pack(side="left", padx=12)

        card = ctk.CTkFrame(body, corner_radius=12, fg_color=CARD_BG)
        card.pack(fill="both", expand=True, pady=(10, 0))
        self.verify_log = ctk.CTkTextbox(card, font=("Consolas", 12), wrap="word")
        self.verify_log.pack(fill="both", expand=True, padx=10, pady=10)

    # ---------------------------------------------------------------- 设置

    def _page_settings(self, page: ctk.CTkFrame) -> None:
        body = self._page_frame(page)
        self._heading(body, "设置", "外观、下载源测速与关于")

        card = ctk.CTkFrame(body, corner_radius=12, fg_color=CARD_BG)
        card.pack(fill="x")
        ctk.CTkLabel(card, text="外观", font=(FONT, 13)).pack(anchor="w", padx=16, pady=(14, 4))
        self.appearance = ctk.CTkSegmentedButton(card, values=["深色", "浅色", "跟随系统"],
                                                 command=self._change_appearance)
        self.appearance.set("深色")
        self.appearance.pack(anchor="w", padx=16, pady=(0, 14))

        ctk.CTkLabel(card, text="下载源", font=(FONT, 13)).pack(anchor="w", padx=16, pady=(0, 4))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(row, text="测速官方源 / BMCLAPI", width=200, command=self.probe_mirrors).pack(side="left")
        self.mirror_result = ctk.CTkLabel(row, text="", text_color=MUTED, font=(FONT, 12))
        self.mirror_result.pack(side="left", padx=12)

        about = ctk.CTkFrame(body, corner_radius=12, fg_color=CARD_BG)
        about.pack(fill="both", expand=True, pady=(12, 0))
        text = ctk.CTkTextbox(about, font=(FONT, 12), wrap="word", fg_color="transparent")
        text.pack(fill="both", expand=True, padx=10, pady=10)
        text.insert("1.0", (
            f"mcvd {__version__}\n\n"
            "Minecraft 存档 / 游戏目录管理工具：\n"
            "· 管理多个 .minecraft 目录与版本隔离\n"
            "· 把隔离存档 / 版本注册到官方启动器\n"
            "· 安装原版与 Fabric / Quilt / Forge / NeoForge\n"
            "· 校验与修复已安装版本\n\n"
            "不提供启动游戏功能。\n"
            "开源：https://github.com/huiyaoxingkong/mc-vanilla-downloader\n"
            "界面：customtkinter（MIT）\n"
        ))
        text.configure(state="disabled")

    def _change_appearance(self, value: str) -> None:
        ctk.set_appearance_mode({"深色": "dark", "浅色": "light", "跟随系统": "system"}.get(value, "dark"))

    # ---------------------------------------------------------------- 后台任务

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass
        self.after(120, self._poll)

    def _handle(self, kind: str, payload) -> None:
        if kind == "log":
            self._log(payload, "verify" if self.current_page == "verify" else "install")
        elif kind == "status":
            self._set_status(str(payload))
        elif kind == "progress":
            done, total = payload
            if total:
                self.install_progress.set(min(1.0, done / total))
                self.install_percent.configure(text=f"{done}/{total}")
        elif kind == "saves":
            self._render_saves(payload)
        elif kind == "installed":
            info, profiles = payload
            self._render_versions(info, profiles)
        elif kind == "versions":
            values = payload
            if values:
                self.version_combo.configure(values=values)
                if self.version_var.get() not in values:
                    self.version_var.set(values[0])
        elif kind == "loader_versions":
            versions = payload
            self.loader_version_menu.configure(values=["自动"] + versions, state="normal")
            self.loader_version_var.set("自动" if versions else "自动")
            if not versions:
                self._set_status("没有取到加载器版本列表（可手动输入？先用「自动」）")
        elif kind == "inspect":
            text, stats = payload
            self.home_info.configure(state="normal")
            self.home_info.delete("1.0", "end")
            self.home_info.insert("1.0", text)
            self.home_info.configure(state="disabled")
            for key, value in stats.items():
                if key in self.stat_labels:
                    self.stat_labels[key].configure(text=str(value))
        elif kind == "inspect_info":
            self._last_info = payload
        elif kind == "busy":
            self._set_busy(bool(payload))
        elif kind == "verify_done":
            self.verify_result.configure(text=str(payload))
        elif kind == "mirror":
            self.mirror_result.configure(text=str(payload))
        elif kind == "refresh_after":
            if payload:
                self.refresh_all()
        elif kind == "done":
            self._set_status(str(payload))

    def _log(self, text: str, box: str = "install") -> None:
        widget = self.install_log if box == "install" else self.verify_log
        widget.configure(state="normal")
        widget.insert("end", text)
        widget.see("end")
        widget.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        try:
            self.install_btn.configure(state=state)
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------------- 刷新

    def refresh_all(self) -> None:
        mc_dir = Path(self.dir_var.get().strip())
        self._set_status(f"正在检测 {mc_dir} …")

        def worker() -> None:
            try:
                info = detect.inspect(mc_dir, with_size=False, with_java=True)
                summary = saves.save_summary(mc_dir)
                self.queue.put(("inspect_info", info))
                self.queue.put(("inspect", (detect.describe(info, brief=True), {
                    "versions": len(info.versions),
                    "saves": summary["total"],
                    "isolated": summary["isolated"],
                    "java": len(info.java_list),
                })))
                self.queue.put(("status", "就绪"))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("status", f"检测失败：{exc}"))

        threading.Thread(target=worker, daemon=True).start()
        self.refresh_versions()
        self.refresh_saves()
        self.refresh_installed_versions()

    def refresh_versions(self) -> None:
        kind_map = {"正式版": "release", "快照": "snapshot", "全部": "all"}
        kind = kind_map.get(self.version_type_var.get() if hasattr(self, "version_type_var") else "正式版", "release")

        def worker() -> None:
            try:
                # 列表用官方清单即可（失败会自动回退 BMCLAPI），避免启动时测速造成卡顿
                payload = manifest.get_manifest(mirrors.MIRROR_OFFICIAL)
                versions = manifest.filter_versions(payload, kind, 60)
                self.queue.put(("versions", [item["id"] for item in versions]))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("status", f"版本列表获取失败：{exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def probe_mirrors(self) -> None:
        self.mirror_result.configure(text="测速中…")

        def worker() -> None:
            results = manifest.probe_mirrors(mirrors.ALL_MIRRORS, timeout=10.0)
            parts = [f"{item['mirror'].name}: " + (f"{item['seconds'] * 1000:.0f} ms" if item["ok"] else "不可用")
                     for item in results]
            self.mirror = None
            self.queue.put(("mirror", "   ".join(parts)))

        self.queue.put(("mirror", "测速中…"))
        threading.Thread(target=worker, daemon=True).start()

    def _mirror_obj(self) -> mirrors.Mirror:
        if self.mirror is not None:
            return self.mirror
        mode = self.mirror_var.get() if hasattr(self, "mirror_var") else "自动测速"
        if mode == "官方源":
            self.mirror = mirrors.MIRROR_OFFICIAL
        elif mode.startswith("BMCLAPI"):
            self.mirror = mirrors.MIRROR_BMCLAPI
        else:
            results = manifest.probe_mirrors(mirrors.ALL_MIRRORS, timeout=10.0)
            available = [item for item in results if item["ok"]]
            self.mirror = min(available, key=lambda item: item["seconds"])["mirror"] if available else mirrors.MIRROR_OFFICIAL
        return self.mirror

    def _make_options(self) -> InstallOptions:
        loader_text = self.loader_var.get()
        loader_key = None if loader_text.startswith("无") else loader_text.lower()
        loader_version = self.loader_version_var.get().strip()
        if loader_version in ("", "自动"):
            loader_version = None
        try:
            threads = max(1, min(64, int(self.threads_var.get())))
        except ValueError:
            threads = 16
        return InstallOptions(
            mc_dir=Path(self.dir_var.get().strip()),
            mirror=self._mirror_obj(),
            threads=threads,
            with_assets=not self.skip_assets_var.get(),
            name=self.name_var.get().strip() or None,
            loader=loader_key,
            loader_version=loader_version,
            register_profile=self.register_profile_var.get(),
            progress_cb=lambda done, total: self.queue.put(("progress", done, total)),
        )

    # ---------------------------------------------------------------- 安装执行

    def start_install(self) -> None:
        if self.busy:
            return
        version = self.version_var.get().strip()
        if not version:
            self._set_status("请先选择游戏版本")
            return
        mc_dir = Path(self.dir_var.get().strip())
        if not mc_dir.is_dir():
            if not messagebox.askyesno("目录不存在", f"{mc_dir}\n\n要创建这个目录吗？"):
                return
            mc_dir.mkdir(parents=True, exist_ok=True)

        self._set_busy(True)
        self.install_progress.set(0)
        self.install_percent.configure(text="准备中…")
        self.show_page("install")
        self._log("\n" + "=" * 60 + "\n")

        def worker() -> None:
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = _QueueWriter(self)
            try:
                options = self._make_options()
                loader_text = self.loader_var.get()
                self.queue.put(("log", f"目标目录：{options.mc_dir}\n"))
                if loader_text.startswith("无"):
                    result = install(version, options)
                else:
                    result = loaders.install_loader(loader_text.lower(), version, options.loader_version, options)
                self.queue.put(("log", f"\n完成：{result.version_id}\n"))
                if self.auto_verify_var.get():
                    report = verify.verify_version(result.version_id, options.mc_dir, options)
                    self.queue.put(("log", verify.format_report(report) + "\n"))
                self.queue.put(("done", f"安装完成：{result.version_id}"))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("log", traceback.format_exc()))
                self.queue.put(("status", f"安装失败：{exc}"))
            finally:
                sys.stdout, sys.stderr = old_out, old_err
                self.queue.put(("busy", False))
                self.queue.put(("done", "刷新中…"))
                self.queue.put(("refresh_after", True))

        threading.Thread(target=worker, daemon=True).start()

    def start_verify(self, fix: bool) -> None:
        if self.busy:
            return
        mc_dir = Path(self.dir_var.get().strip())
        if not mc_dir.is_dir():
            self._set_status("目录不存在")
            return
        self._set_busy(True)
        self.show_page("verify")
        self.verify_result.configure(text="校验中…")

        def worker() -> None:
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = _QueueWriter(self)
            try:
                options = self._make_options()
                names = verify.all_versions(mc_dir)
                if not names:
                    self.queue.put(("verify_done", "没有已安装版本"))
                    return
                bad = 0
                for name in names:
                    report = verify.verify_version(name, mc_dir, options, fix=fix)
                    self.queue.put(("log", verify.format_report(report) + "\n"))
                    bad += len(report.problems)
                self.queue.put(("verify_done", f"完成：{len(names)} 个版本，{bad} 个问题"))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("log", traceback.format_exc()))
                self.queue.put(("verify_done", f"失败：{exc}"))
            finally:
                sys.stdout, sys.stderr = old_out, old_err
                self.queue.put(("busy", False))

        threading.Thread(target=worker, daemon=True).start()

    # ---------------------------------------------------------------- 下拉联动

    def _on_game_version_change(self) -> None:
        if not self.loader_var.get().startswith("无"):
            self._on_loader_change()

    def _on_loader_change(self) -> None:
        loader_text = self.loader_var.get()
        if loader_text.startswith("无"):
            self.loader_version_menu.configure(values=["自动"], state="disabled")
            self.loader_version_var.set("自动")
            return
        self.loader_version_menu.configure(values=["加载中…"], state="disabled")
        self.loader_version_var.set("加载中…")
        loader = loader_text.lower()
        game = self.version_var.get().strip() or "latest"

        def worker() -> None:
            try:
                manifest_payload = manifest.get_manifest(mirrors.MIRROR_OFFICIAL)
                game_id = manifest.pick_version(manifest_payload, game)["id"]
                versions = loaders.loaders_for(game_id, loader)
                self.queue.put(("loader_versions", versions[:80]))
                self.queue.put(("status", f"{loader_text}：{game_id} 共 {len(versions)} 个可用版本"))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("loader_versions", []))
                self.queue.put(("status", f"加载器版本获取失败：{exc}"))

        threading.Thread(target=worker, daemon=True).start()


class _QueueWriter:
    def __init__(self, app: App) -> None:
        self.app = app

    def write(self, text: str) -> None:
        if text:
            self.app.queue.put(("log", text))

    def flush(self) -> None:
        pass


def run() -> int:
    if not _single_instance_guard():
        return 0
    app = App()
    app.mainloop()
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
