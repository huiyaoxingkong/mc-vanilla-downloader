# mc-vanilla-downloader（mcvd）

一个只用 Python 标准库写的 **Minecraft 原版 / 加载器安装器**：从 Mojang 官方或国内镜像（BMCLAPI）把指定版本的客户端、依赖库、资源文件下载到 `.minecraft` 目录，生成 **PCL / HMCL / 官方启动器都能直接识别**的版本。

支持 **Fabric / Quilt / Forge / NeoForge**，支持**自定义版本名**（对应 PCL 的「版本名称」），内置**版本完整性校验与自动修复**，还能打包成**双击即用的单文件 exe**。

- 多源自动测速选源，单文件失败自动切换镜像
- 断点续传、SHA-1 校验、失败重试、HTTP 连接复用（keep-alive）
- 多线程并发下载
- 只依赖 Python 3.9+ 标准库，运行时不需 `pip install` 任何东西

> 背景：2026-10-20 起 PCL、HMCL 等在中国大陆展业的启动器陆续关闭了游戏本体下载功能。
> 本工具不在启动器里改任何东西，只是把**官方原版文件**按标准目录结构装好，供**个人自用**。
> 请先阅读 [免责声明](#免责声明)。

## 快速开始

```bash
# 不需要安装，直接从仓库运行
python -m mcvd                    # 交互模式（就是双击 exe 看到的菜单）
python -m mcvd mirrors            # 测一下官方源和国内镜像哪个快
python -m mcvd list --limit 10    # 看看有哪些版本
python -m mcvd install latest     # 下载最新正式版到 %APPDATA%\.minecraft
```

也可以安装成命令：

```bash
pip install -e .
mcvd install 26.3
```

装完打开 PCL / HMCL，版本列表里就会出现新版本（它们会自动扫描 `versions/` 目录）。

## 命令

| 命令 | 说明 |
|---|---|
| `mcvd` | 交互菜单（双击 exe 即进入） |
| `mcvd mirrors` | 检测官方源与 BMCLAPI 的可用性和耗时 |
| `mcvd list [--type release\|snapshot\|all] [--limit N] [--json]` | 列出可用版本 |
| `mcvd info <版本>` | 查看版本信息（Java 版本、依赖库数量、客户端大小等） |
| `mcvd loaders <fabric\|quilt> <游戏版本>` | 列出加载器支持的版本 |
| `mcvd install <版本> [--loader ...] [--name NAME]` | 下载并安装原版或加载器版本 |
| `mcvd verify [版本] [--fix]` | 校验已安装版本（默认校验全部），`--fix` 自动重下缺失/损坏文件 |

常用示例：

```bash
mcvd install latest --dry-run                  # 只看要下多少，不实际下载
mcvd install 26.3 --mirror bmclapi             # 强制走国内镜像
mcvd install 1.20.1 --dir D:\MC                # 装到指定目录
mcvd install 1.21.4 --loader fabric            # 原版 + Fabric
mcvd install 1.20.1 --loader forge --name 我的整合包   # 自定义版本名
mcvd verify --fix                              # 校验并修复全部版本
```

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

`--name` 会把版本目录、`<id>.json` 里的 `id`、客户端 jar 文件名统一改成你给的名字：

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

校验会沿着 `inheritsFrom` 把父版本（原版）的文件一起算进去，逐文件核对 SHA-1 和大小；资源索引缺失时也会提示。

## 打包成单文件 exe

```powershell
powershell -ExecutionPolicy Bypass -File packaging/build.ps1
```

产物是 `dist\mcvd.exe`（约 9 MB，单文件、无需 Python 环境）。双击它进入交互菜单：

```
  1) 安装原版（最新正式版）
  2) 安装原版（指定版本）
  3) 安装 Fabric
  4) 安装 Forge
  5) 安装 Quilt
  6) 校验已安装版本（可自动修复）
  7) 测试下载源
  8) 查看可用版本列表
  0) 退出
```

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
├── cli.py        # 命令行 + 交互菜单
├── mirrors.py    # 镜像定义与 URL 重写
├── manifest.py   # 版本清单/版本 JSON 解析
├── rules.py      # libraries 的 rules 判定（os / arch / features）
├── netio.py      # HTTP：多源回退、续传、SHA-1、连接复用
├── installer.py  # 安装编排：客户端、依赖库、资源文件
├── loaders.py    # Fabric / Quilt / Forge / NeoForge
├── java.py       # 查找本机 Java（Forge 安装器需要）
└── verify.py     # 版本完整性校验与修复
packaging/        # PyInstaller 入口与构建脚本
tests/            # 47 个纯离线单元测试
docs/MIRRORS.md   # 镜像调研与实测数据
```

## 测试

```bash
python -m unittest discover -s tests -v
```

单元测试不联网，覆盖 URL 重写、rules 判定、版本选择、路径生成、哈希校验、校验/修复逻辑、加载器工具函数。

## 开源与致谢

- 代码以 **MIT** 许可发布，见 [LICENSE](LICENSE)。
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
