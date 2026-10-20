# 国内镜像源调研（2026-10-21 实测）

本文记录 mcvd 选源策略的依据：Mojang 官方下载链路在国内的可用性、BMCLAPI 镜像的路径映射与实测速度。

测试环境：Windows 10/11，中国大陆家宽，2026-10-21 02:5x（Asia/Hong_Kong）。

## 1. 结论

1. **官方源目前仍可直连**（版本清单、client.jar 都能 200），所以 `auto` 模式默认不写死镜像，而是每次启动时实测选源。
2. **BMCLAPI 是唯一活跃的国内 Minecraft 文件镜像**，覆盖版本清单 / 版本 JSON / client.jar / 依赖库 / 资源对象；路径规则见第 3 节。
3. BMCLAPI 存在**冷启动慢**现象（首次请求可能 10s 级），所以必须做「超时 + 重试 + 换源」，不能单源死等。
4. 小文件（资源对象，平均几十 KB）的瓶颈是**请求往返**，不是带宽：开启 HTTP keep-alive + 16 并发后，同一份安装从 433 KB/s 提升到 837 KB/s。
5. 大文件（client.jar、依赖库）速度差异明显：本机官方源 23.9 MB/s，BMCLAPI 22.5 MB/s（热连接），都属于可用区间。

## 2. 可用性实测

### 版本清单（`version_manifest_v2.json`，约 272 KB）

| 地址 | 结果 | 耗时 |
|---|---|---|
| `https://launchermeta.mojang.com/mc/game/version_manifest_v2.json` | 200 | 937–1362 ms |
| `https://piston-meta.mojang.com/mc/game/version_manifest_v2.json` | 200 | 1241 ms |
| `https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json` | 200 | 199 ms（HEAD）/ 9991 ms（首次 GET，冷启动）/ 1442 ms（再次） |

### 大文件（26.3 的 `client.jar`，41,483,720 B，取前 8 MiB）

| 地址 | 分段结果 | 速度 |
|---|---|---|
| `piston-data.mojang.com/v1/objects/<sha1>/client.jar` | 200 / 8.00 MB / 251 ms | 31.87 MB/s |
| `bmclapi2.bangbang93.com/v1/objects/<sha1>/client.jar` | 200 / 8.00 MB / 1773 ms | 4.51 MB/s（冷） |
| 同上（第二次） | 200 / 8.00 MB / 356 ms | 22.47 MB/s |

### 完整安装实测

| 场景 | 源 | 文件数 / 体积 | 耗时 | 平均速度 |
|---|---|---|---|---|
| 1.0（含 749 个资源对象） | bmclapi | 761 / 48.99 MB | 122 s | 433 KB/s（8 线程，无 keep-alive） |
| 1.0（同上） | bmclapi | 761 / 48.99 MB | 62 s | **837 KB/s**（16 线程 + keep-alive） |
| 26.3（`--no-assets`） | official | 75 / 123.26 MB | 6.6 s | **23.88 MB/s** |

> 这说明：**下资源文件慢是请求数太多**（700+ 个小文件），不是带宽不够。`--no-assets` 只下客户端和库时非常快。

## 3. BMCLAPI 路径映射（全部实测 200）

| 官方地址 | BMCLAPI 等价地址 | 实测 |
|---|---|---|
| `launchermeta.mojang.com/mc/game/version_manifest_v2.json` | `bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json` | 200 |
| `piston-meta.mojang.com/v1/packages/<hash>/<ver>.json` | `bmclapi2.bangbang93.com/v1/packages/<hash>/<ver>.json` | 200 |
| `piston-data.mojang.com/v1/objects/<hash>/client.jar` | `bmclapi2.bangbang93.com/v1/objects/<hash>/client.jar` | 200 |
| `libraries.minecraft.net/<group>/.../<artifact>.jar` | `bmclapi2.bangbang93.com/maven/<group>/.../<artifact>.jar` | 200 |
| `resources.download.minecraft.net/<ab>/<hash>` | `bmclapi2.bangbang93.com/assets/<ab>/<hash>` | 200 |
| — | `bmclapi2.bangbang93.com/version/<ver>/json` | 200（便捷接口） |
| — | `bmclapi2.bangbang93.com/version/<ver>/client` | 200（便捷接口） |

> 注意：`bmclapi2.bangbang93.com/<ab>/<hash>`（不带 `/assets`）是 **404**，资源对象必须走 `/assets/` 前缀。

## 4. mcvd 的选源策略

```
--mirror auto   （默认）
   ├─ 启动时对每个源 GET 一次版本清单，记录耗时
   ├─ 选最快的作为主源
   └─ 每个文件下载失败 → 自动按候选列表换源重试（最多 retries×源数 次）
--mirror official / bmclapi   → 强制指定主源，仍然保留换源回退
```

实现位置：`src/mcvd/mirrors.py`（URL 重写）、`src/mcvd/manifest.py::probe_mirrors`（测速）、`src/mcvd/netio.py::download_file`（回退与重试）。

## 5. 其他已知镜像

| 名称 | 状态 |
|---|---|
| BMCLAPI（bangbang93） | ✅ 活跃，事实标准 |
| MCBBS 镜像源 | ❌ 已随 MCBBS 关站失效 |
| 各高校开源镜像站 | ❌ 无 Minecraft 文件 |
| 网易我的世界 | 仅中国版（基岩版/网易版），不提供 Java 国际版原版文件 |

## 6. 礼貌使用

BMCLAPI 是**免费公益服务**。mcvd 默认并发 16、失败重试 3 次；如果你要批量镜像或高并发抓取，请先联系服务方，不要给公益服务添乱。
