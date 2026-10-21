# 开源与致谢说明（NOTICE）

本项目（mcvd / mc-vanilla-downloader）的代码除下列注明外，均为原创实现，以 **MIT** 许可证发布。
下面列出本项目**参考过的公开规范、接口与服务**。除特别说明外，**没有复制任何第三方项目的源代码**。

## 1. 数据格式与规范（参考，未复制代码）

| 来源 | 用途 | 链接 |
|---|---|---|
| Mojang 版本清单 / 版本 JSON（`version_manifest_v2.json`、`<version>.json`） | 版本号、下载地址、SHA-1、依赖库规则、资源索引 | <https://launchermeta.mojang.com/mc/game/version_manifest_v2.json> |
| Minecraft Wiki — Client.json | `libraries` 的 `rules` 语义、`natives`/`classifiers`、`assetIndex` 的 `virtual` / `map_to_resources` | <https://minecraft.wiki/w/Client.json> |
| wiki.vg（历史文档，内容已并入 Minecraft Wiki） | 旧版本资源索引格式 | <https://minecraft.wiki/w/Client.json> |

## 2. 下载镜像（调用服务，未复制代码）

| 名称 | 说明 | 链接 |
|---|---|---|
| **BMCLAPI** | 国内 Minecraft 文件镜像服务，由 **bangbang93** 维护、社区公益运营。本项目通过其公开接口镜像官方文件：`/v1/packages/...`、`/v1/objects/...`、`/maven/...`、`/assets/...`。路径映射规则是**实测验证**得出的，并非复制其代码。 | <https://github.com/bangbang93/BMCLAPI> · <https://bmclapi2.bangbang93.com> |
| Mojang 官方 CDN | `launchermeta.mojang.com`、`piston-meta.mojang.com`、`piston-data.mojang.com`、`libraries.minecraft.net`、`resources.download.minecraft.net` | <https://www.minecraft.net> |

> BMCLAPI 是免费公益服务。请勿滥用（本项目默认并发 8、失败重试有限次），也请在其服务条款允许的范围内使用。

## 3. 加载器相关的官方接口与安装器（调用官方服务/工具，未复制代码）

| 名称 | 用途 | 链接 |
|---|---|---|
| Fabric Meta API | 查询 Fabric Loader 版本、获取带 `inheritsFrom` 的 profile JSON | <https://meta.fabricmc.net> |
| Quilt Meta API | 同上，Quilt | <https://meta.quiltmc.org> |
| Forge 官网 / maven | 版本推荐列表、官方 `installer.jar` | <https://files.minecraftforge.net> · <https://maven.minecraftforge.net> |
| NeoForge maven | 版本列表、官方 `installer.jar` | <https://maven.neoforged.net> |
| Minecraft Wiki — Client.json | 版本 JSON、`inheritsFrom`、`libraries`、`assetIndex` 语义 | <https://minecraft.wiki/w/Client.json> |

> Forge / NeoForge 的安装是通过**运行官方 installer.jar**完成的（`--installClient`），
> 安装器本身不随本项目分发，每次使用时从官方 maven 现下现用。

## 4. 启动器格式与行为参考（未使用其源代码）

| 项目 | 参考内容 | 许可证 / 链接 |
|---|---|---|
| 官方启动器 `launcher_profiles.json` | `profiles` 条目字段（`type` / `created` / `lastUsed` / `lastVersionId` / `icon`）、`settings`、`version: 6` 的格式；按本机 `%APPDATA%\.minecraft\launcher_profiles.json` 实测 | Mojang / Microsoft，仅参考文件格式 |
| PCL2（Plain Craft Launcher 2） | 目录布局（`versions/<id>/<id>.json` + `<id>.jar`、便携模式 `PCL/`）、版本隔离设置 `LaunchArgumentIndieV2` / `VersionArgumentIndieV2` 的取值语义 | 闭源（现已在 GitHub 开源，Meloong-Git/PCL），仅参考行为 |
| HMCL | 版本扫描方式（`versions/`）、全局版本隔离语义（`DefaultIsolationType`: ALWAYS / MODDED / NEVER）、配置位置（新版 `config/launcher-settings.json`、旧版 `hmcl.json`） | GPL-3.0，**未引用任何代码** · <https://github.com/HMCL-dev/HMCL> · <https://docs.hmcl.net/launcher/isolation.html> |
| BakaXL / LauncherX / MSL | 仅识别其配置文件名 / 目录（`BakaXL/`、`launcherx.json`、`MSL.exe`），用于在界面上提示 | 闭源，仅识别文件 |

如果你认为本项目某处侵犯了你的权利，请开 issue，我们会立即处理。

## 5. 运行时依赖

命令行 / 安装核心只用 **Python 3.9+ 标准库**；图形界面额外使用两个开源库（打包时已一并打进 exe）：

| 依赖 | 用途 | 许可证 | 链接 |
|---|---|---|---|
| **customtkinter** | 现代风格 tkinter 主题与控件 | MIT | <https://github.com/TomSchimansky/CustomTkinter> |
| **darkdetect** | 跟随系统深浅色 | BSD-3-Clause | <https://github.com/albertosottile/darkdetect> |

以上许可证与本项目 MIT 兼容；本项目的代码未修改这两个库。

## 6. 免责声明

- 本项目**不包含、不托管、不分发**任何 Mojang / Microsoft 的游戏文件；所有文件都从 Mojang 官方服务器或其公开镜像实时下载。
- 使用本项目下载游戏，仍需你**自行拥有合法的 Minecraft 账号**，并遵守 [Minecraft 使用条款（EULA）](https://www.minecraft.net/eula)。
- 请在所在地法律法规允许的范围内使用。因使用本项目产生的一切后果由使用者自行承担。
