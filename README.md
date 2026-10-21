# mc-vanilla-downloader（mcvd）

**Minecraft 存档 / 游戏目录管理工具 + 原版安装器**（默认图形界面，深色现代 UI）。管理多个 `.minecraft` 目录、版本与存档，识别 PCL / HMCL 的版本隔离，把**隔离存档注册到官方启动器**；同时提供原版 / Fabric / Quilt / Forge / NeoForge 的下载安装。

> **不提供启动游戏功能**：只做目录、存档、版本与安装的管理。

![主界面](docs/images/gui-main.png)

- 💾 **存档管理**：列出全局 `saves/` 与各隔离版本 `versions/<版本>/saves` 里的存档（大小、最近游玩时间），一键注册到官方启动器
- 🧩 **版本管理**：每个版本的隔离状态、隔离存档数、官方启动器配置条数
- 📁 **多目录**：自动识别 .minecraft、启动器配置（PCL / HMCL / BakaXL / LauncherX / MSL）、Java、占用空间
- ⬇ **安装游戏**：原版与加载器，加载器版本**联网拉取后可选**（不再只有「自动」）
- ✅ **校验修复**：沿 `inheritsFrom` 全量校验 SHA-1，可自动重下损坏文件
- 单实例运行（重复双击只把已有窗口提到前台）、后台任务不弹窗打扰
- 界面使用 [customtkinter](https://github.com/TomSchimansky/CustomTkinter)（MIT）；打包后的 exe 免安装

> 背景：2026-10-20 起 PCL、HMCL 等在中国大陆展业的启动器陆续关闭了游戏本体下载功能。
> 本工具不在启动器里改任何东西，只是把**官方原版文件**按标准目录结构装好，供**个人自用**。
> 请先阅读 [免责声明](#免责声明)。

## 图形界面（默认）

双击 `mcvd.exe`，或者运行 `python -m mcvd`（不带参数）。左侧导航，共 6 个页面：

| 页面 | 能做什么 |
|---|---|
| **游戏目录** | 选择任意 `.minecraft`；识别版本、存档、assets/libraries、**PCL 便携配置与版本隔离**、启动器、Java、占用空间；「详情」看逐个版本状态；「创建…」新建游戏文件夹 |
| **存档管理** | 全局 + 隔离存档列表；每条可「注册到官方启动器」「打开」；顶部可「注册全部隔离版本」 |
| **版本管理** | 已安装版本卡片：隔离状态、隔离存档数、官方启动器配置数；可注册到官方启动器 / 打开目录 |
| **安装游戏** | 游戏版本、加载器与**加载器版本下拉（联网获取）**、自定义版本名、下载源、线程、进度条与日志 |
| **校验修复** | 校验全部 / 校验并修复，结果写入日志 |
| **设置** | 深色 / 浅色 / 跟随系统、下载源测速、关于 |

「创建游戏文件夹」对话框：选创建位置、文件夹名、**默认版本隔离**（写入 `PCL/Setup.ini` 的 `LaunchArgumentIndieV2`），可勾选生成基础结构与 PCL 便携配置。

![创建游戏文件夹](docs/images/gui-create.png)

存档管理（每条存档都能一键注册到官方启动器）与安装页面（加载器版本联网获取后可下拉选择）：

![存档管理](docs/images/gui-saves.png)

![安装游戏](docs/images/gui-install.png)

「版本隔离」的识别依据（与 PCL 2.9x 一致）：

- 全局默认：`PCL/Setup.ini` 的 `LaunchArgumentIndieV2`（0=关闭，1=隔离可安装 Mod 的版本，2=隔离非正式版，3=两者，4=隔离所有版本）；
- 单版本覆盖：`versions/<id>/PCL/Setup.ini` 的 `VersionArgumentIndieV2`（True/False）；
- 没有配置时：如果版本目录下存在非空的 `mods/` 或 `saves/`，按 PCL 的自动规则判定为「已隔离」。

## 存档管理：把隔离存档注册到官方启动器

启用版本隔离后，存档不在 `.minecraft/saves`，而在 `versions/<版本>/saves`。官方启动器默认只看 `.minecraft/saves`，所以这些存档在官方启动器里「看不见」。

解决方法：往 `launcher_profiles.json` 写一条带 `gameDir` 的 `custom` 配置，`gameDir` 指向 `versions/<版本>`。本工具在「存档管理」「版本管理」里都可以一键完成：

```json
"profiles": {
  "<uuid>": {
    "name": "新的世界（NTM NEXT）",
    "type": "custom",
    "lastVersionId": "NTM NEXT",
    "gameDir": "C:\\Users\\lihao\\AppData\\Roaming\\.minecraft\\versions\\NTM NEXT",
    "icon": "Grass",
    "created": "2026-10-21T20:58:00.000Z",
    "lastUsed": "2026-10-21T20:58:00.000Z"
  }
}
```

## 启动器兼容

安装出来的就是标准 `.minecraft` 结构，下面这些启动器都能直接识别：

| 启动器 | 需要的格式 | 本工具的处理 |
|---|---|---|
| **官方启动器**（Minecraft Launcher） | 除 `versions/<id>/` 外，还要在 `launcher_profiles.json` 的 `profiles` 里有一条 `type: "custom"` 的配置 | 安装完成后自动写入 / 更新配置（保留原有 profiles 与 settings，`version: 6`）；界面里可勾选「注册到官方启动器」，CLI 用 `--no-profile` 关闭 |
| **PCL2 / PCL2-CE** | 便携模式读 `PCL/Setup.ini`，扫描 `versions/` | 安装结构天然兼容；创建目录时可写入默认版本隔离；识别时读取并显示 |
| **HMCL** | 扫描 `versions/<id>/<id>.json`；设置在新版 `config/launcher-settings.json`、旧版 `hmcl.json` | 安装结构天然兼容；识别并显示 HMCL 配置是否存在、能读到的隔离设置 |
| **BakaXL / LauncherX / MSL** | 扫描标准 `.minecraft` 结构 | 安装结构天然兼容；识别到对应文件时在界面标出 |

GUI 的目录检测会直接列出「启动器：官方启动器（launcher_profiles.json，N 个配置）· HMCL · PCL2 …」。
安装时只写两个地方：`versions/` 与 `launcher_profiles.json`（后者可关），不会改动启动器本体。

## 命令行

`mcvd-cli.exe`（或本机 Python 的 `python -m mcvd <命令>`）保留完整 CLI，适合脚本与自动化：

```bash
python -m mcvd gui                 # 打开图形界面
python -m mcvd mirrors             # 测一下官方源和国内镜像哪个快
python -m mcvd list --limit 10     # 看看有哪些版本
python -m mcvd install latest      # 下载最新正式版到 %APPDATA%\.minecraft
mcvd install 1.20.1 --loader forge --name 我的整合包
mcvd verify --fix                  # 校验并修复全部版本
```

| 命令 | 说明 |
|---|---|
| `mcvd`（无参数） | 打开图形界面 |
| `mcvd gui` | 同上（显式） |
| `mcvd mirrors` | 检测官方源与 BMCLAPI 的可用性和耗时 |
| `mcvd list [--type release\|snapshot\|all] [--limit N] [--json]` | 列出可用版本 |
| `mcvd info <版本>` | 查看版本信息 |
| `mcvd loaders <fabric\|quilt> <游戏版本>` | 列出加载器支持的版本 |
| `mcvd install <版本> [--loader ...] [--name NAME]` | 下载并安装原版或加载器版本 |
| `mcvd verify [版本] [--fix]` | 校验已安装版本（默认全部），`--fix` 自动重下 |
| `mcvd tui` | 文字交互菜单（没有图形环境时） |

## 加载器

| 加载器 | 实现方式 | 备注 |
|---|---|---|
| **Fabric** | 拉 `meta.fabricmc.net` 的 profile JSON（`inheritsFrom` 原版），下载其库 | 自动选最新稳定版，`--loader-version` 可指定 |
| **Quilt** | 同上，`meta.quiltmc.org` | |
| **Forge** | 下载官方 `installer.jar`，用本机 Java 执行 `--installClient <目录>` | 自动按游戏版本选 Java（1.20.1→17，1.21→21，1.16.5→8…），也可 `--java` 指定 |
| **NeoForge** | 同 Forge，走 `maven.neoforged.net` | 该 maven 在部分网络下不可达，可用 `--installer` 指定已下载的 installer.jar |

```bash
mcvd install 1.21.4 --loader fabric --loader-version 0.16.9
mcvd install 1.20.1 --loader forge --name 生存服客户端
mcvd install 1.20.1 --loader forge --installer D:\downloads\forge-1.20.1-47.2.0-installer.jar
```

加载器版本会写成 `versions/<名字>/<名字>.json`，`inheritsFrom` 指向原版；PCL / HMCL 会像处理自己装的版本一样处理它。

## 自定义版本名（PCL 的「版本名称」）

`--name`（或界面里的「版本名」）会把版本目录、`<id>.json` 里的 `id`、客户端 jar 文件名统一改成你给的名字：

```bash
mcvd install 1.21.4 --loader fabric --name 原版生存
mcvd install 1.20.1 --name 老版本备份
```

对 Forge/NeoForge（由官方安装器生成目录）会在安装完成后自动重命名目录并改写 JSON。

## 校验与修复

```bash
mcvd verify                    # 校验全部已安装版本
mcvd verify 1.21.4             # 只校验某个版本
mcvd verify --fix              # 发现缺失/损坏的文件自动重新下载
```

校验会沿着 `inheritsFrom` 把父版本（原版）的文件一起算进去，逐文件核对 SHA-1 和大小；资源索引缺失时也会提示。图形界面里点「校验并修复」等价于 `verify --fix`。

## 打包成单文件 exe

```powershell
powershell -ExecutionPolicy Bypass -File packaging/build.ps1
```

会生成两个文件：

- `dist\mcvd.exe` —— 图形界面版（无控制台窗口，双击进入界面）
- `dist\mcvd-cli.exe` —— 命令行版（保留控制台，给脚本用）

## 下载源：官方 vs 国内镜像

`--mirror auto`（默认）会在启动时各拉一次版本清单测速，选快的那个；下载单个文件失败时会自动换另一个源重试。

实测数据见 [docs/MIRRORS.md](docs/MIRRORS.md)，要点：

- **BMCLAPI**（`bmclapi2.bangbang93.com`）是国内事实标准镜像，覆盖版本清单、版本 JSON、客户端 jar、依赖库、资源对象；
- 官方源在本机实测有时比镜像更快（跨境线路好时），所以默认不写死镜像，而是**每次测量**；
- 镜像偶发冷启动慢（首包 10s 级），已做超时 + 重试 + 换源处理，不会卡死。

URL 重写规则（纯函数，见 `src/mcvd/mirrors.py`）：

| 官方域名 | BMCLAPI 路径 |
|---|---|
| `launchermeta.mojang.com` / `piston-meta.mojang.com` / `piston-data.mojang.com` | 同路径 |
| `libraries.minecraft.net/<path>` | `/maven/<path>` |
| `resources.download.minecraft.net/<ab>/<hash>` | `/assets/<ab>/<hash>` |

## 安装出来的目录结构

```
<.minecraft>/
├── versions/<id>/<id>.json     # 版本 JSON（原版或加载器 profile）
├── versions/<id>/<id>.jar      # client.jar（加载器版本通过 inheritsFrom 复用原版）
├── versions/<id>/PCL/Setup.ini # 该版本的独立设置（版本隔离等，PCL 生成）
├── versions/<id>/mcvd-install.json
├── libraries/...               # Maven 布局的依赖库（含 natives）
├── assets/indexes/<id>.json    # 资源索引
├── assets/objects/<ab>/<hash>  # 资源对象（SHA-1 命名）
└── resources/                  # 仅旧版本：map_to_resources 兼容副本
```

安装器不会修改任何启动器文件，也不会写注册表。

## 项目结构

```
src/mcvd/
├── gui.py        # 图形界面（customtkinter）
├── saves.py      # 存档发现 / 注册到官方启动器（gameDir）
├── detect.py     # 目录识别 / 创建（版本隔离判定）
├── compat.py     # 启动器兼容（官方 launcher_profiles / HMCL / BakaXL 等识别）
├── cli.py        # 命令行
├── mirrors.py    # 镜像定义与 URL 重写
├── manifest.py   # 版本清单/版本 JSON 解析
├── rules.py      # libraries 的 rules 判定（os / arch / features）
├── netio.py      # HTTP：多源回退、续传、SHA-1、连接复用
├── installer.py  # 安装编排：客户端、依赖库、资源文件
├── loaders.py    # Fabric / Quilt / Forge / NeoForge
├── java.py       # 查找本机 Java（Forge 安装器需要）
└── verify.py     # 版本完整性校验与修复
packaging/        # PyInstaller 入口与构建脚本
tests/            # 74 个纯离线单元测试
docs/MIRRORS.md   # 镜像调研与实测数据
```

## 测试

```bash
python -m unittest discover -s tests -v
```

单元测试不联网，覆盖 URL 重写、rules 判定、版本选择、路径生成、哈希校验、校验/修复逻辑、目录识别与版本隔离判定、启动器兼容（launcher_profiles 注册与保留、HMCL 配置识别）、存档发现与「隔离存档注册到官方启动器」、加载器版本列表解析。

## 开源与致谢

- 代码以 **MIT** 许可发布，见 [LICENSE](LICENSE)。
- 界面使用 **customtkinter**（MIT）与 **darkdetect**（BSD-3-Clause），已打包进 exe。
- 参考的公开规范、镜像服务与启动器行为，全部列在 [NOTICE.md](NOTICE.md)：
  Mojang 版本清单规范、Minecraft Wiki 的 Client.json 文档、**BMCLAPI**（bangbang93 维护的社区镜像）、
  **Fabric / Quilt / Forge / NeoForge 官方 meta 与安装器**、PCL2 / HMCL 的目录约定。
- 本项目**没有复制**任何第三方项目的源代码，也不包含任何游戏文件。

## 免责声明

- 本项目不包含、不托管、不分发任何 Mojang / Microsoft 的游戏文件，所有文件都从官方服务器或公开镜像实时下载。
- 使用前请确保你拥有合法的 Minecraft 账号，并遵守 [Minecraft EULA](https://www.minecraft.net/eula)。
- 仅建议个人自用，请勿用于二次分发游戏内容；请遵守你所在地区的法律法规。
- 因使用本项目产生的一切后果由使用者自行承担。

## License

MIT © 2026 huiyaoxingkong and mcvd contributors
