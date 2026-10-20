# mc-vanilla-downloader（mcvd）

一个只用 Python 标准库写的 **Minecraft 原版下载/安装器**：从 Mojang 官方或国内镜像（BMCLAPI）把指定版本的客户端、依赖库、资源文件下载到 `.minecraft` 目录，生成 **PCL / HMCL / 官方启动器都能直接识别**的版本。

- 多源自动测速选源，单文件失败自动切换镜像
- 断点续传、SHA-1 校验、失败重试、HTTP 连接复用
- 多线程并发下载
- 只依赖 Python 3.9+ 标准库，不需要 `pip install` 任何东西

> 背景：2026-10-20 起 PCL、HMCL 等在中国大陆展业的启动器陆续关闭了游戏本体下载功能。
> 本工具不在启动器里改任何东西，只是把**官方原版文件**按标准目录结构装好，供**个人自用**。
> 请先阅读 [免责声明](#免责声明)。

## 快速开始

```bash
# 不需要安装，直接从仓库运行
python -m mcvd mirrors              # 先测一下官方源和国内镜像哪个快
python -m mcvd list --limit 10      # 看看有哪些版本
python -m mcvd install latest       # 下载最新正式版到 %APPDATA%\.minecraft
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
| `mcvd mirrors` | 检测官方源与 BMCLAPI 的可用性和耗时 |
| `mcvd list [--type release\|snapshot\|all] [--limit N] [--json]` | 列出可用版本 |
| `mcvd info <版本>` | 查看版本信息（Java 版本、依赖库数量、客户端大小等） |
| `mcvd install <版本> [--dir PATH] [--mirror auto\|official\|bmclapi] [--threads N] [--dry-run] [--no-assets] [--no-libraries] [--force]` | 下载并安装 |

常用示例：

```bash
mcvd install latest --dry-run              # 只看要下多少，不实际下载
mcvd install 26.3 --mirror bmclapi         # 强制走国内镜像
mcvd install 1.20.1 --dir D:\MC            # 装到指定目录
mcvd install latest --no-assets            # 只下客户端和依赖库（资源文件很大）
```

## 下载源：官方 vs 国内镜像

`--mirror auto`（默认）会在启动时各拉一次版本清单测速，选快的那个；下载单个文件失败时会自动换另一个源重试。

实测数据见 [docs/MIRRORS.md](docs/MIRRORS.md)，要点：

- **BMCLAPI**（`bmclapi2.bangbang93.com`）是国内事实标准镜像，覆盖版本清单、版本 JSON、客户端 jar、依赖库、资源对象，路径是官方 URL 的少量前缀映射；
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
├── versions/<id>/<id>.json     # 官方版本 JSON（原样）
├── versions/<id>/<id>.jar      # client.jar
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
├── cli.py        # 命令行
├── mirrors.py    # 镜像定义与 URL 重写
├── manifest.py   # 版本清单/版本 JSON 解析
├── rules.py      # libraries 的 rules 判定（os / arch / features）
├── netio.py      # HTTP：多源回退、续传、SHA-1、连接复用
└── installer.py  # 安装编排：客户端、依赖库、资源文件
tests/            # 34 个纯离线单元测试
docs/MIRRORS.md   # 镜像调研与实测数据
```

## 测试

```bash
python -m unittest discover -s tests -v
```

单元测试不联网，覆盖 URL 重写、rules 判定、版本选择、路径生成、哈希校验。

## 开源与致谢

- 代码以 **MIT** 许可发布，见 [LICENSE](LICENSE)。
- 参考的公开规范、镜像服务与启动器行为，全部列在 [NOTICE.md](NOTICE.md)：
  Mojang 版本清单规范、Minecraft Wiki 的 Client.json 文档、**BMCLAPI**（bangbang93 维护的社区镜像）、PCL2 / HMCL 的目录约定。
- 本项目**没有复制**任何第三方项目的源代码，也不包含任何游戏文件。

## 免责声明

- 本项目不包含、不托管、不分发任何 Mojang / Microsoft 的游戏文件，所有文件都从官方服务器或公开镜像实时下载。
- 使用前请确保你拥有合法的 Minecraft 账号，并遵守 [Minecraft EULA](https://www.minecraft.net/eula)。
- 仅建议个人自用，请勿用于二次分发游戏内容；请遵守你所在地区的法律法规。
- 因使用本项目产生的一切后果由使用者自行承担。

## License

MIT © 2026 huiyaoxingkong and mcvd contributors
